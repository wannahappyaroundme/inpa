"""Planner baseline money normalization and exact-scope selection."""
from decimal import Decimal

from inpa.customers.models import PlannerBaseline

__all__ = ['normalize_money', 'select_baseline']


def normalize_money(value, unit):
    if value is None or unit == PlannerBaseline.UNIT_ACCOUNT:
        return None
    amount = Decimal(value)
    if unit == PlannerBaseline.UNIT_TEN_THOUSAND_WON:
        return amount * Decimal('10000')
    if unit == PlannerBaseline.UNIT_WON:
        return amount
    return None


def select_baseline(candidates, *, insurance_type, age_band, gender):
    product_group = {
        1: PlannerBaseline.PRODUCT_GROUP_LIFE,
        2: PlannerBaseline.PRODUCT_GROUP_NONLIFE,
    }.get(insurance_type)
    if product_group is None or age_band is None:
        return None
    scoped = [row for row in candidates
              if row.product_group == product_group and row.age_band == age_band]
    exact = [row for row in scoped if row.gender == gender]
    common = [row for row in scoped if row.gender is None]
    chosen = exact or common
    return chosen[0] if len(chosen) == 1 else None
