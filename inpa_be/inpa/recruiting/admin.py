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
admin.site.register(RecruitingCandidate)
admin.site.register(RecruitingConsentLog)
admin.site.register(RecruitingActivity)
admin.site.register(SettlementCheck)
admin.site.register(RecruitingEvent)
