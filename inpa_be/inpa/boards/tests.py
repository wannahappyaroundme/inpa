"""게시판 & 커뮤니티 핵심 가시성·권한 테스트 (dev/17 §13 수용 기준).

★ 검증 항목:
  [공유 — 게시판]
  S1  피드 목록 — 인증 설계사 A/B 모두 전체 게시글 조회
  S2  피드 목록 커서 페이지네이션 — next_cursor 포함
  S3  글 작성 → 201, 비인증 401
  S4  글 수정·삭제 — 작성자 O, 남의 글 403
  S5  관리자 — 숨김 글 접근 O, 일반 설계사 404
  S6  소프트 삭제 → is_deleted=True, 피드 미노출
  S7  좋아요 토글 — unique_together 중복 방지 + like_count F() 원자 업데이트
  S8  댓글 작성 → comment_count 증가, 2단계 대댓글 400
  S9  댓글 수정·삭제 — 작성자 O, 남의 댓글 403
  S10 신고 중복 400, 신고 목록 본인/관리자 가시성

  [공개읽기 + 관리자쓰기 — 공지/FAQ]
  N1  GET /board/notices/ — 비인증 200, 쓰기 401/403
  N2  관리자 공지 작성·수정·삭제 O, 일반 설계사 403
  F1  GET /board/faqs/ — 비인증 200 (카테고리 필터·검색)
  F2  관리자 FAQ CRUD O, 일반 설계사 403

  [비공개 — 1:1 문의]
  I1  내 문의 목록·상세 조회 O
  I2  타 설계사 문의 접근 → 404 (OwnedQuerySetMixin)
  I3  관리자 전체 문의 조회 O
  I4  관리자 답변 → Inquiry.status = answered 자동 전환
  I5  답변 달린 문의 수정·취소 → 400

  [첨부 MIME 화이트리스트]
  A1  허용 MIME 통과, 미허용 MIME 400

  [알림 연동]
  NT1 댓글 작성 → 원글 작성자 board_comment 알림 (자기 글 제외)
  NT2 좋아요 생성 → 원글 작성자 board_like 알림 (자기 글 제외)
"""
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.notifications.models import Notification

from .models import (
    BlogPost,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    PostLike,
    Report,
)


# ─── 헬퍼 ─────────────────────────────────────────────────────────

