# 블로그 확장과 design-refactor 통합 배포 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 검증된 블로그 31편 릴리스와 `feat/design-refactor` 작업 폴더의 아직 유효한 게시판 운영 변경을 최신 `master` 위에 커밋 단위로 정리하고, 프리뷰 승인 뒤 운영 배포까지 완료한다.

**Architecture:** `codex/blog-design-release`를 유일한 통합 브랜치로 사용한다. 이미 최신 `master`에 있는 랜딩·요금제·첫 로그인 안내는 재적용하지 않고 회귀 검증만 하며, 게시판 안내는 Django 설정에 따라 실행 시점에 고정 목록을 조합해 닫힌 기능이 공개되지 않게 한다. 배포는 GitHub PR 병합으로 Vercel·Render 자동 배포를 시작하고, 블로그 v3 데이터는 기존 snapshot 기반 명령으로 적용·복구한다.

**Tech Stack:** Django 5.2, Python 3.11, Next.js 16, React 19, TypeScript, Vitest, Node test runner, SQLite local test DB, PostgreSQL production, GitHub Actions, Vercel, Render.

## Global Constraints

- 작업 브랜치와 worktree는 `codex/blog-design-release`와 `/Users/kyungsbook/Desktop/inpa/.worktrees/blog-design-release`만 사용한다.
- `/Users/kyungsbook/Desktop/inpa`의 `feat/design-refactor` 작업 폴더는 읽기만 하고 수정·stage·commit·stash하지 않는다.
- 전략 HTML, DOCX, XLSX, 과거 계획·설계 문서, `sales-marketing-execution-html.test.tsx`, `outputs/`는 이번 배포에서 제외한다.
- 기존 블로그 12개 커밋은 재작성·squash하지 않는다.
- 새 커밋은 지정 파일만 명시적으로 stage하며 `git add -A`와 `git add -u`를 사용하지 않는다.
- `INSURANCE_REVIEW_GATE_ENABLED=False`에서는 스캔 PDF, 검토 표시, 원문 대조·확정, 동시 업로드, 고객 동의 안내를 시드하지 않는다.
- 기존 Manager 공지·FAQ와 모든 관리자 편집은 보존한다.
- `cleanup_demo_boards`는 자동 배포 명령에 넣지 않고 기본 dry-run을 유지한다.
- 사용자 화면 문구는 쉬운 말, 긍정 표현, 사실 확인 가능 문구만 사용하고 em dash(U+2014)를 넣지 않는다.
- 운영 병합 전 GitHub Actions와 Vercel 프리뷰를 확인하고 PM에게 운영 병합 확인을 받는다.
- 운영 성공 전에는 `README.md`와 `AGENTS.md`에 배포 완료라고 기록하지 않는다.

---

### Task 1: 기능 상태에 맞춘 게시판 안내

**Files:**
- Modify: `inpa_be/inpa/boards/management/commands/seed_boards.py`
- Modify: `inpa_be/inpa/boards/tests.py`

**Interfaces:**
- Consumes: `settings.INSURANCE_REVIEW_GATE_ENABLED: bool`, `Notice`, `Faq`, 기존 `seed_boards`의 exact-match 갱신·`get_or_create` 규칙.
- Produces: `REVIEW_NOTICES`, `REVIEW_FAQS`, 개인정보 FAQ exact-match 갱신, 게이트별 멱등 시드 동작.

- [ ] **Step 1: 현재 관리자 편집 보존 테스트를 기준선으로 실행**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.SeedBoardsNeutralCopyTests
```

Expected: 기존 Manager 공지·FAQ, 비교 FAQ, 관리자 편집 보존 테스트가 모두 PASS.

- [ ] **Step 2: 기능 게이트가 닫힐 때 공개 전 안내가 생기지 않는 실패 테스트 작성**

`django.test` import를 `from django.test import TestCase, override_settings`로 바꾸고 `SeedBoardsNeutralCopyTests`의 기존 상수 아래에 다음 class attributes를 추가한다.

```python
    REVIEW_NOTICE = '이용 가이드: 증권 자동 정리 결과 확인하기'
    REVIEW_QUESTIONS = (
        '스캔 PDF나 휴대폰 사진으로 만든 증권도 정리할 수 있나요?',
        '자동 정리한 값이 확실하지 않을 때는 어떻게 하나요?',
        '여러 설계사가 동시에 증권을 올리면 자료가 섞이지 않나요?',
        '고객 동의는 언제 받나요?',
    )

    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=False)
    def test_review_guidance_stays_hidden_while_gate_is_closed(self):
        call_command('seed_boards')
        self.assertFalse(Notice.objects.filter(title=self.REVIEW_NOTICE).exists())
        self.assertFalse(Faq.objects.filter(question__in=self.REVIEW_QUESTIONS).exists())
