"""인파 백엔드 루트 URL 라우팅."""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import include, path


def health(_request):
    return JsonResponse({'status': 'ok', 'service': 'inpa-be'})


urlpatterns = [
    path('admin/', admin.site.urls),
    path('healthz/', health),
    path('api/v1/auth/', include('inpa.accounts.urls')),
]
