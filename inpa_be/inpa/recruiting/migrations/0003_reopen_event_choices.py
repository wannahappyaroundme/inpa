from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("recruiting", "0002_seed_copy_templates")]

    operations = [
        migrations.AlterField(
            model_name="recruitingactivity",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("stage_changed", "단계 변경"),
                    ("contact_stopped", "연락 중단"),
                    ("leader_changed", "담당 변경"),
                    ("team_joined", "팀 합류"),
                    ("settlement_completed", "정착 확인"),
                    ("settlement_reopened", "정착 일정 재개"),
                    ("candidate_purged", "정보 정리"),
                ],
                max_length=30,
            ),
        ),
        migrations.AlterField(
            model_name="recruitingevent",
            name="event_type",
            field=models.CharField(
                choices=[
                    ("page_published", "페이지 공개"),
                    ("link_copied", "링크 복사"),
                    ("page_view", "페이지 방문"),
                    ("application_submitted", "지원 제출"),
                    ("first_contact", "첫 연락"),
                    ("conversation_started", "대화 시작"),
                    ("preparing_started", "위촉 준비 시작"),
                    ("team_join", "팀 합류"),
                    ("settlement_completed", "정착 확인"),
                    ("settlement_reopened", "정착 일정 재개"),
                    ("manager_promoted", "관리자 성장"),
                ],
                db_index=True,
                max_length=40,
            ),
        ),
    ]
