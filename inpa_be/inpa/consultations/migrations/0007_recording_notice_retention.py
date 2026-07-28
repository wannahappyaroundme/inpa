from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('consultations', '0006_consultationruntimeconfig_cost_limits'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultationrecording',
            name='notice_attested_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='notice_text_hash',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='notice_version',
            field=models.CharField(blank=True, default='', max_length=40),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='retention_days_snapshot',
            field=models.PositiveSmallIntegerField(default=7),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='retention_hours_snapshot',
            field=models.PositiveSmallIntegerField(default=168),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='retention_policy_version',
            field=models.CharField(default='v1-7d', max_length=40),
        ),
        migrations.AddField(
            model_name='consultationrecording',
            name='verified_container',
            field=models.CharField(blank=True, default='', max_length=16),
        ),
        migrations.AddConstraint(
            model_name='consultationrecording',
            constraint=models.CheckConstraint(
                condition=(
                    ~models.Q(retention_policy_version='v2-30d')
                    | (
                        models.Q(
                            notice_version=(
                                'consultation-notice-v2-2026-07-28'
                            ),
                        )
                        & models.Q(notice_attested_at__isnull=False)
                        & models.Q(
                            notice_text_hash=(
                                'f316dff62e8c9628babccbcfb8d2ae1ddfc9a1572e72f58a'
                                'c087d83fc45ec432'
                            ),
                        )
                        & models.Q(retention_hours_snapshot=720)
                        & models.Q(retention_days_snapshot=30)
                    )
                ),
                name='v2_recording_notice_evidence_required',
            ),
        ),
    ]