```

- [ ] **Step 3: 기능 게이트가 열릴 때만 안내가 한 번 생성되는 실패 테스트 작성**

```python
    @override_settings(INSURANCE_REVIEW_GATE_ENABLED=True)
    def test_seeds_review_guidance_once_when_gate_is_open(self):
        call_command('seed_boards')
        call_command('seed_boards')

        self.assertEqual(Notice.objects.filter(title=self.REVIEW_NOTICE).count(), 1)
        for question in self.REVIEW_QUESTIONS:
            self.assertEqual(Faq.objects.filter(question=question).count(), 1)

        self.assertIn(
            '직접 고친 뒤 확정',
            Faq.objects.get(
                question='자동 정리한 값이 확실하지 않을 때는 어떻게 하나요?',
            ).answer,
        )
```

- [ ] **Step 4: 개인정보 FAQ exact-match 갱신과 관리자 편집 보존 실패 테스트 작성**

```python
    LEGACY_PRIVACY_ANSWER = (
        '네. 고객 정보는 설계사님 계정에만 보이도록 분리되어 있어요. 다른 설계사는 볼 수 '
        '없습니다. 고객에게 보내는 공유 화면도 필요한 정보만 담기고, 민감한 내용은 빠집니다.'
    )

    def test_upgrades_only_untouched_privacy_faq(self):
        Faq.objects.create(
            author=self.admin,
            category='개인정보·보안',
            order=6,
            question='제가 등록한 고객 정보는 안전한가요?',
            answer=self.LEGACY_PRIVACY_ANSWER,
            is_published=True,
        )
        call_command('seed_boards')
        faq = Faq.objects.get(question='제가 등록한 고객 정보는 안전한가요?')
        self.assertIn('계정별로 조회 범위', faq.answer)
        self.assertIn('식별 정보를 먼저 가립니다', faq.answer)

    def test_preserves_admin_edited_privacy_faq(self):
        edited = '관리자가 현재 운영 방식에 맞게 수정한 개인정보 안내입니다.'
        Faq.objects.create(
            author=self.admin,
            category='개인정보·보안',
            order=6,
            question='제가 등록한 고객 정보는 안전한가요?',
            answer=edited,
            is_published=True,
        )
        call_command('seed_boards')
        self.assertTrue(Faq.objects.filter(
            question='제가 등록한 고객 정보는 안전한가요?', answer=edited,
        ).exists())
```

- [ ] **Step 5: 새 테스트가 production 변경 전 RED인지 확인**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.SeedBoardsNeutralCopyTests
```

Expected: 게이트 open과 개인정보 FAQ 갱신 테스트는 FAIL, 게이트 closed와 기존 테스트는 PASS.

- [ ] **Step 6: 고정 안내 목록과 게이트 조합 구현**

`seed_boards.py`에 `from django.conf import settings`를 추가하고 기존 목록을 직접 변경하지 않는 별도 상수를 만든다.

