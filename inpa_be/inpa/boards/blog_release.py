"""Validated, versioned release tooling for repository-owned blog content."""

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import re

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inpa.core.copyguard import scan_blog_content

from .models import BlogContentRelease, BlogPost


RELEASE_VERSION = '2026-08-blog-enrichment-v1'
REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONTENT_DIR = REPO_ROOT / 'docs' / 'blog-content'
DEFAULT_MANIFEST_PATH = REPO_ROOT / 'inpa_fe' / 'public' / 'blog-assets' / 'manifest.json'

BLOG_TEMPLATE_DISCLAIMER = (
    '인파는 보험을 중개·권유하지 않는 분석·정리 소프트웨어입니다. '
    '보장 판단과 고객 안내는 설계사님의 업무입니다.'
)
SAFETY_SLUGS = frozenset({
    '보험-갈아타기-비교',
    '비교안내서-한눈에-보는-비교표',
    '보험-갈아타기-설계사-순서',
})
RELEASE_CREATED_SLUGS = frozenset({
    '보험-증권-요청-문자-안내',
    '보험-상담-준비-체크리스트',
    '보험-상담-후-기록-다음-연락',
    '상담-예약-전날-당일-안내',
    '보험설계사-고객관리표-필수-항목',
    '보험나이-계산법-6개월-예시',
    '보험-직업급수-확인-순서',
})
RELEASE_EXISTING_SLUGS = frozenset({
    '신입-보험설계사-지인-영업-다음-할-일',
    '상담-예약률-높이는-문자와-화법',
    '보험-증권-보는-법-3분-체크리스트',
    '갱신형-비갱신형-차이',
    '3대-진단비란-암-뇌-심장',
    '회사마다-보험-담보-이름-다른-이유',
    '보험-갈아타기-비교',
    '비교안내서-한눈에-보는-비교표',
    '상담-준비에-쫓기던-새내기-하루-각색',
    '보험-갈아타기-설계사-순서',
    '보험-가입-전-확인사항',
    '좋은-보험이란',
    '실손의료비보험-기본-쉽게-짚어보기',
})
RELEASE_SLUGS = RELEASE_EXISTING_SLUGS | RELEASE_CREATED_SLUGS

PUBLIC_CONTENT_FIELDS = (
    'title',
    'slug',
    'body',
    'excerpt',
    'cover_image',
    'cover_asset_path',
    'category',
    'tags',
    'is_published',
    'published_at',
    'seo_title',
    'seo_description',
    'is_noindex',
)
_SNAPSHOT_STRING_LIMITS = {
    'title': 200,
    'slug': 200,
    'body': None,
    'excerpt': 300,
    'cover_image': 100,
    'cover_asset_path': 300,
    'category': 30,
    'tags': 200,
    'seo_title': 60,
    'seo_description': 160,
}

_META_FIELDS = frozenset({
    'slug',
    'category',
    'excerpt',
    'tags',
    'seo_title',
    'seo_description',
    'cover_asset_path',
    'is_published',
    'review_gate',
    'legal_review',
    'sources',
})
_SOURCE_PATTERN = re.compile(
    r'\A<!-- blog-meta\n(?P<meta>\{.*?\})\n-->\n'
    r'# (?P<title>[^\n]+)\n\n<!-- blog-body -->\n\n(?P<body>.*)\Z',
    re.DOTALL,
)
_BODY_IMAGE_PATTERN = re.compile(
    r'!\[[^\]]*\]\(\s*(?P<path><[^>]+>|[^\s\)]+)'
)
_REFERENCE_IMAGE_PATTERN = re.compile(
    r'!\[(?P<alt>[^\]]*)\]\[(?P<label>[^\]]*)\]'
)
_SHORTCUT_REFERENCE_IMAGE_PATTERN = re.compile(
    r'!\[(?P<alt>[^\]]+)\](?![\(\[])'
)
_REFERENCE_DEFINITION_PATTERN = re.compile(
    r'^\s*\[(?P<label>[^\]]+)\]:\s*(?P<path>\S+)', re.MULTILINE,
)
_ISO_DATE_PATTERN = re.compile(r'^\d{4}-\d{2}-\d{2}$')
_ISO_DATETIME_PATTERN = re.compile(
    r'^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?$'
)
_DIGEST_PATTERN = re.compile(r'^[0-9a-f]{64}$')


