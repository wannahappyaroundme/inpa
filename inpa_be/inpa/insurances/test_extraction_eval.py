import io
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from .extraction_eval import (
    EvalContractError,
    EvalObservation,
    EvalRunContext,
    _discover_git_worktree_roots,
    evaluate_dataset,
    nearest_rank_summary,
    parse_compare,
    run_private_evaluation,
    validate_manifest_and_truth,
)
from .extraction_eval_adapters import (
    LegacyExtractionAdapter,
    OpenAIReviewExtractionAdapter,
    _policy_review_fields,
    build_live_runtime,
)
from .import_contract import PDFImportError
from .import_claude import ExtractionFailure


RUN_CONTEXT = {
    'model_id': 'private-eval-model',
    'schema_version': 'insurance-review-v1',
    'prompt_version': 'claude-extraction-v1',
    'normalization_snapshot': 'sha256:' + ('a' * 64),
}
REQUIRED_CARRIERS = [1, 2, 7, 11, 12, 201, 206, 213]


def _content_digest(value):
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(',', ':'),
    ).encode('utf-8')
    return 'sha256:' + hashlib.sha256(payload).hexdigest()


def _prediction(truth, *, reviewed=True):
    return {
        'schema_version': 'insurance-extraction-prediction-v1',
        'case_id': truth['case_id'],
        'run_contract': RUN_CONTEXT,
        'policy': dict(truth['policy']),
        'policy_review_fields': [],
        'coverage_rows': [
            {
                'row_id': f"p-{row['gold_row_id']}",
                'source_ref': dict(row['source_ref']),
                'raw_name': row['raw_name'],
                'assurance_amount': row['assurance_amount'],
                'premium': row['premium'],
                'standard_path': row['standard_path'],
                'state': 'manual' if reviewed else 'review_ready',
                'review_fields': [],
                'reason_codes': [],
            }
            for row in truth['coverage_rows']
        ],
        'surfaced_items': [],
    }


def _independent_reviewed_prediction(index):
    case_id = f'holdout_{index:04d}'
    return {
        'schema_version': 'insurance-extraction-prediction-v1',
        'case_id': case_id,
        'run_contract': RUN_CONTEXT,
        'policy': {
            'carrier_code': REQUIRED_CARRIERS[index % len(REQUIRED_CARRIERS)],
            'product_name': f'private-product-{index:04d}',
            'contract_date': '2020-01-01',
            'expiry_date': '2040-01-01',
            'monthly_premium': 50000 + index,
        },
        'policy_review_fields': [],
        'coverage_rows': [
            {
                'row_id': f'p-g{row_index:04d}',
                'source_ref': {
                    'page': 1,
                    'line_start': row_index + 1,
                    'line_end': row_index + 1,
                },
                'raw_name': (
                    f'private-coverage-{index:04d}-{row_index:02d}'),
                'assurance_amount': 1000000 + row_index,
                'premium': 1000 + row_index,
                'standard_path': [
                    'category', 'subcategory', f'leaf-{row_index}'],
                'state': 'manual',
                'review_fields': [],
                'reason_codes': [],
            }
            for row_index in range(10)
        ],
        'surfaced_items': [],
    }


def _reviewed_envelope(index):
    prediction = _independent_reviewed_prediction(index)
    return {
        'schema_version': 'insurance-extraction-reviewed-v1',
        'case_id': prediction['case_id'],
        'provenance': {
            'reviewer_ref': 'reviewer-synthetic01',
            'reviewed_at': '2026-07-17T00:00:00Z',
            'review_tool_version': 'synthetic-review-ui-v1',
            'review_schema_version': RUN_CONTEXT['schema_version'],
            'truth_access': False,
            'content_digest': _content_digest(prediction),
        },
        'prediction': prediction,
    }


def _refresh_reviewed_digest(reviewed):
    reviewed['provenance']['content_digest'] = _content_digest(
        reviewed['prediction'])


class PrivateDataset:
    def __init__(self, *, reviewed=True):
        self._tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.root = Path(self._tmp.name).resolve()
        self.manifest_path = self.root / 'holdout.json'
        (self.root / 'pdf').mkdir()
        (self.root / 'truth').mkdir()
        (self.root / 'reviewed').mkdir()
        cases = []
        for index in range(100):
            case_id = f'holdout_{index:04d}'
            pdf_rel = f'pdf/{case_id}.pdf'
            truth_rel = f'truth/{case_id}.json'
            reviewed_rel = f'reviewed/{case_id}.json'
            (self.root / pdf_rel).write_bytes(b'%PDF-1.4\nsynthetic\n')
            truth = {
                'schema_version': 'insurance-extraction-truth-v1',
                'case_id': case_id,
                'policy': {
                    'carrier_code': REQUIRED_CARRIERS[
                        index % len(REQUIRED_CARRIERS)],
                    'product_name': f'private-product-{index:04d}',
                    'contract_date': '2020-01-01',
                    'expiry_date': '2040-01-01',
                    'monthly_premium': 50000 + index,
                },
                'coverage_rows': [
                    {
                        'gold_row_id': f'g{row_index:04d}',
                        'source_ref': {
                            'page': 1,
                            'line_start': row_index + 1,
                            'line_end': row_index + 1,
                        },
                        'raw_name': f'private-coverage-{index:04d}-{row_index:02d}',
                        'assurance_amount': 1000000 + row_index,
                        'premium': 1000 + row_index,
                        'standard_path': ['category', 'subcategory', f'leaf-{row_index}'],
                    }
                    for row_index in range(10)
                ],
            }
            (self.root / truth_rel).write_text(
                json.dumps(truth, ensure_ascii=False), encoding='utf-8')
            case = {
                'case_id': case_id,
                'pdf_path': pdf_rel,
                'truth_path': truth_rel,
                'strata': {
                    'insurance_type': 'life' if index % 2 else 'loss',
                    'carrier_code': REQUIRED_CARRIERS[
                        index % len(REQUIRED_CARRIERS)],
                    'form_era': 'legacy' if index < 50 else 'current',
                    'document_length': 'short' if index % 2 else 'long',
                },
            }
            if reviewed:
                (self.root / reviewed_rel).write_text(
                    json.dumps(
                        _reviewed_envelope(index), ensure_ascii=False),
                    encoding='utf-8',
                )
                case['reviewed_output_path'] = reviewed_rel
            cases.append(case)
        self.manifest = {
            'schema_version': 'insurance-extraction-manifest-v1',
            'split': 'holdout',
            'requirements': {
                'min_cases': 100,
                'min_coverage_rows': 1000,
                'required_insurance_types': ['life', 'loss'],
                'min_cases_per_required_insurance_type': 20,
                'required_carrier_codes': REQUIRED_CARRIERS,
                'min_cases_per_required_carrier': 5,
                'required_form_eras': ['legacy', 'current'],
                'min_cases_per_required_form_era': 20,
                'required_document_lengths': ['short', 'long'],
                'min_cases_per_required_document_length': 10,
            },
            'cases': cases,
        }
        self.write_manifest()

    def write_manifest(self):
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8')

    def truth(self, index=0):
        return json.loads(
            (self.root / self.manifest['cases'][index]['truth_path'])
            .read_text(encoding='utf-8'))

    def write_truth(self, index, truth):
        (self.root / self.manifest['cases'][index]['truth_path']).write_text(
            json.dumps(truth, ensure_ascii=False), encoding='utf-8')

    def close(self):
        self._tmp.cleanup()


