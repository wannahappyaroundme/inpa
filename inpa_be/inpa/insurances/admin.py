"""보험 도메인 관리자 화면."""

from django.contrib import admin

from .models import (
    InsuranceExtractionJob,
    InsuranceExtractionResult,
    InsuranceImportCommand,
    InsuranceImportCreateRequest,
    InsuranceImportRuntimeConfig,
    ManualInsuranceCommand,
)


class ReadOnlySystemRecordAdmin(admin.ModelAdmin):
    """시스템 작업 기록은 관리자 화면에서 조회만 허용한다."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(InsuranceExtractionJob)
class InsuranceExtractionJobAdmin(ReadOnlySystemRecordAdmin):
    list_display = [
        'id', 'owner', 'customer_id', 'intent', 'portfolio_type', 'status',
        'attempt_count', 'lease_expired_count', 'created_at', 'completed_at',
    ]
    list_filter = ['status', 'intent', 'portfolio_type', 'error_type']
    search_fields = ['id', 'owner__email']
    ordering = ['-created_at']
    exclude = [
        'source_storage_key', 'safe_display_name', 'masked_lines',
        'draft_payload', 'validation_summary',
    ]


@admin.register(InsuranceExtractionResult)
class InsuranceExtractionResultAdmin(ReadOnlySystemRecordAdmin):
    list_display = [
        'job_id', 'provider', 'model_id', 'outcome', 'input_tokens',
        'output_tokens', 'estimated_cost_krw', 'latency_ms', 'created_at',
    ]
    list_filter = ['provider', 'outcome']
    search_fields = ['job__id']
    ordering = ['-created_at']
    exclude = ['structured_payload']


@admin.register(InsuranceImportCommand)
class InsuranceImportCommandAdmin(ReadOnlySystemRecordAdmin):
    list_display = [
        'job_id', 'operation', 'response_status', 'created_at', 'completed_at',
    ]
    list_filter = ['operation', 'response_status']
    search_fields = ['job__id']
    ordering = ['-created_at']
    exclude = ['response_body']


@admin.register(ManualInsuranceCommand)
class ManualInsuranceCommandAdmin(ReadOnlySystemRecordAdmin):
    list_display = [
        'insurance_id', 'operation', 'response_status',
        'created_at', 'completed_at',
    ]
    list_filter = ['operation', 'response_status']
    ordering = ['-created_at']
    exclude = ['idempotency_key', 'request_sha256', 'response_body']


@admin.register(InsuranceImportCreateRequest)
class InsuranceImportCreateRequestAdmin(ReadOnlySystemRecordAdmin):
    list_display = [
        'id', 'owner_id', 'job_id', 'resolution_job_id', 'response_status',
        'created_at', 'completed_at',
    ]
    list_filter = ['response_status']
    search_fields = ['owner__email', 'job__id']
    ordering = ['-created_at']
    exclude = ['idempotency_key', 'request_sha256', 'response_body']


@admin.register(InsuranceImportRuntimeConfig)
class InsuranceImportRuntimeConfigAdmin(admin.ModelAdmin):
    list_display = [
        'per_owner_concurrency', 'global_concurrency',
        'force_manual_carrier_codes', 'updated_at',
    ]
    readonly_fields = ['updated_at']

    def has_add_permission(self, request):
        return not InsuranceImportRuntimeConfig.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