class ReleaseError(ValueError):
    """A release package or state failed a blocking safety check."""


@dataclass(frozen=True)
class BlogReleaseItem:
    slug: str
    category: str
    excerpt: str
    tags: list[str]
    seo_title: str
    seo_description: str
    cover_asset_path: str
    is_published: bool
    review_gate: str
    legal_review: dict | None
    sources: list[dict]
    title: str
    body: str


def _normalized_bytes(path):
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        raise ReleaseError(f'릴리스 파일을 읽을 수 없습니다: {Path(path).name}') from exc
    return raw.replace(b'\r\n', b'\n').replace(b'\r', b'\n')


def _is_nonempty_string(value):
    return type(value) is str and bool(value.strip())


def _valid_legal_review(value):
    if type(value) is not dict:
        return False
    if set(value) != {'reviewer', 'reviewed_at', 'reference'}:
        return False
    structurally_valid = (
        _is_nonempty_string(value.get('reviewer'))
        and _is_nonempty_string(value.get('reference'))
        and _is_nonempty_string(value.get('reviewed_at'))
        and bool(_ISO_DATETIME_PATTERN.fullmatch(value['reviewed_at']))
    )
    if not structurally_valid:
        return False
    try:
        datetime.fromisoformat(value['reviewed_at'].replace('Z', '+00:00'))
    except ValueError:
        return False
    return True


def _parse_source(path, source_bytes):
    try:
        source = source_bytes.decode('utf-8')
    except UnicodeDecodeError as exc:
        raise ReleaseError(f'{path.name}: UTF-8 원고가 아닙니다') from exc
    match = _SOURCE_PATTERN.fullmatch(source)
    if not match:
        raise ReleaseError(f'{path.name}: blog-meta/H1/blog-body 형식이 정확하지 않습니다')
    try:
        metadata = json.loads(match.group('meta'))
    except json.JSONDecodeError as exc:
        raise ReleaseError(f'{path.name}: blog-meta JSON이 올바르지 않습니다') from exc
    if type(metadata) is not dict or set(metadata) != _META_FIELDS:
        raise ReleaseError(f'{path.name}: blog-meta 필드 구성이 정확하지 않습니다')

    string_fields = (
        'slug', 'category', 'excerpt', 'seo_title', 'seo_description',
    )
    if any(not _is_nonempty_string(metadata[field]) for field in string_fields):
        raise ReleaseError(f'{path.name}: 필수 문자열 메타데이터가 비어 있습니다')
    if metadata['category'] not in dict(BlogPost.CATEGORY_CHOICES):
        raise ReleaseError(f'{path.name}: category가 올바르지 않습니다')
    if type(metadata['cover_asset_path']) is not str:
        raise ReleaseError(f'{path.name}: cover_asset_path는 문자열이어야 합니다')
    if type(metadata['tags']) is not list or any(
        not _is_nonempty_string(tag) for tag in metadata['tags']
    ):
        raise ReleaseError(f'{path.name}: tags는 비어 있지 않은 문자열 목록이어야 합니다')
    if type(metadata['is_published']) is not bool:
        raise ReleaseError(f'{path.name}: is_published는 bool이어야 합니다')
    if type(metadata['review_gate']) is not str or metadata['review_gate'] not in {
        'none', 'legal',
    }:
        raise ReleaseError(f'{path.name}: review_gate는 none 또는 legal이어야 합니다')
    if metadata['legal_review'] is not None and not _valid_legal_review(metadata['legal_review']):
        raise ReleaseError(f'{path.name}: legal_review 기록이 완전하지 않습니다')
    if type(metadata['sources']) is not list:
        raise ReleaseError(f'{path.name}: sources는 목록이어야 합니다')

    title = match.group('title').strip()
    body = match.group('body').rstrip('\n')
    if not title or not body:
        raise ReleaseError(f'{path.name}: 제목과 본문은 비어 있을 수 없습니다')
    return BlogReleaseItem(title=title, body=body, **metadata)


