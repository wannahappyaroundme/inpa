from django.contrib import admin

from .models import MonthlyGoal


@admin.register(MonthlyGoal)
class MonthlyGoalAdmin(admin.ModelAdmin):
    list_display = ('id', 'owner', 'year_month', 'target_meetings', 'target_premium', 'income_multiplier')
    list_filter = ('year_month',)
    raw_id_fields = ('owner',)
