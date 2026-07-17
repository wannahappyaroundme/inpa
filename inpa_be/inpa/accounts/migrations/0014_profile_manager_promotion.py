from django.db import migrations, models
from django.db.models import Q
from django.utils import timezone


def backfill_manager_promotion(apps, schema_editor):
    Profile = apps.get_model('accounts', 'Profile')
    User = apps.get_model('accounts', 'User')
    Subscription = apps.get_model('billing', 'Subscription')

    manager_ids = (
        Profile.objects
        .exclude(manager_id=None)
        .values_list('manager_id', flat=True)
        .distinct()
    )
    for manager_id in manager_ids:
        agent_user_ids = Profile.objects.filter(
            manager_id=manager_id
        ).values_list('user_id', flat=True)
        promoted_at = (
            User.objects
            .filter(pk__in=agent_user_ids)
            .order_by('date_joined')
            .values_list('date_joined', flat=True)
            .first()
        )
        if promoted_at is not None:
            Profile.objects.filter(user_id=manager_id).update(
                manager_promoted_at=promoted_at,
                manager_promotion_seen_at=promoted_at,
            )

    valid_manager_subscriptions = (
        Subscription.objects
        .filter(plan__code='manager', status__in=['active', 'trial'])
        .filter(Q(expires_at__isnull=True) | Q(expires_at__gt=timezone.now()))
    )
    for subscription in valid_manager_subscriptions.iterator():
        Profile.objects.filter(
            user_id=subscription.user_id,
            manager_promoted_at__isnull=True,
        ).update(
            manager_promoted_at=subscription.started_at,
            manager_promotion_seen_at=subscription.started_at,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0013_profile_utm_campaign_profile_utm_medium_and_more'),
        ('billing', '0010_plan_price_annual_krw_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='manager_promoted_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='profile',
            name='manager_promotion_seen_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_manager_promotion, migrations.RunPython.noop),
    ]