def load_release(content_dir=None, manifest_path=None):
    """Parse release sources and return slug-sorted items plus a stable digest."""
    content_dir = Path(content_dir) if content_dir is not None else DEFAULT_CONTENT_DIR
    manifest_path = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST_PATH
    if not content_dir.is_dir():
        raise ReleaseError(f'원고 디렉터리를 찾을 수 없습니다: {content_dir.name}')

    source_records = []
    for path in sorted(content_dir.glob('*.md')):
        normalized = _normalized_bytes(path)
        if normalized.startswith(b'<!-- blog-meta\n'):
            source_records.append((path, normalized))

    manifest_bytes = _normalized_bytes(manifest_path)
    digest_builder = hashlib.sha256()
    for _, source_bytes in source_records:
        digest_builder.update(len(source_bytes).to_bytes(8, 'big'))
        digest_builder.update(source_bytes)
    digest_builder.update(len(manifest_bytes).to_bytes(8, 'big'))
    digest_builder.update(manifest_bytes)

    items = [_parse_source(path, source_bytes) for path, source_bytes in source_records]
    return sorted(items, key=lambda item: item.slug), digest_builder.hexdigest()


def _read_manifest(manifest_path):
    try:
        payload = json.loads(Path(manifest_path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None, ['manifest.json을 읽거나 해석할 수 없습니다']
    if type(payload) is not list:
        return None, ['manifest.json 최상위 값은 목록이어야 합니다']
    errors = []
    records = {}
    for index, record in enumerate(payload, start=1):
        if type(record) is not dict or not _is_nonempty_string(record.get('path')):
            errors.append(f'manifest {index}번 항목의 path가 없습니다')
            continue
        path = record['path']
        if path in records:
            errors.append(f'manifest 경로가 중복되었습니다: {path}')
            continue
        records[path] = record
        if record.get('pii_reviewed') is not True:
            errors.append(f'PII 검토가 완료되지 않은 자산입니다: {path}')
        if record.get('rights_reviewed') is not True:
            errors.append(f'권리 검토가 완료되지 않은 자산입니다: {path}')
        used_by = record.get('used_by')
        if type(used_by) is not list or any(not _is_nonempty_string(slug) for slug in used_by):
            errors.append(f'used_by 목록이 올바르지 않은 자산입니다: {path}')
    return records, errors


def _asset_file(manifest_path, asset_path):
    if not asset_path.startswith('/blog-assets/'):
        return None
    asset_root = (Path(manifest_path).parent.parent / 'blog-assets').resolve()
    resolved = (Path(manifest_path).parent.parent / asset_path.lstrip('/')).resolve()
    if not resolved.is_relative_to(asset_root):
        return None
    return resolved


def _body_image_paths(body):
    paths = [match.group('path').strip('<>') for match in _BODY_IMAGE_PATTERN.finditer(body)]
    definitions = {
        ' '.join(match.group('label').lower().split()): match.group('path').strip('<>')
        for match in _REFERENCE_DEFINITION_PATTERN.finditer(body)
    }
    unresolved = 0
    for match in _REFERENCE_IMAGE_PATTERN.finditer(body):
        label = match.group('label') or match.group('alt')
        path = definitions.get(' '.join(label.lower().split()))
        if path is None:
            unresolved += 1
        else:
            paths.append(path)
    for match in _SHORTCUT_REFERENCE_IMAGE_PATTERN.finditer(body):
        label = ' '.join(match.group('alt').lower().split())
        path = definitions.get(label)
        if path is None:
            unresolved += 1
        else:
            paths.append(path)
    return paths, unresolved


def validate_release(items, *, manifest_path=None):
    """Return all blocking package errors without mutating files or database rows."""
    manifest_path = Path(manifest_path) if manifest_path is not None else DEFAULT_MANIFEST_PATH
    errors = []
    if len(items) != 20:
        errors.append(f'릴리스 원고는 정확히 20개여야 합니다: 현재 {len(items)}개')

    slugs = [item.slug for item in items]
    duplicate_slugs = sorted({slug for slug in slugs if slugs.count(slug) > 1})
    errors.extend(f'중복 slug가 있습니다: {slug}' for slug in duplicate_slugs)
    if set(slugs) != RELEASE_SLUGS:
        errors.append(
            '릴리스 원고는 승인된 20개 slug와 정확히 일치해야 합니다'
        )

    cover_paths = [item.cover_asset_path for item in items if item.cover_asset_path]
    duplicate_covers = sorted({path for path in cover_paths if cover_paths.count(path) > 1})
    errors.extend(f'중복 대표 이미지 경로가 있습니다: {path}' for path in duplicate_covers)

    manifest, manifest_errors = _read_manifest(manifest_path)
    errors.extend(manifest_errors)
    manifest = manifest or {}

    normalized_disclaimer = ' '.join(BLOG_TEMPLATE_DISCLAIMER.split())
    for item in items:
        if not item.cover_asset_path:
            errors.append(f'{item.slug}: 대표 이미지 경로가 없습니다')

        references = []
        if item.cover_asset_path:
            references.append(('대표 이미지', item.cover_asset_path))
        body_paths, unresolved_references = _body_image_paths(item.body)
        if unresolved_references:
            errors.append(f'{item.slug}: 정의되지 않은 reference 이미지가 있습니다')
        for body_path in body_paths:
            if not body_path.startswith('/blog-assets/'):
                errors.append(f'{item.slug}: 외부 이미지 경로는 사용할 수 없습니다')
                continue
            references.append(('본문 이미지', body_path))

        for role, asset_path in references:
            record = manifest.get(asset_path)
            if record is None:
                errors.append(f'{item.slug}: {role}가 manifest에 없습니다: {asset_path}')
                continue
            disk_path = _asset_file(manifest_path, asset_path)
            if disk_path is None or not disk_path.is_file():
                errors.append(f'{item.slug}: {role} 파일이 없습니다: {asset_path}')
            used_by = record.get('used_by')
            if role == '본문 이미지' and (
                type(used_by) is not list or item.slug not in used_by
            ):
                errors.append(f'{item.slug}: 본문 이미지 used_by에 slug가 없습니다: {asset_path}')

        if not item.sources:
            errors.append(f'{item.slug}: 공식 출처가 없습니다')
        for source_index, source in enumerate(item.sources, start=1):
            if type(source) is not dict or not _is_nonempty_string(source.get('title')):
                errors.append(f'{item.slug}: {source_index}번 공식 출처 제목이 없습니다')
                continue
            if not _is_nonempty_string(source.get('url')):
                errors.append(f'{item.slug}: {source_index}번 공식 출처 URL이 없습니다')
            checked_at = source.get('checked_at')
            valid_checked_at = False
            if _is_nonempty_string(checked_at) and _ISO_DATE_PATTERN.fullmatch(checked_at):
                try:
                    date.fromisoformat(checked_at)
                    valid_checked_at = True
                except ValueError:
                    pass
            if not valid_checked_at:
                errors.append(f'{item.slug}: {source_index}번 공식 출처 확인일이 올바르지 않습니다')

        warnings = scan_blog_content({
            'title': item.title,
            'body': item.body,
            'excerpt': item.excerpt,
            'seo_title': item.seo_title,
            'seo_description': item.seo_description,
        })
        for warning in warnings:
            errors.append(
                f'{item.slug}: 카피 검사 경고 {warning["issue"]} ({warning["field"]})'
            )

        if item.slug in SAFETY_SLUGS:
            if item.review_gate != 'legal':
                errors.append(f'{item.slug}: 법무 검토 대상은 review_gate=legal이어야 합니다')
            if item.is_published and not _valid_legal_review(item.legal_review):
                errors.append(f'{item.slug}: 유효한 법무 검토 기록 전에는 공개할 수 없습니다')

        normalized_body = ' '.join(item.body.split())
        if item.is_published and normalized_disclaimer in normalized_body:
            errors.append(f'{item.slug}: 템플릿 정직성 문구가 본문에 중복되었습니다')
    return errors


def _serialize_public_fields(post):
    values = {}
    for field in PUBLIC_CONTENT_FIELDS:
        value = getattr(post, field)
        if field == 'cover_image':
            value = value.name
        elif field == 'published_at':
            value = value.isoformat() if value is not None else None
        values[field] = value
    return values


def _snapshot_digest(payload):
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
    ).encode('utf-8')
    return hashlib.sha256(canonical).hexdigest()


def _build_snapshot(*, kind, digest, item_count, created_slugs, posts):
    payload = {
        'kind': kind,
        'version': RELEASE_VERSION,
        'release_digest': digest,
        'item_count': item_count,
        'created_slugs': sorted(created_slugs),
        'posts': [
            {
                'slug': post.slug,
                'guard_updated_at': post.updated_at.isoformat(),
                'fields': _serialize_public_fields(post),
            }
            for post in sorted(posts, key=lambda row: row.slug)
        ],
    }
    return {**payload, 'snapshot_digest': _snapshot_digest(payload)}


def _stage_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
    ).encode('utf-8')
    temporary = None
    try:
        for counter in range(100):
            candidate = path.with_name(f'.{path.name}.tmp-{os.getpid()}-{counter}')
            try:
                handle = candidate.open('xb')
            except FileExistsError:
                continue
            temporary = candidate
            break
        else:
            raise ReleaseError(f'임시 백업 파일을 만들 수 없습니다: {path.name}')
        with handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def _atomic_write_json(path, payload):
    path = Path(path)
    temporary = _stage_json(path, payload)
    try:
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _finalize_after_snapshot(staged_path, after_path):
    try:
        os.replace(staged_path, after_path)
    except OSError as exc:
        raise ReleaseError(
            'DB 적용은 완료됐지만 after snapshot 확정에 실패했습니다. '
            '같은 명령을 다시 실행해 복구하세요.'
        ) from exc


