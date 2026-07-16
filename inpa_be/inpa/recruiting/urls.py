from django.urls import path
from rest_framework.routers import SimpleRouter

from .public_views import (
    PublicRecruitingCampaignView,
    PublicRecruitingLeaderChoiceView,
    PublicRecruitingManageView,
)
from .views import (
    RecruitingCampaignCopiedView,
    RecruitingCampaignView,
    RecruitingCandidateViewSet,
    RecruitingPageView,
    RecruitingTemplateListView,
)


app_name = "recruiting"

router = SimpleRouter()
router.register("recruiting/candidates", RecruitingCandidateViewSet, basename="recruiting-candidate")

urlpatterns = router.urls + [
    path("recruiting/page/", RecruitingPageView.as_view(), name="page"),
    path("recruiting/templates/", RecruitingTemplateListView.as_view(), name="templates"),
    path("recruiting/campaign/", RecruitingCampaignView.as_view(), name="campaign"),
    path("recruiting/campaign/copied/", RecruitingCampaignCopiedView.as_view(), name="campaign-copied"),
    path("r/manage/<uuid:token>/", PublicRecruitingManageView.as_view(), name="public-manage"),
    path("r/choice/<str:token>/", PublicRecruitingLeaderChoiceView.as_view(), name="public-choice"),
    path("r/<uuid:token>/", PublicRecruitingCampaignView.as_view(), name="public-page"),
]
