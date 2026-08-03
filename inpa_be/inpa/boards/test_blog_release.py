import hashlib
import io
import json
import tempfile
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inpa.accounts.models import Profile, User
from inpa.boards.blog_release import (
    BLOG_TEMPLATE_DISCLAIMER,
    PUBLIC_CONTENT_FIELDS,
    RELEASE_CREATED_SLUGS,
    RELEASE_EXISTING_SLUGS,
    RELEASE_VERSION,
    ReleaseError,
    apply_release,
    load_release,
    restore_release,
    validate_release,
)
from inpa.boards.models import (
    BlogContentRelease,
    BlogPost,
    blog_review_content_digest,
)


SAFETY_SLUGS = [
    '보험-갈아타기-비교',
    '비교안내서-한눈에-보는-비교표',
    '보험-갈아타기-설계사-순서',
]
PRIMARY_EXISTING_SLUG = sorted(RELEASE_EXISTING_SLUGS)[0]
SECONDARY_EXISTING_SLUG = sorted(RELEASE_EXISTING_SLUGS)[1]


class ReleasePackageMixin:
    def make_package(self):
        self.package_tmp = tempfile.TemporaryDirectory()
        root = Path(self.package_tmp.name)
        self.content_dir = root / 'docs' / 'blog-content'
        self.manifest_path = root / 'public' / 'blog-assets' / 'manifest.json'
        self.content_dir.mkdir(parents=True)
        self.manifest_path.parent.mkdir(parents=True)
        ordinary_slugs = sorted(RELEASE_EXISTING_SLUGS - set(SAFETY_SLUGS))
        slugs = ordinary_slugs + SAFETY_SLUGS + sorted(RELEASE_CREATED_SLUGS)
        self.metadata = []
        self.bodies = []
        self.manifest = []
        for index, slug in enumerate(slugs, start=1):
            is_safety = slug in SAFETY_SLUGS
            cover_path = f'/blog-assets/{slug}/cover.webp'
            self.metadata.append({
                'slug': slug,
                'category': 'safety' if is_safety else 'coverage',
                'excerpt': f'{index}번 글의 핵심 내용을 정리합니다.',
                'tags': [f'태그{index}', '설계사실무'],
                'seo_title': f'{index}번 검증 글 제목',
                'seo_description': f'{index}번 검증 글의 내용을 쉽게 확인합니다.',
                'cover_asset_path': cover_path,
                'is_published': not is_safety,
                'review_gate': 'legal' if is_safety else 'none',
                'legal_review': None,
                'sources': [{
                    'title': '보험업법',
                    'url': 'https://www.law.go.kr/법령/보험업법',
                    'checked_at': '2026-08-03',
                }],
            })
            self.bodies.append(f'## {index}번 질문\n\n본문 {index}입니다.')
            self.manifest.append({
                'path': cover_path,
                'role': 'cover',
                'source_type': 'generated-object',
                'license': 'generated-for-inpa',
                'created_at': '2026-08-03',
                'used_by': [slug],
                'pii_reviewed': True,
                'rights_reviewed': True,
                'width': 1600,
                'height': 900,
                'alt': '',
                'caption': f'{index}번 글의 장식용 대표 이미지',
            })
        self.flush_package()

    def flush_package(self):
        for old_path in self.content_dir.glob('*.md'):
            old_path.unlink()
        for index, (metadata, body) in enumerate(zip(self.metadata, self.bodies), start=1):
            title = f'{index}번 검증 글'
            source = (
                '<!-- blog-meta\n'
                f'{json.dumps(metadata, ensure_ascii=False, separators=(",", ":"))}\n'
                '-->\n'
                f'# {title}\n\n'
                '<!-- blog-body -->\n\n'
                f'{body}\n'
            )
            # Keep the fixture filename independent from metadata under test.
            # Linux filesystems cap each filename at 255 bytes, so an invalid
            # multibyte slug must reach the parser instead of failing in setup.
            (self.content_dir / f'{index:02d}-post.md').write_text(
                source, encoding='utf-8', newline='\n',
            )
        self.manifest_path.write_text(
            json.dumps(self.manifest, ensure_ascii=False), encoding='utf-8', newline='\n',
        )
        public_root = self.manifest_path.parent.parent
        for record in self.manifest:
            asset_path = public_root / record['path'].lstrip('/')
            asset_path.parent.mkdir(parents=True, exist_ok=True)
            if not asset_path.exists():
                asset_path.write_bytes(b'webp fixture')

    def load_and_validate(self):
        items, digest = load_release(self.content_dir, self.manifest_path)
        errors = validate_release(items, manifest_path=self.manifest_path)
        return items, digest, errors

    def existing_release_items(self, items):
        return [item for item in items if item.slug not in RELEASE_CREATED_SLUGS]

    def seed_existing_targets(self, items, *, author=None, count=13):
        published_at = timezone.now().replace(microsecond=0)
        posts = []
        for index, item in enumerate(self.existing_release_items(items)[:count]):
            posts.append(BlogPost.objects.create(
                author=author,
                title=f'기존 제목 {index}',
                slug=item.slug,
                body=f'기존 본문 {index}',
                excerpt=f'기존 요약 {index}',
                cover_image=f'blog/legacy-{index}.webp',
                cover_asset_path=f'/legacy/{index}.webp',
                category=BlogPost.CATEGORY_STORY,
                tags=f'기존{index},기록',
                is_published=True,
                published_at=published_at,
                seo_title=f'기존 검색 제목 {index}',
                seo_description=f'기존 검색 설명 {index}',
                is_noindex=True,
                view_count=100 + index,
            ))
        return posts


