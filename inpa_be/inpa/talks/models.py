from django.conf import settings
from django.db import models


class PersonalTalkTemplate(models.Model):
    CHANNEL_MESSAGE = 'message'
    CHANNEL_CALL = 'call'
    CHANNEL_CHOICES = (
        (CHANNEL_MESSAGE, '메시지'),
        (CHANNEL_CALL, '통화'),
    )

    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='personal_talk_templates',
        verbose_name='설계사(소유자)',
    )
    source_key = models.CharField(
        '기본 화법 출처 키',
        max_length=80,
        null=True,
        blank=True,
    )
    title = models.CharField('제목', max_length=100)
    body = models.TextField('본문', max_length=5000)
    category = models.CharField('분류', max_length=40)
    channel = models.CharField(
        '채널',
        max_length=20,
        choices=CHANNEL_CHOICES,
    )
    sort_order = models.IntegerField('정렬 순서', default=0)
    is_active = models.BooleanField('사용', default=True)
    is_deleted = models.BooleanField('삭제', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'talks_personal_template'
        ordering = ('sort_order', 'created_at', 'id')
        verbose_name = '개인 화법 템플릿'
        verbose_name_plural = '개인 화법 템플릿'

    def __str__(self):
        return f'{self.owner_id}:{self.title}'


class TalkTemplatePreference(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='talk_template_preferences',
        verbose_name='설계사(소유자)',
    )
    source_key = models.CharField('기본 화법 출처 키', max_length=80)
    is_hidden = models.BooleanField('숨김', default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'talks_template_preference'
        constraints = [
            models.UniqueConstraint(
                fields=('owner', 'source_key'),
                name='talk_pref_owner_source_uniq',
            ),
        ]
        verbose_name = '기본 화법 선호'
        verbose_name_plural = '기본 화법 선호'

    def __str__(self):
        return f'{self.owner_id}:{self.source_key}'