def _recover_staged_after_snapshot(after_path, digest):
    after_path = Path(after_path)
    candidates = sorted(after_path.parent.glob(f'.{after_path.name}.tmp-*'))
    if len(candidates) != 1:
        raise ReleaseError('적용 marker의 after snapshot을 안전하게 확인할 수 없습니다')
    _validate_after_snapshot(candidates[0], digest)
    _finalize_after_snapshot(candidates[0], after_path)


def _validate_snapshot_rows(rows, *, expected_slugs, label):
    if type(rows) is not list:
        raise ReleaseError(f'{label} posts가 올바르지 않습니다')
    post_slugs = []
    for row in rows:
        if type(row) is not dict or set(row) != {'slug', 'guard_updated_at', 'fields'}:
            raise ReleaseError(f'{label} post schema가 올바르지 않습니다')
        if not _is_nonempty_string(row['slug']) or not _is_nonempty_string(
            row['guard_updated_at']
        ):
            raise ReleaseError(f'{label} post 식별값이 올바르지 않습니다')
        if type(row['fields']) is not dict or set(row['fields']) != set(
            PUBLIC_CONTENT_FIELDS
        ):
            raise ReleaseError(f'{label} 공개 필드 구성이 올바르지 않습니다')
        string_fields = set(PUBLIC_CONTENT_FIELDS) - {
            'cover_image', 'is_published', 'published_at', 'is_noindex',
        }
        if any(type(row['fields'][field]) is not str for field in string_fields):
            raise ReleaseError(f'{label} 공개 필드 타입이 올바르지 않습니다')
        if row['fields']['cover_image'] is not None and type(
            row['fields']['cover_image']
        ) is not str:
            raise ReleaseError(f'{label} 공개 필드 타입이 올바르지 않습니다')
        if any(
            limit is not None
            and row['fields'][field] is not None
            and len(row['fields'][field]) > limit
            for field, limit in _SNAPSHOT_STRING_LIMITS.items()
        ):
            raise ReleaseError(f'{label} 공개 필드 길이가 올바르지 않습니다')
        if not row['fields']['title'] or not row['fields']['slug']:
            raise ReleaseError(f'{label} 필수 공개 필드가 비어 있습니다')
        if row['fields']['category'] not in dict(BlogPost.CATEGORY_CHOICES):
            raise ReleaseError(f'{label} category가 올바르지 않습니다')
        if type(row['fields']['is_published']) is not bool or type(
            row['fields']['is_noindex']
        ) is not bool:
            raise ReleaseError(f'{label} 공개 필드 타입이 올바르지 않습니다')
        if row['fields']['slug'] != row['slug']:
            raise ReleaseError(f'{label} post slug가 일치하지 않습니다')
        if parse_datetime(row['guard_updated_at']) is None:
            raise ReleaseError(f'{label} guard_updated_at이 올바르지 않습니다')
        published_at = row['fields']['published_at']
        if published_at is not None and (
            type(published_at) is not str or parse_datetime(published_at) is None
        ):
            raise ReleaseError(f'{label} published_at이 올바르지 않습니다')
        post_slugs.append(row['slug'])
    if len(post_slugs) != len(set(post_slugs)):
        raise ReleaseError(f'{label} post slug가 중복되었습니다')
    if set(post_slugs) != expected_slugs:
        raise ReleaseError(f'{label} 대상 slug 구성이 올바르지 않습니다')
    return post_slugs


