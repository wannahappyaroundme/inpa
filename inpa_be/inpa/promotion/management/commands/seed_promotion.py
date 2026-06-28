"""판촉물 골격 샘플 적재(멱등) — seed_promotion.

명함(가로/세로)·달력(탁상/벽걸이)·리플렛·팜플렛·파일보관함의 '틀'을 만든다.
디자인 시안 이미지는 inpa_fe/public/promo/ 에 규칙대로 투입(README 참조) → image_url 이
상대경로 /promo/<파일명> 라 FE 가 같은 오리진에서 서빙. 파일 투입 전까지는 404 →
FE 가 '이미지 없음' 폴백을 보여준다(깨진 이미지 안 보임).

멱등: name 기준 update_or_create. 재실행/재배포해도 중복 없이 메타만 갱신.
운영팀은 Django admin 에서 설명·폼필드·is_available 을 다듬고, 시안 이미지를 추가하면 된다.
"""
from django.core.management.base import BaseCommand

from inpa.promotion.models import PromotionSample, PromotionSampleImage

_QTY = {'key': 'quantity', 'label': '수량', 'type': 'number', 'required': True, 'min': 50, 'step': 50}
_PRINT = {'key': 'print_text', 'label': '인쇄 정보(이름·연락처·소속)', 'type': 'textarea',
          'required': True, 'placeholder': '예: 홍길동 설계사 · 010-1234-5678 · 인파손해보험'}
_ADDR = {'key': 'delivery_address', 'label': '배송지', 'type': 'textarea', 'required': True}

# 골격 샘플 — image 는 inpa_fe/public/promo/ 투입 파일과 1:1(README 명명규칙).
SAMPLES = [
    {
        'name': '가로형 명함', 'category': PromotionSample.CATEGORY_BUSINESS_CARD, 'sort_order': 1,
        'description': '가로형 명함. 무광/유광 코팅 선택, 양면 인쇄 가능. 납기 3~5일. (재질·사이즈 운영팀 확정)',
        'image': '/promo/card-h-1.png',
        'form_fields': [_QTY, _PRINT,
                        {'key': 'coating', 'label': '코팅', 'type': 'radio', 'required': False,
                         'options': ['무광', '유광']}],
    },
    {
        'name': '세로형 명함', 'category': PromotionSample.CATEGORY_BUSINESS_CARD, 'sort_order': 2,
        'description': '세로형 명함. 무광/유광 코팅 선택, 양면 인쇄 가능. 납기 3~5일.',
        'image': '/promo/card-v-1.png',
        'form_fields': [_QTY, _PRINT,
                        {'key': 'coating', 'label': '코팅', 'type': 'radio', 'required': False,
                         'options': ['무광', '유광']}],
    },
    {
        'name': '탁상용 달력', 'category': PromotionSample.CATEGORY_CALENDAR, 'sort_order': 3,
        'description': '탁상용 달력. 표지에 설계사 이름·연락처 인쇄. 납기 2~3주.',
        'image': '/promo/calendar-desk-1.png',
        'form_fields': [_QTY, _PRINT,
                        {'key': 'cover_color', 'label': '표지 색상', 'type': 'radio', 'required': False,
                         'options': ['베이지', '네이비', '그린']}],
    },
    {
        'name': '벽걸이용 달력', 'category': PromotionSample.CATEGORY_CALENDAR, 'sort_order': 4,
        'description': '벽걸이용 달력. 하단에 설계사 정보 인쇄. 납기 2~3주.',
        'image': '/promo/calendar-wall-1.png',
        'form_fields': [_QTY, _PRINT],
    },
    {
        'name': '리플렛', 'category': PromotionSample.CATEGORY_LEAFLET, 'sort_order': 5,
        'description': '보장 안내 리플렛(낱장 접지). 상담 시 배포용. 납기 1~2주.',
        'image': '/promo/leaflet-1.png',
        'form_fields': [_QTY,
                        {'key': 'fold', 'label': '접지', 'type': 'radio', 'required': False,
                         'options': ['2단', '3단']}, _PRINT],
    },
    {
        'name': '팜플렛', 'category': PromotionSample.CATEGORY_PAMPHLET, 'sort_order': 6,
        'description': '상품 안내 팜플렛(여러 페이지). 설명회·상담용. 납기 2~3주.',
        'image': '/promo/pamphlet-1.png',
        'form_fields': [_QTY,
                        {'key': 'pages', 'label': '페이지 수', 'type': 'select', 'required': False,
                         'options': ['8p', '12p', '16p']}, _PRINT],
    },
    {
        'name': '파일보관함', 'category': PromotionSample.CATEGORY_FILE_HOLDER, 'sort_order': 7,
        'description': '증권·서류 보관용 파일보관함(고객 증정용). 로고 인쇄 가능. 납기 3~4주.',
        'image': '/promo/file-holder-1.png',
        'form_fields': [_QTY,
                        {'key': 'logo', 'label': '로고 인쇄', 'type': 'radio', 'required': False,
                         'options': ['있음', '없음']}, _ADDR],
    },
]


class Command(BaseCommand):
    help = '판촉물 골격 샘플 적재(멱등). 디자인 시안은 inpa_fe/public/promo/ 에 투입(README 명명규칙).'

    def handle(self, *args, **options):
        created = updated = 0
        for raw in SAMPLES:
            spec = dict(raw)
            image = spec.pop('image')
            sample, was_created = PromotionSample.objects.update_or_create(
                name=spec['name'],
                defaults={k: v for k, v in spec.items() if k != 'name'},
            )
            # 대표 이미지 1개 보장(멱등) — 시안 미투입이면 404 → FE '이미지 없음' 폴백.
            primary = sample.images.filter(is_primary=True).order_by('sort_order').first()
            if primary is None:
                PromotionSampleImage.objects.create(
                    sample=sample, image_url=image, is_primary=True, sort_order=0)
            elif primary.image_url != image:
                primary.image_url = image
                primary.save(update_fields=['image_url'])
            created += 1 if was_created else 0
            updated += 0 if was_created else 1
        self.stdout.write(self.style.SUCCESS(
            f'[seed_promotion] 골격 샘플 생성 {created} · 갱신 {updated} (총 {len(SAMPLES)}). '
            f'시안은 inpa_fe/public/promo/ 에 투입하세요.'))
