from django.conf import settings

from .models import ConsultationPilotAccess, ConsultationRuntimeConfig


def recording_feature_enabled(user=None):
    if not settings.CONSULTATION_RECORDING_ENABLED:
        return False
    if not ConsultationRuntimeConfig.solo().recording_enabled:
        return False
    if user is None:
        return True
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.is_admin:
        return True
    access = ConsultationPilotAccess.objects.filter(user=user).first()
    return bool(access and access.recording_allowed)


def summary_feature_enabled(user=None):
    if not settings.CONSULTATION_AI_SUMMARY_ENABLED:
        return False
    if not ConsultationRuntimeConfig.solo().ai_summary_enabled:
        return False
    if user is None:
        return True
    profile = getattr(user, 'profile', None)
    if profile is not None and profile.is_admin:
        return True
    access = ConsultationPilotAccess.objects.filter(user=user).first()
    return bool(access and access.summary_allowed)