```python
LEGACY_PRIVACY_FAQ_ANSWER = (
    '네. 고객 정보는 설계사님 계정에만 보이도록 분리되어 있어요. 다른 설계사는 볼 수 '
    '없습니다. 고객에게 보내는 공유 화면도 필요한 정보만 담기고, 민감한 내용은 빠집니다.'
)
PRIVACY_FAQ_ANSWER = (
    '등록한 고객, 증권, 분석 자료는 설계사님 계정별로 조회 범위가 나뉩니다. '
    '자동 정리를 위해 외부 분석 단계를 사용할 때는 이름·전화번호·주민등록번호 같은 '
    '식별 정보를 먼저 가립니다. 고객에게 보내는 공유 화면에는 선택한 자료만 담깁니다.'
)

REVIEW_NOTICES = [
    {
        'title': '이용 가이드: 증권 자동 정리 결과 확인하기',
        'is_pinned': False,
        'body': (
            '증권을 올리면 원문과 자동 정리 결과를 나란히 확인할 수 있어요.\n\n'
            '글자가 흐리거나 표가 복잡해 확신이 낮은 값은 확인 표시로 알려드립니다. '
            '보험료, 가입금액, 기간을 원문과 대조한 뒤 바로 수정하고 확정해 주세요.\n\n'
            '확정 전 초안은 고객 자료와 분석 합계에 반영되지 않습니다.'
        ),
    },
]

REVIEW_FAQS = [
    {
        'category': '기능문의', 'order': 8,
        'question': '스캔 PDF나 휴대폰 사진으로 만든 증권도 정리할 수 있나요?',
        'answer': (
            '네. 사진을 PDF로 저장해 올리면 자동으로 글자와 표를 정리합니다. '
            '문서를 평평하게 펴고 그림자와 반사를 줄여 촬영하면 더 또렷하게 읽을 수 있어요. '
            '작은 글자는 원본 크기를 유지하고, 여러 페이지는 순서대로 한 파일에 담아 주세요.'
        ),
    },
    {
        'category': '기능문의', 'order': 9,
        'question': '자동 정리한 값이 확실하지 않을 때는 어떻게 하나요?',
        'answer': (
            '확신이 낮은 값은 확인 표시와 함께 보여드립니다. 원문 페이지를 바로 열어 보험료, '
            '가입금액, 기간을 대조하고 직접 고친 뒤 확정할 수 있어요. 확정 전 초안은 고객 자료와 '
            '분석 합계에 반영되지 않습니다.'
        ),
    },
    {
        'category': '개인정보·보안', 'order': 10,
        'question': '여러 설계사가 동시에 증권을 올리면 자료가 섞이지 않나요?',
        'answer': (
            '각 업로드는 설계사 계정, 고객, 작업 번호를 함께 묶어 처리합니다. 목록 조회와 결과 '
            '확정도 같은 계정 소유 범위 안에서만 이어져 다른 설계사의 고객이나 증권과 섞이지 '
            '않도록 분리되어 있습니다.'
        ),
    },
    {
        'category': '기능문의', 'order': 11,
        'question': '고객 동의는 언제 받나요?',
        'answer': (
            '증권을 자동 정리하기 전에 고객 전용 동의 링크를 먼저 보내 주세요. 고객이 최신 '
            '동의문을 확인하면 해당 고객의 증권 업로드를 바로 이어갈 수 있습니다.'
        ),
    },
]
```

기존 `FAQS`의 개인정보 질문은 새 설치에서도 같은 답변을 쓰도록 `answer: PRIVACY_FAQ_ANSWER`로 바꾼다. 기존 Manager FAQ의 `order=7`과 문구는 유지한다.

`handle` 내부에서 exact-match 갱신 후 실행별 목록을 만든다.

```python
Faq.objects.filter(
    question='제가 등록한 고객 정보는 안전한가요?',
    answer=LEGACY_PRIVACY_FAQ_ANSWER,
).update(answer=PRIVACY_FAQ_ANSWER)

notices = list(NOTICES)
faqs = list(FAQS)
if settings.INSURANCE_REVIEW_GATE_ENABLED:
    notices.extend(REVIEW_NOTICES)
    faqs.extend(REVIEW_FAQS)

for notice in notices:
    _, created = Notice.objects.get_or_create(
        title=notice['title'],
        defaults={
            'author': author,
            'body': notice['body'],
            'is_pinned': notice.get('is_pinned', False),
            'is_published': True,
            'published_at': now,
        },
    )
    created_n += int(created)
for faq in faqs:
    _, created = Faq.objects.get_or_create(
        question=faq['question'],
        defaults={
            'author': author,
            'category': faq['category'],
            'answer': faq['answer'],
            'order': faq['order'],
            'is_published': True,
        },
    )
    created_f += int(created)
```

- [ ] **Step 7: 게이트별 테스트와 기존 보존 테스트 실행**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.SeedBoardsNeutralCopyTests
```

Expected: PASS, 동일 질문·공지 중복 0, 관리자 편집 보존.

- [ ] **Step 8: 카피와 Django 점검 실행**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py check
cd ../inpa_fe
npm run lint:copy
```

Expected: Django issue 0, copy findings 0.

