"""인파 백엔드 루트 URL 라우팅."""
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path

from inpa.accounts.invite import TeamInviteInfoView, TeamInviteLinkView
from inpa.accounts.manager import ManagerDashboardView
from inpa.accounts.public import IntroductionCardView


def health(_request):
    return JsonResponse({'status': 'ok', 'service': 'inpa-be'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health),
    path('api/v1/manager/dashboard/', ManagerDashboardView.as_view(), name='manager-dashboard'),
    path('api/v1/manager/invite-link/', TeamInviteLinkView.as_view(), name='manager-invite-link'),
    path('api/v1/manager/invite-info/', TeamInviteInfoView.as_view(), name='manager-invite-info'),
    path('api/v1/p/<str:refcode>/', IntroductionCardView.as_view(), name='public-intro-card'),
    path('api/v1/auth/', include('inpa.accounts.urls')),
    path('api/v1/', include('inpa.customers.urls')),
    path('api/v1/', include('inpa.analysis.urls')),
    path('api/v1/', include('inpa.insurances.urls')),
    path('api/v1/', include('inpa.notifications.urls')),
    path('api/v1/', include('inpa.billing.urls')),
    path('api/v1/', include('inpa.boards.urls')),
    path('api/v1/', include('inpa.promotion.urls')),
    path('api/v1/', include('inpa.admin_console.urls')),
    path('api/v1/', include('inpa.analytics.urls')),
    path('api/v1/', include('inpa.booking.urls')),
    path('api/v1/', include('inpa.dashboard.urls')),
    path('api/v1/', include('inpa.schedule.urls')),
]

# 업로드 미디어(명함 등) — 개발 서버에서만 Django가 서빙. 운영은 whitenoise/오브젝트 스토리지.
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
