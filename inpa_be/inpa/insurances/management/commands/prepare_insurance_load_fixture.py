import copy
import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from dataclasses import asdict
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from rest_framework.authtoken.models import Token

from inpa.accounts.models import Profile, User
from inpa.analysis.models import AnalysisDetail
from inpa.customers.consent_texts import CONSENT_TEXTS_VERSION
from inpa.customers.models import ConsentLog, Customer

from ...import_contract import CoverageCandidate, MaskedLine
from ...import_validation import validate_draft
from ...models import (
    CustomerInsurance,
    CustomerInsuranceDetail,
    InsuranceCategory,
    InsuranceDetail,
    InsuranceExtractionJob,
    InsuranceSubCategory,
)
from ...tasks import NORMALIZATION_VERSION


FIXTURE_MARKER = 'INPA_SYNTHETIC_LOAD_FIXTURE_V1'
MARKER_FILE = '.inpa-load-fixture.json'
MARKER_SCHEMA = 'inpa-insurance-load-fixture-v1'
SCENARIO_SCHEMA = 'insurance-import-concurrency-scenario-v2'
AUTH_SCHEMA = 'insurance-import-concurrency-auth-v1'
OWNER_COUNT = 20
DOCUMENTS_PER_OWNER = 3
SAFE_REF = re.compile(r'^[A-Za-z0-9._-]{1,64}$')
SAFE_HOST = re.compile(r'^[a-z0-9.-]{1,253}$')
TARGET_NAME = '[합성 부하] 교체 대상 보험'
STAGING_DATABASE_NAME = 'inpa_insurance_staging'
STAGING_BUCKET_NAME = 'inpa-insurance-staging'
STAGING_STORAGE_BACKEND = 'storages.backends.s3.S3Storage'


def fixture_emails():
    return tuple(
        f'inpa-load-owner-{index:02d}@load.inpa.invalid'
        for index in range(1, OWNER_COUNT + 1)
    )


def fixture_run_marker(run_id):
    return f'{FIXTURE_MARKER}:{run_id}'


def validate_staging_resources(expected_host):
    host = expected_host.lower()
    if (not SAFE_HOST.fullmatch(host) or '..' in host
            or 'staging' not in host):
        raise CommandError('staging 전용 호스트를 입력해 주세요.')
    if (connection.vendor != 'postgresql'
            or connection.settings_dict.get('NAME') != STAGING_DATABASE_NAME):
        raise CommandError('전용 staging 데이터베이스에서만 실행할 수 있습니다.')
    if getattr(settings, 'AWS_STORAGE_BUCKET_NAME', '') != STAGING_BUCKET_NAME:
        raise CommandError('전용 staging 저장소에서만 실행할 수 있습니다.')
    storage = settings.STORAGES.get('insurance_sources', {})
    options = storage.get('OPTIONS', {})
    if (storage.get('BACKEND') != STAGING_STORAGE_BACKEND
            or options.get('bucket_name') != STAGING_BUCKET_NAME):
        raise CommandError('비공개 staging 증권 저장소를 확인해 주세요.')
    return host


def _owner_label(index):
    return chr(ord('a') + index - 1)


