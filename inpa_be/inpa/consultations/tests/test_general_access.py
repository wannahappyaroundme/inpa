from django.test import TestCase, override_settings

from inpa.accounts.models import Profile, User
from inpa.consultations.gates import (
    recording_feature_enabled,
    summary_feature_enabled,
)
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRuntimeConfig,
)


@override_settings(
    CONSULTATION_RECORDING_ENABLED=True,
    CONSULTATION_AI_SUMMARY_ENABLED=True,
)
class ConsultationGeneralAccessGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='general-access@example.com',
            password='strong-password',
        )
        Profile.objects.create(user=self.user)

    def _runtime(self, **fields):
        config = ConsultationRuntimeConfig.solo()
        config.recording_enabled = True
        config.ai_summary_enabled = True
        for name, value in fields.items():
            setattr(config, name, value)
        config.save(update_fields=[
            'recording_enabled',
            'ai_summary_enabled',
            'general_access_enabled',
            'updated_at',
        ])
        return config

    def test_general_access_opens_both_gates_without_a_pilot_row(self):
        self._runtime(general_access_enabled=True)

        self.assertFalse(
            ConsultationPilotAccess.objects.filter(user=self.user).exists(),
        )
        self.assertTrue(recording_feature_enabled(self.user))
        self.assertTrue(summary_feature_enabled(self.user))

    @override_settings(
        SHOWCASE_ACCOUNT_EMAIL='general-access@example.com',
        CONSULTATION_SHOWCASE_PILOT_ENABLED=False,
    )
    def test_general_access_keeps_the_showcase_account_closed(self):
        self.user.profile.is_showcase = True
        self.user.profile.save(update_fields=['is_showcase'])
        self._runtime(general_access_enabled=True)

        self.assertFalse(recording_feature_enabled(self.user))
        self.assertFalse(summary_feature_enabled(self.user))

    def test_general_access_still_follows_the_runtime_recording_switch(self):
        self._runtime(general_access_enabled=True, recording_enabled=False)

        self.assertFalse(recording_feature_enabled(self.user))
        self.assertTrue(summary_feature_enabled(self.user))

    def test_general_access_still_follows_the_runtime_summary_switch(self):
        self._runtime(general_access_enabled=True, ai_summary_enabled=False)

        self.assertFalse(summary_feature_enabled(self.user))
        self.assertTrue(recording_feature_enabled(self.user))

    @override_settings(CONSULTATION_RECORDING_ENABLED=False)
    def test_general_access_cannot_open_a_closed_environment_gate(self):
        self._runtime(general_access_enabled=True)

        self.assertFalse(recording_feature_enabled(self.user))

    def test_pilot_rules_stay_in_place_while_general_access_is_off(self):
        self._runtime(general_access_enabled=False)

        self.assertFalse(recording_feature_enabled(self.user))
        self.assertFalse(summary_feature_enabled(self.user))

        access = ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
            summary_allowed=False,
        )
        self.assertTrue(recording_feature_enabled(self.user))
        self.assertFalse(summary_feature_enabled(self.user))

        access.summary_allowed = True
        access.save(update_fields=['summary_allowed', 'updated_at'])
        self.assertTrue(summary_feature_enabled(self.user))

    def test_general_access_defaults_to_off(self):
        self.assertFalse(ConsultationRuntimeConfig.solo().general_access_enabled)
