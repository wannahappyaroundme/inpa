import hashlib
import io
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from inpa.accounts.models import Profile, User
from inpa.boards import blog_release
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
EXPECTED_PUBLICATION_PLAN = {
    '신입-보험설계사-지인-영업-다음-할-일': '2026-07-01T09:20:00+09:00',
    '상담-예약률-높이는-문자와-화법': '2026-07-03T14:40:00+09:00',
    '보험-증권-보는-법-3분-체크리스트': '2026-07-06T09:40:00+09:00',
    '갱신형-비갱신형-차이': '2026-07-06T15:20:00+09:00',
    '3대-진단비란-암-뇌-심장': '2026-07-08T10:10:00+09:00',
    '회사마다-보험-담보-이름-다른-이유': '2026-07-10T14:30:00+09:00',
    '보험-갈아타기-비교': '2026-07-13T09:30:00+09:00',
    '비교안내서-한눈에-보는-비교표': '2026-07-13T15:40:00+09:00',
    '상담-준비에-쫓기던-새내기-하루-각색': '2026-07-15T10:20:00+09:00',
    '보험-갈아타기-설계사-순서': '2026-07-16T14:50:00+09:00',
    '보험-가입-전-확인사항': '2026-07-20T09:40:00+09:00',
    '좋은-보험이란': '2026-07-22T10:30:00+09:00',
    '실손의료비보험-기본-쉽게-짚어보기': '2026-07-22T15:10:00+09:00',
    '보험-증권-요청-문자-안내': '2026-07-24T14:20:00+09:00',
    '보험-상담-준비-체크리스트': '2026-07-27T09:50:00+09:00',
    '보험-상담-후-기록-다음-연락': '2026-07-29T10:40:00+09:00',
    '상담-예약-전날-당일-안내': '2026-07-29T15:30:00+09:00',
    '보험설계사-고객관리표-필수-항목': '2026-07-31T14:10:00+09:00',
    '보험나이-계산법-6개월-예시': '2026-08-04T10:20:00+09:00',
    '보험-직업급수-확인-순서': '2026-08-07T15:20:00+09:00',
    '보험설계사-주간-계획표-고객-단계별-다음-행동': '2026-08-10T10:20:00+09:00',
    '보험설계사-소개-카드-고객-확인사항': '2026-08-12T14:40:00+09:00',
    '보험설계사-월말-복기-영업-숫자': '2026-08-14T09:30:00+09:00',
    '보험설계사-고객-연간-일정-관리법': '2026-08-18T15:10:00+09:00',
    '보험설계사-팀장-일대일-질문': '2026-08-20T10:40:00+09:00',
    '보험설계사-고객관리-프로그램-선택-기준': '2026-08-25T10:20:00+09:00',
    '보험설계사-보장분석-프로그램-확인-항목': '2026-09-08T09:30:00+09:00',
    '보험설계사-고객-자료-파일-정리': '2026-09-22T10:40:00+09:00',
    '보험설계사-휴면-고객-다시-연락': '2026-10-06T09:50:00+09:00',
    '보험설계사-상담-예약-링크': '2026-10-20T10:10:00+09:00',
    '보장분석-결과-고객-공유': '2026-11-03T09:40:00+09:00',
}
BASE_RELEASE_VERSION = '2026-08-blog-expansion-v2'
BASE_RELEASE_CREATED_SLUGS = {
    '보험설계사-주간-계획표-고객-단계별-다음-행동',
    '보험설계사-소개-카드-고객-확인사항',
    '보험설계사-월말-복기-영업-숫자',
    '보험설계사-고객-연간-일정-관리법',
    '보험설계사-팀장-일대일-질문',
}
NEW_PUBLICATION_PLAN = {
    slug: published_at
    for slug, published_at in EXPECTED_PUBLICATION_PLAN.items()
    if slug not in BASE_RELEASE_CREATED_SLUGS
    and published_at >= '2026-08-25T00:00:00+09:00'
}
UPDATED_EXISTING_SLUGS = {
    '신입-보험설계사-지인-영업-다음-할-일',
    '보험-증권-보는-법-3분-체크리스트',
    '보험-증권-요청-문자-안내',
    '보험-상담-준비-체크리스트',
    '보험-상담-후-기록-다음-연락',
    '보험설계사-고객관리표-필수-항목',
}
PRIMARY_EXISTING_SLUG = sorted(RELEASE_EXISTING_SLUGS)[0]
SECONDARY_EXISTING_SLUG = sorted(RELEASE_EXISTING_SLUGS)[1]
FIRST_RELEASE_SLUG = next(iter(EXPECTED_PUBLICATION_PLAN))


