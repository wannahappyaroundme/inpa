"""보험 라우팅 — 증권 OCR 업로드 (dev/02 §7, dev/12 §5).

base 는 config/urls.py 에서 /api/v1/ 로 마운트.
  POST /api/v1/customers/<customer_pk>/insurances/ocr/   InsuranceOcrViewSet (★동의 게이트)

하위 라우트는 외부 패키지(drf-nested-routers) 없이 ViewSet.as_view 매핑으로 명시
(customers/urls.py 와 동일 패턴 — 외부 의존 최소화).
"""
from django.urls import path

from .churn import ChurnRadarView, ChurnSyncAlertsView, InsuranceChurnView
from .import_views import (
    InsuranceImportCancelView,
    InsuranceImportConfirmView,
    InsuranceImportCollectionView,
    InsuranceImportConfigView,
    InsuranceImportDetailView,
    InsuranceImportDraftView,
    InsuranceImportSourcePreviewView,
    InsuranceImportSourceURLView,
)
from .self_diagnosis import SelfDiagnosisView
from .views import (
    CustomerInsuranceManualViewSet,
    InsuranceOcrViewSet,
    ManualCoverageCollectionView,
    ManualCoverageDetailView,
    ManualInsuranceConfirmView,
    ManualInsuranceExcludeView,
)

app_name = 'insurances'

urlpatterns = [
    path('customers/<int:customer_pk>/insurance-imports/',
         InsuranceImportCollectionView.as_view(),
         name='insurance-import-collection'),
    path('insurance-imports/config/',
         InsuranceImportConfigView.as_view(),
         name='insurance-import-config'),
    path('insurance-imports/source/<str:token>/',
         InsuranceImportSourcePreviewView.as_view(),
         name='insurance-import-source-preview'),
    path('insurance-imports/<uuid:job_id>/',
         InsuranceImportDetailView.as_view(),
         name='insurance-import-detail'),
    path('insurance-imports/<uuid:job_id>/draft/',
         InsuranceImportDraftView.as_view(),
         name='insurance-import-draft'),
    path('insurance-imports/<uuid:job_id>/cancel/',
         InsuranceImportCancelView.as_view(),
         name='insurance-import-cancel'),
    path('insurance-imports/<uuid:job_id>/confirm/',
         InsuranceImportConfirmView.as_view(),
         name='insurance-import-confirm'),
    path('insurance-imports/<uuid:job_id>/source-url/',
         InsuranceImportSourceURLView.as_view(),
         name='insurance-import-source-url'),
    path('customers/<int:customer_pk>/insurances/ocr/',
         InsuranceOcrViewSet.as_view({'post': 'create'}),
         name='insurance-ocr-upload'),
    # 수기 보험 등록(보유/제안) — OCR 폴백 + 제안 입력. owner 전용.
    path('customers/<int:customer_pk>/insurances/manual/',
         CustomerInsuranceManualViewSet.as_view({'get': 'list', 'post': 'create'}),
         name='insurance-manual-list'),
    path('customers/<int:customer_pk>/insurances/manual/<int:pk>/',
         CustomerInsuranceManualViewSet.as_view(
             {'get': 'retrieve', 'patch': 'partial_update', 'delete': 'destroy'}),
         name='insurance-manual-detail'),
    path(
        'customers/<int:customer_pk>/insurances/manual/'
        '<int:insurance_pk>/coverages/',
        ManualCoverageCollectionView.as_view(),
        name='insurance-manual-coverage-list'),
    path(
        'customers/<int:customer_pk>/insurances/manual/'
        '<int:insurance_pk>/coverages/<int:case_pk>/',
        ManualCoverageDetailView.as_view(),
        name='insurance-manual-coverage-detail'),
    path(
        'customers/<int:customer_pk>/insurances/manual/'
        '<int:insurance_pk>/confirm/',
        ManualInsuranceConfirmView.as_view(),
        name='insurance-manual-confirm'),
    path(
        'customers/<int:customer_pk>/insurances/manual/'
        '<int:insurance_pk>/exclude/',
        ManualInsuranceExcludeView.as_view(),
        name='insurance-manual-exclude'),
    # 환수 레이더(A/S) — 집계 GET + 수기 PATCH + 문제 알림 동기화
    path('churn-radar/', ChurnRadarView.as_view(), name='churn-radar'),
    path('churn-radar/sync-alerts/', ChurnSyncAlertsView.as_view(), name='churn-sync-alerts'),
    path('insurances/<int:pk>/churn/', InsuranceChurnView.as_view(), name='insurance-churn'),
    # 셀프진단 인바운드(공개) — 잠재고객 본인 증권 진단 → 설계사 리드
    path('d/<str:refcode>/', SelfDiagnosisView.as_view(), name='self-diagnosis'),
]
