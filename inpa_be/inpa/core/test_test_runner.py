import io
import unittest
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class CacheIsolatedTestRunnerTests(SimpleTestCase):
    def tearDown(self):
        cache.clear()
        super().tearDown()

    def test_result_clears_cache_before_each_test_case(self):
        from inpa.core.test_runner import CacheIsolatedTextTestResult

        observed = []

        def leave_throttle_history():
            cache.set('throttle_insurance_import_1', [1.0] * 600, 3600)

        def next_test_starts_clean():
            observed.append(cache.get('throttle_insurance_import_1'))

        suite = unittest.TestSuite([
            unittest.FunctionTestCase(leave_throttle_history),
            unittest.FunctionTestCase(next_test_starts_clean),
        ])
        runner = unittest.TextTestRunner(
            stream=io.StringIO(),
            resultclass=CacheIsolatedTextTestResult,
            verbosity=0,
        )

        result = runner.run(suite)

        self.assertTrue(result.wasSuccessful())
        self.assertEqual(observed, [None])

    def test_django_test_command_uses_cache_isolated_runner(self):
        self.assertEqual(
            settings.TEST_RUNNER,
            'inpa.core.test_runner.CacheIsolatedTestRunner',
        )

    def test_parallel_runner_is_rejected_before_cache_is_touched(self):
        from inpa.core.test_runner import CacheIsolatedTestRunner

        with mock.patch('inpa.core.test_runner.caches.all') as cache_all:
            with self.assertRaisesMessage(
                    CommandError, 'remove --parallel or use --parallel=1'):
                CacheIsolatedTestRunner(parallel=2)

        cache_all.assert_not_called()

    def test_explicit_single_process_keeps_isolated_result(self):
        from inpa.core.test_runner import (
            CacheIsolatedTestRunner, CacheIsolatedTextTestResult,
        )

        runner = CacheIsolatedTestRunner(parallel=1)

        self.assertEqual(runner.parallel, 1)
        self.assertIs(runner.get_resultclass(), CacheIsolatedTextTestResult)
