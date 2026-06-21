from rest_framework import serializers

from .models import MonthlyGoal


class MonthlyGoalSerializer(serializers.ModelSerializer):
    """목표 갱신용. year_month는 URL/현재월로 결정(read-only). 음수는 명시 min_value=0으로 400."""
    target_meetings = serializers.IntegerField(min_value=0, required=False)
    target_premium = serializers.IntegerField(min_value=0, required=False)
    income_multiplier = serializers.DecimalField(
        max_digits=5, decimal_places=1, min_value=0, required=False, coerce_to_string=False)

    class Meta:
        model = MonthlyGoal
        fields = ('year_month', 'target_meetings', 'target_premium', 'income_multiplier', 'updated_at')
        read_only_fields = ('year_month', 'updated_at')
