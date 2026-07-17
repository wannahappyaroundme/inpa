import unittest

from django.core.cache import caches
from django.core.management.base import CommandError
from django.test.runner import DiscoverRunner


class CacheIsolationResultMixin:
    """Make non-transactional cache state obey test isolation boundaries."""

    def startTest(self, test):
        for backend in caches.all():
            backend.clear()
        super().startTest(test)


class CacheIsolatedTextTestResult(
        CacheIsolationResultMixin, unittest.TextTestResult):
    pass


class CacheIsolatedTestRunner(DiscoverRunner):
    """Clear shared cache state before every test in the standard runner."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.parallel == 'auto' or self.parallel > 1:
            raise CommandError(
                'CacheIsolatedTestRunner requires sequential execution; '
                'remove --parallel or use --parallel=1.'
            )

    def get_resultclass(self):
        resultclass = super().get_resultclass()
        if resultclass is None:
            return CacheIsolatedTextTestResult
        return type(
            f'CacheIsolated{resultclass.__name__}',
            (CacheIsolationResultMixin, resultclass),
            {},
        )