- [ ] **Step 9: 게시판 안내 커밋**

```bash
git add inpa_be/inpa/boards/management/commands/seed_boards.py \
  inpa_be/inpa/boards/tests.py
git commit -m "feat(게시판): 기능 상태에 맞춘 안내 보강"
```

---

### Task 2: 수동 데모 공지 정리 명령

**Files:**
- Create: `inpa_be/inpa/boards/management/commands/cleanup_demo_boards.py`
- Modify: `inpa_be/inpa/boards/tests.py`

**Interfaces:**
- Consumes: `Notice.title`, `Faq.question`, Django `BaseCommand`, `transaction.atomic`.
- Produces: `python manage.py cleanup_demo_boards [--apply]`; 기본 dry-run, 명시적 apply에서만 `[DEMO]` 공지·FAQ 삭제.

- [ ] **Step 1: 삭제 범위를 고정하는 실패 테스트 작성**

`tests.py` 상단에 `from io import StringIO`를 추가한다. `CleanupDemoBoardsTests`를 새 클래스로 추가하며 기존 `SeedBoardsNeutralCopyTests`의 테스트를 이동·삭제하지 않는다.

```python
class CleanupDemoBoardsTests(TestCase):
    def setUp(self):
        self.admin, _ = _make_planner('cleanup-admin@test.com', is_admin=True)
        self.demo_notice = Notice.objects.create(
            author=self.admin,
            title='[DEMO] 샘플 공지',
            body='정리 대상입니다.',
            is_published=True,
        )
        self.demo_faq = Faq.objects.create(
            author=self.admin,
            category='기능문의',
            order=99,
            question='[DEMO] 샘플 FAQ',
            answer='정리 대상입니다.',
            is_published=True,
        )
        self.demo_post = Post.objects.create(
            author=self.admin,
            title='[DEMO] 유지할 게시글',
            body='공지와 FAQ 외 데이터는 유지합니다.',
        )
        self.real_notice = Notice.objects.create(
            author=self.admin,
            title='실제 공지',
            body='운영 공지는 유지합니다.',
            is_published=True,
        )

    def test_dry_run_keeps_every_row(self):
        out = StringIO()
        call_command('cleanup_demo_boards', stdout=out)
        self.assertTrue(Notice.objects.filter(pk=self.demo_notice.pk).exists())
        self.assertTrue(Faq.objects.filter(pk=self.demo_faq.pk).exists())
        self.assertIn('공지 1건, FAQ 1건', out.getvalue())

    def test_apply_deletes_only_demo_notices_and_faqs(self):
        call_command('cleanup_demo_boards', apply=True)
        self.assertFalse(Notice.objects.filter(pk=self.demo_notice.pk).exists())
        self.assertFalse(Faq.objects.filter(pk=self.demo_faq.pk).exists())
        self.assertTrue(Post.objects.filter(pk=self.demo_post.pk).exists())
        self.assertTrue(Notice.objects.filter(pk=self.real_notice.pk).exists())
```

- [ ] **Step 2: 명령이 없는 상태에서 RED 확인**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.CleanupDemoBoardsTests
```

Expected: `Unknown command: 'cleanup_demo_boards'`로 FAIL.

- [ ] **Step 3: 최소 명령 구현**

```python
"""공지와 FAQ에 남은 [DEMO] 행만 좁게 정리한다."""

from django.core.management.base import BaseCommand
from django.db import transaction

from inpa.boards.models import Faq, Notice


class Command(BaseCommand):
    help = '제목이 [DEMO]로 시작하는 공지와 FAQ만 정리합니다(기본 dry-run).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='확인된 [DEMO] 공지와 FAQ를 실제로 삭제합니다.',
        )

    def handle(self, *args, **options):
        notice_rows = Notice.objects.filter(title__startswith='[DEMO]')
        faq_rows = Faq.objects.filter(question__startswith='[DEMO]')
        notice_count = notice_rows.count()
        faq_count = faq_rows.count()

        if not options['apply']:
            self.stdout.write(
                f'[dry-run] 정리 대상: 공지 {notice_count}건, FAQ {faq_count}건. '
                '--apply를 붙이면 이 두 종류만 삭제합니다.'
            )
            return

        with transaction.atomic():
            notice_rows.select_for_update().delete()
            faq_rows.select_for_update().delete()

        self.stdout.write(self.style.SUCCESS(
            f'[완료] [DEMO] 공지 {notice_count}건, FAQ {faq_count}건을 정리했습니다.'
        ))
