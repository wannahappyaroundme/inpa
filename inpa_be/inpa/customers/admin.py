"""고객 도메인 admin — 운영 조회용(관리자 bypass). 비개발자 접근 가능."""
from django.contrib import admin

from .models import (
    ConsentLog, Customer, CustomerMedicalHistory, CustomerTag, FamilyMember,
    JobRiskCode, PlannerBaseline,
)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'owner', 'mobile_phone_number', 'consent_overseas_at', 'created_at')
    list_filter = ('gender',)
    search_fields = ('name', 'mobile_phone_number')
    raw_id_fields = ('owner', 'job_code')


@admin.register(CustomerTag)
class CustomerTagAdmin(admin.ModelAdmin):
    list_display = ('id', 'label', 'owner', 'color')
    search_fields = ('label',)
    raw_id_fields = ('owner',)


@admin.register(FamilyMember)
class FamilyMemberAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'relation', 'name')
    raw_id_fields = ('customer',)


@admin.register(CustomerMedicalHistory)
class CustomerMedicalHistoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'disease_name', 'is_inpatient', 'created_at')
    raw_id_fields = ('customer',)


@admin.register(ConsentLog)
class ConsentLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'customer', 'scope', 'subject', 'doc_version', 'agreed_at', 'revoked_at')
    list_filter = ('scope', 'subject')
    raw_id_fields = ('customer',)
    # append-only — admin에서도 수정/삭제 금지(감사 무결성)
    readonly_fields = ('agreed_at',)

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(PlannerBaseline)
class PlannerBaselineAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'coverage_key', 'product_group', 'age_band',
                    'gender', 'baseline_source', 'is_active')
    list_filter = ('product_group', 'baseline_source', 'is_active')
    raw_id_fields = ('owner',)


@admin.register(JobRiskCode)
class JobRiskCodeAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'risk_grade', 'source')
    search_fields = ('name', 'sctg_cd')
