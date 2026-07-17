from django.db import migrations, models
from django.db.models import Count, Q


def prepare_legacy_snapshots(apps, schema_editor):
    ShareSnapshot = apps.get_model('analytics', 'ShareSnapshot')
    duplicates = (
        ShareSnapshot.objects.exclude(share_token__isnull=True)
        .values('share_token')
        .annotate(row_count=Count('id'))
        .filter(row_count__gt=1)
    )
    for duplicate in duplicates.iterator():
        rows = ShareSnapshot.objects.filter(
            share_token=duplicate['share_token']).order_by('-captured_at', '-pk')
        keep_id = rows.values_list('pk', flat=True).first()
        rows.exclude(pk=keep_id).update(share_token=None)


class Migration(migrations.Migration):

    dependencies = [
        ('analytics', '0003_alter_northstarevent_event_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='sharesnapshot',
            name='payload_version',
            field=models.CharField(
                default='v1-legacy-actions', max_length=40,
                verbose_name='공유 본문 버전'),
        ),
        migrations.AddField(
            model_name='sharesnapshot',
            name='link_expires_at',
            field=models.DateTimeField(
                blank=True, db_index=True, null=True,
                verbose_name='공개 링크 만료일'),
        ),
        migrations.AddField(
            model_name='sharesnapshot',
            name='revoked_at',
            field=models.DateTimeField(
                blank=True, null=True, verbose_name='공개 링크 회수 시각'),
        ),
        migrations.AddField(
            model_name='sharesnapshot',
            name='revoked_reason',
            field=models.CharField(
                blank=True, default='', max_length=40,
                verbose_name='공개 링크 회수 사유'),
        ),
        migrations.AddField(
            model_name='sharesnapshot',
            name='first_viewed_at',
            field=models.DateTimeField(
                blank=True, null=True, verbose_name='첫 열람 시각'),
        ),
        migrations.RunPython(
            prepare_legacy_snapshots, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='sharesnapshot',
            constraint=models.UniqueConstraint(
                condition=Q(share_token__isnull=False),
                fields=('share_token',),
                name='uniq_share_snapshot_nonnull_token'),
        ),
    ]
