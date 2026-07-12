"""게시판 & 커뮤니티 URL 라우팅 (dev/17 §8).

base: config/urls.py → /api/v1/ 마운트.

게시판 (Post/Comment/Like/Attachment/Report):
  GET    /api/v1/board/posts/                    피드 목록 (커서 페이지네이션)
  POST   /api/v1/board/posts/                    글 작성
  GET    /api/v1/board/posts/:id/                글 상세
  PATCH  /api/v1/board/posts/:id/                글 수정 (IsAuthorOrAdmin)
  DELETE /api/v1/board/posts/:id/                소프트 삭제 (IsAuthorOrAdmin)
  POST   /api/v1/board/posts/:id/like/           좋아요 토글
  GET    /api/v1/board/posts/:post_id/comments/  댓글 목록
  POST   /api/v1/board/posts/:post_id/comments/  댓글 작성
  PATCH  /api/v1/board/comments/:id/             댓글 수정 (IsAuthorOrAdmin)
  DELETE /api/v1/board/comments/:id/             댓글 소프트 삭제 (IsAuthorOrAdmin)
  POST   /api/v1/board/posts/attachments/        첨부 메타 저장
  POST   /api/v1/board/reports/                  신고 접수
  GET    /api/v1/board/reports/                  신고 목록 (본인/관리자)

공지사항 (Notice — AllowAny GET):
  GET    /api/v1/board/notices/                  목록
  GET    /api/v1/board/notices/:id/              상세
  POST   /api/v1/board/notices/                  작성 (IsAdmin)
  PATCH  /api/v1/board/notices/:id/              수정 (IsAdmin)
  DELETE /api/v1/board/notices/:id/              삭제 (IsAdmin)

FAQ (Faq — AllowAny GET):
  GET    /api/v1/board/faqs/                     목록 (?category, ?q)
  GET    /api/v1/board/faqs/:id/                 상세
  POST   /api/v1/board/faqs/                     작성 (IsAdmin)
  PATCH  /api/v1/board/faqs/:id/                 수정 (IsAdmin)
  DELETE /api/v1/board/faqs/:id/                 삭제 (IsAdmin)

1:1 문의 (Inquiry — 비공개):
  GET    /api/v1/board/inquiries/                내 목록
  POST   /api/v1/board/inquiries/                작성
  GET    /api/v1/board/inquiries/:id/            상세 + 답변
  PATCH  /api/v1/board/inquiries/:id/            수정 (open 상태만)
  DELETE /api/v1/board/inquiries/:id/            취소 (open 상태만)
  POST   /api/v1/board/inquiries/:inquiry_id/replies/   관리자 답변 작성
  PATCH  /api/v1/board/inquiry-replies/:id/      관리자 답변 수정
"""
from django.urls import include, path

from .views import (
    AttachmentViewSet,
    BlogPostViewSet,
    CommentViewSet,
    FaqViewSet,
    InquiryReplyViewSet,
    InquiryViewSet,
    NoticeViewSet,
    PostViewSet,
    ReportViewSet,
)

app_name = 'boards'

# ── 게시판 ────────────────────────────────────────────────────────

post_list = PostViewSet.as_view({'get': 'list', 'post': 'create'})
post_detail = PostViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})
post_like = PostViewSet.as_view({'post': 'like_toggle'})

comment_list_create = CommentViewSet.as_view({'get': 'list', 'post': 'create'})
comment_detail = CommentViewSet.as_view({'patch': 'partial_update', 'delete': 'destroy'})

attachment_create = AttachmentViewSet.as_view({'post': 'create'})

report_list_create = ReportViewSet.as_view({'get': 'list', 'post': 'create'})

# ── 공지사항 ──────────────────────────────────────────────────────

notice_list = NoticeViewSet.as_view({'get': 'list', 'post': 'create'})
notice_detail = NoticeViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

# ── FAQ ───────────────────────────────────────────────────────────

faq_list = FaqViewSet.as_view({'get': 'list', 'post': 'create'})
faq_detail = FaqViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

# ── 인파 노트 (BlogPost — AllowAny GET, 읽기 전용; 쓰기는 /admin/blog/) ──

blog_list = BlogPostViewSet.as_view({'get': 'list'})
blog_sitemap = BlogPostViewSet.as_view({'get': 'sitemap'})
blog_detail = BlogPostViewSet.as_view({'get': 'retrieve'})

# ── 1:1 문의 ──────────────────────────────────────────────────────

inquiry_list = InquiryViewSet.as_view({'get': 'list', 'post': 'create'})
inquiry_detail = InquiryViewSet.as_view({'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'})

inquiry_reply_create = InquiryReplyViewSet.as_view({'post': 'create'})
inquiry_reply_detail = InquiryReplyViewSet.as_view({'patch': 'partial_update'})

urlpatterns = [
    # 게시판
    path('board/posts/', post_list, name='post-list'),
    path('board/posts/attachments/', attachment_create, name='post-attachment-create'),
    path('board/posts/<int:pk>/', post_detail, name='post-detail'),
    path('board/posts/<int:pk>/like/', post_like, name='post-like'),
    path('board/posts/<int:post_pk>/comments/', comment_list_create, name='comment-list'),
    path('board/comments/<int:pk>/', comment_detail, name='comment-detail'),
    path('board/reports/', report_list_create, name='report-list'),

    # 공지사항
    path('board/notices/', notice_list, name='notice-list'),
    path('board/notices/<int:pk>/', notice_detail, name='notice-detail'),

    # FAQ
    path('board/faqs/', faq_list, name='faq-list'),
    path('board/faqs/<int:pk>/', faq_detail, name='faq-detail'),

    # 인파 노트 (BlogPost) — sitemap 은 <str:slug> 보다 먼저 매칭돼야 함
    path('board/blog/', blog_list, name='blog-list'),
    path('board/blog/sitemap/', blog_sitemap, name='blog-sitemap'),
    path('board/blog/<str:slug>/', blog_detail, name='blog-detail'),

    # 1:1 문의
    path('board/inquiries/', inquiry_list, name='inquiry-list'),
    path('board/inquiries/<int:pk>/', inquiry_detail, name='inquiry-detail'),
    path('board/inquiries/<int:inquiry_pk>/replies/', inquiry_reply_create, name='inquiry-reply-create'),
    path('board/inquiry-replies/<int:pk>/', inquiry_reply_detail, name='inquiry-reply-detail'),
]