class BlogReleaseParserTests(ReleasePackageMixin, TestCase):
    def setUp(self):
        self.make_package()

    def tearDown(self):
        self.package_tmp.cleanup()

    def test_load_release_parses_exact_metadata_title_body_and_sorts_by_slug(self):
        items, digest, errors = self.load_and_validate()

        self.assertEqual(errors, [])
        self.assertEqual(len(items), 20)
        self.assertEqual([item.slug for item in items], sorted(item.slug for item in items))
        parsed = next(item for item in items if item.slug == PRIMARY_EXISTING_SLUG)
        self.assertEqual(parsed.title, '1번 검증 글')
        self.assertEqual(parsed.body, '## 1번 질문\n\n본문 1입니다.')
        self.assertEqual(parsed.tags, ['태그1', '설계사실무'])
        self.assertEqual(parsed.review_gate, 'none')
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_digest_normalizes_line_endings(self):
        _, lf_digest = load_release(self.content_dir, self.manifest_path)
        source_path = next(self.content_dir.glob('01-*.md'))
        source_path.write_bytes(source_path.read_bytes().replace(b'\n', b'\r\n'))

        _, crlf_digest = load_release(self.content_dir, self.manifest_path)

        self.assertEqual(crlf_digest, lf_digest)

    def test_parser_rejects_invalid_review_gate(self):
        self.metadata[0]['review_gate'] = 'optional'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'review_gate'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_non_string_review_gate_without_type_error(self):
        self.metadata[0]['review_gate'] = ['legal']
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'review_gate'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_category_outside_blog_model_choices(self):
        self.metadata[0]['category'] = 'arbitrary'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'category'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_incomplete_legal_review(self):
        self.metadata[0]['legal_review'] = {'reviewer': '검토자'}
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'legal_review'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_impossible_legal_review_date(self):
        self.metadata[0]['legal_review'] = {
            'reviewer': '실제 검토자',
            'credential': '대한민국 변호사',
            'reviewed_at': '2026-99-99T10:30:00+09:00',
            'reference': '내부 검토 기록',
        }
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'legal_review'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_legal_review_without_timezone(self):
        self.metadata[0]['legal_review'] = {
            'reviewer': '검토자',
            'credential': '대한민국 변호사',
            'reviewed_at': '2026-08-03T10:30:00',
            'reference': '검토 기록',
        }
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'legal_review'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_values_over_blog_model_field_limits(self):
        cases = [
            ('title', '가' * 201),
            ('slug', '가' * 201),
            ('excerpt', '가' * 301),
            ('cover_asset_path', '/' + 'a' * 300),
            ('seo_title', '가' * 61),
            ('seo_description', '가' * 161),
            ('tags', ['가' * 201]),
        ]
        for index, (field, value) in enumerate(cases):
            with self.subTest(field=field):
                if index:
                    self.package_tmp.cleanup()
                    self.make_package()
                if field == 'title':
                    self.flush_package()
                    source_path = sorted(self.content_dir.glob('*.md'))[0]
                    source = source_path.read_text(encoding='utf-8')
                    source_path.write_text(
                        source.replace('# 1번 검증 글', f'# {value}', 1),
                        encoding='utf-8',
                        newline='\n',
                    )
                else:
                    self.metadata[0][field] = value
                    self.flush_package()

                with self.assertRaisesRegex(ReleaseError, '길이'):
                    load_release(self.content_dir, self.manifest_path)

    def test_validator_requires_exactly_twenty_items(self):
        self.metadata.pop()
        self.bodies.pop()
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('20개' in error for error in errors))

    def test_validator_rejects_slug_outside_approved_twenty_post_catalog(self):
        self.metadata[0]['slug'] = '승인-목록-밖-글'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('승인된 20개 slug' in error for error in errors))

    def test_validator_rejects_duplicate_slug(self):
        self.metadata[1]['slug'] = self.metadata[0]['slug']
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('중복 slug' in error for error in errors))

    def test_validator_rejects_missing_and_duplicate_cover_paths(self):
        self.metadata[0]['cover_asset_path'] = ''
        self.metadata[1]['cover_asset_path'] = self.metadata[2]['cover_asset_path']
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('대표 이미지 경로가 없습니다' in error for error in errors))
        self.assertTrue(any('중복 대표 이미지' in error for error in errors))

    def test_validator_rejects_cover_missing_from_manifest(self):
        missing = self.metadata[0]['cover_asset_path']
        self.manifest = [record for record in self.manifest if record['path'] != missing]
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('manifest에 없습니다' in error and missing in error for error in errors))

    def test_validator_rejects_cover_missing_on_disk(self):
        missing = self.metadata[0]['cover_asset_path']
        self.flush_package()
        (self.manifest_path.parent.parent / missing.lstrip('/')).unlink()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('파일이 없습니다' in error and missing in error for error in errors))

    def test_validator_rejects_body_image_missing_from_manifest(self):
        missing = f'/blog-assets/{PRIMARY_EXISTING_SLUG}/missing-inline.webp'
        self.bodies[0] += f'\n\n![설명]({missing})'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('manifest에 없습니다' in error and missing in error for error in errors))

    def test_validator_rejects_body_image_missing_on_disk(self):
        inline = f'/blog-assets/{PRIMARY_EXISTING_SLUG}/inline.webp'
        self.bodies[0] += f'\n\n![설명]({inline})'
        self.manifest.append({**self.manifest[0], 'path': inline, 'role': 'inline'})
        self.flush_package()
        (self.manifest_path.parent.parent / inline.lstrip('/')).unlink()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('파일이 없습니다' in error and inline in error for error in errors))

    def test_validator_rejects_external_body_image(self):
        self.bodies[0] += '\n\n![외부](https://images.example.com/photo.webp)'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('외부 이미지' in error for error in errors))

    def test_validator_rejects_external_reference_style_body_image(self):
        self.bodies[0] += (
            '\n\n![외부 설명][external-cover]'
            '\n\n[external-cover]: https://images.example.com/private.webp?token=hidden'
        )
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('외부 이미지' in error for error in errors))
        self.assertFalse(any('hidden' in error for error in errors))

    def test_validator_rejects_external_shortcut_reference_body_image(self):
        self.bodies[0] += (
            '\n\n![외부 설명]'
            '\n\n[외부 설명]: https://images.example.com/private.webp?token=shortcut-hidden'
        )
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('외부 이미지' in error for error in errors))
        self.assertFalse(any('shortcut-hidden' in error for error in errors))

    def test_validator_rejects_incomplete_asset_reviews(self):
        self.manifest[0]['pii_reviewed'] = False
        self.manifest[1]['rights_reviewed'] = False
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('PII 검토' in error for error in errors))
        self.assertTrue(any('권리 검토' in error for error in errors))

    def test_validator_rejects_missing_source_and_checked_date(self):
        self.metadata[0]['sources'] = []
        self.metadata[1]['sources'][0]['checked_at'] = ''
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('공식 출처가 없습니다' in error for error in errors))
        self.assertTrue(any('확인일' in error for error in errors))

    def test_validator_blocks_copyguard_warning(self):
        self.bodies[0] += '\n\n검사 경고 — 문장'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('카피 검사' in error and 'em_dash' in error for error in errors))

    def test_validator_keeps_unreviewed_safety_posts_unpublished(self):
        safety_index = next(
            index for index, metadata in enumerate(self.metadata)
            if metadata['slug'] == SAFETY_SLUGS[0]
        )
        self.metadata[safety_index]['is_published'] = True
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any(
            '법률 검토 대상 배포 원고' in error and SAFETY_SLUGS[0] in error
            for error in errors
        ))

    def test_validator_rejects_repository_supplied_legal_review(self):
        safety_index = next(
            index for index, metadata in enumerate(self.metadata)
            if metadata['slug'] == SAFETY_SLUGS[0]
        )
        self.metadata[safety_index]['is_published'] = True
        self.metadata[safety_index]['legal_review'] = {
            'reviewer': '실제 검토자',
            'credential': '대한민국 변호사',
            'reviewed_at': '2026-08-03T10:30:00+09:00',
            'reference': '내부 검토 기록 2026-08-03',
        }
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any(
            '배포 원고에는 법률 검토 기록을 넣을 수 없습니다' in error
            for error in errors
        ))
        self.assertTrue(any('임시저장 상태' in error for error in errors))

    def test_validator_rejects_any_published_legal_gated_release_post(self):
        regular_index = next(
            index for index, metadata in enumerate(self.metadata)
            if metadata['slug'] not in SAFETY_SLUGS
        )
        self.metadata[regular_index]['review_gate'] = 'legal'
        self.metadata[regular_index]['is_published'] = True
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any(
            '법률 검토 대상 배포 원고는 임시저장 상태' in error
            and self.metadata[regular_index]['slug'] in error
            for error in errors
        ))

    def test_validator_rejects_published_body_template_disclaimer(self):
        self.bodies[0] += f'\n\n{BLOG_TEMPLATE_DISCLAIMER}'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('정직성 문구가 본문에 중복' in error for error in errors))

    def test_validator_requires_body_asset_used_by_slug(self):
        inline = '/blog-assets/shared/inline.webp'
        self.bodies[0] += f'\n\n![설명]({inline})'
        self.manifest.append({
            **self.manifest[0],
            'path': inline,
            'role': 'inline',
            'used_by': [SECONDARY_EXISTING_SLUG],
        })
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any(
            'used_by' in error and PRIMARY_EXISTING_SLUG in error for error in errors
        ))

    def test_validator_requires_used_by_to_be_a_list(self):
        inline = '/blog-assets/shared/string-used-by.webp'
        self.bodies[0] += f'\n\n![설명]({inline})'
        self.manifest.append({
            **self.manifest[0],
            'path': inline,
            'role': 'inline',
            'used_by': PRIMARY_EXISTING_SLUG,
        })
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('used_by 목록' in error for error in errors))


