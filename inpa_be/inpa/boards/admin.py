"""게시판 Django 관리자 콘솔 등록."""
from django.contrib import admin

from .models import (
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


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = ['id', 'author', 'title', 'category', 'is_hidden', 'is_deleted', 'pinned', 'like_count', 'comment_count', 'created_at']
    list_filter = ['is_hidden', 'is_deleted', 'pinned', 'category']
    search_fields = ['title', 'body', 'author__email']
    actions = ['hide_posts', 'unhide_posts']

    def hide_posts(self, request, queryset):
        queryset.update(is_hidden=True)
    hide_posts.short_description = '선택 게시글 숨김 처리'

    def unhide_posts(self, request, queryset):
        queryset.update(is_hidden=False)
    unhide_posts.short_description = '선택 게시글 숨김 해제'


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ['id', 'post', 'author', 'parent', 'is_hidden', 'is_deleted', 'created_at']
    list_filter = ['is_hidden', 'is_deleted']
    search_fields = ['body', 'author__email']


@admin.register(PostLike)
class PostLikeAdmin(admin.ModelAdmin):
    list_display = ['id', 'post', 'user', 'created_at']


@admin.register(PostAttachment)
class PostAttachmentAdmin(admin.ModelAdmin):
    list_display = ['id', 'post', 'uploader', 'file_name', 'mime_type', 'file_size', 'created_at']


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ['id', 'reporter', 'content_type', 'object_id', 'reason', 'status', 'resolved_by', 'created_at']
    list_filter = ['status', 'content_type', 'reason']
    actions = ['resolve_reports', 'dismiss_reports']

    def resolve_reports(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='resolved', resolved_by=request.user, resolved_at=timezone.now())
    resolve_reports.short_description = '선택 신고 처리 완료 (숨김)'

    def dismiss_reports(self, request, queryset):
        from django.utils import timezone
        queryset.update(status='dismissed', resolved_by=request.user, resolved_at=timezone.now())
    dismiss_reports.short_description = '선택 신고 기각'


@admin.register(Notice)
class NoticeAdmin(admin.ModelAdmin):
    list_display = ['id', 'title', 'is_pinned', 'is_published', 'author', 'created_at']
    list_filter = ['is_pinned', 'is_published']
    search_fields = ['title', 'body']


@admin.register(Faq)
class FaqAdmin(admin.ModelAdmin):
    list_display = ['id', 'category', 'question', 'order', 'is_published', 'created_at']
    list_filter = ['category', 'is_published']
    search_fields = ['question', 'answer']


@admin.register(Inquiry)
class InquiryAdmin(admin.ModelAdmin):
    list_display = ['id', 'owner', 'category', 'title', 'status', 'created_at']
    list_filter = ['status', 'category']
    search_fields = ['title', 'body', 'owner__email']


@admin.register(InquiryReply)
class InquiryReplyAdmin(admin.ModelAdmin):
    list_display = ['id', 'inquiry', 'author', 'created_at']
