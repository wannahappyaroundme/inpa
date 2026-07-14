"""게시판 & 커뮤니티 ViewSet (dev/17 §8 API 계약).

가시성 강제 (dev/02 §0 매트릭스):

  PostViewSet       — 공유(IsAuthenticated+IsEmailVerified), 수정·삭제 IsAuthorOrAdmin
  CommentViewSet    — 공유, 수정·삭제 IsAuthorOrAdmin
  AttachmentViewSet — 공유, 업로드 본인(작성 시 자동 uploader 주입)
  ReportViewSet     — 본인 생성/조회, 관리자 전체
  NoticeViewSet     — GET AllowAny, 쓰기 IsAdminOnly
  FaqViewSet        — GET AllowAny, 쓰기 IsAdminOnly
  InquiryViewSet    — OwnedQuerySetMixin + IsOwner (비공개)
  InquiryReplyViewSet — 관리자 작성·수정, 문의 소유자 읽기

★ 알림 연동 (dev/17 §13 / dev/02 §9.1):
  댓글 작성 → 원글 작성자 board_comment 알림 (자기 글 댓글 제외)
  좋아요 생성 → 원글 작성자 board_like 알림 (자기 글 좋아요 제외)
  두 type 모두 ReminderRule 대상 아님 — 즉시 이벤트 트리거.

★ 정직성 레드라인 (dev/14): 자동발송 금지, AI면책 없음 (게시판 자유 글 영역).
"""
from django.db import IntegrityError, transaction
from django.db.models import F, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle

from inpa.core.mixins import OwnedQuerySetMixin
from inpa.core.permissions import IsEmailVerified, IsOwner

from .models import (
    BlogPost,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    PostAttachment,
    PostLike,
    Report,
)
from .pagination import BlogPostPagination, PostCursorPagination
from .permissions import IsAdminOnly, IsAuthorOrAdmin
from .serializers import (
    AttachmentSerializer,
    BlogPostDetailSerializer,
    BlogPostListSerializer,
    CommentSerializer,
    CommentUpdateSerializer,
    FaqSerializer,
    InquiryDetailSerializer,
    InquiryReplySerializer,
    InquiryReplyWriteSerializer,
    InquirySerializer,
    InquiryWriteSerializer,
    NoticeSerializer,
    NoticeWriteSerializer,
    PostDetailSerializer,
    PostFeedSerializer,
    PostWriteSerializer,
    ReportSerializer,
)


# ─── 알림 생성 헬퍼 (즉시 이벤트, ReminderRule 대상 아님) ────────────

def _create_board_notification(owner, notif_type, title, body, post=None):
    """board_comment / board_like 인앱 알림 생성.

    notif_type이 Notification.notif_type choices에 없으면 저장 실패 → 조용히 무시
    (알림 실패가 게시판 본 동작을 막으면 안 됨).
    """
    try:
        from inpa.notifications.models import Notification
        Notification.objects.create(
            owner=owner,
            notif_type=notif_type,
            title=title,
            body=body,
        )
    except Exception:
        # 알림 생성 실패는 무시 — 게시판 주 동작 보호
        pass


def _notify_admins_inquiry(inquiry):
    """새 문의/피드백 접수 → 관리자(profile.is_admin) 전원에게 inquiry_received 알림.

    analysis/flags._notify_admins 패턴. 알림 실패가 문의 접수 본 동작을 막으면 안 됨.
    """
    try:
        from django.contrib.auth import get_user_model
        from inpa.notifications.models import Notification, NotifType
        User = get_user_model()
        who = inquiry.owner.email if inquiry.owner_id else (inquiry.contact_email or '비회원')
        label = inquiry.get_category_display()
        for admin in User.objects.filter(profile__is_admin=True):
            Notification.objects.create(
                owner=admin,
                notif_type=NotifType.INQUIRY_RECEIVED,
                title=f'새 문의가 접수됐어요: {label}',
                body=f'{who} · "{inquiry.title}"',
            )
    except Exception:
        pass


# ─── PostViewSet ────────────────────────────────────────────────────

