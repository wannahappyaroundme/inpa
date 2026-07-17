"""Single write path for linking an agent to a manager."""
import logging
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .models import Profile


logger = logging.getLogger(__name__)


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

    locked_profiles = list(
        Profile.objects
        .select_for_update()
        .filter(user_id__in=[agent.pk, manager.pk])
        .order_by('user_id')
    )
    if len(locked_profiles) != 2:
        raise Profile.DoesNotExist
    profiles_by_user_id = {profile.user_id: profile for profile in locked_profiles}
    agent_profile = profiles_by_user_id[agent.pk]
    manager_profile = profiles_by_user_id[manager.pk]
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

    if promoted_now:
        manager_id = manager.pk

        def create_manager_promotion_notification():
            try:
                from inpa.recruiting.jobs import create_recruiting_notification_once

                create_recruiting_notification_once(
                    owner_id=manager_id,
                    notif_type='manager_promoted',
                    title='관리자 기능이 열렸어요',
                    body='첫 팀원이 합류해 팀 관리 흐름을 시작할 수 있어요.',
                    dedupe_key=f'manager-promoted:{manager_id}',
                )
            except Exception as exc:  # 알림 실패는 팀 연결과 역할 활성화를 되돌리지 않는다.
                logger.warning(
                    'team callback failed callback=manager_promotion_notification exception=%s',
                    type(exc).__name__,
                )

        transaction.on_commit(create_manager_promotion_notification)

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