def _is_within(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _worktree_roots():
    repo_root = Path(settings.BASE_DIR).resolve().parent
    roots = {repo_root}
    try:
        completed = subprocess.run(
            ['git', 'worktree', 'list', '--porcelain'],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return roots
    for line in completed.stdout.splitlines():
        if line.startswith('worktree '):
            roots.add(Path(line.removeprefix('worktree ')).resolve())
    return roots


def _assert_no_symlink_components(path, *, allow_missing_leaf):
    current = Path(path.anchor)
    parts = path.parts[1:]
    for index, part in enumerate(parts):
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            if allow_missing_leaf and index == len(parts) - 1:
                return
            raise CommandError('비공개 경로를 먼저 준비해 주세요.') from None
        if stat.S_ISLNK(metadata.st_mode):
            raise CommandError('바로 연결된 경로에는 부하 자료를 만들지 않습니다.')


def validate_private_root(value, *, create=False, missing_ok=False):
    root = Path(value)
    if not root.is_absolute() or '..' in root.parts:
        raise CommandError('비공개 절대경로를 입력해 주세요.')
    if 'samples' in {part.lower() for part in root.parts}:
        raise CommandError('실제 증권 보관 경로는 부하 자료에 사용할 수 없습니다.')
    _assert_no_symlink_components(
        root, allow_missing_leaf=create or missing_ok)
    resolved = root.resolve(strict=False)
    if any(_is_within(resolved, worktree) for worktree in _worktree_roots()):
        raise CommandError('작업 폴더 밖의 비공개 경로를 사용해 주세요.')
    if create and not root.exists():
        try:
            root.mkdir(mode=0o700)
        except OSError:
            raise CommandError('비공개 폴더를 만들지 못했습니다.') from None
    if missing_ok and not root.exists():
        return resolved
    try:
        metadata = root.lstat()
    except OSError:
        raise CommandError('비공개 폴더를 찾지 못했습니다.') from None
    if (not stat.S_ISDIR(metadata.st_mode)
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise CommandError('비공개 폴더 권한은 0700이어야 합니다.')
    return root.resolve()


def expected_fixture_files(root):
    files = {
        root / MARKER_FILE,
        root / 'scenario.json',
        root / 'auth.json',
    }
    files.update(
        root / 'documents' / f'o{owner:02d}-d{document}.pdf'
        for owner in range(1, OWNER_COUNT + 1)
        for document in range(1, DOCUMENTS_PER_OWNER + 1)
    )
    return files


def validate_fixture_subset(root, run_id):
    marker_path = root / MARKER_FILE
    allowed_files = expected_fixture_files(root)
    documents_dir = root / 'documents'
    actual_files = set()
    for path in root.rglob('*'):
        metadata = path.lstat()
        if stat.S_ISLNK(metadata.st_mode):
            raise CommandError('바로 연결된 합성 자료는 사용하지 않습니다.')
        if stat.S_ISDIR(metadata.st_mode):
            if path != documents_dir:
                raise CommandError('정해진 합성 자료만 사용할 수 있습니다.')
            if stat.S_IMODE(metadata.st_mode) != 0o700:
                raise CommandError('합성 문서 폴더 권한은 0700이어야 합니다.')
        elif stat.S_ISREG(metadata.st_mode):
            if path not in allowed_files:
                raise CommandError('정해진 합성 자료만 사용할 수 있습니다.')
            if stat.S_IMODE(metadata.st_mode) != 0o600:
                raise CommandError('합성 자료 파일 권한은 0600이어야 합니다.')
            actual_files.add(path)
        else:
            raise CommandError('정해진 합성 자료만 사용할 수 있습니다.')
    if marker_path not in actual_files:
        raise CommandError('합성 자료 표식을 확인해 주세요.')
    try:
        marker = json.loads(marker_path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise CommandError('합성 자료 표식을 확인해 주세요.') from None
    if marker != {'schema_version': MARKER_SCHEMA, 'run_id': run_id}:
        raise CommandError('다른 실행의 비공개 폴더는 사용하지 않습니다.')
    return actual_files


def _write_private(path, payload):
    if path.exists() and stat.S_ISLNK(path.lstat().st_mode):
        raise CommandError('바로 연결된 파일은 덮어쓰지 않습니다.')
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = None
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(payload)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError
            remaining = remaining[written:]
    except OSError:
        raise CommandError('비공개 파일을 안전하게 저장하지 못했습니다.') from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _json_bytes(value):
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
        + '\n').encode('utf-8')


def _pdf_bytes(text):
    safe_text = text.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
    stream = f'BT /F1 11 Tf 48 760 Td ({safe_text}) Tj ET\n'.encode('ascii')
    objects = (
        b'<< /Type /Catalog /Pages 2 0 R >>',
        b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
        (b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] '
         b'/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>'),
        b'<< /Length ' + str(len(stream)).encode('ascii')
        + b' >>\nstream\n' + stream + b'endstream',
        b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
    )
    result = bytearray(
        f'%PDF-1.4\n%{FIXTURE_MARKER}\n'.encode('ascii'))
    offsets = [0]
    for index, body in enumerate(objects, 1):
        offsets.append(len(result))
        result.extend(f'{index} 0 obj\n'.encode('ascii'))
        result.extend(body)
        result.extend(b'\nendobj\n')
    xref = len(result)
    result.extend(f'xref\n0 {len(objects) + 1}\n'.encode('ascii'))
    result.extend(b'0000000000 65535 f \n')
    for offset in offsets[1:]:
        result.extend(f'{offset:010d} 00000 n \n'.encode('ascii'))
    result.extend(
        f'trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n'
        f'startxref\n{xref}\n%%EOF\n'.encode('ascii'))
    return bytes(result)


def _review_material():
    line = MaskedLine(
        line_id='p01-l001', page=1, line=1,
        text_masked='일반암진단비 가입금액 3,000만원 보험료 30,000원')
    candidate = CoverageCandidate(
        candidate_id='c00001', evidence_line_ids=(line.line_id,),
        text_masked=line.text_masked)
    empty = {'value': None, 'evidence_line_ids': []}
    payload = {
        'schema_version': 'insurance-review-v1',
        'policy': {
            'carrier_name': copy.deepcopy(empty),
            'company_code': copy.deepcopy(empty),
            'insurance_type': {
                'value': 'loss', 'evidence_line_ids': [], 'state': 'manual'},
            'product_name': {
                'value': '합성 부하 건강보험',
                'evidence_line_ids': [], 'state': 'manual'},
            'contract_date': copy.deepcopy(empty),
            'expiry_date': copy.deepcopy(empty),
            'monthly_premium': copy.deepcopy(empty),
        },
        'coverage_rows': [{
            'row_id': 'row-1',
            'raw_name': '일반암진단비',
            'assurance_amount': 30_000_000,
            'premium': 30_000,
            'is_renewal': False,
            'renewal_period': None,
            'payment_period': 20,
            'payment_period_unit': 'years',
            'warranty_period': 100,
            'warranty_period_unit': 'age',
            'disposition': 'assigned',
            'standard_category': '진단-암',
            'standard_subcategory': '일반암',
            'standard_detail_name': '일반암진단비',
            'exclusion_reason': None,
            'duplicate_of_row_id': None,
            'source_candidate_ids': ['c00001'],
            'evidence_line_ids': ['p01-l001'],
        }],
    }
    validated = validate_draft(
        (line,), (candidate,), payload, allow_manual=True)
    summary = {
        **validated.summary,
        'intake_candidates': [{
            **asdict(candidate),
            'evidence_line_ids': list(candidate.evidence_line_ids),
        }],
        '_system': {'source_readability': {
            'page_count': 1,
            'image_only_page_count': 0,
            'image_only_pages': [],
            'quarantined_line_count': 0,
            'quarantined_pages': [],
            'analysis_signal_quarantined_line_count': 0,
            'analysis_signal_quarantined_pages': [],
            'pages_requiring_manual_source_review': [],
        }},
    }
    return line, validated.draft, summary


def _catalog_detail():
    with transaction.atomic():
        seeded_matches = list(
            AnalysisDetail.objects.select_for_update().filter(
                sub_category__category__name='[표준]진단-암',
                sub_category__name='일반암',
                name='일반암진단비',
            ).order_by('pk')[:2]
        )
        if len(seeded_matches) != 1:
            raise CommandError('표준 담보 시드를 먼저 준비해 주세요.')
        seeded_detail = seeded_matches[0]

        categories = list(
            InsuranceCategory.objects.select_for_update().filter(
                name='진단-암').order_by('pk')[:2]
        )
        if len(categories) > 1:
            raise CommandError('합성 부하용 담보 연결을 확인해 주세요.')
        category = categories[0] if categories else InsuranceCategory.objects.create(
            name='진단-암',
            order=seeded_detail.sub_category.category.order,
        )

        subcategories = list(
            InsuranceSubCategory.objects.select_for_update().filter(
                category=category,
                name='일반암',
            ).order_by('pk')[:2]
        )
        if len(subcategories) > 1:
            raise CommandError('합성 부하용 담보 연결을 확인해 주세요.')
        subcategory = (
            subcategories[0]
            if subcategories
            else InsuranceSubCategory.objects.create(
                category=category,
                name='일반암',
                order=seeded_detail.sub_category.order,
            )
        )

        details = list(
            InsuranceDetail.objects.select_for_update().filter(
                sub_category=subcategory,
                name='일반암진단비',
            ).order_by('pk')[:2]
        )
        if len(details) > 1:
            raise CommandError('합성 부하용 담보 연결을 확인해 주세요.')
        detail = details[0] if details else InsuranceDetail.objects.create(
            sub_category=subcategory,
            name='일반암진단비',
            order=seeded_detail.order,
            chart_based_amount=seeded_detail.chart_based_amount,
        )

        linked_ids = set(detail.analysis_detail.values_list('pk', flat=True))
        if not linked_ids:
            detail.analysis_detail.add(seeded_detail)
        elif linked_ids != {seeded_detail.pk}:
            raise CommandError('합성 부하용 담보 연결을 확인해 주세요.')
        return detail


class Command(BaseCommand):
    help = 'Create the private synthetic 20-owner insurance load fixture.'

    def add_arguments(self, parser):
        parser.add_argument('--private-root', required=True)
        parser.add_argument('--run-id', required=True)
        parser.add_argument('--expected-host', required=True)

    def handle(self, *args, **options):
        if not settings.INSURANCE_LOAD_TEST_ENABLED:
            raise CommandError('합성 부하 실행 스위치를 먼저 열어 주세요.')
        if not settings.INSURANCE_REVIEW_GATE_ENABLED:
            raise CommandError('검토형 staging 경로를 먼저 열어 주세요.')
        run_id = options['run_id']
        host = options['expected_host'].lower()
        if not SAFE_REF.fullmatch(run_id):
            raise CommandError('안전한 실행 이름을 입력해 주세요.')
        run_marker = fixture_run_marker(run_id)
        if len(run_marker) > Profile._meta.get_field('affiliation').max_length:
            raise CommandError('실행 이름을 더 짧게 입력해 주세요.')
        host = validate_staging_resources(host)
        root = validate_private_root(options['private_root'], create=True)
        marker_path = root / MARKER_FILE
        if any(root.iterdir()):
            validate_fixture_subset(root, run_id)
        _write_private(marker_path, _json_bytes({
            'schema_version': MARKER_SCHEMA,
            'run_id': run_id,
        }))

        documents_dir = root / 'documents'
        if not documents_dir.exists():
            documents_dir.mkdir(mode=0o700)
        if (stat.S_ISLNK(documents_dir.lstat().st_mode)
                or stat.S_IMODE(documents_dir.stat().st_mode) != 0o700):
            raise CommandError('합성 문서 폴더 권한은 0700이어야 합니다.')

        catalog_detail = _catalog_detail()
        line, draft, summary = _review_material()
        owners = []
        tokens = {}
        prepared_jobs = []
        user_rows = []
        with transaction.atomic():
            for index, email in enumerate(fixture_emails(), 1):
                user, created = User.objects.get_or_create(
                    email=email,
                    defaults={'is_active': True},
                )
                if created:
                    user.set_unusable_password()
                    user.save(update_fields=['password'])
                    Profile.objects.create(
                        user=user,
                        affiliation=run_marker,
                        email_verified_at=timezone.now(),
                    )
                else:
                    try:
                        profile = user.profile
                    except Profile.DoesNotExist:
                        raise CommandError('합성 계정 표식을 확인해 주세요.') from None
                    if (profile.affiliation != run_marker
                            or user.has_usable_password()
                            or user.is_staff or user.is_superuser):
                        raise CommandError('합성 계정 표식을 확인해 주세요.')
                if not user.is_active:
                    user.is_active = True
                    user.save(update_fields=['is_active'])
                customer, _ = Customer.objects.get_or_create(
                    owner=user,
                    name=f'합성 부하 고객 {index:02d}',
                    defaults={'birth_day': '1990-01-01'},
                )
                customer.consent_overseas_at = timezone.now()
                customer.save(update_fields=['consent_overseas_at'])
                ConsentLog.objects.get_or_create(
                    customer=customer,
                    scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
                    subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
                    doc_version=CONSENT_TEXTS_VERSION,
                )
                token, _ = Token.objects.get_or_create(user=user)
                owner_ref = f'owner-{_owner_label(index)}'
                user_rows.append((user, customer, owner_ref))
                tokens[owner_ref] = token.key

            fixture_users = [item[0] for item in user_rows]
            InsuranceExtractionJob.objects.filter(
                owner__in=fixture_users).delete()
            CustomerInsurance.objects.filter(
                customer__owner__in=fixture_users,
            ).exclude(name=TARGET_NAME).delete()

            _replace_user, replace_customer, _ = user_rows[1]
            target, _ = CustomerInsurance.objects.get_or_create(
                customer=replace_customer,
                name=TARGET_NAME,
                defaults={'portfolio_type': 1},
            )
            target.portfolio_type = 1
            target.review_status = 'confirmed'
            target.analysis_included = True
            target.data_version = 1
            target.save(update_fields=(
                'portfolio_type', 'review_status', 'analysis_included',
                'data_version', 'updated_at'))
            target.case_list.all().delete()
            CustomerInsuranceDetail.objects.create(
                insurance=target,
                detail=catalog_detail,
                raw_name='일반암진단비',
                assurance_amount=20_000_000,
                premium=20_000,
                payment_period_type=1,
                payment_period=20,
                warranty_period_type=1,
                warranty_period='100',
                mapping_source='global',
                confirmed_at=timezone.now(),
            )

            specs = (
                ('prepared-add-a', user_rows[0], 'add', None),
                ('prepared-add-b', user_rows[0], 'add', None),
                ('prepared-replace-a', user_rows[1], 'replace', target),
                ('prepared-replace-b', user_rows[1], 'replace', target),
            )
            for index, (job_ref, owner_row, intent, target_row) in enumerate(specs, 1):
                user, customer, owner_ref = owner_row
                job_id = uuid.uuid5(
                    uuid.NAMESPACE_URL, f'inpa-load:{run_id}:{job_ref}')
                digest = hashlib.sha256(
                    f'{FIXTURE_MARKER}:{run_id}:{job_ref}'.encode()).hexdigest()
                job = InsuranceExtractionJob.objects.create(
                    id=job_id,
                    owner=user,
                    customer=customer,
                    target_insurance=target_row,
                    target_insurance_version=(
                        target_row.data_version if target_row else None),
                    intent=intent,
                    portfolio_type=1,
                    status='review_required',
                    file_sha256=digest,
                    file_size=100,
                    page_count=1,
                    safe_display_name='synthetic-policy.pdf',
                    source_expires_at=timezone.now() + timedelta(hours=1),
                    masked_lines=[asdict(line)],
                    draft_payload=copy.deepcopy(draft),
                    validation_summary=copy.deepcopy(summary),
                    normalization_version=NORMALIZATION_VERSION,
                )
                prepared_jobs.append({
                    'job_ref': job_ref,
                    'job_id': str(job.id),
                    'owner_ref': owner_ref,
                    'customer_id': customer.pk,
                    'intent': intent,
                    'status': 'review_required',
                    'expected_confirmed_coverage_count': 1,
                })

        shared_pdf = _pdf_bytes(
            f'{FIXTURE_MARKER} SYNTHETIC DIGITAL POLICY SHARED '
            'CANCER COVERAGE AMOUNT 30000000 PREMIUM 30000')
        for index, (_user, customer, owner_ref) in enumerate(user_rows, 1):
            owner_documents = []
            for document_index in range(1, DOCUMENTS_PER_OWNER + 1):
                path = documents_dir / f'o{index:02d}-d{document_index}.pdf'
                payload = shared_pdf if document_index == 1 else _pdf_bytes(
                    f'{FIXTURE_MARKER} SYNTHETIC DIGITAL POLICY '
                    f'O{index:02d} D{document_index} CANCER COVERAGE '
                    'AMOUNT 30000000 PREMIUM 30000')
                _write_private(path, payload)
                owner_documents.append({
                    'case_id': (
                        f'case-{_owner_label(index)}-'
                        f'{chr(96 + document_index)}'),
                    'file_path': str(path),
                    'hash_group': (
                        'shared-a' if document_index == 1
                        else f'hash-{_owner_label(index)}-'
                        f'{chr(96 + document_index)}'),
                    'intent': 'add',
                    'portfolio_type': 1,
                })
            owners.append({
                'owner_ref': owner_ref,
                'customer_id': customer.pk,
                'documents': owner_documents,
            })

        scenario = {
            'schema_version': SCENARIO_SCHEMA,
            'run_id': run_id,
            'expected_host': host,
            'private_root': str(root),
            'polling': {
                'timeout_seconds': 45,
                'drain_timeout_seconds': 600,
                'interval_seconds': 1,
                'max_attempts': 600,
            },
            'owners': owners,
            'prepared_jobs': prepared_jobs,
            'confirm_groups': [{
                'group_ref': 'preserve-two-adds',
                'owner_ref': user_rows[0][2],
                'job_refs': ['prepared-add-a', 'prepared-add-b'],
                'expected': 'both_confirmed',
                'analysis_customer_id': user_rows[0][1].pk,
                'expected_analysis_total_amount': 60_000_000,
            }, {
                'group_ref': 'single-replace-winner',
                'owner_ref': user_rows[1][2],
                'job_refs': ['prepared-replace-a', 'prepared-replace-b'],
                'target_ref': 'prepared-target-a',
                'expected': 'one_confirmed_one_target_changed',
                'analysis_customer_id': user_rows[1][1].pk,
                'expected_analysis_total_amount': 30_000_000,
            }],
        }
        auth = {'schema_version': AUTH_SCHEMA, 'tokens': tokens}
        _write_private(root / 'scenario.json', _json_bytes(scenario))
        _write_private(root / 'auth.json', _json_bytes(auth))
        self.stdout.write(
            'LOAD FIXTURE READY owners=20 documents=60 jobs=4')
