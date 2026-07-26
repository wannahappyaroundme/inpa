from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('consultations', '0005_consultationsummaryrun_consultationcustomerbenefit_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='consultationruntimeconfig',
            name='daily_ai_cost_limit_krw',
            field=models.PositiveIntegerField(default=50000),
        ),
        migrations.AddField(
            model_name='consultationruntimeconfig',
            name='monthly_ai_cost_limit_krw',
            field=models.PositiveIntegerField(default=500000),
        ),
    ]
