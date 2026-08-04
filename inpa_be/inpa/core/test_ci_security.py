from pathlib import Path

from django.test import SimpleTestCase


class CryptographyAuditExceptionTests(SimpleTestCase):
    repo_root = Path(__file__).resolve().parents[3]
    workflow_path = repo_root / '.github' / 'workflows' / 'ci.yml'
    blocked_apis = (
        'pkcs7_decrypt_der',
        'pkcs7_decrypt_pem',
        'pkcs7_decrypt_smime',
    )

    def test_ci_exception_is_limited_to_the_unreleased_fix(self):
        workflow = self.workflow_path.read_text(encoding='utf-8')

        self.assertIn('--ignore-vuln CVE-2026-69247', workflow)
        self.assertEqual(workflow.count('--ignore-vuln'), 1)
        self.assertIn('cryptography>=50.0.0', workflow)

    def test_production_code_does_not_use_the_affected_pkcs7_decrypt_apis(self):
        source_root = self.repo_root / 'inpa_be' / 'inpa'
        violations = []
        for path in source_root.rglob('*.py'):
            relative_parts = path.relative_to(source_root).parts
            if path.name.startswith('test') or 'tests' in relative_parts:
                continue
            source = path.read_text(encoding='utf-8')
            for api in self.blocked_apis:
                if api in source:
                    violations.append(f'{path.relative_to(self.repo_root)}: {api}')

        self.assertEqual(
            violations,
            [],
            'CVE-2026-69247 예외가 유지되는 동안 영향받는 API를 사용할 수 없습니다.',
        )
