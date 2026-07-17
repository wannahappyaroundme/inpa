from django.db import migrations, models
from django.db.models import Exists, F, OuterRef, Q


def converge_confirmed_lineages(apps, schema_editor):
    Job = apps.get_model('insurances', 'InsuranceExtractionJob')
    CustomerInsurance = apps.get_model('insurances', 'CustomerInsurance')
    seen = set()
    valid_analysis_link = CustomerInsurance.objects.filter(
        source_job_id=OuterRef('pk'),
        review_status='confirmed',
        analysis_included=True,
    )
    jobs = Job.objects.filter(status='confirmed').annotate(
        _has_valid_analysis_link=Exists(valid_analysis_link),
    ).order_by(
        'owner_id', 'customer_id', 'file_sha256', 'portfolio_type',
        '-_has_valid_analysis_link',
        F('confirmed_at').desc(nulls_last=True),
        F('created_at').desc(nulls_last=True),
        '-pk',
    )
    for job in jobs.iterator():
        lineage = (
            job.owner_id,
            job.customer_id,
            job.file_sha256,
            job.portfolio_type,
        )
        if lineage not in seen:
            seen.add(lineage)
            continue
        Job.objects.filter(pk=job.pk, status='confirmed').update(
            status='superseded')
        CustomerInsurance.objects.filter(
            source_job_id=job.pk,
        ).update(
            review_status='superseded',
            analysis_included=False,
            data_version=F('data_version') + 1,
        )


class Migration(migrations.Migration):

    dependencies = [
        ('insurances', '0012_manualinsurancecommand'),
    ]

    operations = [
        migrations.RunPython(
            converge_confirmed_lineages,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name='insuranceextractionjob',
            constraint=models.UniqueConstraint(
                fields=(
                    'owner', 'customer', 'file_sha256', 'portfolio_type'),
                condition=Q(status='confirmed'),
                name='uniq_confirmed_ins_import_hash',
            ),
        ),
    ]
