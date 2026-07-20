from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from inpa.boards.models import Faq, Notice


SALES_NOTICE_TITLE = '새 기능: 고객 영업과 설계사 영업을 따로 관리'
MANAGER_FAQ_QUESTION = '설계사가 팀에 합류하면 Manager로 어떻게 바뀌나요?'


class SalesBoardVisibilityTests(TestCase):
    def setUp(self):
        author = get_user_model().objects.create_user(
            email='sales-board-author@test.com',
            password='test-password',
        )
        Notice.objects.create(
            author=author,
            title=SALES_NOTICE_TITLE,
            body='영업 메뉴 안내',
            is_published=True,
        )
        Faq.objects.create(
            author=author,
            category='계정',
            question=MANAGER_FAQ_QUESTION,
            answer='Manager 역할 안내',
            is_published=True,
        )
        self.client = APIClient()

    @override_settings(RECRUITING_ENABLED=False)
    def test_closed_recruiting_hides_sales_notice_and_manager_faq(self):
        notices = self.client.get('/api/v1/board/notices/').json()
        faqs = self.client.get('/api/v1/board/faqs/').json()

        self.assertNotIn(SALES_NOTICE_TITLE, [row['title'] for row in notices])
        self.assertNotIn(MANAGER_FAQ_QUESTION, [row['question'] for row in faqs])

    @override_settings(RECRUITING_ENABLED=True)
    def test_open_recruiting_shows_sales_notice_and_manager_faq(self):
        notices = self.client.get('/api/v1/board/notices/').json()
        faqs = self.client.get('/api/v1/board/faqs/').json()

        self.assertIn(SALES_NOTICE_TITLE, [row['title'] for row in notices])
        self.assertIn(MANAGER_FAQ_QUESTION, [row['question'] for row in faqs])
