from django.apps import apps
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from inpa.accounts.models import Profile, User


TEMPLATES_URL = '/api/v1/talk-templates/'
PREFERENCES_URL = '/api/v1/talk-template-preferences/'


def _planner(email, *, verified=True, is_admin=False):
    user = User.objects.create_user(email=email, password='inpaPass123!')
    user.is_active = verified
    user.save(update_fields=['is_active'])
    Profile.objects.create(
        user=user,
        email_verified_at=timezone.now() if verified else None,
        is_admin=is_admin,
    )
    client = APIClient()
    client.force_authenticate(user=user)
    return user, client


def _template_model():
    return apps.get_model('talks', 'PersonalTalkTemplate')


def _preference_model():
    return apps.get_model('talks', 'TalkTemplatePreference')


def _payload(**overrides):
    payload = {
        'title': '내 마무리',
        'body': '{고객명} 고객님, 오늘 신청 절차를 이어가겠습니다.',
        'category': 'closing',
        'channel': 'message',
        'sort_order': 10,
    }
    payload.update(overrides)
    return payload


class TalkTemplateAccessTests(TestCase):
    def setUp(self):
        self.user_a, self.client_a = _planner('talk-a@test.com')
        self.user_b, self.client_b = _planner('talk-b@test.com')

    def test_personal_template_is_owner_scoped(self):
        created = self.client_a.post(TEMPLATES_URL, _payload(), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(
            self.client_b.get(TEMPLATES_URL).json()['results'],
            [],
        )
        self.assertEqual(
            self.client_b.get(
                f"{TEMPLATES_URL}{created.json()['id']}/"
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client_b.patch(
                f"{TEMPLATES_URL}{created.json()['id']}/",
                {'title': '가로챈 제목'},
                format='json',
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client_b.delete(
                f"{TEMPLATES_URL}{created.json()['id']}/"
            ).status_code,
            404,
        )

    def test_create_ignores_client_owner_and_uses_authenticated_user(self):
        response = self.client_a.post(
            TEMPLATES_URL,
            _payload(owner=self.user_b.pk),
            format='json',
        )
        self.assertEqual(response.status_code, 201, response.content)
        stored = _template_model().objects.get(pk=response.json()['id'])
        self.assertEqual(stored.owner_id, self.user_a.pk)

    def test_admin_uses_existing_owner_mixin_bypass(self):
        created = self.client_a.post(TEMPLATES_URL, _payload(), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        _, admin_client = _planner(
            'talk-admin@test.com',
            is_admin=True,
        )

        listed = admin_client.get(TEMPLATES_URL)
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [item['id'] for item in listed.json()['results']],
            [created.json()['id']],
        )
        updated = admin_client.patch(
            f"{TEMPLATES_URL}{created.json()['id']}/",
            {'title': '관리자 확인 제목'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()['title'], '관리자 확인 제목')

    def test_anonymous_and_unverified_users_are_rejected(self):
        anonymous = APIClient()
        self.assertEqual(anonymous.get(TEMPLATES_URL).status_code, 401)
        self.assertEqual(
            anonymous.put(
                PREFERENCES_URL,
                {'source_key': 'closing-next-step', 'is_hidden': True},
                format='json',
            ).status_code,
            401,
        )

        _, unverified = _planner('talk-unverified@test.com', verified=False)
        self.assertEqual(unverified.get(TEMPLATES_URL).status_code, 403)
        self.assertEqual(
            unverified.put(
                PREFERENCES_URL,
                {'source_key': 'closing-next-step', 'is_hidden': True},
                format='json',
            ).status_code,
            403,
        )


class TalkTemplateCrudTests(TestCase):
    def setUp(self):
        self.user, self.client = _planner('talk-crud@test.com')

    def test_list_has_exact_shape_and_deterministic_order(self):
        model = _template_model()
        first_tie = model.objects.create(
            owner=self.user,
            **_payload(title='동순위 첫째', sort_order=10),
        )
        second_tie = model.objects.create(
            owner=self.user,
            **_payload(title='동순위 둘째', sort_order=10),
        )
        earliest = model.objects.create(
            owner=self.user,
            **_payload(title='맨 앞', sort_order=-1, is_active=False),
        )

        response = self.client.get(TEMPLATES_URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(set(response.json()), {'results', 'hidden_source_keys'})
        self.assertEqual(
            [item['id'] for item in response.json()['results']],
            [earliest.id, first_tie.id, second_tie.id],
        )
        self.assertFalse(response.json()['results'][0]['is_active'])

    def test_create_retrieve_update_and_xss_remain_plain_json_strings(self):
        script = '<script>alert("x")</script>'
        body = f'  {script}\n원문 공백을 유지합니다.  '
        created = self.client.post(
            TEMPLATES_URL,
            _payload(
                source_key='  closing-next-step  ',
                title=f'  {script}  ',
                body=body,
                category='  closing  ',
                channel='call',
            ),
            format='json',
        )
        self.assertEqual(created.status_code, 201, created.content)
        self.assertEqual(created.json()['source_key'], 'closing-next-step')
        self.assertEqual(created.json()['title'], script)
        self.assertEqual(created.json()['body'], body)
        self.assertEqual(created.json()['category'], 'closing')

        detail_url = f"{TEMPLATES_URL}{created.json()['id']}/"
        retrieved = self.client.get(detail_url)
        self.assertEqual(retrieved.status_code, 200)
        self.assertEqual(retrieved.json()['body'], body)

        updated = self.client.patch(
            detail_url,
            {'title': '  후속 제목  ', 'body': '\n바꾼 원문\n'},
            format='json',
        )
        self.assertEqual(updated.status_code, 200, updated.content)
        self.assertEqual(updated.json()['title'], '후속 제목')
        self.assertEqual(updated.json()['body'], '\n바꾼 원문\n')

    def test_soft_delete_is_idempotently_absent_from_api(self):
        created = self.client.post(TEMPLATES_URL, _payload(), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        detail_url = f"{TEMPLATES_URL}{created.json()['id']}/"

        deleted = self.client.delete(detail_url)

        self.assertEqual(deleted.status_code, 204)
        stored = _template_model().objects.get(pk=created.json()['id'])
        self.assertTrue(stored.is_deleted)
        self.assertEqual(self.client.get(detail_url).status_code, 404)
        self.assertEqual(self.client.delete(detail_url).status_code, 404)
        self.assertEqual(self.client.get(TEMPLATES_URL).json()['results'], [])

    def test_rejects_blank_and_over_limit_text(self):
        invalid_payloads = (
            _payload(title='   '),
            _payload(body='\n\t  '),
            _payload(category='   '),
            _payload(title='가' * 101),
            _payload(body='나' * 5001),
            _payload(category='다' * 41),
            _payload(source_key='s' * 81),
        )
        for payload in invalid_payloads:
            with self.subTest(field_values=payload):
                response = self.client.post(
                    TEMPLATES_URL,
                    payload,
                    format='json',
                )
                self.assertEqual(response.status_code, 400, response.content)

    def test_rejects_unsupported_channel_and_blank_body_update(self):
        invalid_channel = self.client.post(
            TEMPLATES_URL,
            _payload(channel='email'),
            format='json',
        )
        self.assertEqual(invalid_channel.status_code, 400)

        created = self.client.post(TEMPLATES_URL, _payload(), format='json')
        self.assertEqual(created.status_code, 201, created.content)
        invalid_update = self.client.patch(
            f"{TEMPLATES_URL}{created.json()['id']}/",
            {'body': '   '},
            format='json',
        )
        self.assertEqual(invalid_update.status_code, 400)


class TalkTemplatePreferenceTests(TestCase):
    def setUp(self):
        self.user, self.client = _planner('talk-pref@test.com')

    def test_put_hides_restores_and_is_idempotent(self):
        hidden = self.client.put(
            PREFERENCES_URL,
            {'source_key': '  closing-next-step  ', 'is_hidden': True},
            format='json',
        )
        self.assertEqual(hidden.status_code, 200, hidden.content)
        self.assertEqual(
            hidden.json(),
            {'source_key': 'closing-next-step', 'is_hidden': True},
        )
        self.assertEqual(
            self.client.get(TEMPLATES_URL).json()['hidden_source_keys'],
            ['closing-next-step'],
        )

        repeated = self.client.put(
            PREFERENCES_URL,
            {'source_key': 'closing-next-step', 'is_hidden': True},
            format='json',
        )
        self.assertEqual(repeated.status_code, 200, repeated.content)
        self.assertEqual(_preference_model().objects.count(), 1)

        restored = self.client.put(
            PREFERENCES_URL,
            {'source_key': 'closing-next-step', 'is_hidden': False},
            format='json',
        )
        self.assertEqual(restored.status_code, 200, restored.content)
        self.assertEqual(
            restored.json(),
            {'source_key': 'closing-next-step', 'is_hidden': False},
        )
        self.assertEqual(
            self.client.get(TEMPLATES_URL).json()['hidden_source_keys'],
            [],
        )
        self.assertEqual(_preference_model().objects.count(), 1)

    def test_preferences_are_owner_scoped(self):
        hidden = self.client.put(
            PREFERENCES_URL,
            {'source_key': 'closing-next-step', 'is_hidden': True},
            format='json',
        )
        self.assertEqual(hidden.status_code, 200, hidden.content)
        other_user, other_client = _planner('talk-pref-other@test.com')

        self.assertEqual(
            other_client.get(TEMPLATES_URL).json()['hidden_source_keys'],
            [],
        )
        own = other_client.put(
            PREFERENCES_URL,
            {'source_key': 'closing-next-step', 'is_hidden': False},
            format='json',
        )
        self.assertEqual(own.status_code, 200, own.content)
        preferences = _preference_model().objects.order_by('owner_id')
        self.assertEqual(preferences.count(), 2)
        self.assertEqual(
            set(preferences.values_list('owner_id', flat=True)),
            {self.user.pk, other_user.pk},
        )

    def test_preference_rejects_invalid_source_key_and_boolean(self):
        invalid_payloads = (
            {'source_key': '   ', 'is_hidden': True},
            {'source_key': 's' * 81, 'is_hidden': True},
            {'source_key': 'closing-next-step'},
            {'source_key': 'closing-next-step', 'is_hidden': 'yes'},
            [],
        )
        for payload in invalid_payloads:
            with self.subTest(payload=payload):
                response = self.client.put(
                    PREFERENCES_URL,
                    payload,
                    format='json',
                )
                self.assertEqual(response.status_code, 400, response.content)

    def test_database_rejects_duplicate_owner_source_rows(self):
        model = _preference_model()
        model.objects.create(
            owner=self.user,
            source_key='closing-next-step',
            is_hidden=True,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            model.objects.create(
                owner=self.user,
                source_key='closing-next-step',
                is_hidden=False,
            )