```

- [ ] **Step 4: 명령 테스트와 전체 boards 테스트 실행**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.CleanupDemoBoardsTests \
  inpa.boards.tests.SeedBoardsNeutralCopyTests \
  inpa.boards.test_blog_release
```

Expected: PASS. 로컬 기본 DB에는 명령을 실행하지 않는다.

- [ ] **Step 5: Render 시작 명령 비포함 확인**

Run:

```bash
rg -n "cleanup_demo_boards" render.yaml .github inpa_be/config
```

Expected: 자동 실행 경로 0건.

- [ ] **Step 6: 정리 명령 커밋**

```bash
git add inpa_be/inpa/boards/management/commands/cleanup_demo_boards.py \
  inpa_be/inpa/boards/tests.py
git commit -m "chore(게시판): 데모 공지 정리 명령 추가"
```

---

### Task 3: 개발 실패 기록과 사용자 작업 보존 증거

**Files:**
- Modify: `.Codex/failures.md`
- Read only: `/Users/kyungsbook/Desktop/inpa/**`

**Interfaces:**
- Consumes: 기존 실패 로그 형식과 원래 작업 폴더의 상태.
- Produces: Rosetta/esbuild 재발 방지 기록, 원래 작업 폴더가 변경되지 않았다는 상태 증거.

- [ ] **Step 1: 원래 작업 폴더 상태를 읽기 전용으로 기록**

Run:

```bash
git -C /Users/kyungsbook/Desktop/inpa status --porcelain=v2 --branch
git -C /Users/kyungsbook/Desktop/inpa rev-parse HEAD
```

Expected: `feat/design-refactor`, HEAD `4ebee25`, 기존 수정·미추적 파일이 그대로 표시됨.

- [ ] **Step 2: 실패 로그에 확정 원인·해결·예방 추가**

```markdown
### 2026-07-21 Rosetta 실행에서 esbuild CPU 패키지 불일치
Symptom: arm64 Node로 설치한 `@esbuild/darwin-arm64`가 정상인데도 권한을 높여 `tsx`를 두 번 실행하면 x64 패키지가 필요하다는 오류로 테스트가 시작 전에 멈췄다.
Cause: 권한을 높인 셸이 Rosetta x64 실행 경로를 사용해, 일반 셸의 arm64 Node와 같은 `node_modules`를 서로 다른 CPU로 읽었다.
Fix: 일반 arm64 Node에서 `node --import tsx --test` 실행 경로로 단위 테스트를 실행해 `tsx` CLI의 임시 IPC 권한 요구를 없앴다. 제품 코드나 잠금 파일은 변경하지 않았다.
Prevention: 이 Mac에서 프런트 테스트는 번들 Node를 직접 호출한다. 로컬 CPU 문제를 고치기 위해 `package.json`이나 `package-lock.json`에 다른 플랫폼 전용 패키지를 추가하지 않는다.
```

- [ ] **Step 3: 문서 diff 검증과 커밋**

Run:

```bash
git diff --check -- .Codex/failures.md
```

Then:

```bash
git add .Codex/failures.md
git commit -m "docs(개발): Rosetta 테스트 실패 기록"
```

- [ ] **Step 4: 원래 작업 폴더가 그대로인지 재확인**

Run:

```bash
git -C /Users/kyungsbook/Desktop/inpa status --porcelain=v2 --branch
git -C /Users/kyungsbook/Desktop/inpa rev-parse HEAD
```

Expected: Step 1과 같은 branch/HEAD와 같은 사용자 변경 목록.

---

### Task 4: 통합 검증과 독립 리뷰

**Files:**
- Modify only if a confirmed defect exists: Task 1–3 owned files
- Read only: blog content/assets, landing components, release scripts, DB

**Interfaces:**
- Consumes: Tasks 1–3 commits, existing blog v3 release, current landing implementation.
- Produces: zero-important-finding release candidate and exact verification evidence.

- [ ] **Step 1: 원격 변화와 브랜치 범위 확인**

Run:

```bash
git fetch origin
git status --short --branch
git log --oneline origin/master..HEAD
git diff --stat origin/master...HEAD
```

