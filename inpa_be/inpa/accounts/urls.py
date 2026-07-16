"""계정 도메인 라우팅 — base: /api/v1/auth/ (dev/00-INDEX 정본)."""
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('verify-email/', views.VerifyEmailView.as_view(), name='verify-email'),
    path('resend-verification/', views.ResendVerificationView.as_view(), name='resend-verification'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('logout/', views.LogoutView.as_view(), name='logout'),
    path('password-reset/', views.PasswordResetView.as_view(), name='password-reset'),
    path('password-reset/confirm/', views.PasswordResetConfirmView.as_view(), name='password-reset-confirm'),
    path('password/change/', views.PasswordChangeView.as_view(), name='password-change'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('manager-promotion/ack/', views.ManagerPromotionAckView.as_view(),
         name='manager-promotion-ack'),
    path('withdraw/', views.WithdrawView.as_view(), name='withdraw'),
    path('onboarding/attest/', views.OnboardingAttestView.as_view(), name='onboarding-attest'),
    # ── 구글 연동 ──
    path('google/', views.GoogleLoginView.as_view(), name='google-login'),
    path('google/calendar/connect/', views.GoogleCalendarConnectView.as_view(), name='google-calendar-connect'),
    path('google/calendar/callback/', views.GoogleCalendarCallbackView.as_view(), name='google-calendar-callback'),
    path('google/calendar/disconnect/', views.GoogleCalendarDisconnectView.as_view(), name='google-calendar-disconnect'),
]
