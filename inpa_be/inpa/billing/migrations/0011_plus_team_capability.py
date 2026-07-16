from django.db import migrations


def enable_plus_and_super_team_capability(apps, schema_editor):
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(code__in=('plus', 'super')).update(can_use_team=True)


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0010_plan_price_annual_krw_and_more'),
    ]

    operations = [
        migrations.RunPython(
            enable_plus_and_super_team_capability,
            migrations.RunPython.noop,
        ),
    ]
