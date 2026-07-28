from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


IDENTICAL_VALUE_FIELDS = (
    'recommend_min',
    'recommend_max',
    'unit',
    'baseline_source',
    'preset_origin',
    'is_active',
)


def _value_signature(row):
    return tuple(getattr(row, field) for field in IDENTICAL_VALUE_FIELDS)


def backfill_baseline_details(apps, schema_editor):
    AnalysisDetail = apps.get_model('analysis', 'AnalysisDetail')
    PlannerBaseline = apps.get_model('customers', 'PlannerBaseline')

    detail_ids_by_name = {}
    standard_details = AnalysisDetail.objects.filter(
        sub_category__category__name__startswith='[표준]',
    )
    for detail_id, name in standard_details.values_list('id', 'name'):
        detail_ids_by_name.setdefault(name, []).append(detail_id)

    groups = {}
    for row in PlannerBaseline.objects.filter(
            analysis_detail__isnull=True).order_by('created_at', 'id'):
        detail_ids = detail_ids_by_name.get(row.coverage_key, ())
        if len(detail_ids) != 1:
            continue
        detail_id = detail_ids[0]
        key = (
            row.owner_id,
            detail_id,
            row.product_group,
            row.age_band,
            row.gender,
        )
        groups.setdefault(key, []).append(row)

    duplicate_ids = []
    rows_to_link = []
    for key, rows in groups.items():
        if len(rows) > 1:
            signatures = {_value_signature(row) for row in rows}
            if key[-1] is not None or len(signatures) != 1:
                ids = ','.join(str(row.pk) for row in rows)
                raise RuntimeError(
                    'Conflicting PlannerBaseline duplicates require manual '
                    f'review before migration: {ids}'
                )
            duplicate_ids.extend(row.pk for row in rows[1:])
        keeper = rows[0]
        keeper.analysis_detail_id = key[1]
        rows_to_link.append(keeper)

    if duplicate_ids:
        PlannerBaseline.objects.filter(pk__in=duplicate_ids).delete()
    if rows_to_link:
        PlannerBaseline.objects.bulk_update(
            rows_to_link, ['analysis_detail'])


class Migration(migrations.Migration):

    dependencies = [
        ('analysis', '0003_coverageflag'),
        ('customers', '0022_alter_consentlog_scope'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='plannerbaseline',
            name='analysis_detail',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name='planner_baselines',
                to='analysis.analysisdetail',
            ),
        ),
        migrations.CreateModel(
            name='PlannerBaselineRevision',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                (
                    'revision',
                    models.PositiveBigIntegerField(default=0),
                ),
                (
                    'updated_at',
                    models.DateTimeField(auto_now=True),
                ),
                (
                    'owner',
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name='planner_baseline_revision',
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                'verbose_name': '설계사 기준표 변경 번호',
                'verbose_name_plural': '설계사 기준표 변경 번호',
                'db_table': 'planner_baseline_revision',
            },
        ),
        migrations.RunPython(
            backfill_baseline_details,
            migrations.RunPython.noop,
        ),
        migrations.RemoveConstraint(
            model_name='plannerbaseline',
            name='uniq_baseline_scope',
        ),
        migrations.AddConstraint(
            model_name='plannerbaseline',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    gender__isnull=True,
                    analysis_detail__isnull=False,
                ),
                fields=(
                    'owner',
                    'analysis_detail',
                    'product_group',
                    'age_band',
                ),
                name='uniq_baseline_common_gender',
            ),
        ),
        migrations.AddConstraint(
            model_name='plannerbaseline',
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    gender__isnull=False,
                    analysis_detail__isnull=False,
                ),
                fields=(
                    'owner',
                    'analysis_detail',
                    'product_group',
                    'age_band',
                    'gender',
                ),
                name='uniq_baseline_specific_gender',
            ),
        ),
        migrations.AlterField(
            model_name='plannerbaseline',
            name='product_group',
            field=models.SmallIntegerField(
                choices=[
                    (0, '전체 상품'),
                    (1, '생명'),
                    (2, '손해'),
                    (3, '실손'),
                    (4, '연금저축'),
                ],
                verbose_name='상품군',
            ),
        ),
    ]
