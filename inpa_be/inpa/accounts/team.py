"""Single write path for linking an agent to a manager."""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Profile


class TeamSwitchConfirmationRequired(Exception):
    pass


@dataclass(frozen=True)
class TeamLinkResult:
    manager_id: int
    promoted_now: bool
    switched: bool


@transaction.atomic
def link_agent_to_manager(*, agent, manager, confirm_switch=False) -> TeamLinkResult:
    if agent.pk == manager.pk:
        raise ValueError('self_management')

    agent_profile = Profile.objects.select_for_update().get(user=agent)
    manager_profile = Profile.objects.select_for_update().get(user=manager)
    previous_manager_id = agent_profile.manager_id

    if previous_manager_id and previous_manager_id != manager.pk and not confirm_switch:
        raise TeamSwitchConfirmationRequired

    switched = bool(previous_manager_id and previous_manager_id != manager.pk)
    if agent_profile.manager_id != manager.pk:
        agent_profile.manager = manager
        agent_profile.save(update_fields=['manager'])

    from inpa.billing.credit import resolve_effective_plan
    needs_promotion_stamp = manager_profile.manager_promoted_at is None
    try:
        legacy_manager = resolve_effective_plan(manager).code == 'manager'
    except RuntimeError:
        legacy_manager = False
    promoted_now = needs_promotion_stamp and not legacy_manager
    if needs_promotion_stamp:
        manager_profile.manager_promoted_at = timezone.now()
        if legacy_manager:
            manager_profile.manager_promotion_seen_at = manager_profile.manager_promoted_at
        manager_profile.save(update_fields=[
            'manager_promoted_at', 'manager_promotion_seen_at',
        ])

    return TeamLinkResult(
        manager_id=manager.pk,
        promoted_now=promoted_now,
        switched=switched,
    )


def profile_has_manager_role(profile) -> bool:
    if profile.manager_promoted_at is not None:
        return True

    from inpa.billing.credit import resolve_effective_plan
    try:
        return resolve_effective_plan(profile.user).code == 'manager'
    except RuntimeError:
        return False
