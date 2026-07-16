from django.contrib import admin

from .models import (
    RecruitingActivity,
    RecruitingCampaign,
    RecruitingCandidate,
    RecruitingConsentLog,
    RecruitingCopyTemplate,
    RecruitingEvent,
    RecruitingPage,
    SettlementCheck,
)


admin.site.register(RecruitingCopyTemplate)
admin.site.register(RecruitingPage)
admin.site.register(RecruitingCampaign)


class ReadOnlyAdmin(admin.ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RecruitingCandidate)
class RecruitingCandidateAdmin(ReadOnlyAdmin):
    exclude = ("identity_ref",)
    list_display = ("id", "stage", "campaign", "created_at", "retention_expires_at")
    list_filter = ("stage",)
    search_fields = ()


@admin.register(RecruitingConsentLog)
class RecruitingConsentLogAdmin(ReadOnlyAdmin):
    list_display = ("id", "scope", "doc_version", "agreed_at", "revoked_at")


@admin.register(RecruitingActivity)
class RecruitingActivityAdmin(ReadOnlyAdmin):
    list_display = (
        "id",
        "candidate_ref",
        "event_type",
        "from_stage",
        "to_stage",
        "actor_id",
        "created_at",
    )


@admin.register(SettlementCheck)
class SettlementCheckAdmin(ReadOnlyAdmin):
    list_display = ("id", "week", "due_on", "state", "completed_at")


@admin.register(RecruitingEvent)
class RecruitingEventAdmin(ReadOnlyAdmin):
    list_display = ("id", "event_type", "channel", "created_at")