Expected: 승인된 블로그 12개 커밋, 설계·계획, 게시판 2개 커밋, 실패 기록만 존재.

- [ ] **Step 2: 백엔드 집중 검사**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py check
/tmp/inpa-blog-expansion-venv/bin/python manage.py test \
  inpa.boards.tests.SeedBoardsNeutralCopyTests \
  inpa.boards.tests.CleanupDemoBoardsTests \
  inpa.boards.test_blog_release \
  inpa.boards.tests.BlogPublicReadTests
```

Expected: issue 0, 모든 테스트 PASS.

- [ ] **Step 3: 프론트 콘텐츠·전체 검사**

Run:

```bash
cd inpa_fe
npm ci
npm run test:blog-lint
npm run lint:blog
npm run test:copy-lint
npm run lint:copy
npm run test:run
npm run build
```

Expected: blog tests 41+, 31 posts/31 covers/79 assets, copy findings 0, Vitest 709+, Next 85 pages.

- [ ] **Step 4: 전체 백엔드 검사**

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py test inpa
```

Expected: 전체 suite exit 0. 의도된 4xx/5xx 로그와 unittest failure를 구분한다.

- [ ] **Step 5: 블로그 dry-run의 DB 무변경 확인**

실행 전후 로컬 `db.sqlite3`의 SHA-256, 크기, mtime과 release marker·BlogPost count를 비교한다.

Run:

```bash
cd inpa_be
/tmp/inpa-blog-expansion-venv/bin/python manage.py refresh_blog_content
```

Expected output fields: `targets=31 existing=25 new=6 update_targets=6 published=28 drafts=3`; DB 지문과 marker 상태는 전후 동일.

- [ ] **Step 6: 랜딩과 블로그 시각 QA**

로컬 Django와 Next를 실행하고 in-app Browser로 다음을 desktop 1440×900, mobile 390×844에서 확인한다.

- `/`: header가 블로그·로그인·무료 시작만 노출, 요금제 Free/Plus/Super 정확히 3개, Manager 별도 카드 0, 가로 넘침 0.
- `/blog`: 카드 이미지 로딩, 밝은 테마, CTA, 가로 넘침 0.
- 변경 글 12편: H1, 본문 이미지, 표, 관련 글 3개, CTA 1개, 오류 화면 0.

Expected: console error 0, broken image 0, dark theme 0.

- [ ] **Step 7: 독립 전체 브랜치 리뷰**

리뷰자는 `origin/master...HEAD` 전체를 correctness, privacy/security, UX/copy, data/rollback, scope의 다섯 관점으로 검토한다. Critical 또는 Important가 있으면 해당 task로 돌아가 실패 테스트부터 수정한다.

Expected: Critical 0, Important 0.

- [ ] **Step 8: 최종 diff와 작업 트리 확인**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: 추적·미추적 변경 0.

---

### Task 5: GitHub PR과 프리뷰

**Files:**
- No source changes expected
- Create externally: draft PR to `master`

**Interfaces:**
- Consumes: Task 4 release candidate.
- Produces: GitHub Actions 결과, Vercel preview URL, PM 운영 병합 판단 자료.

- [ ] **Step 1: push 직전 원격 최신화**

```bash
git fetch origin
git rev-list --left-right --count origin/master...HEAD
git diff --name-status origin/master...HEAD
```

새 master 변경이 있으면 강제 push하지 않고 보존 병합 후 Task 4 영향 검사를 재실행한다.

- [ ] **Step 2: 릴리스 브랜치 push**

```bash
git push -u origin codex/blog-design-release
```

- [ ] **Step 3: 초안 PR 생성**

PR 본문에 다음을 실제 값으로 기록한다.

- 블로그 31편·31 covers·79 assets
- 신규 6편 일정과 기존 6편 개선
- 게시판 기능 게이트·관리자 편집 보존
- `cleanup_demo_boards`가 자동 실행되지 않음
- 전체 backend/frontend/build 결과
- 블로그 DB와 코드 롤백 명령
- 원래 `feat/design-refactor` 작업 폴더 제외 범위

- [ ] **Step 4: GitHub Actions와 Vercel preview 완료 대기**

Expected: 필수 GitHub Actions 모두 success, Vercel preview Ready. 실패 시 로그의 첫 실제 오류를 재현하고 수정한다.

