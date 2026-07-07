# 가격 확정 마이그레이션 (2026-07-07, PM 재료 — spec B-2)
#
# 1) Plan.code choices에 'super' 추가 (DB 무영향 — makemigrations --check 정합용).
# 2) 데이터: 프로드의 기존 plus 행이 placeholder(29000)일 때만 price_krw=19900(VAT 별도)
#    + 설명 갱신. 관리자가 Django Admin에서 이미 다른 값으로 바꿨다면 건드리지 않는다(조건부).
#    reverse = no-op (가격 확정을 되돌릴 이유 없음 — 롤백 시에도 값 보존).
from django.db import migrations, models

PLUS_PRICE_PLACEHOLDER = 29000  # seed_billing이 2026-07-07 이전에 심던 미확정 값
PLUS_PRICE_FINAL = 19900        # VAT 별도
PLUS_DESCRIPTION = '월 19,900원 (VAT 별도). OCR 200/AI비교 100/AI분석 200/판촉 100 월 한도.'


def update_plus_placeholder_price(apps, schema_editor):
    """plus 행이 아직 placeholder(29000)일 때만 확정가로 전환. 그 외 값은 보존."""
    Plan = apps.get_model('billing', 'Plan')
    Plan.objects.filter(code='plus', price_krw=PLUS_PRICE_PLACEHOLDER).update(
        price_krw=PLUS_PRICE_FINAL,
        description=PLUS_DESCRIPTION,
    )


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0004_runtimeconfig'),
    ]

    operations = [
        migrations.AlterField(
            model_name='plan',
            name='code',
            field=models.CharField(
                choices=[('free', 'Free'), ('plus', 'Plus'), ('super', 'Super')],
                max_length=20,
                unique=True,
            ),
        ),
        migrations.RunPython(update_plus_placeholder_price, migrations.RunPython.noop),
    ]
