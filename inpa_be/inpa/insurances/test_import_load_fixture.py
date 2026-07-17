import json
import re
import stat
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import pdfplumber
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from scripts.load import insurance_import_concurrency as load_runner

from inpa.accounts.models import Profile, User
from inpa.analysis.models import (
    AnalysisCategory,
    AnalysisDetail,
    AnalysisSubCategory,
)
from inpa.billing.models import Plan

from .models import (
    InsuranceCategory,
    InsuranceDetail,
    InsuranceExtractionJob,
    InsuranceSubCategory,
)
from .management.commands import prepare_insurance_load_fixture as prepare_command


SYNTHETIC_MARKER = 'INPA_SYNTHETIC_LOAD_FIXTURE_V1'
SYNTHETIC_EMAILS = {
    f'inpa-load-owner-{index:02d}@load.inpa.invalid'
    for index in range(1, 21)
}
STAGING_DATABASE_NAME = 'inpa_insurance_staging'
STAGING_BUCKET_NAME = 'inpa-insurance-staging'
STAGING_STORAGES = {
    'default': {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {'bucket_name': STAGING_BUCKET_NAME},
    },
    'insurance_sources': {
        'BACKEND': 'storages.backends.s3.S3Storage',
        'OPTIONS': {
            'bucket_name': STAGING_BUCKET_NAME,
            'location': 'insurance-sources',
        },
    },
    'staticfiles': {
        'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
    },
}


def _service_block(text, service_name):
    for block in re.split(r'(?=^  - type:)', text, flags=re.MULTILINE):
        if re.search(
                rf'^    name: {re.escape(service_name)}$',
                block, flags=re.MULTILINE):
            return block
    raise AssertionError(f'Missing service contract: {service_name}')


class InsuranceLoadRenderContractTests(TestCase):
    def test_production_cleanup_uses_the_production_queue(self):
        repo_root = Path(__file__).resolve().parents[3]
        text = (repo_root / 'render.yaml').read_text(encoding='utf-8')

        cleanup = _service_block(text, 'inpa-insurance-source-cleanup')

        self.assertRegex(
            cleanup,
            r'- key: REDIS_URL\s+fromService:\s+type: keyvalue\s+'
            r'name: inpa-insurance-queue\s+property: connectionString',
        )
        self.assertNotIn('INSURANCE_LOAD_TEST_ENABLED', text)

    def test_staging_blueprint_has_only_distinct_closed_staging_services(self):
        repo_root = Path(__file__).resolve().parents[3]
        text = (repo_root / 'render.staging.yaml').read_text(encoding='utf-8')
        staging_names = {
            'inpa-be-staging',
            'inpa-insurance-queue-staging',
            'inpa-insurance-worker-staging',
            'inpa-insurance-source-cleanup-staging',
        }

        declared = set(re.findall(
            r'^  - type: [a-z]+\n    name: ([A-Za-z0-9-]+)$',
            text,
            re.MULTILINE,
        ))
        self.assertEqual(declared, staging_names)
        self.assertFalse({
            'inpa-be', 'inpa-insurance-queue', 'inpa-insurance-worker',
            'inpa-insurance-source-cleanup',
        } & declared)
        for service_name in staging_names:
            block = _service_block(text, service_name)
            if service_name != 'inpa-insurance-queue-staging':
                for gate in (
                        'INSURANCE_REVIEW_GATE_ENABLED',
                        'INSURANCE_LOAD_TEST_ENABLED',
                        'COMPARE_AI_ENABLED',
                        'COMPARE_PUBLISH_ENABLED',
                        'ANALYZE_MEDICAL_ENABLED'):
                    self.assertRegex(
                        block,
                        rf'- key: {gate}\s+value: "False"',
                    )
                self.assertRegex(
                    block,
                    r'- key: DATABASE_URL\s+fromDatabase:\s+'
                    r'name: inpa-insurance-db-staging\s+'
                    r'property: connectionString',
                )
        self.assertRegex(
            text,
            r'(?ms)^databases:\s+- name: inpa-insurance-db-staging\s+'
            r'databaseName: inpa_insurance_staging\s+'
            r'plan: basic-256mb\s+region: oregon\s+ipAllowList: \[\]',
        )
        web = _service_block(text, 'inpa-be-staging')
        self.assertRegex(
            web,
            r'- key: AWS_STORAGE_BUCKET_NAME\s+'
            r'value: "inpa-insurance-staging"',
        )
        self.assertNotRegex(
            text,
            r'(?m)^\s+name: (?:inpa-be|inpa-insurance-queue)\s*$',
        )


