"""게시판 & 커뮤니티 직렬화 (dev/17 §8 API 계약).

PostFeedSerializer      — 피드 목록 (body_preview, thumbnail_url 포함)
PostDetailSerializer    — 게시글 상세 (attachments 인라인)
PostWriteSerializer     — 글 작성/수정 입력
CommentSerializer       — 댓글 목록/작성
AttachmentSerializer    — 첨부 파일 메타 저장
ReportSerializer        — 신고 접수
NoticeSerializer        — 공지사항
FaqSerializer           — FAQ
InquirySerializer       — 1:1 문의
InquiryDetailSerializer — 문의 + 답변 인라인
InquiryWriteSerializer  — 문의 작성/수정 입력
InquiryReplySerializer  — 관리자 답변

★ 정직성 레드라인: 첨부 MIME 화이트리스트 외 400 반환 (dev/17 §13).
"""
from rest_framework import serializers

from .models import (
    ALLOWED_MIME_TYPES,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    PostAttachment,
    Report,
)

_BODY_PREVIEW_LEN = 150


# ─── 공통 헬퍼 ─────────────────────────────────────────────────────

class _AuthorField(serializers.SerializerMethodField):
    """작성자 요약 {id, display_name} — 탈퇴 시 null 또는 "탈퇴한 사용자"."""

    def to_representation(self, value):
        author = value.author
        if author is None:
            return {'id': None, 'display_name': '탈퇴한 사용자'}
        email = author.email
        display = email.split('@')[0]  # 임시 display: 이메일 앞부분
        return {'id': author.id, 'display_name': display}


# ─── Post ──────────────────────────────────────────────────────────

class AttachmentInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostAttachment
        fields = ['id', 'file_url', 'file_name', 'mime_type', 'file_size']
        read_only_fields = fields


class PostFeedSerializer(serializers.ModelSerializer):
    """피드 목록용 — body_preview, thumbnail_url 포함 (dev/17 §8.1)."""
    author = _AuthorField()
    body_preview = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    is_edited = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id',
            'author',
            'title',
            'body_preview',
            'like_count',
            'comment_count',
            'view_count',
            'created_at',
            'updated_at',
            'is_pinned',
            'is_edited',
            'category',
            'thumbnail_url',
        ]
        read_only_fields = fields

    # is_pinned 필드명을 pinned에서 맵핑
    is_pinned = serializers.BooleanField(source='pinned', read_only=True)

    def get_body_preview(self, obj):
        return obj.body[:_BODY_PREVIEW_LEN]

    def get_thumbnail_url(self, obj):
        # 첫 번째 이미지 첨부 URL 반환 (없으면 null)
        img = obj.attachments.filter(
            mime_type__in=['image/jpeg', 'image/png', 'image/webp']
        ).first()
        return img.file_url if img else None

    def get_is_edited(self, obj):
        # 수정 이력: updated_at이 created_at과 다르면 "수정됨" (dev/17 §4.3)
        delta = obj.updated_at - obj.created_at
        return delta.total_seconds() > 2


class PostDetailSerializer(serializers.ModelSerializer):
    """게시글 상세 — 첨부 인라인, 본문 전체 포함."""
    author = _AuthorField()
    attachments = AttachmentInlineSerializer(many=True, read_only=True)
    is_pinned = serializers.BooleanField(source='pinned', read_only=True)
    is_edited = serializers.SerializerMethodField()

    class Meta:
        model = Post
        fields = [
            'id',
            'author',
            'title',
            'body',
            'like_count',
            'comment_count',
            'view_count',
            'created_at',
            'updated_at',
            'is_pinned',
            'is_deleted',
            'is_hidden',
            'is_edited',
            'category',
            'attachments',
        ]
        read_only_fields = fields

    def get_is_edited(self, obj):
        delta = obj.updated_at - obj.created_at
        return delta.total_seconds() > 2


class PostWriteSerializer(serializers.ModelSerializer):
    """글 작성/수정 입력 — body 필수, 나머지 선택."""
    class Meta:
        model = Post
        fields = ['title', 'body', 'category']
        extra_kwargs = {
            'body': {'required': True},
            'title': {'required': False, 'allow_blank': True},
            'category': {'required': False, 'allow_null': True},
        }

    def validate_body(self, value):
        if len(value) > 5000:
            raise serializers.ValidationError('본문은 5,000자 이내여야 합니다.')
        return value


# ─── Comment ───────────────────────────────────────────────────────

