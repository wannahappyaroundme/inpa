"""북극성 이벤트 관리자 콘솔 (읽기전용 — append-only 감사 로그).

가시성: 관리자 전용 집계. 이벤트는 append-only 이므로 admin 에서 추가/수정/삭제 금지.
"""
from django.contrib import admin

from .models import NorthStarEvent, ShareSnapshot


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


@admin.register(ShareSnapshot)
class ShareSnapshotAdmin(admin.ModelAdmin):
    """공유 기록 — 읽기전용(서버 자동 캡처만). 삭제는 허용(고객 파기 요청 등 수동 대응 창구)."""
    list_display = ('id', 'customer', 'owner', 'insurance_count', 'consent_overseas',
                    'captured_at', 'retention_expires_at')
    list_filter = ('consent_overseas', 'captured_at')
    search_fields = ('customer__name', 'owner__email')
    raw_id_fields = ('customer', 'owner')
    readonly_fields = ('owner', 'customer', 'share_token', 'payload', 'consent_overseas',
                       'consent_doc_version', 'consent_scopes', 'dict_version',
                       'insurance_count', 'captured_at', 'retention_expires_at')
    ordering = ('-captured_at',)

    def has_add_permission(self, request):
        return False  # 서버 자동 캡처 전용 — 수기 추가 금지

    def has_change_permission(self, request, obj=None):
        return False  # append-only(값 불변)
