import secrets
import uuid

from django.core.files.storage import storages


class SourceNamespaceMismatch(Exception):
    pass


class SourceAlreadyExists(Exception):
    pass


def _owner_namespace(value):
    # accounts.User keeps Django's positive integer primary key.  Using the
    # email here made every real InsuranceExtractionJob fail even though the
    # old storage unit tests passed with an email-shaped double.
    if type(value) is not int or value <= 0:
        raise SourceNamespaceMismatch
    return str(value)


def _customer_namespace(value):
    if type(value) is not int or value <= 0:
        raise SourceNamespaceMismatch
    return str(value)


def _job_namespace(value):
    if not isinstance(value, uuid.UUID):
        raise SourceNamespaceMismatch
    return str(value)


def source_key(job):
    owner_id = _owner_namespace(job.owner_id)
    customer_id = _customer_namespace(job.customer_id)
    job_id = _job_namespace(job.id)
    return (
        f'insurance-imports/{owner_id}/{customer_id}/'
        f'{job_id}/source.pdf'
    )


def assert_source_namespace(job, key):
    expected = source_key(job)
    if not isinstance(key, str) or not secrets.compare_digest(key, expected):
        raise SourceNamespaceMismatch


def _source_storage():
    return storages['insurance_sources']


def save_source(job, uploaded_file, *, storage=None):
    storage = storage or _source_storage()
    key = source_key(job)
    assert_source_namespace(job, key)
    if storage.exists(key):
        raise SourceAlreadyExists
    uploaded_file.seek(0)
    stored_key = storage.save(key, uploaded_file)
    try:
        assert_source_namespace(job, stored_key)
    except SourceNamespaceMismatch:
        expected_directory = key.rsplit('/', 1)[0]
        if (isinstance(stored_key, str)
                and stored_key.rsplit('/', 1)[0] == expected_directory):
            storage.delete(stored_key)
        raise
    return stored_key


def delete_source(job, *, key=None, storage=None):
    storage = storage or _source_storage()
    exact_key = (
        key if key is not None
        else job.source_storage_key or source_key(job)
    )
    assert_source_namespace(job, exact_key)
    storage.delete(exact_key)
