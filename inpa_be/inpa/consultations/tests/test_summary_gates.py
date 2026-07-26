from django.test import TestCase, override_settings

from inpa.accounts.models import User
from inpa.consultations.gates import summary_feature_enabled
from inpa.consultations.models import (
    ConsultationPilotAccess,
    ConsultationRuntimeConfig,
)
from inpa.customers.consent_texts import (
    CONSULTATION_CONSENT_VERSIONS,
    has_current_consultation_summary_consents,
)
from inpa.customers.models import ConsentLog, Customer


class ConsultationSummaryGateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email='summary-gate@example.com',
            password='strong-password',
        )
        self.customer = Customer.objects.create(
            owner=self.user,
            name='요약 게이트 고객',
        )

    def _grant(self, scope, version):
        ConsentLog.objects.create(
            customer=self.customer,
            scope=scope,
            subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
            purpose='상담 요약 테스트',
            doc_version=version,
        )

    def test_summary_requires_all_three_customer_self_current_versions(self):
        for scope, version in CONSULTATION_CONSENT_VERSIONS.items():
            self._grant(scope, version)
        self.assertFalse(
            has_current_consultation_summary_consents(self.customer),
        )

        self._grant(
            ConsentLog.SCOPE_CONSULTATION_OVERSEAS_SUMMARY,
            'v1-2026-07-22',
        )

        self.assertTrue(
            has_current_consultation_summary_consents(self.customer),
        )

    @override_settings(CONSULTATION_AI_SUMMARY_ENABLED=False)
    def test_runtime_switch_does_not_override_closed_ai_environment_gate(self):
        config = ConsultationRuntimeConfig.solo()
        config.ai_summary_enabled = True
        config.save(update_fields=['ai_summary_enabled', 'updated_at'])
        ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
            summary_allowed=True,
        )

        self.assertFalse(summary_feature_enabled(self.user))

    @override_settings(CONSULTATION_AI_SUMMARY_ENABLED=True)
    def test_summary_requires_runtime_and_pilot_switches(self):
        config = ConsultationRuntimeConfig.solo()
        config.ai_summary_enabled = True
        config.save(update_fields=['ai_summary_enabled', 'updated_at'])
        access = ConsultationPilotAccess.objects.create(
            user=self.user,
            recording_allowed=True,
            summary_allowed=False,
        )
        self.assertFalse(summary_feature_enabled(self.user))

        access.summary_allowed = True
        access.save(update_fields=['summary_allowed', 'updated_at'])
        self.assertTrue(summary_feature_enabled(self.user))