@override_settings(
    AWS_STORAGE_BUCKET_NAME=STAGING_BUCKET_NAME,
    STORAGES=STAGING_STORAGES,
)
class InsuranceLoadFixtureCommandTests(TestCase):
    def setUp(self):
        Plan.objects.create(code='free', display_name='Free')
        analysis_category = AnalysisCategory.objects.create(
            name='[표준]진단-암')
        analysis_subcategory = AnalysisSubCategory.objects.create(
            category=analysis_category, name='일반암')
        self.analysis_detail = AnalysisDetail.objects.create(
            sub_category=analysis_subcategory, name='일반암진단비')
        category = InsuranceCategory.objects.create(name='진단-암')
        subcategory = InsuranceSubCategory.objects.create(
            category=category, name='일반암')
        detail = InsuranceDetail.objects.create(
            sub_category=subcategory, name='일반암진단비')
        detail.analysis_detail.add(self.analysis_detail)
        self.tempdir = TemporaryDirectory()
        self.private_root = (
            Path(self.tempdir.name).resolve() / 'inpa-insurance-load-run-safe')
        self.run_id = 'inpa-load-20260717-a'
        self.host = 'inpa-be-staging.onrender.com'

    def tearDown(self):
        self.tempdir.cleanup()

    def _staging_connection(self, *, vendor='postgresql', name=None):
        return SimpleNamespace(
            vendor=vendor,
            settings_dict={'NAME': name or STAGING_DATABASE_NAME},
        )

    def _prepare(self, *, resource_connection=None, expected_host=None):
        output = StringIO()
        with mock.patch.object(
                prepare_command,
                'connection',
                resource_connection or self._staging_connection(),
                create=True):
            call_command(
                'prepare_insurance_load_fixture',
                private_root=str(self.private_root),
                run_id=self.run_id,
                expected_host=expected_host or self.host,
                stdout=output,
            )
        return output.getvalue()

    def _cleanup(self, *, run_id=None):
        output = StringIO()
        with mock.patch.object(
                prepare_command,
                'connection',
                self._staging_connection(),
                create=True):
            call_command(
                'cleanup_insurance_load_fixture',
                private_root=str(self.private_root),
                run_id=run_id or self.run_id,
                expected_host=self.host,
                stdout=output,
            )
        return output.getvalue()

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_resource_mismatch_refuses_before_database_or_files(self):
        cases = (
            ('host', self._staging_connection(), {}, 'api.inpa.kr'),
            ('engine', self._staging_connection(vendor='sqlite'), {}, self.host),
            ('database', self._staging_connection(name='inpa'), {}, self.host),
            ('bucket', self._staging_connection(), {
                'AWS_STORAGE_BUCKET_NAME': 'inpa-production',
            }, self.host),
            ('storage', self._staging_connection(), {
                'STORAGES': {
                    **STAGING_STORAGES,
                    'insurance_sources': {
                        'BACKEND': 'django.core.files.storage.FileSystemStorage',
                        'OPTIONS': {'location': '/tmp/insurance-sources'},
                    },
                },
            }, self.host),
        )

        for label, resource_connection, setting_changes, expected_host in cases:
            with self.subTest(label=label), override_settings(**setting_changes):
                with self.assertRaises(CommandError):
                    self._prepare(
                        resource_connection=resource_connection,
                        expected_host=expected_host,
                    )
                self.assertFalse(self.private_root.exists())
                self.assertFalse(
                    User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    def test_load_flag_is_closed_by_default(self):
        self.assertFalse(settings.INSURANCE_LOAD_TEST_ENABLED)

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=False,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_refuses_before_any_mutation_when_load_flag_is_closed(self):
        with self.assertRaises(CommandError):
            self._prepare()
        self.assertFalse(self.private_root.exists())
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=False,
    )
    def test_prepare_refuses_when_review_workflow_is_closed(self):
        with self.assertRaises(CommandError):
            self._prepare()
        self.assertFalse(self.private_root.exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_creates_exact_private_idempotent_synthetic_contract(self):
        output = self._prepare()
        scenario_path = self.private_root / 'scenario.json'
        auth_path = self.private_root / 'auth.json'
        marker_path = self.private_root / '.inpa-load-fixture.json'
        scenario = json.loads(scenario_path.read_text(encoding='utf-8'))
        auth = json.loads(auth_path.read_text(encoding='utf-8'))
        validated_scenario, validated_auth = load_runner.load_and_validate_inputs(
            scenario_path, auth_path)

        self.assertEqual(output, 'LOAD FIXTURE READY owners=20 documents=60 jobs=4\n')
        self.assertEqual(stat.S_IMODE(self.private_root.stat().st_mode), 0o700)
        self.assertEqual(len(scenario['owners']), 20)
        documents = [
            document
            for owner in scenario['owners']
            for document in owner['documents']
        ]
        self.assertEqual(len(documents), 60)
        self.assertEqual(len({item['file_path'] for item in documents}), 60)
        self.assertEqual(len(scenario['prepared_jobs']), 4)
        self.assertEqual(len(auth['tokens']), 20)
        self.assertEqual(validated_scenario, scenario)
        self.assertEqual(validated_auth, auth)
        self.assertEqual(scenario['private_root'], str(self.private_root))
        self.assertEqual(scenario['expected_host'], self.host)
        for path in (scenario_path, auth_path, marker_path):
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        for document in documents:
            path = Path(document['file_path'])
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(path.parent, self.private_root / 'documents')
            self.assertNotIn('samples', {part.lower() for part in path.parts})
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
            self.assertIn(SYNTHETIC_MARKER.encode(), path.read_bytes())
            with pdfplumber.open(path) as document:
                self.assertIn(
                    SYNTHETIC_MARKER, document.pages[0].extract_text())
        self.assertEqual(
            User.objects.filter(email__in=SYNTHETIC_EMAILS).count(), 20)
        self.assertEqual(
            Profile.objects.filter(
                user__email__in=SYNTHETIC_EMAILS,
                affiliation=f'{SYNTHETIC_MARKER}:{self.run_id}',
            ).count(), 20)
        self.assertEqual(
            Token.objects.filter(user__email__in=SYNTHETIC_EMAILS).count(), 20)
        self.assertFalse(any(
            user.has_usable_password()
            for user in User.objects.filter(email__in=SYNTHETIC_EMAILS)
        ))
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                owner__email__in=SYNTHETIC_EMAILS,
                status='review_required',
            ).count(), 4)

        first_scenario = scenario_path.read_bytes()
        first_auth = auth_path.read_bytes()
        self.assertEqual(
            self._prepare(),
            'LOAD FIXTURE READY owners=20 documents=60 jobs=4\n',
        )
        self.assertEqual(scenario_path.read_bytes(), first_scenario)
        self.assertEqual(auth_path.read_bytes(), first_auth)
        self.assertEqual(
            User.objects.filter(email__in=SYNTHETIC_EMAILS).count(), 20)
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                owner__email__in=SYNTHETIC_EMAILS).count(), 4)

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_creates_canonical_catalog_bridge_after_analysis_seed_only(self):
        InsuranceCategory.objects.all().delete()

        self._prepare()

        category = InsuranceCategory.objects.get(name='진단-암')
        subcategory = InsuranceSubCategory.objects.get(
            category=category, name='일반암')
        bridge = InsuranceDetail.objects.get(
            sub_category=subcategory, name='일반암진단비')
        self.assertEqual(
            list(bridge.analysis_detail.values_list('pk', flat=True)),
            [self.analysis_detail.pk],
        )

        bridge_id = bridge.pk
        self._prepare()
        self.assertEqual(
            InsuranceDetail.objects.get(
                sub_category=subcategory,
                name='일반암진단비',
            ).pk,
            bridge_id,
        )

        self._cleanup()
        self.assertTrue(InsuranceDetail.objects.filter(pk=bridge_id).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_refuses_nonmatching_existing_catalog_bridge(self):
        other_analysis = AnalysisDetail.objects.create(
            sub_category=self.analysis_detail.sub_category,
            name='특정암진단비',
        )
        bridge = InsuranceDetail.objects.get(
            sub_category__category__name='진단-암',
            sub_category__name='일반암',
            name='일반암진단비',
        )
        bridge.analysis_detail.set([other_analysis])

        with self.assertRaises(CommandError):
            self._prepare()

        self.assertEqual(
            list(bridge.analysis_detail.values_list('pk', flat=True)),
            [other_analysis.pk],
        )
        self.assertTrue(
            (self.private_root / '.inpa-load-fixture.json').exists())
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_links_an_unlinked_canonical_catalog_bridge(self):
        bridge = InsuranceDetail.objects.get(
            sub_category__category__name='진단-암',
            sub_category__name='일반암',
            name='일반암진단비',
        )
        bridge.analysis_detail.clear()

        self._prepare()

        self.assertEqual(
            list(bridge.analysis_detail.values_list('pk', flat=True)),
            [self.analysis_detail.pk],
        )

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_refuses_ambiguous_seeded_analysis_leaf(self):
        AnalysisDetail.objects.create(
            sub_category=self.analysis_detail.sub_category,
            name=self.analysis_detail.name,
        )

        with self.assertRaises(CommandError):
            self._prepare()

        bridge = InsuranceDetail.objects.get(
            sub_category__category__name='진단-암',
            sub_category__name='일반암',
            name='일반암진단비',
        )
        self.assertEqual(
            list(bridge.analysis_detail.values_list('pk', flat=True)),
            [self.analysis_detail.pk],
        )
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_refuses_ambiguous_catalog_path(self):
        InsuranceCategory.objects.create(name='진단-암')

        with self.assertRaises(CommandError):
            self._prepare()

        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_fixed_accounts_refuse_a_different_overlapping_run(self):
        self._prepare()
        second_root = (
            Path(self.tempdir.name).resolve() / 'inpa-insurance-load-run-other')

        with mock.patch.object(
                prepare_command, 'connection', self._staging_connection()), \
                self.assertRaises(CommandError):
            call_command(
                'prepare_insurance_load_fixture',
                private_root=str(second_root),
                run_id='inpa-load-20260717-b',
                expected_host=self.host,
                stdout=StringIO(),
            )

        self.assertEqual(
            Profile.objects.filter(
                user__email__in=SYNTHETIC_EMAILS,
                affiliation=f'{SYNTHETIC_MARKER}:{self.run_id}',
            ).count(), 20)
        self.assertEqual(
            InsuranceExtractionJob.objects.filter(
                owner__email__in=SYNTHETIC_EMAILS).count(), 4)

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_private_marker_is_written_before_the_first_db_mutation(self):
        with mock.patch.object(
                User.objects, 'get_or_create',
                side_effect=RuntimeError('injected-db-stop')):
            with self.assertRaisesRegex(RuntimeError, 'injected-db-stop'):
                self._prepare()

        marker = self.private_root / '.inpa-load-fixture.json'
        self.assertTrue(marker.exists())
        self.assertEqual(stat.S_IMODE(marker.stat().st_mode), 0o600)
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_partial_file_failure_can_rerun_and_cleanup_twice(self):
        original_write = prepare_command._write_private
        calls = 0

        def fail_third_write(path, payload):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise CommandError('injected-file-stop')
            return original_write(path, payload)

        with mock.patch.object(
                prepare_command, '_write_private', side_effect=fail_third_write):
            with self.assertRaisesMessage(CommandError, 'injected-file-stop'):
                self._prepare()

        self.assertTrue((self.private_root / '.inpa-load-fixture.json').exists())
        self.assertEqual(
            User.objects.filter(email__in=SYNTHETIC_EMAILS).count(), 20)
        self.assertEqual(
            self._prepare(),
            'LOAD FIXTURE READY owners=20 documents=60 jobs=4\n',
        )
        self.assertEqual(self._cleanup(), 'LOAD FIXTURE CLEANED owners=20\n')
        self.assertEqual(self._cleanup(), 'LOAD FIXTURE CLEANED owners=0\n')
        self.assertFalse(self.private_root.exists())
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_partial_file_failure_can_cleanup_without_a_rerun(self):
        original_write = prepare_command._write_private
        calls = 0

        def fail_third_write(path, payload):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise CommandError('injected-file-stop')
            return original_write(path, payload)

        with mock.patch.object(
                prepare_command, '_write_private', side_effect=fail_third_write):
            with self.assertRaisesMessage(CommandError, 'injected-file-stop'):
                self._prepare()

        self.assertEqual(self._cleanup(), 'LOAD FIXTURE CLEANED owners=20\n')
        self.assertFalse(self.private_root.exists())
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_rejects_unexpected_partial_files_dirs_and_symlinks(self):
        self._prepare()
        jobs = set(InsuranceExtractionJob.objects.filter(
            owner__email__in=SYNTHETIC_EMAILS).values_list('pk', flat=True))
        unexpected = (
            self.private_root / 'unexpected.txt',
            self.private_root / 'unexpected-dir',
            self.private_root / 'unexpected-link',
        )
        (unexpected[0]).write_text('not-fixture', encoding='utf-8')
        unexpected[0].chmod(0o600)
        unexpected[1].mkdir(mode=0o700)
        unexpected[2].symlink_to(self.private_root / 'scenario.json')

        for path in unexpected:
            with self.subTest(path=path), self.assertRaises(CommandError):
                self._prepare()
            self.assertEqual(set(InsuranceExtractionJob.objects.filter(
                owner__email__in=SYNTHETIC_EMAILS).values_list(
                    'pk', flat=True)), jobs)

        unexpected[2].unlink()
        unexpected[1].rmdir()
        unexpected[0].unlink()

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_stale_old_root_cannot_delete_a_new_run(self):
        old_root = self.private_root
        old_run = self.run_id
        self._prepare()
        self._cleanup()
        old_root.mkdir(mode=0o700)
        marker = old_root / '.inpa-load-fixture.json'
        marker.write_text(json.dumps({
            'schema_version': 'inpa-insurance-load-fixture-v1',
            'run_id': old_run,
        }), encoding='utf-8')
        marker.chmod(0o600)

        self.private_root = (
            Path(self.tempdir.name).resolve() / 'inpa-insurance-load-run-new')
        self.run_id = 'inpa-load-20260717-b'
        self._prepare()

        with mock.patch.object(
                prepare_command, 'connection', self._staging_connection()), \
                self.assertRaises(CommandError):
            call_command(
                'cleanup_insurance_load_fixture',
                private_root=str(old_root),
                run_id=old_run,
                expected_host=self.host,
                stdout=StringIO(),
            )

        self.assertEqual(
            Profile.objects.filter(
                user__email__in=SYNTHETIC_EMAILS,
                affiliation=f'{SYNTHETIC_MARKER}:{self.run_id}',
            ).count(), 20)

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_prepare_rejects_real_sample_or_worktree_output(self):
        repo_root = Path(settings.BASE_DIR).resolve().parent
        for candidate in (
                repo_root / 'samples' / 'load-fixture',
                repo_root / '.private-load-fixture'):
            with self.subTest(candidate=candidate), mock.patch.object(
                    prepare_command,
                    'connection',
                    self._staging_connection()), self.assertRaises(CommandError):
                call_command(
                    'prepare_insurance_load_fixture',
                    private_root=str(candidate),
                    run_id=self.run_id,
                    expected_host=self.host,
                    stdout=StringIO(),
                )
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=True,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_cleanup_requires_exact_marker_and_deletes_only_fixture_scope(self):
        self._prepare()
        unrelated = User.objects.create_user(
            email='inpa-load-owner-99@load.inpa.invalid')
        unrelated.set_unusable_password()
        unrelated.save(update_fields=['password'])
        Profile.objects.create(user=unrelated, affiliation='not-load-fixture')

        with self.assertRaises(CommandError):
            self._cleanup(run_id='different-run')
        self.assertEqual(
            User.objects.filter(email__in=SYNTHETIC_EMAILS).count(), 20)

        output = self._cleanup()

        self.assertEqual(output, 'LOAD FIXTURE CLEANED owners=20\n')
        self.assertFalse(self.private_root.exists())
        self.assertFalse(User.objects.filter(email__in=SYNTHETIC_EMAILS).exists())
        self.assertTrue(User.objects.filter(pk=unrelated.pk).exists())

    @override_settings(
        INSURANCE_LOAD_TEST_ENABLED=False,
        INSURANCE_REVIEW_GATE_ENABLED=True,
    )
    def test_cleanup_refuses_when_load_flag_is_closed(self):
        with self.assertRaises(CommandError):
            self._cleanup()