def _make_planner(email, is_admin=False):
    """이메일 인증 완료 설계사 + APIClient 반환."""
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = True
    user.save(update_fields=['is_active'])
    Profile.objects.create(
        user=user,
        email_verified_at=timezone.now(),
        is_admin=is_admin,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _make_post(author, **kwargs):
    return Post.objects.create(
        author=author,
        title=kwargs.get('title', '테스트 글'),
        body=kwargs.get('body', '본문 내용입니다.'),
        **{k: v for k, v in kwargs.items() if k not in ('title', 'body')},
    )


# ─── S1·S2: 공유 피드 목록 ─────────────────────────────────────────

class PostFeedTests(TestCase):
    """피드는 인증 설계사 전원 공유 — A가 B의 글 조회 가능."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('a@test.com')
        self.user_b, self.client_b = _make_planner('b@test.com')

    def test_shared_feed_all_see_all_posts(self):
        """S1: 설계사 A/B 모두 전체 게시글 조회."""
        post_a = _make_post(self.user_a, title='A의 글')
        post_b = _make_post(self.user_b, title='B의 글')

        r = self.client_a.get('/api/v1/board/posts/')
        self.assertEqual(r.status_code, 200)
        ids = [p['id'] for p in r.json()['results']]
        self.assertIn(post_a.id, ids)
        self.assertIn(post_b.id, ids)

    def test_feed_has_cursor_pagination(self):
        """S2: 커서 페이지네이션 — next_cursor 키 포함."""
        r = self.client_a.get('/api/v1/board/posts/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertIn('next_cursor', data)
        self.assertIn('results', data)

    def test_unauthenticated_blocked(self):
        """비인증 피드 접근 → 401."""
        c = APIClient()
        self.assertEqual(c.get('/api/v1/board/posts/').status_code, 401)

    def test_search_by_q(self):
        """?q= 검색 — title/body 포함 글만 반환."""
        _make_post(self.user_a, title='암진단비 설명법', body='암진단비 설명 내용')
        _make_post(self.user_a, title='일반 글', body='관련 없음')

        r = self.client_a.get('/api/v1/board/posts/?q=암진단비')
        ids = [p['id'] for p in r.json()['results']]
        titles = [p['title'] for p in r.json()['results']]
        self.assertTrue(any('암진단비' in t for t in titles))

    def test_category_filter(self):
        """?category= 필터."""
        _make_post(self.user_a, category='꿀팁')
        _make_post(self.user_a, category='질문')

        r = self.client_a.get('/api/v1/board/posts/?category=꿀팁')
        for p in r.json()['results']:
            self.assertEqual(p['category'], '꿀팁')


# ─── S3: 글 작성 ────────────────────────────────────────────────────

class PostCreateTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('writer@test.com')

    def test_create_post_success(self):
        """S3: 글 작성 → 201."""
        r = self.client.post(
            '/api/v1/board/posts/',
            {'title': '제목', 'body': '본문입니다.'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['title'], '제목')

    def test_create_post_no_title(self):
        """제목 없는 글 작성 허용 (피드형 단문 허용)."""
        r = self.client.post(
            '/api/v1/board/posts/',
            {'body': '제목 없는 본문'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_create_post_no_body_400(self):
        """본문 없는 글 → 400."""
        r = self.client.post('/api/v1/board/posts/', {'title': '제목만'}, format='json')
        self.assertEqual(r.status_code, 400)

    def test_body_max_5000_chars(self):
        """5001자 본문 → 400."""
        r = self.client.post(
            '/api/v1/board/posts/',
            {'body': 'A' * 5001},
            format='json',
        )
        self.assertEqual(r.status_code, 400)


# ─── S4·S5·S6: 수정·삭제·숨김 ─────────────────────────────────────

class PostEditDeleteTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('pa@test.com')
        self.user_b, self.client_b = _make_planner('pb@test.com')
        self.admin, self.client_admin = _make_planner('admin@test.com', is_admin=True)
        self.post_a = _make_post(self.user_a)

    def test_author_can_edit_own_post(self):
        """S4: 작성자 수정 O."""
        r = self.client_a.patch(
            f'/api/v1/board/posts/{self.post_a.id}/',
            {'title': '수정된 제목'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)

    def test_other_user_cannot_edit(self):
        """S4: 남의 글 수정 → 403."""
        r = self.client_b.patch(
            f'/api/v1/board/posts/{self.post_a.id}/',
            {'title': '무단 수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_admin_can_edit_any_post(self):
        """S4: 관리자 타인 글 수정 O."""
        r = self.client_admin.patch(
            f'/api/v1/board/posts/{self.post_a.id}/',
            {'title': '관리자 수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)

    def test_soft_delete_by_author(self):
        """S6: 작성자 소프트 삭제 → is_deleted=True, 피드 미노출."""
        r = self.client_a.delete(f'/api/v1/board/posts/{self.post_a.id}/')
        self.assertEqual(r.status_code, 204)
        self.post_a.refresh_from_db()
        self.assertTrue(self.post_a.is_deleted)

        # 피드에서 사라짐
        feed = self.client_a.get('/api/v1/board/posts/')
        ids = [p['id'] for p in feed.json()['results']]
        self.assertNotIn(self.post_a.id, ids)

    def test_hidden_post_invisible_to_regular_user(self):
        """S5: 관리자 숨김 처리 → 일반 설계사 404."""
        self.post_a.is_hidden = True
        self.post_a.save()

        r = self.client_b.get(f'/api/v1/board/posts/{self.post_a.id}/')
        self.assertEqual(r.status_code, 404)

    def test_hidden_post_visible_to_admin(self):
        """S5: 숨김 글 관리자 접근 O."""
        self.post_a.is_hidden = True
        self.post_a.save()

        r = self.client_admin.get(f'/api/v1/board/posts/{self.post_a.id}/')
        self.assertEqual(r.status_code, 200)

    def test_other_user_cannot_delete(self):
        """남의 글 삭제 → 403."""
        r = self.client_b.delete(f'/api/v1/board/posts/{self.post_a.id}/')
        self.assertEqual(r.status_code, 403)


# ─── S7: 좋아요 토글 ────────────────────────────────────────────────

class PostLikeTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('la@test.com')
        self.user_b, self.client_b = _make_planner('lb@test.com')
        self.post = _make_post(self.user_a)

    def test_like_creates_and_increments(self):
        """S7: 좋아요 → liked=True, like_count +1."""
        r = self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertTrue(data['liked'])
        self.assertEqual(data['like_count'], 1)

    def test_unlike_decrements(self):
        """S7: 이미 좋아요 → 취소, like_count -1."""
        # 좋아요 먼저
        self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        # 토글 → 취소
        r = self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertFalse(data['liked'])
        self.assertEqual(data['like_count'], 0)

    def test_like_count_atomic(self):
        """S7: F() 원자 업데이트 — DB like_count 정확."""
        self.client_a.post(f'/api/v1/board/posts/{self.post.id}/like/')
        self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        self.post.refresh_from_db()
        self.assertEqual(self.post.like_count, 2)


# ─── S8·S9: 댓글 ────────────────────────────────────────────────────

class CommentTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('ca@test.com')
        self.user_b, self.client_b = _make_planner('cb@test.com')
        self.admin, self.client_admin = _make_planner('cadmin@test.com', is_admin=True)
        self.post = _make_post(self.user_a)

    def test_comment_create_increments_count(self):
        """S8: 댓글 작성 → 201, comment_count +1."""
        r = self.client_b.post(
            f'/api/v1/board/posts/{self.post.id}/comments/',
            {'body': '댓글입니다.'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.post.refresh_from_db()
        self.assertEqual(self.post.comment_count, 1)

    def test_reply_to_comment_allowed(self):
        """S8: 1단계 대댓글 허용."""
        parent = Comment.objects.create(post=self.post, author=self.user_a, body='부모 댓글')
        r = self.client_b.post(
            f'/api/v1/board/posts/{self.post.id}/comments/',
            {'body': '대댓글', 'parent': parent.id},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_2depth_reply_rejected(self):
        """S8: 2단계 대댓글 → 400 (부모의 부모가 있음)."""
        parent = Comment.objects.create(post=self.post, author=self.user_a, body='부모')
        child = Comment.objects.create(post=self.post, author=self.user_b, body='자식', parent=parent)

        r = self.client_a.post(
            f'/api/v1/board/posts/{self.post.id}/comments/',
            {'body': '손자 댓글 시도', 'parent': child.id},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_comment_edit_by_author(self):
        """S9: 작성자 댓글 수정 O."""
        c = Comment.objects.create(post=self.post, author=self.user_b, body='원본')
        r = self.client_b.patch(
            f'/api/v1/board/comments/{c.id}/',
            {'body': '수정된 댓글'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)

    def test_comment_edit_by_other_403(self):
        """S9: 남의 댓글 수정 → 403."""
        c = Comment.objects.create(post=self.post, author=self.user_a, body='원본')
        r = self.client_b.patch(
            f'/api/v1/board/comments/{c.id}/',
            {'body': '무단 수정'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_comment_soft_delete(self):
        """S9: 댓글 소프트 삭제 → is_deleted=True."""
        c = Comment.objects.create(post=self.post, author=self.user_b, body='삭제할 댓글')
        r = self.client_b.delete(f'/api/v1/board/comments/{c.id}/')
        self.assertEqual(r.status_code, 204)
        c.refresh_from_db()
        self.assertTrue(c.is_deleted)

    def test_admin_can_delete_any_comment(self):
        """관리자 남의 댓글 삭제 O."""
        c = Comment.objects.create(post=self.post, author=self.user_a, body='삭제 대상')
        r = self.client_admin.delete(f'/api/v1/board/comments/{c.id}/')
        self.assertEqual(r.status_code, 204)


# ─── S10: 신고 ──────────────────────────────────────────────────────

class ReportTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('ra@test.com')
        self.user_b, self.client_b = _make_planner('rb@test.com')
        self.admin, self.client_admin = _make_planner('radmin@test.com', is_admin=True)
        self.post = _make_post(self.user_a)

    def test_report_create(self):
        """S10: 신고 접수 → 201."""
        r = self.client_b.post(
            '/api/v1/board/reports/',
            {'content_type': 'post', 'object_id': self.post.id, 'reason': 'spam'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_duplicate_report_400(self):
        """S10: 중복 신고 → 400."""
        data = {'content_type': 'post', 'object_id': self.post.id, 'reason': 'spam'}
        self.client_b.post('/api/v1/board/reports/', data, format='json')
        r = self.client_b.post('/api/v1/board/reports/', data, format='json')
        self.assertEqual(r.status_code, 400)

    def test_report_list_own_only(self):
        """S10: 일반 설계사 신고 목록 — 본인 신고만."""
        Report.objects.create(
            reporter=self.user_a,
            content_type='post',
            object_id=self.post.id,
            reason='spam',
        )
        Report.objects.create(
            reporter=self.user_b,
            content_type='post',
            object_id=self.post.id,
            reason='hate',
        )

        r = self.client_a.get('/api/v1/board/reports/')
        self.assertEqual(r.status_code, 200)
        reporters = [rep.get('reporter') for rep in r.json()]
        # 응답에 reporter 노출 안 되지만 실제 DB 레벨에서는 본인 것만 필터
        self.assertEqual(len(r.json()), 1)

    def test_admin_sees_all_reports(self):
        """S10: 관리자 전체 신고 조회."""
        Report.objects.create(reporter=self.user_a, content_type='post', object_id=self.post.id, reason='spam')
        Report.objects.create(reporter=self.user_b, content_type='post', object_id=self.post.id, reason='hate')

        r = self.client_admin.get('/api/v1/board/reports/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(len(r.json()), 2)


# ─── N1·N2: 공지사항 ────────────────────────────────────────────────

class NoticeTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('nu@test.com')
        self.admin, self.client_admin = _make_planner('nadmin@test.com', is_admin=True)
        self.notice = Notice.objects.create(
            author=self.admin,
            title='공지입니다',
            body='공지 내용',
            is_published=True,
        )

    def test_public_get_list_no_auth(self):
        """N1: 비인증 공지 목록 → 200."""
        c = APIClient()
        r = c.get('/api/v1/board/notices/')
        self.assertEqual(r.status_code, 200)

    def test_public_get_detail_no_auth(self):
        """N1: 비인증 공지 상세 → 200."""
        c = APIClient()
        r = c.get(f'/api/v1/board/notices/{self.notice.id}/')
        self.assertEqual(r.status_code, 200)

    def test_unauthenticated_write_401(self):
        """N1: 비인증 공지 작성 → 401."""
        c = APIClient()
        r = c.post('/api/v1/board/notices/', {'title': '제목', 'body': '본문'}, format='json')
        self.assertEqual(r.status_code, 401)

    def test_regular_user_write_403(self):
        """N2: 일반 설계사 공지 작성 → 403."""
        r = self.client.post(
            '/api/v1/board/notices/',
            {'title': '제목', 'body': '본문'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_admin_create_notice(self):
        """N2: 관리자 공지 작성 → 201."""
        r = self.client_admin.post(
            '/api/v1/board/notices/',
            {'title': '새 공지', 'body': '내용'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_admin_update_notice(self):
        """N2: 관리자 공지 수정 → 200."""
        r = self.client_admin.patch(
            f'/api/v1/board/notices/{self.notice.id}/',
            {'title': '수정된 공지'},
            format='json',
        )
        self.assertEqual(r.status_code, 200)

    def test_admin_delete_notice(self):
        """N2: 관리자 공지 삭제 → 204."""
        r = self.client_admin.delete(f'/api/v1/board/notices/{self.notice.id}/')
        self.assertEqual(r.status_code, 204)
        self.assertFalse(Notice.objects.filter(id=self.notice.id).exists())

    def test_unpublished_invisible_to_regular(self):
        """비게시 공지 — 일반 설계사 목록에 미노출."""
        Notice.objects.create(author=self.admin, title='초안', body='본문', is_published=False)
        r = self.client.get('/api/v1/board/notices/')
        titles = [n['title'] for n in r.json()]
        self.assertNotIn('초안', titles)


# ─── F1·F2: FAQ ─────────────────────────────────────────────────────

class FaqTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('fu@test.com')
        self.admin, self.client_admin = _make_planner('fadmin@test.com', is_admin=True)
        self.faq = Faq.objects.create(
            author=self.admin,
            category='기능',
            question='히트맵이란?',
            answer='담보 현황을 3색으로 표시합니다.',
            is_published=True,
        )

    def test_public_get_faq_no_auth(self):
        """F1: 비인증 FAQ 목록 → 200."""
        c = APIClient()
        r = c.get('/api/v1/board/faqs/')
        self.assertEqual(r.status_code, 200)

    def test_faq_category_filter(self):
        """F1: 카테고리 필터."""
        Faq.objects.create(author=self.admin, category='요금제', question='q', answer='a', is_published=True)
        r = self.client.get('/api/v1/board/faqs/?category=기능')
        for f in r.json():
            self.assertEqual(f['category'], '기능')

    def test_faq_search(self):
        """F1: ?q= 검색."""
        r = self.client.get('/api/v1/board/faqs/?q=히트맵')
        self.assertTrue(any('히트맵' in f['question'] for f in r.json()))

    def test_regular_user_write_403(self):
        """F2: 일반 설계사 FAQ 작성 → 403."""
        r = self.client.post(
            '/api/v1/board/faqs/',
            {'category': '기능', 'question': '?', 'answer': '!'},
            format='json',
        )
        self.assertEqual(r.status_code, 403)

    def test_admin_create_faq(self):
        """F2: 관리자 FAQ 작성 → 201."""
        r = self.client_admin.post(
            '/api/v1/board/faqs/',
            {'category': '기능', 'question': '새 질문', 'answer': '새 답변'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)


class SeedBoardsNeutralCopyTests(TestCase):
    OLD_NOTICE_BODY = (
        '안녕하세요, 인파(Inpa)입니다.\n\n'
        '설계사님의 하루가 조금 더 가벼워지도록, 고객 발굴부터 증권 정리, 담보 한눈표, '
        '비교 분석, 상담 예약까지 한 흐름으로 담았습니다.\n\n'
        '지금 무료로 이용하실 수 있어요. 써 보시다가 불편한 점이나 바라는 기능이 있으면 '
        '1:1 문의로 편하게 남겨 주세요. 하나씩 반영해 나가겠습니다.\n\n'
        '앞으로도 꾸준히 기능을 더하고 다듬겠습니다. 감사합니다.'
    )
    OLD_FAQ_QUESTION = '비교 분석표는 무엇인가요?'
    OLD_FAQ_ANSWER = (
        '지금 보장과 제안 보장을 나란히 놓고 추가·삭제·변경을 정리해 주는 표예요. '
        '산출물은 AI가 정리한 참고 자료이며, 보장 판단과 고객 안내는 설계사님의 업무입니다.'
    )

    def setUp(self):
        self.admin, _ = _make_planner('seed-admin@test.com', is_admin=True)

    def test_upgrades_untouched_official_notice_and_faq_to_neutral_copy(self):
        Notice.objects.create(
            author=self.admin,
            title='인파를 시작합니다',
            body=self.OLD_NOTICE_BODY,
            is_published=True,
        )
        Faq.objects.create(
            author=self.admin,
            category='기능문의',
            order=3,
            question=self.OLD_FAQ_QUESTION,
            answer=self.OLD_FAQ_ANSWER,
            is_published=True,
        )

        call_command('seed_boards')
        call_command('seed_boards')

        notice = Notice.objects.get(title='인파를 시작합니다')
        self.assertIn('여러 증권 비교', notice.body)
        faq_rows = Faq.objects.filter(
            question='여러 증권 비교는 무엇인가요?',
            is_published=True,
        )
        self.assertEqual(faq_rows.count(), 1)
        faq = faq_rows.get()
        self.assertIn('증권 A와 증권 B', faq.answer)
        for deprecated in ('현재와 제안', '제안 보장', '갈아타기', '승환', '비교안내서'):
            self.assertNotIn(deprecated, notice.body)
            self.assertNotIn(deprecated, faq.answer)
        self.assertFalse(Faq.objects.filter(question=self.OLD_FAQ_QUESTION).exists())

    def test_preserves_admin_edited_notice_and_faq(self):
        edited_notice = '관리자가 직접 수정한 공지 본문입니다.'
        edited_answer = '관리자가 직접 수정한 FAQ 답변입니다.'
        Notice.objects.create(
            author=self.admin,
            title='인파를 시작합니다',
            body=edited_notice,
            is_published=True,
        )
        Faq.objects.create(
            author=self.admin,
            category='기능문의',
            order=3,
            question=self.OLD_FAQ_QUESTION,
            answer=edited_answer,
            is_published=True,
        )

        call_command('seed_boards')

        self.assertTrue(Notice.objects.filter(
            title='인파를 시작합니다', body=edited_notice,
        ).exists())
        self.assertTrue(Faq.objects.filter(
            question=self.OLD_FAQ_QUESTION, answer=edited_answer,
        ).exists())


# ─── I1~I5: 1:1 문의 ────────────────────────────────────────────────

class InquiryTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _make_planner('ia@test.com')
        self.user_b, self.client_b = _make_planner('ib@test.com')
        self.admin, self.client_admin = _make_planner('iadmin@test.com', is_admin=True)
        self.inquiry_a = Inquiry.objects.create(
            owner=self.user_a,
            category='feature',
            title='기능 문의',
            body='히트맵 색상이 이상해요.',
        )

    def test_owner_can_list_own_inquiries(self):
        """I1: 내 문의 목록 조회."""
        r = self.client_a.get('/api/v1/board/inquiries/')
        self.assertEqual(r.status_code, 200)
        ids = [i['id'] for i in r.json()]
        self.assertIn(self.inquiry_a.id, ids)

    def test_other_user_cannot_access(self):
        """I2: 타 설계사 문의 → 404 (OwnedQuerySetMixin)."""
        r = self.client_b.get(f'/api/v1/board/inquiries/{self.inquiry_a.id}/')
        self.assertEqual(r.status_code, 404)

    def test_other_user_inquiry_not_in_list(self):
        """I2: B의 목록에 A의 문의가 없음."""
        r = self.client_b.get('/api/v1/board/inquiries/')
        ids = [i['id'] for i in r.json()]
        self.assertNotIn(self.inquiry_a.id, ids)

    def test_admin_sees_all_inquiries(self):
        """I3: 관리자 전체 문의 조회."""
        Inquiry.objects.create(owner=self.user_b, category='billing', title='요금 문의', body='내용')
        r = self.client_admin.get('/api/v1/board/inquiries/')
        self.assertEqual(r.status_code, 200)
        self.assertGreaterEqual(len(r.json()), 2)

    def test_admin_reply_changes_status_to_answered(self):
        """I4: 관리자 답변 → Inquiry.status = answered."""
        r = self.client_admin.post(
            f'/api/v1/board/inquiries/{self.inquiry_a.id}/replies/',
            {'body': '답변 드립니다.'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.inquiry_a.refresh_from_db()
        self.assertEqual(self.inquiry_a.status, Inquiry.STATUS_ANSWERED)

    def test_cannot_edit_answered_inquiry(self):
        """I5: 답변 달린 문의 수정 → 400."""
        self.inquiry_a.status = Inquiry.STATUS_ANSWERED
        self.inquiry_a.save()
        r = self.client_a.patch(
            f'/api/v1/board/inquiries/{self.inquiry_a.id}/',
            {'title': '수정 시도'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_cannot_delete_answered_inquiry(self):
        """I5: 답변 달린 문의 취소 → 400."""
        self.inquiry_a.status = Inquiry.STATUS_ANSWERED
        self.inquiry_a.save()
        r = self.client_a.delete(f'/api/v1/board/inquiries/{self.inquiry_a.id}/')
        self.assertEqual(r.status_code, 400)

    def test_create_inquiry(self):
        """문의 작성 → 201."""
        r = self.client_a.post(
            '/api/v1/board/inquiries/',
            {'category': 'bug', 'title': '버그 신고', 'body': '상세 내용'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)


# ─── A1: 첨부 MIME 화이트리스트 ─────────────────────────────────────

class AttachmentMimeTests(TestCase):
    def setUp(self):
        self.user, self.client = _make_planner('att@test.com')
        self.post = _make_post(self.user)

    def test_allowed_mime_passes(self):
        """A1: image/jpeg 허용 — 201."""
        r = self.client.post(
            '/api/v1/board/posts/attachments/',
            {
                'post': self.post.id,
                'file_url': 'https://cdn.inpa.test/img.jpg',
                'file_name': 'img.jpg',
                'file_size': 1024 * 100,
                'mime_type': 'image/jpeg',
            },
            format='json',
        )
        self.assertEqual(r.status_code, 201)

    def test_disallowed_mime_400(self):
        """A1: 미허용 MIME → 400."""
        r = self.client.post(
            '/api/v1/board/posts/attachments/',
            {
                'post': self.post.id,
                'file_url': 'https://cdn.inpa.test/file.exe',
                'file_name': 'malware.exe',
                'file_size': 1024,
                'mime_type': 'application/octet-stream',
            },
            format='json',
        )
        self.assertEqual(r.status_code, 400)

    def test_image_over_10mb_400(self):
        """A1: 이미지 10MB 초과 → 400."""
        r = self.client.post(
            '/api/v1/board/posts/attachments/',
            {
                'post': self.post.id,
                'file_url': 'https://cdn.inpa.test/big.jpg',
                'file_name': 'big.jpg',
                'file_size': 11 * 1024 * 1024,
                'mime_type': 'image/jpeg',
            },
            format='json',
        )
        self.assertEqual(r.status_code, 400)


# ─── NT1·NT2: 알림 연동 ─────────────────────────────────────────────

class BoardNotificationTests(TestCase):
    """댓글·좋아요 → 원글 작성자 인앱 알림 생성 (dev/17 §13 / dev/02 §9.1)."""

    def setUp(self):
        self.user_a, self.client_a = _make_planner('nta@test.com')
        self.user_b, self.client_b = _make_planner('ntb@test.com')
        self.post = _make_post(self.user_a)

    def test_comment_triggers_board_comment_notification(self):
        """NT1: B가 A의 글에 댓글 → A에게 board_comment 알림."""
        self.client_b.post(
            f'/api/v1/board/posts/{self.post.id}/comments/',
            {'body': '댓글 알림 테스트'},
            format='json',
        )
        notifs = Notification.objects.filter(owner=self.user_a, notif_type='board_comment')
        self.assertEqual(notifs.count(), 1)

    def test_self_comment_no_notification(self):
        """NT1: A가 자기 글에 댓글 → A에게 알림 없음."""
        self.client_a.post(
            f'/api/v1/board/posts/{self.post.id}/comments/',
            {'body': '자기 댓글'},
            format='json',
        )
        notifs = Notification.objects.filter(owner=self.user_a, notif_type='board_comment')
        self.assertEqual(notifs.count(), 0)

    def test_like_triggers_board_like_notification(self):
        """NT2: B가 A의 글에 좋아요 → A에게 board_like 알림."""
        self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        notifs = Notification.objects.filter(owner=self.user_a, notif_type='board_like')
        self.assertEqual(notifs.count(), 1)

    def test_self_like_no_notification(self):
        """NT2: A가 자기 글에 좋아요 → A에게 알림 없음."""
        self.client_a.post(f'/api/v1/board/posts/{self.post.id}/like/')
        notifs = Notification.objects.filter(owner=self.user_a, notif_type='board_like')
        self.assertEqual(notifs.count(), 0)

    def test_unlike_no_extra_notification(self):
        """NT2: 좋아요 취소(토글) 시 추가 알림 없음."""
        # 좋아요
        self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        # 취소
        self.client_b.post(f'/api/v1/board/posts/{self.post.id}/like/')
        # 알림은 좋아요 생성 1건만 (취소 시 추가 알림 없음)
        notifs = Notification.objects.filter(owner=self.user_a, notif_type='board_like')
        self.assertEqual(notifs.count(), 1)


# ─── 인파 노트(BlogPost) — 공개읽기 + 관리자쓰기 (shared/global) ──────

def _make_blog(**kwargs):
    """BlogPost 팩토리 — is_published 기본 True(게시)."""
    defaults = dict(
        title='보험 증권 보는 법',
        slug=None,
        body='본문 마크다운 내용입니다.',
        category=BlogPost.CATEGORY_COVERAGE,
        is_published=True,
    )
    defaults.update(kwargs)
    if not defaults.get('slug'):
        defaults['slug'] = BlogPost.generate_unique_slug(defaults['title'])
    return BlogPost.objects.create(**defaults)


class BlogPublicReadTests(TestCase):
    """공개 목록/상세 — 게시글만 노출, slug 조회, 조회수 증가."""

    def setUp(self):
        self.anon = APIClient()
        self.user, self.client = _make_planner('reader@test.com')
        self.admin, self.admin_client = _make_planner('bloadmin@test.com', is_admin=True)

    def test_public_list_published_only(self):
        """공개 목록: 게시글만, 초안 제외 (비로그인 + 일반 설계사)."""
        pub = _make_blog(title='게시된 글', is_published=True)
        draft = _make_blog(title='초안 글', is_published=False)

        for c in (self.anon, self.client):
            r = c.get('/api/v1/board/blog/')
            self.assertEqual(r.status_code, 200)
            ids = [p['id'] for p in r.json()['results']]
            self.assertIn(pub.id, ids)
            self.assertNotIn(draft.id, ids)

    def test_list_paginated_shape(self):
        """목록 응답 = {count, next, previous, results} + body 미포함."""
        _make_blog(title='한 편')
        r = self.anon.get('/api/v1/board/blog/')
        data = r.json()
        for key in ('count', 'next', 'previous', 'results'):
            self.assertIn(key, data)
        row = data['results'][0]
        self.assertNotIn('body', row)
        self.assertIn('category_label', row)
        self.assertIsInstance(row['tags'], list)

    def test_category_filter(self):
        """?category= 필터."""
        _make_blog(title='영업 글', category=BlogPost.CATEGORY_SALES)
        _make_blog(title='보장 글', category=BlogPost.CATEGORY_COVERAGE)
        r = self.anon.get('/api/v1/board/blog/?category=sales')
        for p in r.json()['results']:
            self.assertEqual(p['category'], 'sales')

    def test_retrieve_by_slug_published(self):
        """게시글 slug 조회 → 200 + body 포함."""
        post = _make_blog(title='슬러그 조회', slug='slug-test')
        r = self.anon.get('/api/v1/board/blog/slug-test/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['id'], post.id)
        self.assertIn('body', r.json())

    def test_draft_404_for_anon_200_for_admin(self):
        """초안: 비로그인/일반 404, 관리자 200."""
        draft = _make_blog(title='비공개 초안', slug='draft-1', is_published=False)
        self.assertEqual(self.anon.get('/api/v1/board/blog/draft-1/').status_code, 404)
        self.assertEqual(self.client.get('/api/v1/board/blog/draft-1/').status_code, 404)
        r = self.admin_client.get('/api/v1/board/blog/draft-1/')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['id'], draft.id)

    def test_view_count_increments_on_public_retrieve(self):
        """공개 조회마다 view_count 증가."""
        post = _make_blog(title='조회수', slug='vc')
        self.anon.get('/api/v1/board/blog/vc/')
        self.anon.get('/api/v1/board/blog/vc/')
        post.refresh_from_db()
        self.assertEqual(post.view_count, 2)

    def test_admin_view_does_not_increment(self):
        """관리자 조회는 view_count 미증가(공개 조회수만 집계)."""
        post = _make_blog(title='관리자 조회', slug='av')
        self.admin_client.get('/api/v1/board/blog/av/')
        post.refresh_from_db()
        self.assertEqual(post.view_count, 0)

    def test_sitemap_published_only(self):
        """sitemap: 게시글 slug만."""
        _make_blog(title='게시', slug='pub-a', is_published=True)
        _make_blog(title='초안', slug='draft-a', is_published=False)
        r = self.anon.get('/api/v1/board/blog/sitemap/')
        self.assertEqual(r.status_code, 200)
        slugs = [row['slug'] for row in r.json()]
        self.assertIn('pub-a', slugs)
        self.assertNotIn('draft-a', slugs)
        self.assertIn('updated_at', r.json()[0])


class BlogAdminCrudTests(TestCase):
    """admin CRUD — IsAdmin, 자동 슬러그, published_at 스탬프, 권한."""

    def setUp(self):
        self.admin, self.admin_client = _make_planner('badmin@test.com', is_admin=True)
        self.user, self.client = _make_planner('normal@test.com')
        self.anon = APIClient()

    def test_create_autoslug_and_published_at(self):
        """게시 상태로 생성 → slug 자동 + published_at 스탬프."""
        r = self.admin_client.post(
            '/api/v1/admin/blog/',
            {'title': '3대 진단비 기초', 'body': '본문', 'category': 'coverage',
             'is_published': True},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        data = r.json()
        self.assertTrue(data['slug'])
        self.assertIsNotNone(data['published_at'])
        self.assertEqual(data['category_label'], '보장분석')

    def test_create_draft_no_published_at(self):
        """초안 생성 → published_at null."""
        r = self.admin_client.post(
            '/api/v1/admin/blog/',
            {'title': '초안 저장', 'body': '본문', 'is_published': False},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertIsNone(r.json()['published_at'])

    def test_slug_uniqueness_on_collision(self):
        """같은 제목 두 번 → slug 충돌 회피(-2 접미)."""
        r1 = self.admin_client.post(
            '/api/v1/admin/blog/', {'title': '보험 이야기', 'body': 'a'}, format='json')
        r2 = self.admin_client.post(
            '/api/v1/admin/blog/', {'title': '보험 이야기', 'body': 'b'}, format='json')
        self.assertNotEqual(r1.json()['slug'], r2.json()['slug'])

    def test_admin_lists_drafts(self):
        """관리자 목록 = 초안 포함, ?status=draft 필터."""
        _make_blog(title='게시글', is_published=True)
        draft = _make_blog(title='초안글', is_published=False)
        r = self.admin_client.get('/api/v1/admin/blog/?status=draft')
        self.assertEqual(r.status_code, 200)
        ids = [p['id'] for p in r.json()['results']]
        self.assertIn(draft.id, ids)

    def test_patch_publish_stamps_published_at(self):
        """초안 → 게시 전환 시 published_at 최초 스탬프."""
        draft = _make_blog(title='나중 게시', is_published=False, published_at=None)
        self.assertIsNone(draft.published_at)
        r = self.admin_client.patch(
            f'/api/v1/admin/blog/{draft.id}/', {'is_published': True}, format='json')
        self.assertEqual(r.status_code, 200)
        self.assertIsNotNone(r.json()['published_at'])

    def test_delete_is_soft(self):
        """삭제 = 소프트(is_published=False), DB 보존."""
        post = _make_blog(title='삭제 대상', is_published=True)
        r = self.admin_client.delete(f'/api/v1/admin/blog/{post.id}/')
        self.assertEqual(r.status_code, 200)
        post.refresh_from_db()
        self.assertFalse(post.is_published)
        self.assertTrue(BlogPost.objects.filter(pk=post.id).exists())

    def test_non_admin_cannot_write(self):
        """일반 설계사 = 403, 비로그인 = 401 (create/update/delete)."""
        post = _make_blog(title='보호 대상')
        # 일반 설계사
        self.assertEqual(
            self.client.post('/api/v1/admin/blog/', {'title': 'x', 'body': 'y'}, format='json').status_code, 403)
        self.assertEqual(
            self.client.patch(f'/api/v1/admin/blog/{post.id}/', {'title': 'z'}, format='json').status_code, 403)
        self.assertEqual(
            self.client.delete(f'/api/v1/admin/blog/{post.id}/').status_code, 403)
        # 비로그인
        self.assertEqual(
            self.anon.post('/api/v1/admin/blog/', {'title': 'x', 'body': 'y'}, format='json').status_code, 401)


class BlogCopyGuardTests(TestCase):
    """게시 시 카피 검사 — em-dash + 권유 단어 경고(비차단)."""

    def setUp(self):
        self.admin, self.admin_client = _make_planner('cadmin@test.com', is_admin=True)

    def test_publish_flags_emdash_and_advice_nonblocking(self):
        """게시 생성 시 em-dash·권유어 경고 반환하되 저장은 성공(201)."""
        r = self.admin_client.post(
            '/api/v1/admin/blog/',
            {'title': '보험 정리 — 핵심만', 'body': '이 상품을 추천합니다.',
             'is_published': True},
            format='json',
        )
        self.assertEqual(r.status_code, 201)  # 비차단 = 저장 성공
        warnings = r.json()['warnings']
        issues = {w['issue'] for w in warnings}
        self.assertIn('em_dash', issues)
        self.assertIn('advice_word', issues)
        # 실제로 저장됐는지 확인
        self.assertTrue(BlogPost.objects.filter(title='보험 정리 — 핵심만').exists())

    def test_clean_publish_no_warnings(self):
        """깨끗한 카피 = 경고 없음."""
        r = self.admin_client.post(
            '/api/v1/admin/blog/',
            {'title': '보장분석 기초 가이드', 'body': '보험 증권을 차분히 살펴봅니다.',
             'is_published': True},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['warnings'], [])

    def test_draft_not_scanned(self):
        """초안(미게시)은 카피 검사 미수행."""
        r = self.admin_client.post(
            '/api/v1/admin/blog/',
            {'title': '초안 — 추천 문구', 'body': '가입하세요', 'is_published': False},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['warnings'], [])


# ─── 피드백 위젯 (공개 제출) ────────────────────────────────────────

from inpa.notifications.models import ADMIN_NOTIF_TYPES, NotifType  # noqa: E402


class FeedbackWidgetTests(TestCase):
    """POST /api/v1/feedback/ — 익명/로그인 제출 + 관리자 fan-out + 검증."""

    def setUp(self):
        self.admin, _ = _make_planner('admin@test.com', is_admin=True)
        self.planner, self.planner_client = _make_planner('planner@test.com')
        self.anon = APIClient()  # 비인증

    def test_anonymous_submission_creates_owner_null_inquiry(self):
        """익명 제출 → owner=None Inquiry + 관리자 알림 fan-out."""
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'feedback', 'body': '화면이 깔끔해서 좋아요',
             'rating': 5, 'contact_email': 'guest@example.com'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        inq = Inquiry.objects.get(pk=r.json()['id'])
        self.assertIsNone(inq.owner_id)
        self.assertEqual(inq.category, Inquiry.CATEGORY_FEEDBACK)
        self.assertEqual(inq.rating, 5)
        self.assertEqual(inq.contact_email, 'guest@example.com')
        self.assertTrue(inq.title.startswith('[이용 의견]'))
        # 관리자 알림 fan-out
        notif = Notification.objects.filter(
            owner=self.admin, notif_type=NotifType.INQUIRY_RECEIVED,
        )
        self.assertEqual(notif.count(), 1)

    def test_authed_submission_sets_owner(self):
        """로그인 제출 → owner=request.user (문의 내역·답변 알림 작동)."""
        r = self.planner_client.post(
            '/api/v1/feedback/',
            {'category': 'feature', 'body': '월별 리포트 내보내기 기능이 있으면 좋겠어요'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        inq = Inquiry.objects.get(pk=r.json()['id'])
        self.assertEqual(inq.owner_id, self.planner.id)
        self.assertEqual(inq.category, Inquiry.CATEGORY_FEATURE)
        # 본인 문의 내역에 노출(OwnedQuerySetMixin)
        listing = self.planner_client.get('/api/v1/board/inquiries/')
        self.assertIn(inq.id, [row['id'] for row in listing.json()])

    def test_bug_meta_whitelist(self):
        """불편 신고 meta 는 화이트리스트 키만 저장, 그 외 키 제거."""
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'bug', 'body': '버튼이 안 눌려요',
             'meta': {'path': '/customers', 'user_agent': 'UA', 'viewport': '390x844',
                      'cookie': 'secret', 'token': 'leak'}},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        inq = Inquiry.objects.get(pk=r.json()['id'])
        self.assertEqual(set(inq.meta.keys()), {'path', 'user_agent', 'viewport'})
        self.assertNotIn('cookie', inq.meta)
        self.assertNotIn('token', inq.meta)

    def test_rating_only_for_feedback_and_clamped(self):
        """rating 은 feedback 만, 범위 밖은 1..5 로 clamp; 타 카테고리는 무시."""
        # 범위 밖(9) → 5로 clamp
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'feedback', 'body': '좋아요', 'rating': 9}, format='json',
        )
        self.assertEqual(Inquiry.objects.get(pk=r.json()['id']).rating, 5)
        # feature 에 rating 줘도 무시(None)
        r2 = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'feature', 'body': '제안합니다', 'rating': 3}, format='json',
        )
        self.assertIsNone(Inquiry.objects.get(pk=r2.json()['id']).rating)

    def test_meta_ignored_for_non_bug(self):
        """meta 는 bug 만 저장 — feedback 제출의 meta 는 무시(None)."""
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'feedback', 'body': '좋아요', 'meta': {'path': '/x'}},
            format='json',
        )
        self.assertIsNone(Inquiry.objects.get(pk=r.json()['id']).meta)

    def test_body_required(self):
        r = self.anon.post('/api/v1/feedback/', {'category': 'feedback'}, format='json')
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'BODY_REQUIRED')

    def test_body_length_cap(self):
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'other', 'body': 'x' * 2001}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'BODY_TOO_LONG')

    def test_invalid_category(self):
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'nope', 'body': '내용'}, format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'INVALID_CATEGORY')

    def test_invalid_contact_email(self):
        r = self.anon.post(
            '/api/v1/feedback/',
            {'category': 'other', 'body': '내용', 'contact_email': 'not-an-email'},
            format='json',
        )
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.json()['code'], 'INVALID_EMAIL')

    def test_throttle_scope_registered(self):
        """feedback throttle scope 가 settings + 뷰에 등록돼 있음."""
        from django.conf import settings as dj_settings
        from inpa.boards.views import FeedbackCreateView
        self.assertIn('feedback', dj_settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'])
        self.assertEqual(FeedbackCreateView.throttle_scope, 'feedback')

    def test_inquiry_received_in_admin_partition(self):
        """INQUIRY_RECEIVED 는 어드민 알림 파티션에 속함."""
        self.assertIn(NotifType.INQUIRY_RECEIVED.value, ADMIN_NOTIF_TYPES)


class InquiryCreateNotifiesAdminsTests(TestCase):
    """기존 /board/inquiries/ 작성도 관리자 알림 fan-out (누락 갭 해소)."""

    def setUp(self):
        self.admin, _ = _make_planner('admin2@test.com', is_admin=True)
        self.planner, self.planner_client = _make_planner('p2@test.com')

    def test_owner_inquiry_create_fans_out_to_admins(self):
        r = self.planner_client.post(
            '/api/v1/board/inquiries/',
            {'category': 'feature', 'title': '기능 문의', 'body': '문의 내용입니다'},
            format='json',
        )
        self.assertEqual(r.status_code, 201)
        self.assertEqual(
            Notification.objects.filter(
                owner=self.admin, notif_type=NotifType.INQUIRY_RECEIVED,
            ).count(),
            1,
        )
