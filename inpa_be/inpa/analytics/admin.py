"""북극성 이벤트 관리자 콘솔 (읽기전용 — append-only 감사 로그).

가시성: 관리자 전용 집계. 이벤트는 append-only 이므로 admin 에서 추가/수정/삭제 금지.
"""
from django.contrib import admin

from .models import NorthStarEvent


@admin.register(NorthStarEvent)
class NorthStarEventAdmin(admin.ModelAdmin):
    list_display = ('id', 'event_type', 'customer', 'sender', 'channel',
                    'viewer_fp', 'created_at')
    list_filter = ('event_type', 'channel', 'created_at')
    search_fields = ('share_token', 'ref_code', 'viewer_fp')
    readonly_fields = ('event_type', 'customer', 'sender', 'share_token',
                       'ref_code', 'viewer_fp', 'channel', 'payload', 'created_at')
    ordering = ('-created_at',)

    def has_add_permission(self, request):
        return False  # append-only — 수기 추가 금지(계측 무결성)

    def has_change_permission(self, request, obj=None):
        return False  # 불변 로그

    def has_delete_permission(self, request, obj=None):
        return False  # 영구 보존(사후복원 불가 자산)