class CommentSerializer(serializers.ModelSerializer):
    """댓글 목록 + 작성.

    대댓글 2단계 이상 금지: parent가 이미 대댓글이면 400 반환.
    """
    author = _AuthorField()
    # 응답에 replies(자식 대댓글) 인라인 — 1단계만
    replies = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = [
            'id',
            'post',
            'author',
            'parent',
            'body',
            'is_deleted',
            'is_hidden',
            'created_at',
            'updated_at',
            'replies',
        ]
        read_only_fields = ['id', 'author', 'is_deleted', 'is_hidden', 'created_at', 'updated_at']
        extra_kwargs = {
            'post': {'required': True},
            'parent': {'required': False, 'allow_null': True},
        }

    def get_replies(self, obj):
        if obj.parent_id is not None:
            return []  # 대댓글에는 또 대댓글 없음
        qs = obj.replies.filter(is_deleted=False, is_hidden=False).order_by('created_at')
        return CommentSerializer(qs, many=True, context=self.context).data

    def validate_parent(self, value):
        if value is not None and value.parent_id is not None:
            raise serializers.ValidationError(
                '대댓글에는 추가 대댓글을 달 수 없습니다 (최대 1단계).'
            )
        return value

    def validate_body(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('댓글 내용을 입력해주세요.')
        return value


class CommentUpdateSerializer(serializers.ModelSerializer):
    """댓글 수정 — body만 수정 가능."""
    class Meta:
        model = Comment
        fields = ['body']

    def validate_body(self, value):
        if not value or not value.strip():
            raise serializers.ValidationError('댓글 내용을 입력해주세요.')
        return value


# ─── PostAttachment ────────────────────────────────────────────────

class AttachmentSerializer(serializers.ModelSerializer):
    """첨부 파일 메타 저장 — MIME 화이트리스트 검사 (dev/17 §11).

    S3 직접 업로드 완료 후 file_url·file_name·file_size·mime_type 전송.
    """
    class Meta:
        model = PostAttachment
        fields = ['id', 'post', 'file_url', 'file_name', 'file_size', 'mime_type', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate_mime_type(self, value):
        if value not in ALLOWED_MIME_TYPES:
            raise serializers.ValidationError(
                f'허용되지 않는 MIME 타입입니다. 허용: {", ".join(ALLOWED_MIME_TYPES)}'
            )
        return value

    def validate_file_size(self, value):
        # 이미지 10MB, PDF 20MB
        if value > 20 * 1024 * 1024:
            raise serializers.ValidationError('파일 크기는 20MB 이하여야 합니다.')
        return value

    def validate(self, data):
        mime = data.get('mime_type', '')
        size = data.get('file_size', 0)
        if mime in ('image/jpeg', 'image/png', 'image/webp') and size > 10 * 1024 * 1024:
            raise serializers.ValidationError({'file_size': '이미지는 10MB 이하여야 합니다.'})
        return data


# ─── Report ────────────────────────────────────────────────────────

class ReportSerializer(serializers.ModelSerializer):
    """신고 접수 (dev/17 §10).

    reporter는 request.user 자동 주입. 중복 신고 → DB UniqueConstraint → 400.
    """
    class Meta:
        model = Report
        fields = ['id', 'content_type', 'object_id', 'reason', 'detail', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

    def validate_content_type(self, value):
        if value not in ('post', 'comment'):
            raise serializers.ValidationError("content_type은 'post' 또는 'comment'여야 합니다.")
        return value


# ─── Notice ────────────────────────────────────────────────────────

class NoticeSerializer(serializers.ModelSerializer):
    """공지사항 — 공개읽기 AllowAny GET, 관리자쓰기."""
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = Notice
        fields = [
            'id',
            'author',
            'author_name',
            'title',
            'body',
            'is_pinned',
            'is_published',
            'published_at',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'author', 'author_name', 'created_at', 'updated_at']

    def get_author_name(self, obj):
        if obj.author is None:
            return '인파 운영팀'
        return obj.author.email.split('@')[0]


class NoticeWriteSerializer(serializers.ModelSerializer):
    """공지 작성/수정 — 관리자 전용 입력."""
    class Meta:
        model = Notice
        fields = ['title', 'body', 'is_pinned', 'is_published', 'published_at']


# ─── Faq ───────────────────────────────────────────────────────────

class FaqSerializer(serializers.ModelSerializer):
    """FAQ — 공개읽기 AllowAny GET, 관리자쓰기."""
    class Meta:
        model = Faq
        fields = [
            'id',
            'category',
            'question',
            'answer',
            'order',
            'is_published',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


# ─── Inquiry ───────────────────────────────────────────────────────

class InquiryReplySerializer(serializers.ModelSerializer):
    """1:1 문의 답변 — 관리자 작성, 문의 소유자 읽기."""
    author_name = serializers.SerializerMethodField()

    class Meta:
        model = InquiryReply
        fields = ['id', 'inquiry', 'author', 'author_name', 'body', 'created_at', 'updated_at']
        read_only_fields = ['id', 'inquiry', 'author', 'author_name', 'created_at', 'updated_at']

    def get_author_name(self, obj):
        return '인파 운영팀'  # 항상 운영팀 표기 (dev/17 §7.2)


class InquirySerializer(serializers.ModelSerializer):
    """1:1 문의 목록 — 상태 + 카테고리."""
    class Meta:
        model = Inquiry
        fields = ['id', 'category', 'title', 'status', 'created_at', 'updated_at']
        read_only_fields = ['id', 'status', 'created_at', 'updated_at']


class InquiryDetailSerializer(serializers.ModelSerializer):
    """1:1 문의 상세 + 답변 인라인."""
    replies = InquiryReplySerializer(many=True, read_only=True)

    class Meta:
        model = Inquiry
        fields = ['id', 'category', 'title', 'body', 'status', 'created_at', 'updated_at', 'replies']
        read_only_fields = fields


class InquiryWriteSerializer(serializers.ModelSerializer):
    """문의 작성/수정 — open 상태만 수정 가능 (뷰에서 검사)."""
    class Meta:
        model = Inquiry
        fields = ['category', 'title', 'body']
        extra_kwargs = {
            'category': {'required': True},
            'title': {'required': True},
            'body': {'required': True},
        }

    def validate_title(self, value):
        if len(value) > 200:
            raise serializers.ValidationError('제목은 200자 이내여야 합니다.')
        return value

    def validate_body(self, value):
        if len(value) > 3000:
            raise serializers.ValidationError('내용은 3,000자 이내여야 합니다.')
        return value


class InquiryReplyWriteSerializer(serializers.ModelSerializer):
    """관리자 답변 작성/수정."""
    class Meta:
        model = InquiryReply
        fields = ['body']
