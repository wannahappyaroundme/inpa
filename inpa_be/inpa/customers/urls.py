"""고객 도메인 라우팅 (dev/02 §0, dev/12 §5).

base는 config/urls.py에서 /api/v1/로 마운트.
  /api/v1/customers/                          CustomerViewSet
  /api/v1/customers/{customer_pk}/family/     FamilyMemberViewSet
  /api/v1/customers/{customer_pk}/medical/    CustomerMedicalHistoryViewSet (★동의 게이트)
  /api/v1/customers/{customer_pk}/consents/   ConsentLogViewSet (append-only)
  /api/v1/customer-tags/                      CustomerTagViewSet
  /api/v1/planner-baselines/                  PlannerBaselineViewSet

하위 라우트는 drf-nested-routers 의존 없이 DRF ViewSet.as_view 매핑으로 명시(외부 패키지 최소화).
"""
from django.urls import path
from rest_framework.routers import SimpleRouter

from . import views
from .public_consent import PublicConsentView

app_name = 'customers'

router = SimpleRouter()
router.register('customers', views.CustomerViewSet, basename='customer')
router.register('customer-tags', views.CustomerTagViewSet, basename='customer-tag')
router.register('planner-baselines', views.PlannerBaselineViewSet, basename='planner-baseline')


def _nested(viewset):
    return {
        'list': viewset.as_view({'get': 'list', 'post': 'create'}),
        'detail': viewset.as_view({'get': 'retrieve', 'put': 'update',
                                   'patch': 'partial_update', 'delete': 'destroy'}),
    }


_family = _nested(views.FamilyMemberViewSet)
_medical = _nested(views.CustomerMedicalHistoryViewSet)
_consent = _nested(views.ConsentLogViewSet)
_checklist = _nested(views.ContractChecklistViewSet)

urlpatterns = router.urls + [
    path('customers/<int:customer_pk>/family/', _family['list'], name='family-list'),
    path('customers/<int:customer_pk>/family/<int:pk>/', _family['detail'], name='family-detail'),
    path('customers/<int:customer_pk>/medical/', _medical['list'], name='medical-list'),
    path('customers/<int:customer_pk>/medical/<int:pk>/', _medical['detail'], name='medical-detail'),
    path('customers/<int:customer_pk>/consents/', _consent['list'], name='consent-list'),
    path('customers/<int:customer_pk>/consents/<int:pk>/', _consent['detail'], name='consent-detail'),
    # 계약 설명의무 체크리스트 (PM 06.24)
    path('customers/<int:customer_pk>/checklist/', _checklist['list'], name='checklist-list'),
    path('customers/<int:customer_pk>/checklist/apply-template/',
         views.ContractChecklistViewSet.as_view({'post': 'apply_template'}), name='checklist-template'),
    path('customers/<int:customer_pk>/checklist/<int:pk>/', _checklist['detail'], name='checklist-detail'),
    path('customers/<int:customer_pk>/checklist/<int:pk>/toggle/',
         views.ContractChecklistViewSet.as_view({'post': 'toggle'}), name='checklist-toggle'),
    # P3c — 동의 요청 링크 생성(설계사) + 고객 본인 동의(공개)
    path('customers/<int:customer_pk>/consent-requests/',
         views.ConsentRequestCreateView.as_view(), name='consent-request-create'),
    path('c/<str:token>/', PublicConsentView.as_view(), name='public-consent'),
]