class BlogReleaseDatabaseTests(ReleasePackageMixin, TestCase):
    def setUp(self):
        self.make_package()
        self.items, self.digest, errors = self.load_and_validate()
        self.assertEqual(errors, [])
        self.admin = User.objects.create_user(
            email='release-admin@example.com', password='StrongPass123!', is_active=True,
        )
        Profile.objects.create(user=self.admin, is_admin=True)
        self.other_author = User.objects.create_user(
            email='existing-author@example.com', password='StrongPass123!', is_active=True,
        )
        self.backup_tmp = tempfile.TemporaryDirectory()
        self.backup_path = Path(self.backup_tmp.name) / 'before.json'

    def tearDown(self):
        self.package_tmp.cleanup()
        self.backup_tmp.cleanup()

    def create_existing_targets(self, count=13):
        return self.seed_existing_targets(
            self.items, author=self.other_author, count=count,
        )

    def test_apply_updates_by_slug_preserves_published_at_and_writes_marker(self):
        existing = self.create_existing_targets()
        original_published_at = existing[0].published_at

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result, {'created': 7, 'updated': 13})
        refreshed = BlogPost.objects.get(slug=self.items[0].slug)
        self.assertEqual(refreshed.title, self.items[0].title)
        self.assertEqual(refreshed.tags, ','.join(self.items[0].tags))
        self.assertEqual(refreshed.published_at, original_published_at)
        self.assertEqual(refreshed.author, self.other_author)
        created_slug = sorted(RELEASE_CREATED_SLUGS)[0]
        created = BlogPost.objects.get(slug=created_slug)
        self.assertEqual(created.author, self.admin)
        self.assertIsNotNone(created.published_at)
        marker = BlogContentRelease.objects.get(version=RELEASE_VERSION)
        self.assertEqual(marker.digest, self.digest)
        self.assertEqual(marker.item_count, 20)
        self.assertTrue(self.backup_path.exists())
        self.assertTrue((self.backup_path.parent / f'{RELEASE_VERSION}-after.json').exists())

    def test_same_release_version_is_noop_and_preserves_later_admin_edit(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        post = BlogPost.objects.get(slug=self.items[0].slug)
        post.title = '관리자가 나중에 고친 제목'
        post.save(update_fields=['title', 'updated_at'])

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result, {'created': 0, 'updated': 0})
        post.refresh_from_db()
        self.assertEqual(post.title, '관리자가 나중에 고친 제목')

    def test_same_release_retry_with_different_backup_directory_is_noop(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        canonical_after = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        canonical_bytes = canonical_after.read_bytes()
        post = BlogPost.objects.get(slug=PRIMARY_EXISTING_SLUG)
        post.title = '관리자 후속 편집 유지'
        post.save(update_fields=['title', 'updated_at'])
        alternate_dir = self.backup_path.parent / 'alternate'
        alternate_backup = alternate_dir / 'before.json'

        result = apply_release(
            items=self.items,
            digest=self.digest,
            backup_path=alternate_backup,
        )

        self.assertEqual(result, {'created': 0, 'updated': 0})
        post.refresh_from_db()
        self.assertEqual(post.title, '관리자 후속 편집 유지')
        self.assertEqual(canonical_after.read_bytes(), canonical_bytes)
        self.assertFalse(alternate_dir.exists())

    def test_same_version_with_different_digest_aborts(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        with self.assertRaisesRegex(ReleaseError, 'digest'):
            apply_release(items=self.items, digest='0' * 64, backup_path=self.backup_path)

    def test_apply_requires_backup_path(self):
        self.create_existing_targets()

        with self.assertRaisesRegex(ReleaseError, 'backup'):
            apply_release(items=self.items, digest=self.digest, backup_path=None)

        self.assertFalse(BlogContentRelease.objects.exists())
        self.assertEqual(BlogPost.objects.count(), 13)

    def test_apply_rejects_reserved_after_snapshot_as_backup_path(self):
        self.create_existing_targets()
        collision_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=collision_path)

        self.assertFalse(collision_path.exists())
        self.assertFalse(BlogContentRelease.objects.exists())
        self.assertEqual(BlogPost.objects.count(), 13)

    def test_apply_requires_exact_thirteen_existing_and_seven_new_slugs(self):
        self.create_existing_targets(count=12)

        with self.assertRaisesRegex(ReleaseError, '13개'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(self.backup_path.exists())
        self.assertFalse(BlogContentRelease.objects.exists())
        self.assertEqual(BlogPost.objects.count(), 12)

    def test_apply_rejects_preexisting_release_created_slug(self):
        self.create_existing_targets()
        BlogPost.objects.create(
            title='미리 생긴 신규 글', slug=sorted(RELEASE_CREATED_SLUGS)[0], body='본문',
        )

        with self.assertRaisesRegex(ReleaseError, '신규 slug'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(self.backup_path.exists())
        self.assertFalse(BlogContentRelease.objects.exists())

    def test_after_snapshot_finalize_failure_is_recovered_by_idempotent_retry(self):
        self.create_existing_targets()
        after_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        real_replace = __import__('os').replace

        def fail_after_only(source, destination):
            if Path(destination) == after_path:
                raise OSError('after finalize failed')
            return real_replace(source, destination)

        with mock.patch('inpa.boards.blog_release.os.replace', side_effect=fail_after_only):
            with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
                apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertTrue(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())
        self.assertFalse(after_path.exists())
        post = BlogPost.objects.get(slug=self.existing_release_items(self.items)[0].slug)
        post.title = '관리자 후속 편집'
        post.save(update_fields=['title', 'updated_at'])

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result, {'created': 0, 'updated': 0})
        self.assertTrue(after_path.exists())
        post.refresh_from_db()
        self.assertEqual(post.title, '관리자 후속 편집')

    def test_idempotent_retry_rejects_tampered_after_snapshot(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        after_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        after_snapshot = json.loads(after_path.read_text(encoding='utf-8'))
        after_snapshot['posts'][0]['fields']['title'] = '변조된 after 제목'
        after_path.write_text(
            json.dumps(after_snapshot, ensure_ascii=False), encoding='utf-8',
        )

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

    def test_idempotent_retry_rejects_rechecksummed_invalid_after_schema(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        after_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        after_snapshot = json.loads(after_path.read_text(encoding='utf-8'))
        after_snapshot['posts'][0]['fields']['title'] = ['잘못된', '타입']
        unsigned = {
            key: value for key, value in after_snapshot.items()
            if key != 'snapshot_digest'
        }
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        after_snapshot['snapshot_digest'] = hashlib.sha256(canonical).hexdigest()
        after_path.write_text(
            json.dumps(after_snapshot, ensure_ascii=False), encoding='utf-8',
        )

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

    def test_idempotent_retry_rejects_duplicate_after_created_slugs(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        after_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        after_snapshot = json.loads(after_path.read_text(encoding='utf-8'))
        after_snapshot['created_slugs'].append(after_snapshot['created_slugs'][0])
        unsigned = {
            key: value for key, value in after_snapshot.items()
            if key != 'snapshot_digest'
        }
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        after_snapshot['snapshot_digest'] = hashlib.sha256(canonical).hexdigest()
        after_path.write_text(
            json.dumps(after_snapshot, ensure_ascii=False), encoding='utf-8',
        )

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

    def test_retry_validates_staged_after_snapshot_before_promoting_it(self):
        self.create_existing_targets()
        after_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'
        real_replace = __import__('os').replace

        def fail_after_only(source, destination):
            if Path(destination) == after_path:
                raise OSError('after finalize failed')
            return real_replace(source, destination)

        with mock.patch('inpa.boards.blog_release.os.replace', side_effect=fail_after_only):
            with self.assertRaises(ReleaseError):
                apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        staged_path = next(after_path.parent.glob(f'.{after_path.name}.tmp-*'))
        staged = json.loads(staged_path.read_text(encoding='utf-8'))
        staged['posts'][0]['fields']['category'] = 'invalid-category'
        unsigned = {key: value for key, value in staged.items() if key != 'snapshot_digest'}
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        staged['snapshot_digest'] = hashlib.sha256(canonical).hexdigest()
        staged_path.write_text(json.dumps(staged, ensure_ascii=False), encoding='utf-8')

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(after_path.exists())
        self.assertTrue(staged_path.exists())

    def test_failure_rolls_back_posts_and_release_marker_but_keeps_backup(self):
        existing = self.create_existing_targets()
        original_title = existing[0].title
        with mock.patch.object(
            BlogContentRelease.objects,
            'create',
            side_effect=RuntimeError('marker write failed'),
        ):
            with self.assertRaisesRegex(RuntimeError, 'marker write failed'):
                apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(BlogPost.objects.count(), 13)
        self.assertFalse(BlogContentRelease.objects.exists())
        self.assertEqual(
            BlogPost.objects.get(slug=self.items[0].slug).title,
            original_title,
        )
        self.assertTrue(self.backup_path.exists())

    def test_backup_contains_public_content_only_and_no_author_email(self):
        self.create_existing_targets()

        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        snapshot = json.loads(self.backup_path.read_text(encoding='utf-8'))
        self.assertEqual(set(snapshot['posts'][0]['fields']), set(PUBLIC_CONTENT_FIELDS))
        self.assertIn('body', snapshot['posts'][0]['fields'])
        serialized = json.dumps(snapshot, ensure_ascii=False)
        self.assertNotIn('author', serialized)
        self.assertNotIn('release-admin@example.com', serialized)
        self.assertNotIn('existing-author@example.com', serialized)

    def test_restore_rejects_tampered_snapshot_before_db_write(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        snapshot = json.loads(self.backup_path.read_text(encoding='utf-8'))
        snapshot['posts'][0]['fields']['title'] = '변조된 제목'
        self.backup_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')

        with self.assertRaisesRegex(ReleaseError, 'snapshot digest'):
            restore_release(snapshot_path=self.backup_path, confirm_version=RELEASE_VERSION)

        self.assertIsNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_rejects_invalid_public_field_types_before_db_write(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        snapshot = json.loads(self.backup_path.read_text(encoding='utf-8'))
        snapshot['posts'][0]['fields']['title'] = ['잘못된', '타입']
        unsigned = {key: value for key, value in snapshot.items() if key != 'snapshot_digest'}
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        snapshot['snapshot_digest'] = hashlib.sha256(canonical).hexdigest()
        self.backup_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')

        with self.assertRaisesRegex(ReleaseError, '공개 필드 타입'):
            restore_release(snapshot_path=self.backup_path, confirm_version=RELEASE_VERSION)

        self.assertIsNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_rejects_wrong_thirteen_seven_snapshot_composition(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        snapshot = json.loads(self.backup_path.read_text(encoding='utf-8'))
        snapshot['created_slugs'].pop()
        unsigned = {key: value for key, value in snapshot.items() if key != 'snapshot_digest'}
        canonical = json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')
        snapshot['snapshot_digest'] = hashlib.sha256(canonical).hexdigest()
        self.backup_path.write_text(json.dumps(snapshot, ensure_ascii=False), encoding='utf-8')

        with self.assertRaisesRegex(ReleaseError, '13/7'):
            restore_release(snapshot_path=self.backup_path, confirm_version=RELEASE_VERSION)

        self.assertIsNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_requires_exact_confirmation(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        with self.assertRaisesRegex(ReleaseError, 'confirm'):
            restore_release(snapshot_path=self.backup_path, confirm_version='wrong-version')

        self.assertIsNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_rejects_posts_edited_after_release(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        post = BlogPost.objects.get(slug=self.items[0].slug)
        post.body = '관리자가 릴리스 뒤에 수정한 본문'
        post.save(update_fields=['body', 'updated_at'])

        with self.assertRaisesRegex(ReleaseError, '릴리스 이후 편집'):
            restore_release(snapshot_path=self.backup_path, confirm_version=RELEASE_VERSION)

        post.refresh_from_db()
        self.assertEqual(post.body, '관리자가 릴리스 뒤에 수정한 본문')
        self.assertIsNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_recovers_existing_posts_and_unpublishes_new_posts(self):
        existing = self.create_existing_targets()
        expected_fields = {
            field: getattr(existing[0], field).name
            if field == 'cover_image' else getattr(existing[0], field)
            for field in PUBLIC_CONTENT_FIELDS
        }
        original_author = existing[0].author
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        result = restore_release(
            snapshot_path=self.backup_path,
            confirm_version=RELEASE_VERSION,
        )

        self.assertEqual(result['restored'], 13)
        self.assertEqual(result['unpublished'], 7)
        restored = BlogPost.objects.get(slug=self.items[0].slug)
        for field, expected in expected_fields.items():
            actual = restored.cover_image.name if field == 'cover_image' else getattr(restored, field)
            self.assertEqual(actual, expected, field)
        self.assertEqual(restored.author, original_author)
        for slug in result['created_slugs']:
            self.assertFalse(BlogPost.objects.get(slug=slug).is_published)
        self.assertIsNotNone(BlogContentRelease.objects.get(version=RELEASE_VERSION).reverted_at)

    def test_restore_recovers_review_timestamp_and_content_binding(self):
        existing = self.create_existing_targets()
        original = existing[0]
        original.review_gate = BlogPost.REVIEW_GATE_LEGAL
        original.legal_review = {
            'reviewer': '김검토',
            'credential': '대한민국 변호사',
            'reviewed_at': '2026-08-03T09:00:00+09:00',
            'reference': '내부 검토 기록',
        }
        original.legal_review_reviewer = '김검토'
        original.legal_review_credential = '대한민국 변호사'
        original.legal_reviewed_at = parse_datetime('2026-08-03T09:00:00+09:00')
        original.legal_review_reference = '내부 검토 기록'
        original.legal_review_content_digest = blog_review_content_digest(original)
        original.save()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        restore_release(
            snapshot_path=self.backup_path,
            confirm_version=RELEASE_VERSION,
        )

        restored = BlogPost.objects.get(pk=original.pk)
        self.assertEqual(restored.legal_reviewed_at.isoformat(), '2026-08-03T00:00:00+00:00')
        self.assertTrue(restored.has_current_legal_review())

    def test_reapply_after_restore_requires_a_new_release_version(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        restore_release(snapshot_path=self.backup_path, confirm_version=RELEASE_VERSION)

        with self.assertRaisesRegex(ReleaseError, '새 release version'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

    def test_apply_persists_review_gate_state(self):
        self.create_existing_targets()

        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        safety = BlogPost.objects.get(slug=SAFETY_SLUGS[0])
        self.assertEqual(safety.review_gate, BlogPost.REVIEW_GATE_LEGAL)
        self.assertTrue(safety.legal_review_required)
        self.assertIsNone(safety.legal_review)
        self.assertFalse(safety.is_published)
        marker = BlogContentRelease.objects.get(version=RELEASE_VERSION)
        self.assertEqual(marker.before_snapshot['kind'], 'before')
        self.assertEqual(marker.after_snapshot['kind'], 'after')
        self.assertEqual(marker.before_snapshot['snapshot_digest'], json.loads(
            self.backup_path.read_text(encoding='utf-8')
        )['snapshot_digest'])


class RefreshBlogContentCommandTests(ReleasePackageMixin, TestCase):
    def setUp(self):
        self.make_package()
        self.output_tmp = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.package_tmp.cleanup()
        self.output_tmp.cleanup()

    def test_dry_run_uses_explicit_package_without_mutation_or_raw_content(self):
        stdout = io.StringIO()

        call_command(
            'refresh_blog_content',
            content_dir=str(self.content_dir),
            manifest_path=str(self.manifest_path),
            stdout=stdout,
        )

        output = stdout.getvalue()
        self.assertIn('dry-run', output)
        self.assertIn('items=20', output)
        self.assertIn(PRIMARY_EXISTING_SLUG, output)
        self.assertNotIn('본문 1입니다', output)
        self.assertNotIn('@example.com', output)
        self.assertFalse(BlogPost.objects.exists())
        self.assertFalse(BlogContentRelease.objects.exists())

    def test_apply_without_backup_exits_before_mutation(self):
        with self.assertRaisesRegex(CommandError, 'backup-out'):
            call_command(
                'refresh_blog_content',
                apply=True,
                content_dir=str(self.content_dir),
                manifest_path=str(self.manifest_path),
            )

        self.assertFalse(BlogPost.objects.exists())
        self.assertFalse(BlogContentRelease.objects.exists())

    def test_apply_command_outputs_counts_and_slugs_only(self):
        stdout = io.StringIO()
        backup_path = Path(self.output_tmp.name) / 'before.json'
        items, _ = load_release(self.content_dir, self.manifest_path)
        self.seed_existing_targets(items)

        call_command(
            'refresh_blog_content',
            apply=True,
            backup_out=str(backup_path),
            content_dir=str(self.content_dir),
            manifest_path=str(self.manifest_path),
            stdout=stdout,
        )

        output = stdout.getvalue()
        self.assertIn('created=7', output)
        self.assertIn('updated=13', output)
        self.assertIn(PRIMARY_EXISTING_SLUG, output)
        self.assertNotIn('본문 1입니다', output)
        self.assertNotIn('@example.com', output)
        self.assertTrue(backup_path.exists())

    def test_restore_command_outputs_only_counts_and_slugs(self):
        backup_path = Path(self.output_tmp.name) / 'before.json'
        items, _ = load_release(self.content_dir, self.manifest_path)
        self.seed_existing_targets(items)
        call_command(
            'refresh_blog_content',
            apply=True,
            backup_out=str(backup_path),
            content_dir=str(self.content_dir),
            manifest_path=str(self.manifest_path),
            stdout=io.StringIO(),
        )
        stdout = io.StringIO()

        call_command(
            'refresh_blog_content',
            restore_from=str(backup_path),
            confirm_version=RELEASE_VERSION,
            stdout=stdout,
        )

        output = stdout.getvalue()
        self.assertIn('restored=13', output)
        self.assertIn('unpublished=7', output)
        self.assertIn(PRIMARY_EXISTING_SLUG, output)
        self.assertNotIn('기존 본문', output)
        self.assertNotIn('@example.com', output)

    def test_restore_command_can_use_durable_marker_snapshot(self):
        backup_path = Path(self.output_tmp.name) / 'before.json'
        items, _ = load_release(self.content_dir, self.manifest_path)
        self.seed_existing_targets(items)
        call_command(
            'refresh_blog_content',
            apply=True,
            backup_out=str(backup_path),
            content_dir=str(self.content_dir),
            manifest_path=str(self.manifest_path),
            stdout=io.StringIO(),
        )
        backup_path.unlink()
        stdout = io.StringIO()

        call_command(
            'refresh_blog_content',
            restore_from_marker=True,
            confirm_version=RELEASE_VERSION,
            stdout=stdout,
        )

        self.assertIn('restored=13', stdout.getvalue())
        self.assertIn('unpublished=7', stdout.getvalue())

    def test_apply_and_restore_options_are_mutually_exclusive(self):
        with self.assertRaisesRegex(CommandError, '동시에'):
            call_command(
                'refresh_blog_content',
                apply=True,
                backup_out=str(Path(self.output_tmp.name) / 'before.json'),
                restore_from=str(Path(self.output_tmp.name) / 'before.json'),
                confirm_version=RELEASE_VERSION,
                content_dir=str(self.content_dir),
                manifest_path=str(self.manifest_path),
            )

    def test_validation_error_does_not_echo_external_url_query(self):
        self.bodies[0] += (
            '\n\n![외부](https://images.example.com/photo.webp?token=private-value)'
        )
        self.flush_package()

        with self.assertRaises(CommandError) as raised:
            call_command(
                'refresh_blog_content',
                content_dir=str(self.content_dir),
                manifest_path=str(self.manifest_path),
            )

        self.assertNotIn('private-value', str(raised.exception))

    def test_non_string_review_gate_becomes_command_error(self):
        self.metadata[0]['review_gate'] = {'mode': 'legal'}
        self.flush_package()

        with self.assertRaisesRegex(CommandError, 'review_gate'):
            call_command(
                'refresh_blog_content',
                content_dir=str(self.content_dir),
                manifest_path=str(self.manifest_path),
            )
