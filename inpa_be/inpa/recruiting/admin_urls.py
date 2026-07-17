from django.urls import path

from .admin_views import (
    AdminRecruitingAuditListView,
    AdminRecruitingCandidateListView,
    AdminRecruitingCandidatePurgeView,
    AdminRecruitingPromotionListView,
    AdminRecruitingSummaryView,
    AdminRecruitingTemplateDetailView,
    AdminRecruitingTemplateListView,
)


urlpatterns = [
    path(
        "admin/recruiting/summary/",
        AdminRecruitingSummaryView.as_view(),
        name="admin-recruiting-summary",
    ),
    path(
        "admin/recruiting/candidates/",
        AdminRecruitingCandidateListView.as_view(),
        name="admin-recruiting-candidates",
    ),
    path(
        "admin/recruiting/candidates/<int:candidate_id>/purge/",
        AdminRecruitingCandidatePurgeView.as_view(),
        name="admin-recruiting-candidate-purge",
    ),
    path(
        "admin/recruiting/templates/",
        AdminRecruitingTemplateListView.as_view(),
        name="admin-recruiting-templates",
    ),
    path(
        "admin/recruiting/templates/<int:template_id>/",
        AdminRecruitingTemplateDetailView.as_view(),
        name="admin-recruiting-template-detail",
    ),
    path(
        "admin/recruiting/promotions/",
        AdminRecruitingPromotionListView.as_view(),
        name="admin-recruiting-promotions",
    ),
    path(
        "admin/recruiting/audit/",
        AdminRecruitingAuditListView.as_view(),
        name="admin-recruiting-audit",
    ),
]