class PostViewSet(viewsets.GenericViewSet):
    """게시판 글 CRUD + 좋아요 토글 (dev/17 §8.1).

    공유 테이블: OwnedQuerySetMixin 미적용.
    수정·삭제: IsAuthorOrAdmin (객체 단위).
    숨김(is_hidden=True): 관리자만 접근, 일반 설계사엔 404.
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    pagination_class = PostCursorPagination

    def get_queryset(self):
        from inpa.core.permissions import _is_admin
        qs = Post.objects.select_related('author').prefetch_related('attachments')
        if not _is_admin(self.request.user):
            # 일반 설계사: 삭제·숨김 제외
            qs = qs.filter(is_deleted=False, is_hidden=False)
        return qs

    def get_serializer_class(self):
        if self.action in ('create', 'partial_update'):
            return PostWriteSerializer
        if self.action == 'retrieve':
            return PostDetailSerializer
        return PostFeedSerializer

    # ── GET /board/posts/ ─────────────────────────────────────────
    def list(self, request):
        """피드 목록 — 커서 페이지네이션, 검색/필터 (dev/17 §8.1)."""
        qs = self.get_queryset()

        # 카테고리 필터
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)

        # 검색 (title + body)
        q = request.query_params.get('q')
        if q:
            qs = qs.filter(Q(title__icontains=q) | Q(body__icontains=q))

        # 정렬: latest(기본) | popular
        ordering = request.query_params.get('ordering', 'latest')
        if ordering == 'popular':
            qs = qs.order_by('-like_count', '-created_at')
        else:
            qs = qs.order_by('-pinned', '-created_at')

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = PostFeedSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    # ── POST /board/posts/ ───────────────────────────────────────
    def create(self, request):
        """글 작성 — author 자동 주입."""
        serializer = PostWriteSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        post = serializer.save(author=request.user)
        return Response(PostDetailSerializer(post).data, status=status.HTTP_201_CREATED)

    # ── GET /board/posts/:id/ ───────────────────────────────────
    def retrieve(self, request, pk=None):
        """글 상세 — 조회수 atomic 증가."""
        post = self._get_visible_post(pk)
        Post.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
        post.refresh_from_db(fields=['view_count'])
        serializer = PostDetailSerializer(post, context={'request': request})
        return Response(serializer.data)

    # ── PATCH /board/posts/:id/ ─────────────────────────────────
    def partial_update(self, request, pk=None):
        """글 수정 — IsAuthorOrAdmin."""
        post = self._get_visible_post(pk)
        self._check_author_or_admin(post)
        serializer = PostWriteSerializer(post, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(PostDetailSerializer(post, context={'request': request}).data)

    # ── DELETE /board/posts/:id/ ─────────────────────────────────
    def destroy(self, request, pk=None):
        """소프트 삭제 — is_deleted=True (dev/17 §2.2)."""
        post = self._get_visible_post(pk)
        self._check_author_or_admin(post)
        post.is_deleted = True
        post.save(update_fields=['is_deleted', 'updated_at'])
        return Response(status=status.HTTP_204_NO_CONTENT)

    # ── POST /board/posts/:id/like/ ──────────────────────────────
    @action(detail=True, methods=['post'], url_path='like')
    def like_toggle(self, request, pk=None):
        """좋아요 토글 — F() 원자 업데이트 (dev/17 §2.4).

        생성: +1, 취소: -1. 자기 글 좋아요 허용(미결 gap#5 — 허용 기본값).
        좋아요 생성 시 원글 작성자에게 board_like 알림 (자기 글 제외).
        """
        post = self._get_visible_post(pk)
        try:
            with transaction.atomic():
                PostLike.objects.create(post=post, user=request.user)
                Post.objects.filter(pk=post.pk).update(like_count=F('like_count') + 1)
            post.refresh_from_db(fields=['like_count'])
            liked = True
            # 알림: 자기 글 제외
            if post.author and post.author != request.user:
                _create_board_notification(
                    owner=post.author,
                    notif_type='board_like',
                    title='게시글에 좋아요가 달렸어요',
                    body=f'"{post.title or post.body[:30]}" 게시글을 좋아합니다.',
                )
        except IntegrityError:
            # 이미 좋아요 → 취소
            with transaction.atomic():
                deleted, _ = PostLike.objects.filter(post=post, user=request.user).delete()
                if deleted:
                    Post.objects.filter(pk=post.pk, like_count__gt=0).update(
                        like_count=F('like_count') - 1
                    )
            post.refresh_from_db(fields=['like_count'])
            liked = False

        return Response({'liked': liked, 'like_count': post.like_count})

    # ── 헬퍼 ─────────────────────────────────────────────────────
    def _get_visible_post(self, pk):
        """숨김·삭제 게시글: 관리자만 접근, 일반 설계사 404."""
        from inpa.core.permissions import _is_admin
        from django.shortcuts import get_object_or_404
        qs = Post.objects.select_related('author').prefetch_related('attachments')
        if _is_admin(self.request.user):
            return get_object_or_404(qs, pk=pk)
        return get_object_or_404(qs, pk=pk, is_deleted=False, is_hidden=False)

    def _check_author_or_admin(self, post):
        """작성자 또는 관리자 아니면 403."""
        from inpa.core.permissions import _is_admin
        from rest_framework.exceptions import PermissionDenied
        if post.author != self.request.user and not _is_admin(self.request.user):
            raise PermissionDenied('수정·삭제는 작성자 또는 관리자만 가능합니다.')


# ─── CommentViewSet ─────────────────────────────────────────────────

class CommentViewSet(viewsets.GenericViewSet):
    """댓글 CRUD (dev/17 §8.1).

    GET    /board/posts/:post_id/comments/         목록
    POST   /board/posts/:post_id/comments/         작성
    PATCH  /board/comments/:id/                    수정 (IsAuthorOrAdmin)
    DELETE /board/comments/:id/                    소프트 삭제 (IsAuthorOrAdmin)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def get_queryset(self):
        return Comment.objects.select_related('author', 'parent').filter(
            is_hidden=False
        )

    # ── GET /board/posts/:post_id/comments/ ─────────────────────
    def list(self, request, post_pk=None):
        """댓글 목록 — 최상위 댓글 + 대댓글 1단계 인라인."""
        from django.shortcuts import get_object_or_404
        post = get_object_or_404(Post, pk=post_pk, is_deleted=False, is_hidden=False)
        # 최상위 댓글만 가져옴 (replies는 serializer에서 인라인)
        qs = Comment.objects.filter(
            post=post, parent__isnull=True, is_hidden=False
        ).select_related('author').prefetch_related(
            'replies__author'
        ).order_by('created_at')
        serializer = CommentSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    # ── POST /board/posts/:post_id/comments/ ────────────────────
    def create(self, request, post_pk=None):
        """댓글 작성 — author 자동 주입, comment_count atomic 증가.

        댓글 작성 시 원글 작성자에게 board_comment 알림 (자기 글 댓글 제외).
        """
        from django.shortcuts import get_object_or_404
        post = get_object_or_404(Post, pk=post_pk, is_deleted=False, is_hidden=False)

        # post 필드를 강제 주입 (URL 파라미터에서)
        data = request.data.copy()
        data['post'] = post.pk

        serializer = CommentSerializer(data=data, context={'request': request})
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            comment = serializer.save(author=request.user)
            Post.objects.filter(pk=post.pk).update(comment_count=F('comment_count') + 1)

        # 알림: 자기 글 댓글 제외
        if post.author and post.author != request.user:
            _create_board_notification(
                owner=post.author,
                notif_type='board_comment',
                title='게시글에 댓글이 달렸어요',
                body=f'"{post.title or post.body[:30]}"에 댓글: {comment.body[:50]}',
            )

        return Response(
            CommentSerializer(comment, context={'request': request}).data,
            status=status.HTTP_201_CREATED,
        )

    # ── PATCH /board/comments/:id/ ───────────────────────────────
    def partial_update(self, request, pk=None):
        """댓글 수정 — IsAuthorOrAdmin."""
        comment = self._get_visible_comment(pk)
        self._check_author_or_admin(comment)
        serializer = CommentUpdateSerializer(comment, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(CommentSerializer(comment, context={'request': request}).data)

    # ── DELETE /board/comments/:id/ ──────────────────────────────
    def destroy(self, request, pk=None):
        """댓글 소프트 삭제 — is_deleted=True.

        자식 댓글 있으면 '삭제된 댓글입니다' 표기용 플래그만 설정 (실제 삭제 X).
        """
        comment = self._get_visible_comment(pk)
        self._check_author_or_admin(comment)
        with transaction.atomic():
            comment.is_deleted = True
            comment.save(update_fields=['is_deleted', 'updated_at'])
            # comment_count 감소 (최상위 댓글만 카운트)
            if comment.parent_id is None:
                Post.objects.filter(pk=comment.post_id, comment_count__gt=0).update(
                    comment_count=F('comment_count') - 1
                )
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _get_visible_comment(self, pk):
        from django.shortcuts import get_object_or_404
        return get_object_or_404(Comment.objects.select_related('author'), pk=pk)

    def _check_author_or_admin(self, comment):
        from inpa.core.permissions import _is_admin
        from rest_framework.exceptions import PermissionDenied
        if comment.author != self.request.user and not _is_admin(self.request.user):
            raise PermissionDenied('수정·삭제는 작성자 또는 관리자만 가능합니다.')


# ─── AttachmentViewSet ──────────────────────────────────────────────

class AttachmentViewSet(viewsets.GenericViewSet):
    """첨부 파일 메타 저장 (S3 presigned 업로드 완료 후 호출).

    POST /board/posts/attachments/   uploader 자동 주입
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    serializer_class = AttachmentSerializer

    def create(self, request):
        serializer = AttachmentSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        attachment = serializer.save(uploader=request.user)
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


# ─── ReportViewSet ──────────────────────────────────────────────────

class ReportViewSet(viewsets.GenericViewSet):
    """신고 (dev/17 §10).

    POST /board/reports/   접수 (인증 설계사 전원)
    GET  /board/reports/   관리자: 전체 / 본인: 자기 신고만
    """
    permission_classes = [IsAuthenticated, IsEmailVerified]
    serializer_class = ReportSerializer

    def get_queryset(self):
        from inpa.core.permissions import _is_admin
        qs = Report.objects.select_related('reporter', 'resolved_by')
        if _is_admin(self.request.user):
            return qs
        return qs.filter(reporter=self.request.user)

    def list(self, request):
        qs = self.get_queryset()
        serializer = ReportSerializer(qs, many=True)
        return Response(serializer.data)

    def create(self, request):
        """신고 접수 — reporter 자동 주입, 중복 신고 400."""
        serializer = ReportSerializer(data=request.data, context={'request': request})
        serializer.is_valid(raise_exception=True)
        try:
            report = serializer.save(reporter=request.user)
        except IntegrityError:
            return Response(
                {'detail': '이미 신고한 콘텐츠입니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ReportSerializer(report).data, status=status.HTTP_201_CREATED)


# ─── NoticeViewSet ──────────────────────────────────────────────────

class NoticeViewSet(viewsets.GenericViewSet):
    """공지사항 — GET AllowAny, 쓰기 IsAdminOnly (dev/17 §8.2)."""

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsAuthenticated(), IsAdminOnly()]

    def get_queryset(self):
        from inpa.core.permissions import _is_admin
        qs = Notice.objects.select_related('author')
        user = self.request.user
        # 비로그인 또는 일반 설계사: 게시된 것만
        if not (user and user.is_authenticated and _is_admin(user)):
            qs = qs.filter(is_published=True)
        return qs

    def list(self, request):
        qs = self.get_queryset().order_by('-is_pinned', '-created_at')
        serializer = NoticeSerializer(qs, many=True, context={'request': request})
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        notice = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(NoticeSerializer(notice, context={'request': request}).data)

    def create(self, request):
        serializer = NoticeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        notice = serializer.save(author=request.user)
        return Response(NoticeSerializer(notice).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        notice = get_object_or_404(Notice, pk=pk)
        serializer = NoticeWriteSerializer(notice, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(NoticeSerializer(notice).data)

    def destroy(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        notice = get_object_or_404(Notice, pk=pk)
        notice.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── FaqViewSet ─────────────────────────────────────────────────────

class FaqViewSet(viewsets.GenericViewSet):
    """FAQ — GET AllowAny, 쓰기 IsAdminOnly (dev/17 §8.3)."""

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [AllowAny()]
        return [IsAuthenticated(), IsAdminOnly()]

    def get_queryset(self):
        from inpa.core.permissions import _is_admin
        qs = Faq.objects.select_related('author')
        user = self.request.user
        if not (user and user.is_authenticated and _is_admin(user)):
            qs = qs.filter(is_published=True)
        return qs

    def list(self, request):
        category = request.query_params.get('category')
        q = request.query_params.get('q')
        qs = self.get_queryset().order_by('category', 'order', 'created_at')
        if category:
            qs = qs.filter(category=category)
        if q:
            qs = qs.filter(Q(question__icontains=q) | Q(answer__icontains=q))
        serializer = FaqSerializer(qs, many=True)
        return Response(serializer.data)

    def retrieve(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        faq = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(FaqSerializer(faq).data)

    def create(self, request):
        serializer = FaqSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        faq = serializer.save(author=request.user)
        return Response(FaqSerializer(faq).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        faq = get_object_or_404(Faq, pk=pk)
        serializer = FaqSerializer(faq, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(FaqSerializer(faq).data)

    def destroy(self, request, pk=None):
        from django.shortcuts import get_object_or_404
        faq = get_object_or_404(Faq, pk=pk)
        faq.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── InquiryViewSet ─────────────────────────────────────────────────

class InquiryViewSet(OwnedQuerySetMixin, viewsets.GenericViewSet):
    """1:1 문의 — 비공개 (OwnedQuerySetMixin + IsOwner) (dev/17 §8.4).

    GET    /board/inquiries/            내 문의 목록
    POST   /board/inquiries/            문의 작성
    GET    /board/inquiries/:id/        문의 상세 + 답변
    PATCH  /board/inquiries/:id/        문의 수정 (open 상태만)
    DELETE /board/inquiries/:id/        문의 취소 (open 상태만)
    """
    permission_classes = [IsAuthenticated, IsEmailVerified, IsOwner]
    queryset = Inquiry.objects.prefetch_related('replies__author')
    owner_field = 'owner'

    def list(self, request):
        qs = self.get_queryset().order_by('-created_at')
        serializer = InquirySerializer(qs, many=True)
        return Response(serializer.data)

    def create(self, request):
        serializer = InquiryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        inquiry = serializer.save(owner=request.user)
        # 새 문의 → 관리자 알림 fan-out (기존 누락 갭 해소).
        _notify_admins_inquiry(inquiry)
        return Response(InquiryDetailSerializer(inquiry).data, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        inquiry = self.get_object()
        return Response(InquiryDetailSerializer(inquiry).data)

    def partial_update(self, request, pk=None):
        inquiry = self.get_object()
        if inquiry.status != Inquiry.STATUS_OPEN:
            return Response(
                {'detail': '답변이 달린 문의는 수정할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = InquiryWriteSerializer(inquiry, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(InquiryDetailSerializer(inquiry).data)

    def destroy(self, request, pk=None):
        inquiry = self.get_object()
        if inquiry.status != Inquiry.STATUS_OPEN:
            return Response(
                {'detail': '답변이 달린 문의는 취소할 수 없습니다.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        inquiry.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ─── InquiryReplyViewSet ─────────────────────────────────────────────

class InquiryReplyViewSet(viewsets.GenericViewSet):
    """1:1 문의 답변 — 관리자 작성·수정 (dev/17 §8.4).

    POST   /board/inquiries/:inquiry_pk/replies/    관리자 답변 작성
    PATCH  /board/inquiry-replies/:id/              관리자 답변 수정
    """
    permission_classes = [IsAuthenticated, IsAdminOnly]
    queryset = InquiryReply.objects.select_related('inquiry', 'author')

    def create(self, request, inquiry_pk=None):
        """관리자 답변 작성 — Inquiry.status → answered 자동 전환."""
        from django.shortcuts import get_object_or_404
        inquiry = get_object_or_404(Inquiry, pk=inquiry_pk)
        serializer = InquiryReplyWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            reply = serializer.save(inquiry=inquiry, author=request.user)
            # status → answered 자동 전환
            if inquiry.status == Inquiry.STATUS_OPEN:
                inquiry.status = Inquiry.STATUS_ANSWERED
                inquiry.save(update_fields=['status', 'updated_at'])
        return Response(InquiryReplySerializer(reply).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, pk=None):
        """관리자 답변 수정."""
        from django.shortcuts import get_object_or_404
        reply = get_object_or_404(InquiryReply, pk=pk)
        serializer = InquiryReplyWriteSerializer(reply, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(InquiryReplySerializer(reply).data)


# ─── BlogPostViewSet (인파 노트 — 공개읽기) ──────────────────────────

class BlogPostViewSet(viewsets.GenericViewSet):
    """인파 노트 — GET AllowAny (게시글만), slug 조회, 관리자는 초안도 열람.

    공유/글로벌 콘텐츠: OwnedQuerySetMixin 미적용 (Notice/Faq 동형).
    쓰기(CRUD)는 admin_console (/api/v1/admin/blog/) — 여기는 읽기 전용.
    """
    permission_classes = [AllowAny]
    pagination_class = BlogPostPagination

    def get_queryset(self):
        from inpa.core.permissions import _is_admin
        qs = BlogPost.objects.select_related('author')
        user = self.request.user
        # 비로그인·일반 설계사: 게시된 글만. 관리자: 초안 포함.
        if not (user and user.is_authenticated and _is_admin(user)):
            qs = qs.filter(is_published=True)
        return qs

    # ── GET /board/blog/ ─────────────────────────────────────────
    def list(self, request):
        """목록 — ?category= 필터 + 페이지네이션 (page_size 12)."""
        qs = self.get_queryset()
        category = request.query_params.get('category')
        if category:
            qs = qs.filter(category=category)
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = BlogPostListSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(serializer.data)

    # ── GET /board/blog/:slug/ ──────────────────────────────────
    def retrieve(self, request, slug=None):
        """상세 — slug 조회. 공개 조회 시 조회수 F() 원자 증가(초안·관리자 제외)."""
        from django.shortcuts import get_object_or_404
        from inpa.core.permissions import _is_admin
        post = get_object_or_404(self.get_queryset(), slug=slug)
        user = request.user
        is_admin = bool(user and user.is_authenticated and _is_admin(user))
        if post.is_published and not is_admin:
            BlogPost.objects.filter(pk=post.pk).update(view_count=F('view_count') + 1)
            post.refresh_from_db(fields=['view_count'])
        return Response(BlogPostDetailSerializer(post, context={'request': request}).data)

    # ── GET /board/blog/sitemap/ ────────────────────────────────
    def sitemap(self, request):
        """게시된 글의 {slug, updated_at} 경량 목록 (비페이지네이션, sitemap.xml 구동용)."""
        rows = BlogPost.objects.filter(is_published=True).order_by(
            '-published_at', '-created_at'
        ).values('slug', 'updated_at')
        return Response([{'slug': r['slug'], 'updated_at': r['updated_at']} for r in rows])


# ─── FeedbackCreateView (피드백 위젯 — 공개 제출) ────────────────────

# 위젯 카테고리 → Inquiry 카테고리 매핑 (feedback 신설, 나머지는 기존 재사용).
_FEEDBACK_CATEGORY_MAP = {
    'feedback': Inquiry.CATEGORY_FEEDBACK,   # 이용 의견 (별점)
    'feature': Inquiry.CATEGORY_FEATURE,     # 기능 제안
    'bug': Inquiry.CATEGORY_BUG,             # 불편 신고 (meta 첨부)
    'other': Inquiry.CATEGORY_OTHER,         # 1:1 문의(익명)
}
_FEEDBACK_BODY_MAX = 2000
_FEEDBACK_META_KEYS = ('path', 'user_agent', 'viewport')  # bug 리포트 화이트리스트


class FeedbackCreateView(viewsets.ViewSet):
    """POST /api/v1/feedback/ — 피드백 위젯 공개 제출 (AllowAny + throttle).

    body: {category, body, rating?, meta?, contact_email?}
      category  위젯 4종(feedback/feature/bug/other) → Inquiry 카테고리로 매핑.
      body      필수, 최대 2000자.
      rating    이용 의견(feedback)만 1..5 로 clamp 저장. 그 외 무시.
      meta      불편 신고(bug)만 {path,user_agent,viewport} 화이트리스트 저장.
      contact_email  익명 제출 시 답변받을 이메일(선택). 로그인 제출은 owner 로 대체.

    title 은 서버 생성(카테고리 라벨 + 본문 앞 30자). 로그인 사용자는 owner 로 저장돼
    본인 '문의 내역' 과 답변 알림이 그대로 작동, 비로그인은 owner=None(익명).
    새 문의 → 관리자 알림 fan-out (INQUIRY_RECEIVED).
    """
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'feedback'

    def create(self, request):
        data = request.data

        # ── 카테고리 검증 ──
        raw_category = str(data.get('category') or '').strip()
        inquiry_category = _FEEDBACK_CATEGORY_MAP.get(raw_category)
        if inquiry_category is None:
            return Response(
                {'code': 'INVALID_CATEGORY',
                 'detail': '알 수 없는 의견 유형이에요.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 본문 검증 ──
        body = str(data.get('body') or '').strip()
        if not body:
            return Response(
                {'code': 'BODY_REQUIRED', 'detail': '내용을 입력해 주세요.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(body) > _FEEDBACK_BODY_MAX:
            return Response(
                {'code': 'BODY_TOO_LONG',
                 'detail': f'내용은 {_FEEDBACK_BODY_MAX}자 이내로 적어 주세요.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 별점: 이용 의견만, 1..5 clamp ──
        rating = None
        if inquiry_category == Inquiry.CATEGORY_FEEDBACK and data.get('rating') is not None:
            try:
                rating = max(1, min(5, int(data.get('rating'))))
            except (TypeError, ValueError):
                rating = None

        # ── meta: 불편 신고만, 화이트리스트 키만 ──
        meta = None
        if inquiry_category == Inquiry.CATEGORY_BUG:
            raw_meta = data.get('meta')
            if isinstance(raw_meta, dict):
                cleaned = {
                    k: str(raw_meta[k])[:500]
                    for k in _FEEDBACK_META_KEYS
                    if raw_meta.get(k) not in (None, '')
                }
                meta = cleaned or None

        # ── owner / contact_email ──
        user = request.user
        is_authed = bool(user and user.is_authenticated)
        owner = user if is_authed else None
        contact_email = ''
        if not is_authed:
            email_field = serializers.EmailField(required=False, allow_blank=True)
            try:
                contact_email = email_field.run_validation(data.get('contact_email') or '')
            except serializers.ValidationError:
                return Response(
                    {'code': 'INVALID_EMAIL',
                     'detail': '이메일 형식을 확인해 주세요.'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── 제목 서버 생성 (카테고리 라벨 + 본문 앞 30자) ──
        label = dict(Inquiry.CATEGORY_CHOICES)[inquiry_category]
        snippet = body[:30]
        title = f'[{label}] {snippet}'[:200]

        inquiry = Inquiry.objects.create(
            owner=owner,
            category=inquiry_category,
            title=title,
            body=body,
            rating=rating,
            meta=meta,
            contact_email=contact_email,
        )

        _notify_admins_inquiry(inquiry)

        return Response(
            {'id': inquiry.id, 'status': inquiry.status},
            status=status.HTTP_201_CREATED,
        )
