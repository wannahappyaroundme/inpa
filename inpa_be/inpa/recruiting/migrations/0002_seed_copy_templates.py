from django.db import migrations


DEFAULTS = (
    (
        "headline-long-growth",
        "headline",
        "함께 오래 성장하기",
        "함께 오래 일할 동료를 찾고 있어요.",
        10,
    ),
    (
        "support-first-week",
        "support",
        "첫 주 동행",
        "첫 주에는 고객 만남과 업무 흐름을 함께 정리해요.",
        10,
    ),
    (
        "support-field",
        "support",
        "현장 지원",
        "혼자 막히는 순간이 없도록 필요한 자리에서 같이 움직여요.",
        20,
    ),
    (
        "support-growth",
        "support",
        "13주 성장 점검",
        "1·4·8·13주에 활동 흐름을 확인하고 다음 목표를 같이 정해요.",
        30,
    ),
    (
        "faq-contract",
        "faq",
        "위촉 전에도 이야기할 수 있나요?",
        "현재 소속과 일정에 맞춰 부담 없이 먼저 대화할 수 있어요.",
        10,
    ),
    (
        "faq-data",
        "faq",
        "남긴 정보는 어디에 쓰이나요?",
        "영입 상담 연락과 일정 조율에만 사용해요.",
        20,
    ),
    (
        "share-known",
        "share",
        "아는 설계사에게",
        "지금보다 오래 성장할 수 있는 환경을 함께 이야기해보고 싶어 링크를 보냅니다.",
        10,
    ),
)


def seed_copy_templates(apps, schema_editor):
    copy_template = apps.get_model("recruiting", "RecruitingCopyTemplate")
    for code, kind, title, body, sort_order in DEFAULTS:
        copy_template.objects.get_or_create(
            code=code,
            defaults={
                "kind": kind,
                "title": title,
                "body": body,
                "sort_order": sort_order,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("recruiting", "0001_initial")]

    operations = [
        migrations.RunPython(seed_copy_templates, migrations.RunPython.noop),
    ]