- [ ] **Step 5: 프리뷰 확인 후 PM에게 운영 병합 승인 요청**

프리뷰 `/`, `/blog`, 공개 가능한 변경 글, 모바일 화면을 확인하고 URL·CI·QA 요약을 PM에게 공유한다. 여기서 멈추고 운영 병합 확인을 받는다.

---

### Task 6: 운영 병합과 배포 검증

**Files:**
- No source changes expected before closeout docs

**Interfaces:**
- Consumes: PM 승인, green PR, Ready preview.
- Produces: production Vercel/Render release, blog v3 applied state, production smoke evidence.

- [ ] **Step 1: 병합 직전 master 겹침 확인**

```bash
git fetch origin
git diff --name-status HEAD...origin/master
```

블로그, 게시판, 랜딩 겹침이 있으면 최신 master를 보존하고 영향 테스트를 재실행한다.

- [ ] **Step 2: PR을 ready로 전환하고 정상 병합**

Force push와 direct master push는 사용하지 않는다. GitHub의 정상 PR merge를 사용한다.

- [ ] **Step 3: Vercel과 Render 배포 완료 대기**

Expected: merge SHA의 Vercel deployment Ready, Render web Live. Render 시작 로그에서 migrate, seed commands, v3 refresh 성공 확인.

- [ ] **Step 4: 운영 스모크**

확인 항목:

- `https://www.inpa.kr/` 200, header·3-tier pricing 정상
- `https://www.inpa.kr/blog` 200
- 기존 개선 글 6편 200 및 새 본문 확인
- 미래 신규 6개 slug는 각 예약 시각 전 404
- sitemap에서 미래 slug 0
- `https://inpa-be.onrender.com/healthz/`가 `{"status":"ok","service":"inpa-be"}`
- API의 공개 글 수와 작성자 `인파 담당자` 정확성
- Render v3 marker 활성, v2 snapshot 복구 가능

- [ ] **Step 5: 오류 상태 5분 관찰**

Vercel/Render/Sentry에서 새 5xx, hydration, asset 404, DB release 오류가 없는지 확인한다. 문제가 있으면 코드 revert PR 또는 v3 snapshot restore 중 영향을 좁히는 롤백을 실행한다.

---

### Task 7: 배포 문서와 최종 커밋 정리

**Files:**
- Modify after production success: `README.md`
- Modify after production success: `AGENTS.md`

**Interfaces:**
- Consumes: 실제 merge SHA, PR number, CI run, Vercel/Render status, production smoke 결과.
- Produces: PM용·agent용 배포 기록과 깨끗한 최종 저장소 상태.

- [ ] **Step 1: README PM 기록 추가**

한국어 쉬운 말로 다음 실제 결과만 기록한다.

- 블로그 총 31편, 신규 6편 주제와 예약 일정
- 기존 6편 개선, 작성자 `인파 담당자`
- 이미지 79개, 중복 차단
- 게시판 안내가 기능 상태에 따라 공개된다는 점
- 운영 검증과 롤백 방법

- [ ] **Step 2: AGENTS SSOT 갱신**

영문·고밀도로 다음을 기록한다.

- v3 release version과 exact 31/31/79
- three-way merge와 distinctness denominator rule
- 게시판 gated seed와 `cleanup_demo_boards` manual-only 계약
- exact production PR/SHA/CI/deployment evidence
- current state 날짜와 명령 설명의 공지·FAQ count

- [ ] **Step 3: 문서 검사와 커밋**

```bash
git diff --check -- README.md AGENTS.md
git add README.md AGENTS.md
git commit -m "docs(배포): 블로그와 디자인 통합 기록"
```

- [ ] **Step 4: closeout 문서를 정상 PR 흐름으로 게시**

문서 브랜치를 push하고 `master` 대상 PR을 만든 뒤 검사 통과 후 병합한다. 운영 `master`의 README·AGENTS가 실제 배포 증거를 포함하는지 확인한다.

- [ ] **Step 5: 최종 상태 확인**

```bash
git fetch origin
git status --short --branch
git log --oneline -15
```

Expected: release와 closeout docs가 `origin/master`에 있고, 통합 worktree가 clean. 원래 `/Users/kyungsbook/Desktop/inpa`의 `feat/design-refactor`와 제외 파일은 보존됨.