class ReleasePackageMixin:
    def make_package(self):
        self.package_tmp = tempfile.TemporaryDirectory()
        root = Path(self.package_tmp.name)
        self.content_dir = root / 'docs' / 'blog-content'
        self.manifest_path = root / 'public' / 'blog-assets' / 'manifest.json'
        self.content_dir.mkdir(parents=True)
        self.manifest_path.parent.mkdir(parents=True)
        slugs = list(EXPECTED_PUBLICATION_PLAN)
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
                'publication_plan_at': EXPECTED_PUBLICATION_PLAN[slug],
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

    def serialize_public_fields(self, post):
        values = {}
        for field in PUBLIC_CONTENT_FIELDS:
            value = getattr(post, field)
            if field == 'cover_image':
                value = value.name
            elif field in {'published_at', 'legal_reviewed_at'}:
                value = value.isoformat() if value is not None else None
            values[field] = value
        return values

    def create_base_release_marker(self, posts):
        digest = 'b' * 64
        unsigned = {
            'kind': 'after',
            'version': BASE_RELEASE_VERSION,
            'release_digest': digest,
            'item_count': 25,
            'created_slugs': sorted(BASE_RELEASE_CREATED_SLUGS),
            'posts': [{
                'slug': post.slug,
                'guard_updated_at': post.updated_at.isoformat(),
                'fields': self.serialize_public_fields(post),
            } for post in sorted(posts, key=lambda row: row.slug)],
        }
        snapshot = {
            **unsigned,
            'snapshot_digest': hashlib.sha256(json.dumps(
                unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
            ).encode('utf-8')).hexdigest(),
        }
        return BlogContentRelease.objects.create(
            version=BASE_RELEASE_VERSION,
            digest=digest,
            item_count=25,
            after_snapshot=snapshot,
        )

    def seed_existing_targets(
        self, items, *, author=None, count=25, create_base_marker=True,
    ):
        published_at = timezone.now().replace(microsecond=0)
        posts = []
        for index, item in enumerate(self.existing_release_items(items)[:count]):
            is_safety = item.slug in SAFETY_SLUGS
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
                is_published=not is_safety,
                review_gate=(
                    BlogPost.REVIEW_GATE_LEGAL if is_safety
                    else BlogPost.REVIEW_GATE_NONE
                ),
                legal_review_required=is_safety,
                published_at=None if is_safety else published_at,
                seo_title=f'기존 검색 제목 {index}',
                seo_description=f'기존 검색 설명 {index}',
                is_noindex=True,
                view_count=100 + index,
            ))
        if create_base_marker and count == 25:
            self.create_base_release_marker(posts)
        return posts


