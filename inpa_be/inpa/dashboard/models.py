"""대시보드 월별 목표 — 소유자 전용. 목표만 저장, 실적은 계산(aggregation.py).

billing.UsageMeter의 (user, year_month) 월별 패턴을 미러. 추후 실적/수입 연동 시
aggregation.compute_actuals만 교체하면 됨(목표 저장은 불변).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class MonthlyGoal(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='monthly_goals', verbose_name='설계사(소유자)')
    year_month = models.CharField('연월(YYYY-MM)', max_length=7)
    target_meetings = models.PositiveIntegerField('만날 고객 수 목표', default=0)
    target_premium = models.PositiveBigIntegerField('월 가입 보험료 목표', default=0)
    target_income = models.PositiveBigIntegerField('예상 월급(수동)', default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'monthly_goal'
        verbose_name = '월별 목표'
        verbose_name_plural = '월별 목표'
        unique_together = ('owner', 'year_month')
        indexes = [models.Index(fields=['owner', 'year_month'])]

    @classmethod
    def current_month(cls):
        return timezone.now().strftime('%Y-%m')

    def __str__(self):
        return f'{self.owner_id}/{self.year_month}'
