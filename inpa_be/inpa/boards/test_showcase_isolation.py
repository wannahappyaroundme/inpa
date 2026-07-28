"""Showcase users can read shared content without changing shared state."""
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User
from inpa.billing.models import Plan
from inpa.notifications.models import Notification

from .models import (
    BlogPost,
    Comment,
    Faq,
    Inquiry,
    InquiryReply,
    Notice,
    Post,
    PostAttachment,
    PostLike,
    Report,
)


SHOWCASE_EMAIL = 'showcase-board-guard@inpa.invalid'


@override_settings(SHOWCASE_ACCOUNT_EMAIL=SHOWCASE_EMAIL)
class ShowcaseBoardIsolationTests(TestCase):
    tracked_models = (
        Post,
        Comment,
        PostLike,
        PostAttachment,
        Report,
        Notice,
        Faq,
        Inquiry,
        InquiryReply,
        BlogPost,
        Notification,
    )

    def setUp(self):
        Plan.objects.create(code='free', display_name='Free', price_krw=0)
        self.showcase = self._user(SHOWCASE_EMAIL, is_showcase=True)
        self.real_user = self._user('real-board-owner@inpa.invalid', is_admin=True)
        self.post = Post.objects.create(
            author=self.real_user,
            title='운영 게시글',
            body='운영 게시글 본문',
        )
        self.comment = Comment.objects.create(
            post=self.post,
            author=self.real_user,
            body='운영 댓글',
        )
        self.notice = Notice.objects.create(
            author=self.real_user,
            title='운영 공지',
            body='운영 공지 본문',
            is_published=True,
        )
        self.faq = Faq.objects.create(
            author=self.real_user,
            category='service',
            question='운영 질문',
            answer='운영 답변',
        )
        self.inquiry = Inquiry.objects.create(
            owner=self.real_user,
            category=Inquiry.CATEGORY_OTHER,
            title='운영 문의',
            body='운영 문의 본문',
        )
        self.reply = InquiryReply.objects.create(
            inquiry=self.inquiry,
            author=self.real_user,
            body='운영 답변',
        )
        self.blog = BlogPost.objects.create(
            author=self.real_user,
            title='운영 노트',
            slug='real-board-note',
            body='운영 노트 본문',
            is_published=True,
            published_at=timezone.now(),
        )
        self.client = APIClient()
        self.client.force_authenticate(user=self.showcase)

    def _user(self, email, *, is_showcase=False, is_admin=False):
        user = User.objects.create_user(email=email)
        user.is_active = True
        user.save(update_fields=['is_active'])
        Profile.objects.create(
            user=user,
            is_showcase=is_showcase,
            is_admin=is_admin,
        )
        return user

    def _shared_state(self):
        return {
            model._meta.label_lower: list(
                model.objects.order_by('pk').values()
            )
            for model in self.tracked_models
        }

    def test_showcase_post_and_blog_reads_do_not_increment_real_view_counts(self):
        post_response = self.client.get(f'/api/v1/board/posts/{self.post.pk}/')
        blog_response = self.client.get(f'/api/v1/board/blog/{self.blog.slug}/')

        self.assertEqual(post_response.status_code, 200, post_response.content)
        self.assertEqual(blog_response.status_code, 200, blog_response.content)
        self.post.refresh_from_db()
        self.blog.refresh_from_db()
        self.assertEqual(self.post.view_count, 0)
        self.assertEqual(self.blog.view_count, 0)

    def test_showcase_shared_writes_are_rejected_without_rows_or_notifications(self):
        self.showcase.profile.is_admin = True
        self.showcase.profile.save(update_fields=['is_admin'])
        requests = [
            (
                'post',
                '/api/v1/board/posts/',
                {'title': '시연 글', 'body': '공유되면 안 되는 본문'},
            ),
            (
                'patch',
                f'/api/v1/board/posts/{self.post.pk}/',
                {'title': '바뀌면 안 되는 글'},
            ),
            ('post', f'/api/v1/board/posts/{self.post.pk}/like/', {}),
            (
                'post',
                f'/api/v1/board/posts/{self.post.pk}/comments/',
                {'body': '공유되면 안 되는 댓글'},
            ),
            (
                'patch',
                f'/api/v1/board/comments/{self.comment.pk}/',
                {'body': '바뀌면 안 되는 댓글'},
            ),
            (
                'post',
                '/api/v1/board/posts/attachments/',
                {
                    'post': self.post.pk,
                    'file_url': 'https://files.inpa.invalid/blocked.pdf',
                    'file_name': 'blocked.pdf',
                    'file_size': 100,
                    'mime_type': 'application/pdf',
                },
            ),
            (
                'post',
                '/api/v1/board/reports/',
                {
                    'content_type': 'post',
                    'object_id': self.post.pk,
                    'reason': 'other',
                    'detail': '공유되면 안 되는 신고',
                },
            ),
            (
                'post',
                '/api/v1/board/notices/',
                {'title': '시연 공지', 'body': '공개되면 안 되는 공지'},
            ),
            (
                'patch',
                f'/api/v1/board/notices/{self.notice.pk}/',
                {'title': '바뀌면 안 되는 공지'},
            ),
            (
                'post',
                '/api/v1/board/faqs/',
                {
                    'category': 'service',
                    'question': '공개되면 안 되는 질문',
                    'answer': '공개되면 안 되는 답변',
                },
            ),
            (
                'patch',
                f'/api/v1/board/faqs/{self.faq.pk}/',
                {'answer': '바뀌면 안 되는 답변'},
            ),
            (
                'post',
                '/api/v1/board/inquiries/',
                {
                    'category': 'other',
                    'title': '전송되면 안 되는 문의',
                    'body': '전송되면 안 되는 문의 본문',
                },
            ),
            (
                'patch',
                f'/api/v1/board/inquiries/{self.inquiry.pk}/',
                {'title': '바뀌면 안 되는 문의'},
            ),
            (
                'post',
                f'/api/v1/board/inquiries/{self.inquiry.pk}/replies/',
                {'body': '전송되면 안 되는 답변'},
            ),
            (
                'patch',
                f'/api/v1/board/inquiry-replies/{self.reply.pk}/',
                {'body': '바뀌면 안 되는 답변'},
            ),
            (
                'post',
                '/api/v1/feedback/',
                {
                    'category': 'feedback',
                    'body': '전송되면 안 되는 의견',
                    'rating': 5,
                },
            ),
            ('delete', f'/api/v1/board/comments/{self.comment.pk}/', {}),
            ('delete', f'/api/v1/board/posts/{self.post.pk}/', {}),
            ('delete', f'/api/v1/board/notices/{self.notice.pk}/', {}),
            ('delete', f'/api/v1/board/faqs/{self.faq.pk}/', {}),
            ('delete', f'/api/v1/board/inquiries/{self.inquiry.pk}/', {}),
        ]

        for method, path, payload in requests:
            with self.subTest(method=method, path=path):
                before = self._shared_state()
                response = getattr(self.client, method)(path, payload, format='json')
                self.assertEqual(response.status_code, 403, response.content)
                self.assertEqual(self._shared_state(), before)