class BlogReleaseParserTests(ReleasePackageMixin, TestCase):
    def setUp(self):
        self.make_package()

    def tearDown(self):
        self.package_tmp.cleanup()

    def test_load_release_parses_exact_metadata_title_body_and_sorts_by_slug(self):
        items, digest, errors = self.load_and_validate()

        self.assertEqual(errors, [])
        self.assertEqual(len(items), 31)
        self.assertEqual([item.slug for item in items], sorted(item.slug for item in items))
        parsed = next(item for item in items if item.slug == PRIMARY_EXISTING_SLUG)
        expected_index = list(EXPECTED_PUBLICATION_PLAN).index(PRIMARY_EXISTING_SLUG) + 1
        self.assertEqual(parsed.title, f'{expected_index}번 검증 글')
        self.assertEqual(
            parsed.body,
            f'## {expected_index}번 질문\n\n본문 {expected_index}입니다.',
        )
        self.assertEqual(parsed.tags, [f'태그{expected_index}', '설계사실무'])
        self.assertEqual(parsed.review_gate, 'none')
        self.assertEqual(
            parsed.publication_plan_at.isoformat(),
            EXPECTED_PUBLICATION_PLAN[PRIMARY_EXISTING_SLUG],
        )
        self.assertRegex(digest, r'^[0-9a-f]{64}$')

    def test_release_contract_names_exact_v3_sets(self):
        self.assertEqual(blog_release.RELEASE_VERSION, '2026-08-internal-organic-v3')
        self.assertEqual(
            getattr(blog_release, 'BASE_RELEASE_VERSION', None),
            BASE_RELEASE_VERSION,
        )
        self.assertEqual(set(blog_release.RELEASE_CREATED_SLUGS), set(NEW_PUBLICATION_PLAN))
        self.assertEqual(
            set(getattr(blog_release, 'RELEASE_UPDATED_SLUGS', ())),
            UPDATED_EXISTING_SLUGS,
        )
        self.assertEqual(len(blog_release.RELEASE_EXISTING_SLUGS), 25)
        self.assertTrue(callable(getattr(blog_release, '_merge_approved_fields', None)))

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

    def test_parser_rejects_reserved_static_page_slug(self):
        self.metadata[0]['slug'] = 'resources'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, '예약'):
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

    def test_parser_rejects_publication_plan_without_timezone(self):
        self.metadata[0]['publication_plan_at'] = '2026-07-01T09:20:00'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'publication_plan_at'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_publication_plan_without_seconds(self):
        self.metadata[0]['publication_plan_at'] = '2026-07-01T09:20+09:00'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'publication_plan_at'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_publication_plan_with_microseconds(self):
        self.metadata[0]['publication_plan_at'] = '2026-07-01T09:20:00.123456+09:00'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'publication_plan_at'):
            load_release(self.content_dir, self.manifest_path)

    def test_parser_rejects_publication_plan_outside_kst(self):
        self.metadata[0]['publication_plan_at'] = '2026-07-01T00:20:00+00:00'
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, 'publication_plan_at'):
            load_release(self.content_dir, self.manifest_path)

    def test_validator_requires_exactly_thirty_one_items(self):
        self.metadata.pop()
        self.bodies.pop()
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('31개' in error for error in errors))

    def test_validator_rejects_slug_outside_approved_thirty_one_post_catalog(self):
        self.metadata[0]['slug'] = '승인-목록-밖-글'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('승인된 31개 slug' in error for error in errors))

    def test_validator_rejects_changed_publication_plan(self):
        self.metadata[0]['publication_plan_at'] = '2026-07-02T09:20:00+09:00'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('발행 일정' in error for error in errors))

    def test_validator_rejects_new_post_weekend_and_official_holiday_dates(self):
        new_index = next(
            index for index, metadata in enumerate(self.metadata)
            if metadata['slug'] in NEW_PUBLICATION_PLAN
        )
        for index, invalid_at in enumerate((
            '2026-08-29T09:20:00+09:00',
            '2026-09-24T09:20:00+09:00',
            '2026-10-05T09:20:00+09:00',
        )):
            with self.subTest(publication_plan_at=invalid_at):
                if index:
                    self.package_tmp.cleanup()
                    self.make_package()
                self.metadata[new_index]['publication_plan_at'] = invalid_at
                self.flush_package()

                _, _, errors = self.load_and_validate()

                self.assertTrue(any('주말과 휴일' in error for error in errors))

    def test_validator_requires_every_new_post_on_tuesday(self):
        new_index = next(
            index for index, metadata in enumerate(self.metadata)
            if metadata['slug'] in NEW_PUBLICATION_PLAN
        )
        self.metadata[new_index]['publication_plan_at'] = '2026-08-26T10:20:00+09:00'
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('화요일' in error for error in errors))

    def test_validator_rejects_duplicate_publication_timestamp(self):
        self.metadata[1]['publication_plan_at'] = self.metadata[0]['publication_plan_at']
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('발행 시각이 중복' in error for error in errors))

    def test_parser_rejects_file_number_order_different_from_schedule(self):
        self.metadata[0], self.metadata[1] = self.metadata[1], self.metadata[0]
        self.flush_package()

        with self.assertRaisesRegex(ReleaseError, '파일 번호 순서'):
            load_release(self.content_dir, self.manifest_path)

    def test_validator_requires_regular_posts_to_be_published(self):
        self.metadata[0]['is_published'] = False
        self.flush_package()

        _, _, errors = self.load_and_validate()

        self.assertTrue(any('게시 상태' in error for error in errors))

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
            'used_by' in error and FIRST_RELEASE_SLUG in error for error in errors
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

    def create_existing_targets(self, count=25, create_base_marker=True):
        return self.seed_existing_targets(
            self.items,
            author=self.other_author,
            count=count,
            create_base_marker=create_base_marker,
        )

    def test_apply_updates_six_approved_rows_creates_six_and_writes_marker(self):
        existing = self.create_existing_targets()
        updated = next(post for post in existing if post.slug in UPDATED_EXISTING_SLUGS)
        untouched = next(
            post for post in existing
            if post.slug not in UPDATED_EXISTING_SLUGS and post.slug not in SAFETY_SLUGS
        )
        untouched_fields = self.serialize_public_fields(untouched)
        original_published_at = updated.published_at
        desired = next(item for item in self.items if item.slug == updated.slug)

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result, {'created': 6, 'updated': 6, 'preserved_edits': {}})
        updated.refresh_from_db()
        self.assertEqual(updated.title, desired.title)
        self.assertEqual(updated.body, desired.body)
        self.assertEqual(updated.excerpt, desired.excerpt)
        self.assertEqual(updated.tags, ','.join(desired.tags))
        self.assertEqual(updated.seo_title, desired.seo_title)
        self.assertEqual(updated.seo_description, desired.seo_description)
        self.assertEqual(updated.published_at, original_published_at)
        untouched.refresh_from_db()
        self.assertEqual(self.serialize_public_fields(untouched), untouched_fields)
        created_slug = sorted(RELEASE_CREATED_SLUGS)[0]
        created = BlogPost.objects.get(slug=created_slug)
        self.assertEqual(created.author, self.admin)
        self.assertEqual(
            created.published_at,
            datetime.fromisoformat(EXPECTED_PUBLICATION_PLAN[created_slug]),
        )
        marker = BlogContentRelease.objects.get(version=RELEASE_VERSION)
        self.assertEqual(marker.digest, self.digest)
        self.assertEqual(marker.item_count, 31)
        self.assertEqual(len(marker.before_snapshot['posts']), 25)
        self.assertEqual(len(marker.after_snapshot['posts']), 31)
        self.assertEqual(set(marker.after_snapshot['created_slugs']), set(NEW_PUBLICATION_PLAN))
        self.assertTrue(self.backup_path.exists())
        self.assertTrue((self.backup_path.parent / f'{RELEASE_VERSION}-after.json').exists())

    def test_apply_preserves_only_admin_edited_fields_and_all_nonapproved_state(self):
        existing = self.create_existing_targets(create_base_marker=False)
        body_post = next(post for post in existing if post.slug in UPDATED_EXISTING_SLUGS)
        title_post = next(
            post for post in existing
            if post.slug in UPDATED_EXISTING_SLUGS and post.slug != body_post.slug
        )
        body_post.cover_image = 'blog/admin-kept.webp'
        body_post.cover_asset_path = '/admin/kept-cover.webp'
        body_post.is_published = False
        body_post.review_gate = BlogPost.REVIEW_GATE_LEGAL
        body_post.legal_review_required = True
        body_post.is_noindex = True
        body_post.save()
        marker = self.create_base_release_marker(existing)
        body_post.body = '운영자가 직접 고친 본문'
        body_post.save(update_fields=['body', 'updated_at'])
        title_post.title = '운영자가 직접 고친 제목'
        title_post.save(update_fields=['title', 'updated_at'])
        self.assertGreater(body_post.updated_at, marker.applied_at)
        protected = {
            'author_id': body_post.author_id,
            'view_count': body_post.view_count,
            'published_at': body_post.published_at,
            'cover_image': body_post.cover_image.name,
            'cover_asset_path': body_post.cover_asset_path,
            'is_published': body_post.is_published,
            'review_gate': body_post.review_gate,
            'legal_review_required': body_post.legal_review_required,
            'is_noindex': body_post.is_noindex,
        }
        desired = next(item for item in self.items if item.slug == body_post.slug)

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result['created'], 6)
        self.assertEqual(result['updated'], 6)
        self.assertEqual(result['preserved_edits'][body_post.slug], ['body'])
        self.assertEqual(result['preserved_edits'][title_post.slug], ['title'])
        body_post.refresh_from_db()
        self.assertEqual(body_post.body, '운영자가 직접 고친 본문')
        self.assertEqual(body_post.title, desired.title)
        self.assertEqual(body_post.excerpt, desired.excerpt)
        self.assertEqual(body_post.tags, ','.join(desired.tags))
        self.assertEqual(body_post.seo_title, desired.seo_title)
        self.assertEqual(body_post.seo_description, desired.seo_description)
        for field, expected in protected.items():
            actual = body_post.cover_image.name if field == 'cover_image' else getattr(
                body_post, field,
            )
            self.assertEqual(actual, expected, field)
        title_post.refresh_from_db()
        self.assertEqual(title_post.title, '운영자가 직접 고친 제목')

    def test_same_release_version_is_noop_and_preserves_later_admin_edit(self):
        self.create_existing_targets()
        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)
        post = BlogPost.objects.get(slug=self.items[0].slug)
        post.title = '관리자가 나중에 고친 제목'
        post.save(update_fields=['title', 'updated_at'])

        result = apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertEqual(result, {'created': 0, 'updated': 0, 'preserved_edits': {}})
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

        self.assertEqual(result, {'created': 0, 'updated': 0, 'preserved_edits': {}})
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

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())
        self.assertEqual(BlogPost.objects.count(), 25)

    def test_apply_rejects_reserved_after_snapshot_as_backup_path(self):
        self.create_existing_targets()
        collision_path = self.backup_path.parent / f'{RELEASE_VERSION}-after.json'

        with self.assertRaisesRegex(ReleaseError, 'after snapshot'):
            apply_release(items=self.items, digest=self.digest, backup_path=collision_path)

        self.assertFalse(collision_path.exists())
        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())
        self.assertEqual(BlogPost.objects.count(), 25)

    def test_apply_requires_exact_twenty_five_existing_and_six_new_slugs(self):
        self.create_existing_targets(count=24)

        with self.assertRaisesRegex(ReleaseError, '25개'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(self.backup_path.exists())
        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())
        self.assertEqual(BlogPost.objects.count(), 24)

    def test_apply_requires_active_v2_base_release(self):
        self.create_existing_targets(create_base_marker=False)

        with self.assertRaisesRegex(ReleaseError, '기준 release'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

    def test_apply_rejects_invalid_v2_marker_digest(self):
        self.create_existing_targets()
        marker = BlogContentRelease.objects.get(version=BASE_RELEASE_VERSION)
        marker.digest = 'invalid'
        marker.save(update_fields=['digest'])

        with self.assertRaisesRegex(ReleaseError, '기준 release digest'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

    def test_apply_rejects_reverted_v2_base_release(self):
        self.create_existing_targets()
        marker = BlogContentRelease.objects.get(version=BASE_RELEASE_VERSION)
        marker.reverted_at = timezone.now()
        marker.save(update_fields=['reverted_at'])

        with self.assertRaisesRegex(ReleaseError, '활성 기준 release'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

    def test_apply_rejects_tampered_v2_after_snapshot(self):
        self.create_existing_targets()
        marker = BlogContentRelease.objects.get(version=BASE_RELEASE_VERSION)
        marker.after_snapshot['posts'][0]['fields']['title'] = '변조된 기준 제목'
        marker.save(update_fields=['after_snapshot'])

        with self.assertRaisesRegex(ReleaseError, '기준 after snapshot digest'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

    def test_apply_rejects_v2_snapshot_without_exact_twenty_five_rows(self):
        self.create_existing_targets()
        marker = BlogContentRelease.objects.get(version=BASE_RELEASE_VERSION)
        snapshot = marker.after_snapshot
        snapshot['posts'].pop()
        unsigned = {key: value for key, value in snapshot.items() if key != 'snapshot_digest'}
        snapshot['snapshot_digest'] = hashlib.sha256(json.dumps(
            unsigned, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
        ).encode('utf-8')).hexdigest()
        marker.after_snapshot = snapshot
        marker.save(update_fields=['after_snapshot'])

        with self.assertRaisesRegex(ReleaseError, '기준 after snapshot.*25개'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

    def test_apply_rejects_preexisting_release_created_slug(self):
        self.create_existing_targets()
        BlogPost.objects.create(
            title='미리 생긴 신규 글', slug=sorted(RELEASE_CREATED_SLUGS)[0], body='본문',
        )

        with self.assertRaisesRegex(ReleaseError, '신규 slug'):
            apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        self.assertFalse(self.backup_path.exists())
        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())

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

        self.assertEqual(result, {'created': 0, 'updated': 0, 'preserved_edits': {}})
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

        self.assertEqual(BlogPost.objects.count(), 25)
        self.assertFalse(BlogContentRelease.objects.filter(version=RELEASE_VERSION).exists())
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

    def test_restore_rejects_wrong_thirty_one_snapshot_composition(self):
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

        with self.assertRaisesRegex(ReleaseError, '25/6'):
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

        self.assertEqual(result['restored'], 25)
        self.assertEqual(result['unpublished'], 6)
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

    def test_apply_preserves_safety_review_state_and_date(self):
        existing = self.create_existing_targets()
        safety_before = next(post for post in existing if post.slug == SAFETY_SLUGS[0])
        safety_before.excerpt = '법률 검토를 기다리는 관리자 메모'
        safety_before.save(update_fields=['excerpt', 'updated_at'])
        original_updated_at = safety_before.updated_at

        apply_release(items=self.items, digest=self.digest, backup_path=self.backup_path)

        safety = BlogPost.objects.get(slug=SAFETY_SLUGS[0])
        self.assertEqual(safety.review_gate, BlogPost.REVIEW_GATE_LEGAL)
        self.assertTrue(safety.legal_review_required)
        self.assertIsNone(safety.legal_review)
        self.assertFalse(safety.is_published)
        self.assertIsNone(safety.published_at)
        self.assertEqual(safety.excerpt, '법률 검토를 기다리는 관리자 메모')
        self.assertEqual(safety.updated_at, original_updated_at)
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
        self.assertIn(
            'dry-run version=2026-08-internal-organic-v3 targets=31 '
            'existing=25 new=6 update_targets=6',
            output,
        )
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
        self.assertIn('created=6', output)
        self.assertIn('updated=6', output)
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
        self.assertIn('restored=25', output)
        self.assertIn('unpublished=6', output)
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

        self.assertIn('restored=25', stdout.getvalue())
        self.assertIn('unpublished=6', stdout.getvalue())

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