def _validate_after_snapshot(after_path, digest):
    try:
        payload = json.loads(Path(after_path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError('after snapshot을 읽거나 해석할 수 없습니다') from exc
    expected_keys = {
        'kind', 'version', 'release_digest', 'item_count', 'created_slugs', 'posts',
        'snapshot_digest',
    }
    if type(payload) is not dict or set(payload) != expected_keys:
        raise ReleaseError('after snapshot schema가 올바르지 않습니다')
    unsigned = {key: value for key, value in payload.items() if key != 'snapshot_digest'}
    if payload['snapshot_digest'] != _snapshot_digest(unsigned):
        raise ReleaseError('after snapshot digest가 일치하지 않습니다')
    if type(payload['created_slugs']) is not list or any(
        not _is_nonempty_string(slug) for slug in payload['created_slugs']
    ):
        raise ReleaseError('after snapshot release 구성이 올바르지 않습니다')
    if len(payload['created_slugs']) != 7 or len(set(payload['created_slugs'])) != 7:
        raise ReleaseError('after snapshot release 구성이 올바르지 않습니다')
    if (
        payload['kind'] != 'after'
        or payload['version'] != RELEASE_VERSION
        or payload['release_digest'] != digest
        or payload['item_count'] != 20
        or set(payload['created_slugs']) != RELEASE_CREATED_SLUGS
    ):
        raise ReleaseError('after snapshot release 구성이 올바르지 않습니다')
    _validate_snapshot_rows(
        payload['posts'], expected_slugs=RELEASE_SLUGS, label='after snapshot',
    )


def _release_values(item):
    return {
        'title': item.title,
        'body': item.body,
        'excerpt': item.excerpt,
        'cover_asset_path': item.cover_asset_path,
        'category': item.category,
        'tags': ','.join(item.tags),
        'is_published': item.is_published,
        'seo_title': item.seo_title,
        'seo_description': item.seo_description,
    }


def apply_release(*, items, digest, backup_path):
    """Back up target public content, then atomically apply one release version."""
    if backup_path is None:
        raise ReleaseError('apply에는 backup 경로가 필요합니다')
    backup_path = Path(backup_path)
    after_path = backup_path.parent / f'{RELEASE_VERSION}-after.json'
    if backup_path.resolve() == after_path.resolve():
        raise ReleaseError('backup 경로는 예약된 after snapshot 경로와 달라야 합니다')
    marker = BlogContentRelease.objects.filter(version=RELEASE_VERSION).first()
    if marker is not None:
        if marker.digest == digest:
            staged_candidates = sorted(
                after_path.parent.glob(f'.{after_path.name}.tmp-*')
            )
            if not after_path.is_file() and staged_candidates:
                _recover_staged_after_snapshot(after_path, digest)
            if after_path.is_file():
                _validate_after_snapshot(after_path, digest)
            return {'created': 0, 'updated': 0}
        raise ReleaseError('같은 release version에 다른 digest가 이미 적용되었습니다')

    target_slugs = [item.slug for item in items]
    if len(target_slugs) != len(set(target_slugs)):
        raise ReleaseError('apply 대상 slug가 중복되었습니다')
    target_slug_set = set(target_slugs)
    if len(items) != 20 or target_slug_set != RELEASE_SLUGS:
        raise ReleaseError('apply 대상은 승인된 13/7 slug 20개와 정확히 일치해야 합니다')
    expected_existing_slugs = RELEASE_EXISTING_SLUGS
    existing = list(BlogPost.objects.filter(slug__in=target_slugs).order_by('slug'))
    existing_slugs = {post.slug for post in existing}
    preexisting_created = sorted(existing_slugs & RELEASE_CREATED_SLUGS)
    if preexisting_created:
        raise ReleaseError(
            f'릴리스 신규 slug가 이미 존재합니다: {", ".join(preexisting_created)}'
        )
    if existing_slugs != expected_existing_slugs:
        missing_count = len(expected_existing_slugs - existing_slugs)
        raise ReleaseError(
            f'apply 전 기존 대상 글 13개가 필요합니다: 누락 {missing_count}개'
        )
    created_slugs = sorted(RELEASE_CREATED_SLUGS)
    before_snapshot = _build_snapshot(
        kind='before',
        digest=digest,
        item_count=len(items),
        created_slugs=created_slugs,
        posts=existing,
    )
    _atomic_write_json(backup_path, before_snapshot)

    guard_times = {post.slug: post.updated_at.isoformat() for post in existing}
    User = get_user_model()
    admin = User.objects.filter(profile__is_admin=True).order_by('id').first()
    now = timezone.now()
    staged_after = None
    try:
        with transaction.atomic():
            locked = {
                post.slug: post
                for post in BlogPost.objects.select_for_update().filter(slug__in=target_slugs)
            }
            if set(locked) != expected_existing_slugs:
                raise ReleaseError('백업 뒤 13/7 대상 구성이 바뀌어 apply를 중단했습니다')
            if any(
                locked[slug].updated_at.isoformat() != guard
                for slug, guard in guard_times.items()
            ):
                raise ReleaseError('백업 뒤 대상 글이 편집되어 apply를 중단했습니다')

            updated = created = 0
            applied_posts = []
            for item in items:
                values = _release_values(item)
                post = locked.get(item.slug)
                if post is None:
                    post = BlogPost(
                        slug=item.slug,
                        author=admin,
                        published_at=now if item.is_published else None,
                        **values,
                    )
                    post.save()
                    created += 1
                else:
                    for field, value in values.items():
                        setattr(post, field, value)
                    post.save(update_fields=[*values, 'updated_at'])
                    updated += 1
                applied_posts.append(post)
            after_snapshot = _build_snapshot(
                kind='after',
                digest=digest,
                item_count=len(items),
                created_slugs=created_slugs,
                posts=applied_posts,
            )
            staged_after = _stage_json(after_path, after_snapshot)
            BlogContentRelease.objects.create(
                version=RELEASE_VERSION,
                digest=digest,
                item_count=len(items),
            )
    except Exception:
        if staged_after is not None:
            staged_after.unlink(missing_ok=True)
        raise

    _finalize_after_snapshot(staged_after, after_path)
    return {'created': created, 'updated': updated}


def _load_before_snapshot(snapshot_path):
    try:
        payload = json.loads(Path(snapshot_path).read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseError('restore snapshot을 읽거나 해석할 수 없습니다') from exc
    expected_keys = {
        'kind', 'version', 'release_digest', 'item_count', 'created_slugs', 'posts',
        'snapshot_digest',
    }
    if type(payload) is not dict or set(payload) != expected_keys:
        raise ReleaseError('restore snapshot schema가 올바르지 않습니다')
    unsigned = {key: value for key, value in payload.items() if key != 'snapshot_digest'}
    if (
        not _is_nonempty_string(payload['snapshot_digest'])
        or payload['snapshot_digest'] != _snapshot_digest(unsigned)
    ):
        raise ReleaseError('restore snapshot digest가 일치하지 않습니다')
    if payload['kind'] != 'before' or payload['version'] != RELEASE_VERSION:
        raise ReleaseError('restore snapshot version 또는 종류가 올바르지 않습니다')
    if not _is_nonempty_string(payload['release_digest']) or not _DIGEST_PATTERN.fullmatch(
        payload['release_digest']
    ):
        raise ReleaseError('restore release digest가 올바르지 않습니다')
    if type(payload['item_count']) is not int or payload['item_count'] < 0:
        raise ReleaseError('restore snapshot item_count가 올바르지 않습니다')
    if type(payload['created_slugs']) is not list or any(
        not _is_nonempty_string(slug) for slug in payload['created_slugs']
    ):
        raise ReleaseError('restore snapshot created_slugs가 올바르지 않습니다')
    if len(payload['created_slugs']) != len(set(payload['created_slugs'])):
        raise ReleaseError('restore snapshot created_slugs가 중복되었습니다')
    if type(payload['posts']) is not list:
        raise ReleaseError('restore snapshot posts가 올바르지 않습니다')
    if (
        payload['item_count'] != 20
        or len(payload['posts']) != 13
        or set(payload['created_slugs']) != RELEASE_CREATED_SLUGS
    ):
        raise ReleaseError('restore snapshot의 정확한 13/7 대상 구성이 올바르지 않습니다')

    post_slugs = _validate_snapshot_rows(
        payload['posts'],
        expected_slugs=RELEASE_EXISTING_SLUGS,
        label='restore snapshot',
    )
    if set(post_slugs) & set(payload['created_slugs']):
        raise ReleaseError('restore snapshot 대상 slug 구성이 겹칩니다')
    if len(post_slugs) + len(payload['created_slugs']) != payload['item_count']:
        raise ReleaseError('restore snapshot의 정확한 13/7 대상 수가 일치하지 않습니다')
    return payload


def _assign_snapshot_fields(post, fields):
    for field in PUBLIC_CONTENT_FIELDS:
        value = fields[field]
        if field == 'published_at' and value is not None:
            value = parse_datetime(value)
        setattr(post, field, value)


def restore_release(*, snapshot_path, confirm_version):
    """Restore a before snapshot unless any release target was edited later."""
    if confirm_version != RELEASE_VERSION:
        raise ReleaseError(f'confirm-version은 정확히 {RELEASE_VERSION}이어야 합니다')
    payload = _load_before_snapshot(snapshot_path)
    marker = BlogContentRelease.objects.filter(version=RELEASE_VERSION).first()
    if (
        marker is None
        or marker.reverted_at is not None
        or marker.digest != payload['release_digest']
        or marker.item_count != payload['item_count']
    ):
        raise ReleaseError('활성 release marker와 snapshot digest가 일치하지 않습니다')

    existing_rows = {row['slug']: row for row in payload['posts']}
    created_slugs = payload['created_slugs']
    target_slugs = [*existing_rows, *created_slugs]
    with transaction.atomic():
        marker = BlogContentRelease.objects.select_for_update().get(pk=marker.pk)
        if marker.reverted_at is not None or marker.digest != payload['release_digest']:
            raise ReleaseError('활성 release marker가 restore 전에 변경되었습니다')
        posts = {
            post.slug: post
            for post in BlogPost.objects.select_for_update().filter(slug__in=target_slugs)
        }
        missing = sorted(set(target_slugs) - set(posts))
        if missing:
            raise ReleaseError(f'restore 대상 글이 없습니다: {", ".join(missing)}')
        edited = sorted(
            slug for slug, post in posts.items()
            if post.updated_at > marker.applied_at
        )
        if edited:
            raise ReleaseError(f'릴리스 이후 편집된 글이 있어 restore를 중단합니다: {", ".join(edited)}')

        for slug, row in existing_rows.items():
            post = posts[slug]
            _assign_snapshot_fields(post, row['fields'])
            post.save(update_fields=[*PUBLIC_CONTENT_FIELDS, 'updated_at'])
        for slug in created_slugs:
            post = posts[slug]
            post.is_published = False
            post.save(update_fields=['is_published', 'updated_at'])
        marker.reverted_at = timezone.now()
        marker.save(update_fields=['reverted_at'])

    return {
        'restored': len(existing_rows),
        'unpublished': len(created_slugs),
        'restored_slugs': sorted(existing_rows),
        'created_slugs': sorted(created_slugs),
    }
