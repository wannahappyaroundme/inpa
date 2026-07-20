from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('insurances', '0008_manual_review_provenance'),
    ]

    operations = [
        migrations.AlterField(
            model_name='customerinsurancedetail',
            name='payment_period_type',
            field=models.SmallIntegerField(
                choices=[
                    (1, '년'),
                    (2, '세'),
                    (3, '년 갱신'),
                    (4, '종신'),
                ],
                default=1,
                verbose_name='납입기간 타입',
            ),
        ),
    ]
