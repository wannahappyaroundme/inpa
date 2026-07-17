import io
import uuid
from types import SimpleNamespace
from unittest import mock

from django.test import SimpleTestCase

from .import_storage import (
    SourceAlreadyExists,
    SourceNamespaceMismatch,
    assert_source_namespace,
    delete_source,
    save_source,
    source_key,
)


_DEFAULT_JOB_ID = uuid.UUID('00000000-0000-0000-0000-000000000123')


def _job(*, owner=17, customer=41,
         job_id=_DEFAULT_JOB_ID,
         stored_key=''):
    return SimpleNamespace(
        owner_id=owner,
        customer_id=customer,
        id=job_id,
        source_storage_key=stored_key,
    )


class ImportSourceStorageTests(SimpleTestCase):
    def test_source_key_contains_exact_owner_customer_and_job_namespace(self):
        job = _job()
        self.assertEqual(
            source_key(job),
            'insurance-imports/17/41/'
            '00000000-0000-0000-0000-000000000123/source.pdf',
        )

    def test_each_owner_customer_and_job_dimension_changes_the_key(self):
        keys = {
            source_key(_job()),
            source_key(_job(owner=18)),
            source_key(_job(customer=42)),
            source_key(_job(
                job_id=uuid.UUID('00000000-0000-0000-0000-000000000124'))),
        }
        self.assertEqual(len(keys), 4)

    def test_namespace_mismatch_fails_closed(self):
        job = _job()
        with self.assertRaises(SourceNamespaceMismatch):
            assert_source_namespace(
                job,
                'insurance-imports/18/41/'
                '00000000-0000-0000-0000-000000000123/source.pdf',
            )

    def test_missing_or_blank_namespace_components_fail_closed(self):
        invalid_jobs = (
            _job(owner=None),
            _job(owner=0),
            _job(owner=-1),
            _job(customer=None),
            _job(customer=''),
            _job(customer='   '),
            _job(job_id=None),
            _job(job_id=''),
            _job(job_id='   '),
        )

        for job in invalid_jobs:
            with self.subTest(job=job), self.assertRaises(
                    SourceNamespaceMismatch):
                source_key(job)

    def test_path_traversal_components_fail_closed(self):
        invalid_jobs = (
            _job(owner='../17'),
            _job(owner='17/18'),
            _job(customer='../41'),
            _job(customer='41/42'),
            _job(job_id='../00000000-0000-0000-0000-000000000123'),
        )

        for job in invalid_jobs:
            with self.subTest(job=job), self.assertRaises(
                    SourceNamespaceMismatch):
                source_key(job)

    def test_noncanonical_ids_cannot_alias_the_same_namespace(self):
        for job in (
                _job(owner='17'),
                _job(customer='41'),
                _job(job_id=str(_DEFAULT_JOB_ID))):
            with self.subTest(job=job), self.assertRaises(
                    SourceNamespaceMismatch):
                source_key(job)

    def test_save_uses_private_alias_and_exact_key(self):
        job = _job()
        key = source_key(job)
        storage = mock.Mock()
        storage.exists.return_value = False
        storage.save.return_value = key
        upload = io.BytesIO(b'%PDF-1.7')

        with mock.patch(
                'inpa.insurances.import_storage.storages',
                {'insurance_sources': storage}):
            stored_key = save_source(job, upload)

        self.assertEqual(stored_key, key)
        storage.save.assert_called_once_with(key, upload)

    def test_existing_exact_key_is_not_silently_renamed_or_overwritten(self):
        job = _job()
        storage = mock.Mock()
        storage.exists.return_value = True

        with self.assertRaises(SourceAlreadyExists):
            save_source(job, io.BytesIO(b'%PDF-1.7'), storage=storage)

        storage.save.assert_not_called()

    def test_storage_returning_renamed_key_fails_closed(self):
        job = _job()
        storage = mock.Mock()
        storage.exists.return_value = False
        storage.save.return_value = source_key(job).replace(
            'source.pdf', 'source_renamed.pdf')

        with self.assertRaises(SourceNamespaceMismatch):
            save_source(job, io.BytesIO(b'%PDF-1.7'), storage=storage)

        storage.delete.assert_called_once_with(storage.save.return_value)

    def test_delete_calls_one_exact_key_only(self):
        job = _job()
        key = source_key(job)
        job.source_storage_key = key
        storage = mock.Mock()

        delete_source(job, storage=storage)

        storage.delete.assert_called_once_with(key)
        self.assertEqual(storage.method_calls, [mock.call.delete(key)])

    def test_delete_rejects_foreign_key_before_touching_storage(self):
        job = _job(stored_key='insurance-imports/foreign/1/job/source.pdf')
        storage = mock.Mock()

        with self.assertRaises(SourceNamespaceMismatch):
            delete_source(job, storage=storage)

        storage.delete.assert_not_called()

    def test_explicit_empty_delete_key_does_not_fall_back(self):
        job = _job(stored_key=source_key(_job()))
        storage = mock.Mock()

        with self.assertRaises(SourceNamespaceMismatch):
            delete_source(job, key='', storage=storage)

        storage.delete.assert_not_called()
