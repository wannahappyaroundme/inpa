"""PostgreSQL-only settings for deterministic concurrency release gates."""

from django.core.exceptions import ImproperlyConfigured

from .local import *  # noqa: F401,F403


_database_url = env('DATABASE_URL', default='')  # noqa: F405
if not _database_url:
    raise ImproperlyConfigured(
        'DATABASE_URL is required for config.settings.test_postgres.'
    )

DATABASES = {  # noqa: F405
    'default': env.db('DATABASE_URL'),  # noqa: F405
}
DATABASES['default'].setdefault('OPTIONS', {})['options'] = (
    '-c lock_timeout=5000 -c statement_timeout=30000'
)

# Keep the test runtime self-contained.  In particular, never inherit the
# production DatabaseCache, private object storage, HTTPS redirect, or security
# cookie settings just to exercise PostgreSQL row locks.
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'inpa-postgres-concurrency-tests',
    },
}

# These are inherited from local/base, but restating their authority here makes
# accidental production-settings inheritance fail visibly in review.
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True
TEST_RUNNER = 'inpa.core.test_runner.CacheIsolatedTestRunner'