class ExactAdapter:
    def __init__(self, dataset):
        self.dataset = dataset
        self.seen_cases = []

    def run(self, case, context):
        assert not hasattr(case, 'truth')
        assert not hasattr(case, 'truth_path')
        assert not hasattr(case, 'reviewed_output_path')
        self.seen_cases.append(case.case_id)
        index = int(case.case_id.rsplit('_', 1)[1])
        truth = self.dataset.truth(index)
        prediction = _prediction(truth, reviewed=False)
        prediction['run_contract'] = context.model_dump(mode='json')
        return EvalObservation.model_validate({
            'outcome': 'success',
            'run_contract': context.model_dump(mode='json'),
            'prediction': prediction,
            'input_tokens': 10,
            'output_tokens': 5,
            'estimated_cost_krw': 1.25,
            'provider_latency_ms': index + 1,
            'pipeline_latency_ms': index + 2,
        })


class LegacyExtractionAdapterPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.context = EvalRunContext.model_validate(RUN_CONTEXT)
        self.adapter = LegacyExtractionAdapter({})
        self._tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.pdf_path = Path(self._tmp.name) / 'synthetic.pdf'
        self.pdf_path.write_bytes(b'%PDF-1.4\nsynthetic\n')
        self.case = SimpleNamespace(
            case_id='holdout_synthetic', pdf_path=self.pdf_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_legacy_provider_receives_only_production_masked_text(self):
        source_sentinel = 'synthetic-source-private'
        safe_text = '[고객_1] 일반암진단비 3,000만원'
        extracted = SimpleNamespace(masked_lines=(
            SimpleNamespace(text_masked=safe_text),
        ))

        with mock.patch(
                'inpa.insurances.import_pdf.extract_pdf',
                return_value=extracted) as production_extract, mock.patch(
                    'inpa.insurances.views._extract_pdf_lines',
                    return_value=([source_sentinel], None)), mock.patch(
                    'inpa.core.ocr.claude_parser.claude_parse',
                    return_value=None) as provider:
            self.adapter.run(self.case, self.context)

        production_extract.assert_called_once()
        provider.assert_called_once()
        provider_lines = provider.call_args.args[0]
        self.assertEqual(provider_lines, [safe_text])
        self.assertNotIn(source_sentinel, repr(provider_lines))

    def test_legacy_pseudonymization_failure_never_calls_provider(self):
        with mock.patch(
                'inpa.insurances.import_pdf.extract_pdf',
                side_effect=PDFImportError(
                    'PII_REDACTION_UNCERTAIN')), mock.patch(
                    'inpa.insurances.views._extract_pdf_lines',
                    return_value=(['synthetic-source-private'], None)), \
                mock.patch(
                    'inpa.core.ocr.claude_parser.claude_parse') as provider:
            observation = self.adapter.run(self.case, self.context)

        provider.assert_not_called()
        self.assertEqual(observation.outcome, 'provider_failure')
        self.assertEqual(
            observation.error_code, 'PII_REDACTION_UNCERTAIN')
        self.assertIsNone(observation.prediction)


class OpenAIExtractionAdapterPrivacyTests(unittest.TestCase):
    def setUp(self):
        self.context = EvalRunContext.model_validate(RUN_CONTEXT)
        self.adapter = OpenAIReviewExtractionAdapter()
        self._tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.pdf_path = Path(self._tmp.name) / 'synthetic.pdf'
        self.pdf_path.write_bytes(b'%PDF-1.4\nsynthetic\n')
        self.case = SimpleNamespace(
            case_id='holdout_synthetic', pdf_path=self.pdf_path)

    def tearDown(self):
        self._tmp.cleanup()

    def test_pseudonymization_failure_is_aggregate_only_and_calls_no_provider(self):
        with mock.patch(
                'inpa.insurances.import_pdf.extract_pdf',
                side_effect=PDFImportError(
                    'PII_REDACTION_UNCERTAIN')), mock.patch(
                        'inpa.insurances.import_openai_eval.extract') as provider:
            observation = self.adapter.run(self.case, self.context)

        provider.assert_not_called()
        self.assertEqual(observation.outcome, 'provider_failure')
        self.assertEqual(
            observation.error_code, 'PII_REDACTION_UNCERTAIN')
        self.assertIsNone(observation.prediction)

    def test_provider_pii_failure_exposes_only_safe_aggregate_fields(self):
        private_sentinel = 'private-person-010-1234-5678'
        extracted = SimpleNamespace(masked_lines=(), candidates=())
        failure = ExtractionFailure(
            'PROVIDER_PII_OUTPUT', error_type='provider_privacy',
            usage={'input_tokens': 1000, 'output_tokens': 100},
        )

        with mock.patch(
                'inpa.insurances.import_pdf.extract_pdf',
                return_value=extracted), mock.patch(
                    'inpa.insurances.import_openai_eval.extract',
                    side_effect=failure):
            observation = self.adapter.run(self.case, self.context)

        public_value = json.dumps(
            observation.model_dump(mode='json'), ensure_ascii=False)
        self.assertEqual(observation.error_code, 'PROVIDER_PII_OUTPUT')
        self.assertEqual(observation.error_type, 'provider_privacy')
        self.assertEqual(observation.estimated_cost_krw, 0.0)
        self.assertNotIn(private_sentinel, public_value)


class ExtractionManifestValidationTests(unittest.TestCase):
    def setUp(self):
        self.dataset = PrivateDataset()

    def tearDown(self):
        self.dataset.close()

    def assert_contract_error(self, code, callback):
        with self.assertRaises(EvalContractError) as caught:
            callback()
        self.assertEqual(caught.exception.code, code)
        self.assertEqual(str(caught.exception), code)

    def validate(self):
        return validate_manifest_and_truth(
            self.dataset.root,
            self.dataset.manifest_path,
            split='holdout',
            worktree_roots=(),
        )

    def test_validates_code_owned_floors_and_loads_attested_review_outputs(self):
        loaded = self.validate()
        self.assertEqual(len(loaded.cases), 100)
        self.assertEqual(loaded.gold_row_count, 1000)
        self.assertTrue(loaded.has_reviewed_outputs)

    def test_worktree_discovery_ignores_only_git_prunable_records(self):
        live_root = self.dataset.root / 'live-worktree'
        live_root.mkdir()
        stale_root = self.dataset.root / 'removed-worktree'
        results = (
            SimpleNamespace(stdout='/synthetic/common.git\n'),
            SimpleNamespace(stdout=(
                f'worktree {stale_root}\n'
                'HEAD deadbeef\n'
                'detached\n'
                'prunable gitdir file points to non-existent location\n\n'
                f'worktree {live_root}\n'
                'HEAD cafebabe\n'
                'detached\n\n'
            )),
        )
        with mock.patch(
                'inpa.insurances.extraction_eval.subprocess.run',
                side_effect=results):
            roots = _discover_git_worktree_roots()

        self.assertEqual(roots, (live_root.resolve(),))

    def test_worktree_discovery_rejects_missing_nonprunable_record(self):
        missing_root = self.dataset.root / 'missing-worktree'
        results = (
            SimpleNamespace(stdout='/synthetic/common.git\n'),
            SimpleNamespace(stdout=(
                f'worktree {missing_root}\n'
                'HEAD deadbeef\n'
                'detached\n\n'
            )),
        )
        with mock.patch(
                'inpa.insurances.extraction_eval.subprocess.run',
                side_effect=results):
            self.assert_contract_error(
                'E_DATASET_PATH', _discover_git_worktree_roots)

    def test_worktree_discovery_rejects_malformed_nonprunable_record(self):
        live_root = self.dataset.root / 'live-worktree'
        live_root.mkdir()
        results = (
            SimpleNamespace(stdout='/synthetic/common.git\n'),
            SimpleNamespace(stdout=(
                f'worktree {live_root}\n'
                'HEAD cafebabe\n'
                'detached\n\n'
                'HEAD deadbeef\n'
                'detached\n\n'
            )),
        )
        with mock.patch(
                'inpa.insurances.extraction_eval.subprocess.run',
                side_effect=results):
            self.assert_contract_error(
                'E_DATASET_PATH', _discover_git_worktree_roots)

    def test_rejects_reviewed_output_without_provenance_attestation(self):
        reviewed_path = (
            self.dataset.root
            / self.dataset.manifest['cases'][0]['reviewed_output_path'])
        reviewed = json.loads(reviewed_path.read_text(encoding='utf-8'))
        reviewed.pop('provenance')
        reviewed_path.write_text(json.dumps(reviewed), encoding='utf-8')
        self.assert_contract_error('E_REVIEWED_OUTPUT_SCHEMA', self.validate)

    def test_rejects_false_same_digest_and_truth_copy_provenance(self):
        for mutation in ('truth_access', 'truth_digest', 'truth_copy'):
            with self.subTest(mutation=mutation):
                fresh = PrivateDataset()
                try:
                    reviewed_path = (
                        fresh.root
                        / fresh.manifest['cases'][0][
                            'reviewed_output_path'])
                    reviewed = json.loads(
                        reviewed_path.read_text(encoding='utf-8'))
                    expected = 'E_REVIEWED_OUTPUT_SCHEMA'
                    if mutation == 'truth_access':
                        reviewed['provenance']['truth_access'] = True
                    elif mutation == 'truth_digest':
                        reviewed['provenance']['content_digest'] = (
                            _content_digest(fresh.truth()))
                        expected = 'E_REVIEWED_OUTPUT_PROVENANCE'
                    else:
                        reviewed = fresh.truth()
                    reviewed_path.write_text(
                        json.dumps(reviewed), encoding='utf-8')
                    with self.assertRaises(EvalContractError) as caught:
                        validate_manifest_and_truth(
                            fresh.root, fresh.manifest_path,
                            split='holdout', worktree_roots=())
                    self.assertEqual(caught.exception.code, expected)
                finally:
                    fresh.close()

    def test_rejects_parent_root_containing_worktree_case_files(self):
        self.assert_contract_error(
            'E_DATASET_PATH',
            lambda: validate_manifest_and_truth(
                self.dataset.root,
                self.dataset.manifest_path,
                split='holdout',
                worktree_roots=(self.dataset.root / 'pdf',),
            ),
        )

    def test_rejects_symlink_resolving_to_child_worktree_file(self):
        worktree = self.dataset.root / 'private-repo'
        worktree.mkdir()
        target = worktree / 'tracked.pdf'
        target.write_bytes(b'%PDF-1.4\nsynthetic\n')
        link = self.dataset.root / 'pdf' / 'tracked-link.pdf'
        link.symlink_to(target)
        self.dataset.manifest['cases'][0]['pdf_path'] = (
            'pdf/tracked-link.pdf')
        self.dataset.write_manifest()
        self.assert_contract_error(
            'E_DATASET_PATH',
            lambda: validate_manifest_and_truth(
                self.dataset.root,
                self.dataset.manifest_path,
                split='holdout',
                worktree_roots=(worktree,),
            ),
        )

    def test_truth_schema_extra_forbids_identity_fields(self):
        truth = self.dataset.truth()
        truth['customer_name'] = 'private-identity-sentinel'
        self.dataset.write_truth(0, truth)
        self.assert_contract_error('E_TRUTH_SCHEMA', self.validate)

    def test_truth_allowed_text_fields_still_reject_direct_identifiers(self):
        truth = self.dataset.truth()
        truth['policy']['product_name'] = (
            'synthetic-policy 010-1234-5678')
        self.dataset.write_truth(0, truth)
        self.assert_contract_error('E_DATASET_PRIVACY', self.validate)

    def test_manifest_allowed_path_fields_reject_direct_identifiers(self):
        self.dataset.manifest['cases'][0]['pdf_path'] = (
            'pdf/synthetic-010-1234-5678.pdf')
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_PRIVACY', self.validate)

    def test_prediction_schema_extra_forbids_identity_fields(self):
        reviewed_path = (
            self.dataset.root
            / self.dataset.manifest['cases'][0]['reviewed_output_path'])
        reviewed = json.loads(reviewed_path.read_text(encoding='utf-8'))
        reviewed['prediction']['policy']['insured_name'] = (
            'private-identity-sentinel')
        reviewed_path.write_text(json.dumps(reviewed), encoding='utf-8')
        self.assert_contract_error('E_REVIEWED_OUTPUT_SCHEMA', self.validate)

    def test_reviewed_outputs_are_all_or_none_and_separate_from_truth(self):
        self.dataset.manifest['cases'][0].pop('reviewed_output_path')
        self.dataset.write_manifest()
        self.assert_contract_error('E_MANIFEST_SCHEMA', self.validate)

        self.dataset.manifest['cases'][0]['reviewed_output_path'] = (
            self.dataset.manifest['cases'][0]['truth_path'])
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_PATH', self.validate)

    def test_manifest_cannot_weaken_any_code_owned_floor(self):
        keys = (
            ('min_cases', 99),
            ('min_coverage_rows', 999),
            ('min_cases_per_required_insurance_type', 19),
            ('min_cases_per_required_carrier', 4),
            ('min_cases_per_required_form_era', 19),
            ('min_cases_per_required_document_length', 9),
        )
        for key, value in keys:
            with self.subTest(key=key):
                original = self.dataset.manifest['requirements'][key]
                self.dataset.manifest['requirements'][key] = value
                self.dataset.write_manifest()
                self.assert_contract_error(
                    'E_MANIFEST_REQUIREMENTS', self.validate)
                self.dataset.manifest['requirements'][key] = original
        self.dataset.manifest['requirements']['required_carrier_codes'] = [1]
        self.dataset.write_manifest()
        self.assert_contract_error('E_MANIFEST_REQUIREMENTS', self.validate)

    def test_rejects_insufficient_case_row_and_strata_counts(self):
        cases = self.dataset.manifest['cases']
        original = list(cases)
        self.dataset.manifest['cases'] = cases[:99]
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_COUNTS', self.validate)
        self.dataset.manifest['cases'] = original

        truth = self.dataset.truth()
        truth['coverage_rows'] = truth['coverage_rows'][:-1]
        self.dataset.write_truth(0, truth)
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_COUNTS', self.validate)

    def test_rejects_missing_life_form_length_or_carrier_strata(self):
        mutations = (
            ('insurance_type', 'loss'),
            ('form_era', 'legacy'),
            ('document_length', 'short'),
            ('carrier_code', 1),
        )
        for field, value in mutations:
            fresh = PrivateDataset()
            try:
                for case in fresh.manifest['cases']:
                    case['strata'][field] = value
                fresh.write_manifest()
                with self.assertRaises(EvalContractError) as caught:
                    validate_manifest_and_truth(
                        fresh.root, fresh.manifest_path,
                        split='holdout', worktree_roots=())
                self.assertEqual(caught.exception.code, 'E_DATASET_STRATA')
            finally:
                fresh.close()

    def test_rejects_duplicate_case_pdf_truth_and_reviewed_paths(self):
        fields = ('case_id', 'pdf_path', 'truth_path', 'reviewed_output_path')
        for field in fields:
            fresh = PrivateDataset()
            try:
                fresh.manifest['cases'][1][field] = (
                    fresh.manifest['cases'][0][field])
                fresh.write_manifest()
                with self.assertRaises(EvalContractError) as caught:
                    validate_manifest_and_truth(
                        fresh.root, fresh.manifest_path,
                        split='holdout', worktree_roots=())
                expected = (
                    'E_MANIFEST_SCHEMA' if field == 'case_id'
                    else 'E_DATASET_PATH')
                self.assertEqual(caught.exception.code, expected)
            finally:
                fresh.close()

    def test_rejects_a_file_reused_across_truth_and_reviewed_roles(self):
        self.dataset.manifest['cases'][1]['reviewed_output_path'] = (
            self.dataset.manifest['cases'][0]['truth_path'])
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_PATH', self.validate)

    def test_rejects_traversal_absolute_outside_symlink_and_worktree_paths(self):
        original = self.dataset.manifest['cases'][0]['pdf_path']
        self.dataset.manifest['cases'][0]['pdf_path'] = '../outside.pdf'
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_PATH', self.validate)
        self.dataset.manifest['cases'][0]['pdf_path'] = str(
            self.dataset.root / original)
        self.dataset.write_manifest()
        self.assert_contract_error('E_DATASET_PATH', self.validate)

        outside = Path('/tmp') / f'inpa-eval-outside-{os.getpid()}.pdf'
        outside.write_bytes(b'%PDF-1.4')
        link = self.dataset.root / 'pdf' / 'outside-link.pdf'
        try:
            link.symlink_to(outside)
            self.dataset.manifest['cases'][0]['pdf_path'] = (
                'pdf/outside-link.pdf')
            self.dataset.write_manifest()
            self.assert_contract_error('E_DATASET_PATH', self.validate)
        finally:
            link.unlink(missing_ok=True)
            outside.unlink(missing_ok=True)

        self.assert_contract_error(
            'E_DATASET_PATH',
            lambda: validate_manifest_and_truth(
                self.dataset.root, self.dataset.manifest_path,
                split='holdout', worktree_roots=(self.dataset.root,)),
        )

    def test_rejects_duplicate_truth_source_refs_before_scoring(self):
        truth = self.dataset.truth()
        truth['coverage_rows'][1]['source_ref'] = dict(
            truth['coverage_rows'][0]['source_ref'])
        self.dataset.write_truth(0, truth)
        self.assert_contract_error('E_TRUTH_SCHEMA', self.validate)


class ExtractionScoringTests(unittest.TestCase):
    def test_review_adapter_maps_company_code_issue_to_carrier_field(self):
        self.assertEqual(
            _policy_review_fields({
                'company_code': [object()],
                'monthly_premium': [object()],
            }),
            ['carrier_code', 'monthly_premium'],
        )

    def setUp(self):
        self.dataset = PrivateDataset(reviewed=False)
        self.loaded = validate_manifest_and_truth(
            self.dataset.root, self.dataset.manifest_path,
            split='holdout', worktree_roots=())
        self.context = EvalRunContext.model_validate(RUN_CONTEXT)

    def tearDown(self):
        self.dataset.close()

    def test_exact_dataset_reports_explicit_numerators_and_null_safe_rates(self):
        report = evaluate_dataset(
            self.loaded, {'legacy': ExactAdapter(self.dataset)}, self.context)
        metrics = report.variants['legacy/pre_review']['metrics']
        self.assertEqual(
            metrics['carrier_exact'],
            {'numerator': 100, 'denominator': 100, 'rate': 1.0},
        )
        self.assertEqual(metrics['coverage_recall']['numerator'], 1000)
        self.assertEqual(metrics['coverage_precision']['denominator'], 1000)
        self.assertEqual(metrics['silent_omission']['count'], 0)
        self.assertIsNone(metrics['ambiguous_rows']['rate'])

    def test_adapter_boundary_exposes_no_truth_derived_strata(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run
        seen_keys = []

        def spy(case, context):
            seen_keys.append(set(vars(case)))
            return original_run(case, context)

        adapter.run = spy
        evaluate_dataset(self.loaded, {'review': adapter}, self.context)
        self.assertEqual(seen_keys, [{'case_id', 'pdf_path'}] * 100)

    def test_source_ref_is_primary_and_amount_mismatch_does_not_change_pair(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def wrong_amount(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                observation.prediction.coverage_rows[0].assurance_amount += 1
            return observation

        adapter.run = wrong_amount
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        metrics = report.variants['review/pre_review']['metrics']
        self.assertEqual(metrics['coverage_recall']['numerator'], 1000)
        self.assertEqual(
            metrics['assurance_amount_exact']['numerator'], 999)
        self.assertEqual(
            metrics['material_amount_error']['count'], 1)

    def test_product_exact_uses_nfc_and_outer_trim_only(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run
        self.loaded.cases[0].truth.policy.product_name = 'caf\u00e9 plan'

        def nfc_variant(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                observation.prediction.policy.product_name = '  cafe\u0301 plan  '
            return observation

        adapter.run = nfc_variant
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        self.assertEqual(
            report.variants['review/pre_review']['metrics']
            ['product_exact']['numerator'],
            100,
        )

    def test_legacy_name_fallback_uses_nfc_trim_and_document_order(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def no_refs(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                rows = observation.prediction.coverage_rows[:2]
                rows[0].source_ref = None
                rows[1].source_ref = None
                rows[0].raw_name = '  cafe\u0301  '
                rows[1].raw_name = '  cafe\u0301  '
                truth = self.dataset.truth(0)
                truth['coverage_rows'][0]['raw_name'] = 'caf\u00e9'
                truth['coverage_rows'][1]['raw_name'] = 'caf\u00e9'
                self.dataset.write_truth(0, truth)
                self.loaded.cases[0].truth.coverage_rows[0].raw_name = 'caf\u00e9'
                self.loaded.cases[0].truth.coverage_rows[1].raw_name = 'caf\u00e9'
            return observation

        adapter.run = no_refs
        report = evaluate_dataset(
            self.loaded, {'legacy': adapter}, self.context)
        metrics = report.variants['legacy/pre_review']['metrics']
        self.assertEqual(metrics['fallback_pairs']['count'], 2)
        self.assertEqual(metrics['ambiguous_rows']['count'], 0)

    def test_review_rows_without_source_refs_never_receive_name_fallback(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def no_refs(case, context):
            observation = original_run(case, context)
            for row in observation.prediction.coverage_rows:
                row.source_ref = None
            return observation

        adapter.run = no_refs
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        variant = report.variants['review/pre_review']
        self.assertEqual(
            variant['metrics']['coverage_recall']['numerator'], 0)
        self.assertEqual(
            variant['metrics']['fallback_pairs']['count'], 0)
        self.assertFalse(variant['reference_contract_match'])

    def test_unresolved_duplicate_fallback_is_ambiguous_not_best_fit(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def ambiguous(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                truth = self.loaded.cases[0].truth
                truth.coverage_rows[0].raw_name = 'duplicate'
                truth.coverage_rows[1].raw_name = 'duplicate'
                first = observation.prediction.coverage_rows[0]
                first.source_ref = None
                first.raw_name = 'duplicate'
                observation.prediction.coverage_rows.pop(1)
            return observation

        adapter.run = ambiguous
        report = evaluate_dataset(
            self.loaded, {'legacy': adapter}, self.context)
        metrics = report.variants['legacy/pre_review']['metrics']
        self.assertEqual(metrics['ambiguous_rows']['count'], 3)
        self.assertEqual(metrics['assurance_amount_exact']['denominator'], 998)
        self.assertEqual(metrics['mapping_accuracy']['denominator'], 998)

    def test_surfaced_omission_is_not_silent_but_unsurfaced_omission_is(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def omissions(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                removed = observation.prediction.coverage_rows.pop(0)
                observation.prediction.surfaced_items.append({
                    'source_ref': removed.source_ref.model_dump(mode='json'),
                    'raw_name': None,
                    'state': 'unmatched',
                    'reason_codes': ['CLAUDE_OMITTED_CANDIDATE'],
                })
            elif case.case_id == 'holdout_0001':
                observation.prediction.coverage_rows.pop(0)
            return observation

        adapter.run = omissions
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        metrics = report.variants['review/pre_review']['metrics']
        self.assertEqual(metrics['coverage_recall']['numerator'], 998)
        self.assertEqual(metrics['silent_omission']['count'], 1)

    def test_validation_catch_and_false_review_are_field_level(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def review_flags(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                observation.prediction.policy.monthly_premium += 1
                observation.prediction.policy_review_fields.append(
                    'monthly_premium')
                row = observation.prediction.coverage_rows[0]
                row.review_fields.append('premium')
            return observation

        adapter.run = review_flags
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        metrics = report.variants['review/pre_review']['metrics']
        self.assertEqual(
            metrics['validation_catch_rate']['numerator'], 1)
        self.assertEqual(
            metrics['validation_catch_rate']['denominator'], 1)
        self.assertEqual(metrics['false_review_rate']['numerator'], 1)

    def test_review_ready_surface_is_visible_but_not_a_validation_catch(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        def surfaced_without_review_flag(case, context):
            observation = original_run(case, context)
            if case.case_id == 'holdout_0000':
                removed = observation.prediction.coverage_rows.pop(0)
                observation.prediction.surfaced_items.append({
                    'source_ref': removed.source_ref.model_dump(mode='json'),
                    'raw_name': None,
                    'state': 'review_ready',
                    'reason_codes': [],
                })
            return observation

        adapter.run = surfaced_without_review_flag
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        metrics = report.variants['review/pre_review']['metrics']
        self.assertEqual(metrics['silent_omission']['count'], 0)
        self.assertEqual(metrics['validation_catch_rate']['numerator'], 0)
        self.assertEqual(metrics['validation_catch_rate']['denominator'], 1)
        self.assertLessEqual(
            metrics['validation_catch_rate']['numerator'],
            metrics['validation_catch_rate']['denominator'],
        )

    def test_provider_failure_exception_is_type_only_and_aggregated(self):
        adapter = ExactAdapter(self.dataset)
        original_run = adapter.run

        class SecretBearingFailure(RuntimeError):
            pass

        def failed(case, context):
            if case.case_id == 'holdout_0000':
                raise SecretBearingFailure('raw-payload-private-sentinel')
            return original_run(case, context)

        adapter.run = failed
        report = evaluate_dataset(
            self.loaded, {'review': adapter}, self.context)
        public = report.to_public_dict()
        encoded = json.dumps(public)
        self.assertNotIn('raw-payload-private-sentinel', encoded)
        self.assertEqual(
            public['variants']['review/pre_review']['provider_failures'], 1)
        self.assertEqual(
            public['variants']['review/pre_review']['failure_types'],
            {'SecretBearingFailure': 1},
        )

    def test_nearest_rank_boundaries_and_empty_sample(self):
        self.assertEqual(
            nearest_rank_summary([]),
            {'sample_count': 0, 'p50': None, 'p95': None},
        )
        self.assertEqual(
            nearest_rank_summary([7]),
            {'sample_count': 1, 'p50': 7, 'p95': 7},
        )
        self.assertEqual(nearest_rank_summary([1, 2])['p95'], 2)
        self.assertEqual(nearest_rank_summary(range(1, 21))['p95'], 19)


class ExtractionOrchestrationTests(unittest.TestCase):
    def test_parse_compare_rejects_unknown_duplicate_or_empty_values(self):
        self.assertEqual(
            parse_compare('legacy,review,openai_review'),
            ('legacy', 'review', 'openai_review'),
        )
        for value in ('', 'legacy,legacy', 'legacy,gpt', 'review,'):
            with self.subTest(value=value):
                with self.assertRaises(EvalContractError) as caught:
                    parse_compare(value)
                self.assertEqual(caught.exception.code, 'E_CLI_CONTRACT')

    @override_settings(CLAUDE_MODEL_PARSE='')
    @mock.patch.dict(os.environ, {}, clear=True)
    @mock.patch(
        'inpa.insurances.extraction_eval_adapters.'
        '_normalization_snapshots_and_lookup')
    def test_openai_runtime_requires_dedicated_key_and_model_before_adapter(
        self, snapshots,
    ):
        snapshots.return_value = (
            'sha256:' + ('b' * 64),
            'sha256:' + ('c' * 64),
            {},
        )
        with self.assertRaises(EvalContractError) as caught:
            build_live_runtime(('openai_review',))
        self.assertEqual(caught.exception.code, 'E_OPENAI_EVAL_CONTRACT')

    @override_settings(CLAUDE_MODEL_PARSE='')
    @mock.patch.dict(os.environ, {
        'OPENAI_EVAL_API_KEY': 'configured-eval-key',
        'OPENAI_EVAL_MODEL': 'configured-eval-model',
    }, clear=True)
    @mock.patch(
        'inpa.insurances.extraction_eval_adapters.'
        '_normalization_snapshots_and_lookup')
    def test_openai_runtime_is_independent_from_claude_credentials(
        self, snapshots,
    ):
        snapshots.return_value = (
            'sha256:' + ('b' * 64),
            'sha256:' + ('c' * 64),
            {},
        )
        contexts, adapters = build_live_runtime(('openai_review',))
        self.assertEqual(
            contexts['openai_review'].model_id, 'configured-eval-model')
        self.assertIsInstance(
            adapters['openai_review'], OpenAIReviewExtractionAdapter)

    def test_openai_diagnostic_never_becomes_release_authority(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            def factory(_compare):
                return (
                    {'openai_review': EvalRunContext.model_validate(
                        RUN_CONTEXT)},
                    {'openai_review': ExactAdapter(dataset)},
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='openai_review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(
                report.variants['openai_review/pre_review']['status'],
                'measured',
            )
            self.assertNotIn('openai_review/post_review', report.variants)
        finally:
            dataset.close()

    def test_invalid_manifest_never_calls_runtime_or_adapter_factory(self):
        dataset = PrivateDataset()
        try:
            dataset.manifest['cases'] = dataset.manifest['cases'][:99]
            dataset.write_manifest()
            runtime_factory = mock.Mock()
            with self.assertRaises(EvalContractError) as caught:
                run_private_evaluation(
                    dataset.root, dataset.manifest_path,
                    split='holdout', compare='legacy,review',
                    runtime_factory=runtime_factory,
                    worktree_roots=(),
                )
            self.assertEqual(caught.exception.code, 'E_DATASET_COUNTS')
            runtime_factory.assert_not_called()
        finally:
            dataset.close()

    def test_each_variant_is_compared_with_its_own_expected_contract(self):
        dataset = PrivateDataset(reviewed=False)
        try:
            legacy_context = EvalRunContext.model_validate({
                **RUN_CONTEXT,
                'schema_version': 'legacy-ocr-data-v1',
                'prompt_version': 'legacy-prompt-v1',
                'normalization_snapshot': 'sha256:' + ('b' * 64),
            })
            review_context = EvalRunContext.model_validate(RUN_CONTEXT)

            def factory(_compare):
                return (
                    {'legacy': legacy_context, 'review': review_context},
                    {
                        'legacy': ExactAdapter(dataset),
                        'review': ExactAdapter(dataset),
                    },
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(
                report.variants['legacy/pre_review']['run_contract_match'])
            self.assertTrue(
                report.variants['review/pre_review']['run_contract_match'])
        finally:
            dataset.close()

    def test_release_gate_requires_complete_legacy_and_review_ab(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {'review': ExactAdapter(dataset)},
                )

            _report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            self.assertEqual(exit_code, 1)
        finally:
            dataset.close()

    def test_self_declared_semantic_copy_is_reportable_but_never_release_authority(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            loaded = validate_manifest_and_truth(
                dataset.root, dataset.manifest_path,
                split='holdout', worktree_roots=(),
            )
            self.assertTrue(loaded.has_reviewed_outputs)

            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {
                        'legacy': ExactAdapter(dataset),
                        'review': ExactAdapter(dataset),
                    },
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            post = report.variants['review/post_review']
            self.assertEqual(exit_code, 1)
            self.assertEqual(post['status'], 'not_verified')
            self.assertEqual(
                post['reason_code'], 'TRUSTED_REVIEW_AUDIT_UNAVAILABLE')
            self.assertTrue(post['report_only'])
            self.assertEqual(
                post['metrics']['material_amount_error']['count'], 0)
        finally:
            dataset.close()

    def test_distinct_self_declared_review_facts_also_never_release_authority(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            reviewed_path = (
                dataset.root
                / dataset.manifest['cases'][0]['reviewed_output_path'])
            reviewed = json.loads(reviewed_path.read_text(encoding='utf-8'))
            reviewed['prediction']['policy']['product_name'] = (
                'distinct-self-declared-product')
            _refresh_reviewed_digest(reviewed)
            reviewed_path.write_text(json.dumps(reviewed), encoding='utf-8')

            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {
                        'legacy': ExactAdapter(dataset),
                        'review': ExactAdapter(dataset),
                    },
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            post = report.variants['review/post_review']
            self.assertEqual(exit_code, 1)
            self.assertEqual(post['status'], 'not_verified')
            self.assertEqual(
                post['metrics']['product_exact']['numerator'], 99)
        finally:
            dataset.close()

    def test_release_gate_rejects_review_rows_without_canonical_refs(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            review = ExactAdapter(dataset)
            original_run = review.run

            def no_refs(case, context):
                observation = original_run(case, context)
                for row in observation.prediction.coverage_rows:
                    row.source_ref = None
                return observation

            review.run = no_refs

            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {
                        'legacy': ExactAdapter(dataset),
                        'review': review,
                    },
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            self.assertEqual(exit_code, 1)
            review_pre = report.variants['review/pre_review']
            self.assertEqual(
                review_pre['metrics']['coverage_recall']['numerator'], 0)
            self.assertFalse(review_pre['reference_contract_match'])
        finally:
            dataset.close()

    @override_settings(CLAUDE_MODEL_PARSE='configured-private-model')
    @mock.patch(
        'inpa.insurances.extraction_eval_adapters.'
        '_legacy_prompt_version', return_value='legacy-prompt-v1')
    @mock.patch(
        'inpa.insurances.extraction_eval_adapters.'
        '_normalization_snapshots_and_lookup')
    def test_live_runtime_uses_honest_distinct_variant_contracts(
        self, snapshots, _prompt_version,
    ):
        snapshots.return_value = (
            'sha256:' + ('b' * 64),
            'sha256:' + ('c' * 64),
            {},
        )
        contexts, adapters = build_live_runtime(('legacy', 'review'))
        self.assertEqual(set(contexts), {'legacy', 'review'})
        self.assertEqual(set(adapters), {'legacy', 'review'})
        self.assertEqual(
            contexts['legacy'].schema_version,
            'legacy-ocr-data-unversioned',
        )
        self.assertEqual(
            contexts['legacy'].prompt_version, 'legacy-prompt-v1')
        self.assertNotEqual(
            contexts['legacy'].normalization_snapshot,
            contexts['review'].normalization_snapshot,
        )
        self.assertNotEqual(
            contexts['legacy'].schema_version,
            contexts['review'].schema_version,
        )

    def test_gates_apply_to_review_not_legacy_and_missing_post_fails_only_when_requested(self):
        dataset = PrivateDataset(reviewed=False)
        try:
            legacy = ExactAdapter(dataset)
            review = ExactAdapter(dataset)
            original = review.run

            def review_omission(case, context):
                observation = original(case, context)
                if case.case_id == 'holdout_0000':
                    observation.prediction.coverage_rows.pop(0)
                return observation

            review.run = review_omission

            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {'legacy': legacy, 'review': review},
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=False,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                report.variants['review/post_review']['status'],
                'not_measured')

            _report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            self.assertEqual(exit_code, 1)
        finally:
            dataset.close()

    def test_review_post_gate_requires_zero_exact_krw_errors_and_contract_match(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            reviewed_path = (
                dataset.root
                / dataset.manifest['cases'][0]['reviewed_output_path'])
            reviewed = json.loads(reviewed_path.read_text(encoding='utf-8'))
            reviewed['prediction']['coverage_rows'][0]['premium'] += 1
            _refresh_reviewed_digest(reviewed)
            reviewed_path.write_text(json.dumps(reviewed), encoding='utf-8')

            def factory(_compare):
                return (
                    EvalRunContext.model_validate(RUN_CONTEXT),
                    {'review': ExactAdapter(dataset)},
                )

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=True,
            )
            self.assertEqual(exit_code, 1)
            self.assertEqual(
                report.variants['review/post_review']['metrics']
                ['material_amount_error']['count'],
                1,
            )
        finally:
            dataset.close()

    def test_provider_failure_returns_exit_one_without_gate_flag(self):
        dataset = PrivateDataset(reviewed=False)
        try:
            adapter = ExactAdapter(dataset)
            original = adapter.run

            def provider_failure(case, context):
                if case.case_id == 'holdout_0000':
                    raise TimeoutError('private-payload-sentinel')
                return original(case, context)

            adapter.run = provider_failure

            def factory(_compare):
                return EvalRunContext.model_validate(RUN_CONTEXT), {
                    'review': adapter,
                }

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=False,
            )
            self.assertEqual(exit_code, 1)
            self.assertNotIn(
                'private-payload-sentinel',
                json.dumps(report.to_public_dict()),
            )
        finally:
            dataset.close()

    def test_legacy_omission_is_reported_but_not_a_release_gate(self):
        dataset = PrivateDataset(reviewed=True)
        try:
            legacy = ExactAdapter(dataset)
            original = legacy.run

            def legacy_omission(case, context):
                observation = original(case, context)
                if case.case_id == 'holdout_0000':
                    observation.prediction.coverage_rows.pop(0)
                return observation

            legacy.run = legacy_omission

            def factory(_compare):
                return EvalRunContext.model_validate(RUN_CONTEXT), {
                    'legacy': legacy,
                    'review': ExactAdapter(dataset),
                }

            report, exit_code = run_private_evaluation(
                dataset.root, dataset.manifest_path,
                split='holdout', compare='legacy,review',
                runtime_factory=factory, worktree_roots=(),
                fail_on_release_gates=False,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(
                report.variants['legacy/pre_review']['metrics']
                ['silent_omission']['count'],
                1,
            )
        finally:
            dataset.close()

    @mock.patch(
        'inpa.insurances.management.commands.eval_insurance_extraction.'
        'build_live_runtime')
    def test_command_maps_pre_adapter_contract_failure_to_exit_two(self, factory):
        dataset = PrivateDataset()
        try:
            dataset.manifest['cases'] = dataset.manifest['cases'][:99]
            dataset.write_manifest()
            with self.assertRaises(CommandError) as caught:
                call_command(
                    'eval_insurance_extraction',
                    dataset_root=str(dataset.root),
                    manifest=str(dataset.manifest_path),
                    split='holdout', compare='legacy,review',
                    stdout=io.StringIO(), stderr=io.StringIO(),
                )
            self.assertEqual(caught.exception.returncode, 2)
            factory.assert_not_called()
        finally:
            dataset.close()

    @mock.patch(
        'inpa.insurances.management.commands.eval_insurance_extraction.'
        'build_live_runtime')
    def test_command_rejects_unverified_review_provenance_before_factory(
        self, factory,
    ):
        for mutation in ('missing', 'truth_access', 'truth_digest', 'copy'):
            with self.subTest(mutation=mutation):
                dataset = PrivateDataset()
                try:
                    reviewed_path = (
                        dataset.root
                        / dataset.manifest['cases'][0][
                            'reviewed_output_path'])
                    reviewed = json.loads(
                        reviewed_path.read_text(encoding='utf-8'))
                    if mutation == 'missing':
                        reviewed.pop('provenance')
                    elif mutation == 'truth_access':
                        reviewed['provenance']['truth_access'] = True
                    elif mutation == 'truth_digest':
                        reviewed['provenance']['content_digest'] = (
                            _content_digest(dataset.truth()))
                    else:
                        reviewed = dataset.truth()
                    reviewed_path.write_text(
                        json.dumps(reviewed), encoding='utf-8')
                    with self.assertRaises(CommandError) as caught:
                        call_command(
                            'eval_insurance_extraction',
                            dataset_root=str(dataset.root),
                            manifest=str(dataset.manifest_path),
                            split='holdout', compare='legacy,review',
                            stdout=io.StringIO(), stderr=io.StringIO(),
                        )
                    self.assertEqual(caught.exception.returncode, 2)
                    factory.assert_not_called()
                finally:
                    dataset.close()

    @mock.patch(
        'inpa.insurances.management.commands.eval_insurance_extraction.'
        'build_live_runtime')
    def test_command_prints_aggregate_only_without_private_values(self, factory):
        dataset = PrivateDataset(reviewed=False)
        try:
            factory.return_value = (
                EvalRunContext.model_validate(RUN_CONTEXT),
                {'legacy': ExactAdapter(dataset)},
            )
            output = io.StringIO()
            call_command(
                'eval_insurance_extraction',
                dataset_root=str(dataset.root),
                manifest=str(dataset.manifest_path),
                split='holdout', compare='legacy',
                stdout=output, stderr=io.StringIO(),
            )
            payload = json.loads(output.getvalue())
            encoded = json.dumps(payload, ensure_ascii=False)
            self.assertEqual(payload['scope'], 'insurance_extraction_only')
            self.assertNotIn('private-product-', encoded)
            self.assertNotIn('private-coverage-', encoded)
            self.assertNotIn(str(dataset.root), encoded)
            self.assertNotIn('case_id', encoded)
        finally:
            dataset.close()
