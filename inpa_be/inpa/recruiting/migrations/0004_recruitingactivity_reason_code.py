from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("recruiting", "0003_reopen_event_choices"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="recruitingconsentlog",
            name="ip_address",
        ),
        migrations.AddField(
            model_name="recruitingactivity",
            name="reason_code",
            field=models.CharField(
                blank=True,
                choices=[
                    ("user_request", "지원자 요청"),
                    ("retention", "보관 기간 만료"),
                    ("admin_correction", "운영 정보 바로잡기"),
                ],
                max_length=30,
            ),
        ),
    ]
