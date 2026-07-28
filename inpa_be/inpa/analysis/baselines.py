"""Planner baseline money normalization and exact-scope selection."""
from decimal import Decimal

from inpa.customers.models import PlannerBaseline

__all__ = [
    'baseline_candidates_for_detail',
    'grading_eligible_baselines',
    'is_grading_eligible_baseline',
    'normalize_money',
    'select_baseline',
]


def baseline_candidates_for_detail(
        candidates, *, analysis_detail_id, coverage_key):
    linked = [
        row
        for row in candidates
        if row.analysis_detail_id == analysis_detail_id
    ]
    if linked:
        return linked
    return [
        row
        for row in candidates
        if (
            row.analysis_detail_id is None
            and row.coverage_key == coverage_key
        )
    ]


def normalize_money(value, unit):
    if value is None or unit == PlannerBaseline.UNIT_ACCOUNT:
        return None
    amount = Decimal(value)
    if unit == PlannerBaseline.UNIT_TEN_THOUSAND_WON:
        return amount * Decimal('10000')
    if unit == PlannerBaseline.UNIT_WON:
        return amount
    return None


def is_grading_eligible_baseline(row):
    return bool(
        getattr(row, 'is_active', True)
        and getattr(row, 'baseline_source', None)
        == PlannerBaseline.SOURCE_PLANNER
    )


def grading_eligible_baselines(candidates):
    return [
        row for row in candidates
        if is_grading_eligible_baseline(row)
    ]


def select_baseline(candidates, *, insurance_type, age_band, gender):
    product_group = (
        insurance_type
        if insurance_type in dict(PlannerBaseline.PRODUCT_GROUP_CHOICES)
        else None
    )
    if product_group is None or age_band is None:
        return None

    allowed_products = {product_group, PlannerBaseline.PRODUCT_GROUP_ALL}
    allowed_ages = {age_band, PlannerBaseline.AGE_ALL}
    ranked = []
    for row in candidates:
        if not is_grading_eligible_baseline(row):
            continue
        if row.product_group not in allowed_products:
            continue
        if row.age_band not in allowed_ages:
            continue
        if row.gender not in {gender, None}:
            continue
        rank = (
            0 if row.product_group == product_group else 1,
            0 if row.age_band == age_band else 1,
            0 if row.gender == gender else 1,
        )
        ranked.append((rank, row))

    if not ranked:
        return None
    best_rank = min(rank for rank, _row in ranked)
    best = [row for rank, row in ranked if rank == best_rank]
    return best[0] if len(best) == 1 else None
