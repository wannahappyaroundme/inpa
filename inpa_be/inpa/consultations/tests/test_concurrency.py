import uuid

from django.db import IntegrityError, transaction
from django.test import TestCase

from inpa.accounts.models import User
from inpa.consultations.models import ConsultationRecording
from inpa.customers.models import Customer


class ActiveUploadConstraintTests(TestCase):
    def test_database_allows_only_one_uploading_recording_per_customer(self):
        user = User.objects.create_user(
            email='recording-concurrency@test.com',
            password='inpaPass123!',
        )
        customer = Customer.objects.create(owner=user, name='김보장')
        ConsultationRecording.objects.create(
            owner=user,
            customer=customer,
            status=ConsultationRecording.STATUS_UPLOADING,
            storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
            mime_type='audio/webm',
        )

        with self.assertRaises(IntegrityError), transaction.atomic():
            ConsultationRecording.objects.create(
                owner=user,
                customer=customer,
                status=ConsultationRecording.STATUS_UPLOADING,
                storage_key=f'consultation-recordings/{uuid.uuid4()}/source',
                mime_type='audio/webm',
            )
