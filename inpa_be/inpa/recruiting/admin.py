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
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(RecruitingCandidate)
class RecruitingCandidateAdmin(ReadOnlyAdmin):
    fields = (
        "id",
        "campaign",
        "career_band",
        "contact_window",
        "selection_status",
        "stage",
        "next_action",
        "next_action_at",
        "last_contacted_at",
        "joined_at",
        "ended_at",
        "retention_expires_at",
        "contact_opt_out_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields
    exclude = ("identity_ref",)
    list_display = ("id", "stage", "campaign", "created_at", "retention_expires_at")
    list_filter = ("stage",)
    search_fields = ()


@admin.register(RecruitingConsentLog)
class RecruitingConsentLogAdmin(ReadOnlyAdmin):
    fields = ("id", "scope", "doc_version", "agreed_at", "revoked_at")
    readonly_fields = fields
    list_display = ("id", "scope", "doc_version", "agreed_at", "revoked_at")


@admin.register(RecruitingActivity)
class RecruitingActivityAdmin(ReadOnlyAdmin):
    fields = (
        "id",
        "candidate_ref",
        "event_type",
        "from_stage",
        "to_stage",
        "actor_id",
        "created_at",
    )
    readonly_fields = fields
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
    fields = (
        "id",
        "week",
        "due_on",
        "state",
        "blocker",
        "next_support",
        "completed_at",
        "created_at",
        "updated_at",
    )
    readonly_fields = fields
    list_display = ("id", "week", "due_on", "state", "completed_at")


@admin.register(RecruitingEvent)
class RecruitingEventAdmin(ReadOnlyAdmin):
    fields = ("id", "event_type", "channel", "created_at")
    readonly_fields = fields
    list_display = ("id", "event_type", "channel", "created_at")
