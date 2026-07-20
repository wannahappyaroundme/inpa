"""실서비스용 공지·FAQ 시드(멱등) — seed_boards.

운영에서 바로 보이는 공지사항/자주 묻는 질문을 채운다. 데모([DEMO]) 아님.
멱등: title/question 기준 get_or_create → 최초 1회만 생성, 이후 Django admin 편집은 보존
(재배포해도 덮어쓰지 않음). 공식 기본 문구 변경은 이전 기본값과 정확히 같은 행만 갱신한다.
작성자는 관리자 계정을 자동으로 잡는다(없으면 안전하게 건너뜀).

★ 카피 레드라인: 쉬운 말, 긍정 어투, em-dash(—) 금지, 출시일/로드맵 비공개.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from inpa.accounts.models import User
from inpa.boards.models import Faq, Notice

LEGACY_WELCOME_NOTICE_BODY = (
    '안녕하세요, 인파(Inpa)입니다.\n\n'
    '설계사님의 하루가 조금 더 가벼워지도록, 고객 발굴부터 증권 정리, 담보 한눈표, '
    '비교 분석, 상담 예약까지 한 흐름으로 담았습니다.\n\n'
    '지금 무료로 이용하실 수 있어요. 써 보시다가 불편한 점이나 바라는 기능이 있으면 '
    '1:1 문의로 편하게 남겨 주세요. 하나씩 반영해 나가겠습니다.\n\n'
    '앞으로도 꾸준히 기능을 더하고 다듬겠습니다. 감사합니다.'
)
WELCOME_NOTICE_BODY = (
    '안녕하세요, 인파(Inpa)입니다.\n\n'
    '설계사님의 하루가 조금 더 가벼워지도록, 고객 발굴부터 증권 정리, 담보 한눈표, '
    '여러 증권 비교, 상담 예약까지 한 흐름으로 담았습니다.\n\n'
    '지금 무료로 이용하실 수 있어요. 써 보시다가 불편한 점이나 바라는 기능이 있으면 '
    '1:1 문의로 편하게 남겨 주세요. 하나씩 반영해 나가겠습니다.\n\n'
    '앞으로도 꾸준히 기능을 더하고 다듬겠습니다. 감사합니다.'
)

LEGACY_COMPARE_FAQ_QUESTION = '비교 분석표는 무엇인가요?'
LEGACY_COMPARE_FAQ_ANSWER = (
    '지금 보장과 제안 보장을 나란히 놓고 추가·삭제·변경을 정리해 주는 표예요. '
    '산출물은 AI가 정리한 참고 자료이며, 보장 판단과 고객 안내는 설계사님의 업무입니다.'
)
COMPARE_FAQ_QUESTION = '여러 증권 비교는 무엇인가요?'
COMPARE_FAQ_ANSWER = (
    '선택한 증권을 증권 A와 증권 B 묶음으로 나눠, 담보·보장금액·보험료 차이를 '
    '같은 기준의 표와 그래프로 확인하는 기능이에요. '
    '인파가 등록된 보장 정보를 정리한 참고 자료입니다.'
)

NOTICES = [
    {
        'title': '인파를 시작합니다',
        'is_pinned': True,
        'body': WELCOME_NOTICE_BODY,
    },
    {
        'title': '새 기능: 고객 여러 명 한 번에 등록',
        'is_pinned': False,
        'body': (
            '연락처에 저장된 고객을 한 분씩 넣기 번거로우셨죠?\n\n'
            '이제 이름과 연락처를 붙여넣으면 여러 명을 한 번에 등록할 수 있어요. '
            '표에서 성별, 생년월일, 직업급수, 유입 경로, 메모까지 바로 채울 수 있습니다.\n\n'
            "고객 화면의 '여러 명 등록'에서 사용해 보세요."
        ),
    },
    {
        'title': '새 기능: 상담 예약 링크로 고객이 직접 시간 잡기',
        'is_pinned': False,
        'body': (
            '상담 가능한 요일과 시간을 정해 두면, 고객이 링크에서 빈 시간을 골라 예약할 수 있어요.\n\n'
            '설계사님은 요청을 받고 수락만 하면 일정에 확정됩니다. '
            "'일정' 화면의 '예약 가용시간 관리'에서 시작하세요."
        ),
    },
    {
        'title': '이용 가이드: 증권 스캔으로 보장 한눈에 보기',
        'is_pinned': False,
        'body': (
            '고객의 증권 PDF를 올리면 보유한 보장을 표준 담보로 자동 정리해 드려요.\n\n'
            '정리된 내용은 담보 한눈표에서 한 화면으로 볼 수 있습니다. '
            '내 기준(보장 기준)을 정해 두면 넉넉·적정·부족을 색으로 바로 구분할 수 있어요.\n\n'
            "기준은 '설정 > 보장 기준'에서 정할 수 있습니다."
        ),
    },
    {
        'title': '새 기능: 고객 영업과 설계사 영업을 따로 관리',
        'is_pinned': False,
        'body': (
            "메뉴의 '영업'에서 보험 가입 고객과 함께할 설계사를 분리해 관리할 수 있어요.\n\n"
            "'고객 영업'은 연락, 상담 준비, 다음 약속을 한 흐름으로 모았습니다. "
            "'설계사 영업'은 지원자 연락부터 팀 합류 뒤 1·4·8·13주 정착 확인까지 이어집니다.\n\n"
            '첫 설계사가 팀에 합류하면 같은 Plus 이용 범위에서 Manager 역할이 자동으로 열립니다.'
        ),
    },
]

FAQS = [
    {
        'category': '기능문의', 'order': 1,
        'question': '증권을 올리면 무엇이 정리되나요?',
        'answer': (
            '고객의 증권 PDF를 올리면 보유한 보장을 표준 담보 체계로 자동 정리해 드려요. '
            '정리된 내용은 담보 한눈표에서 한 화면으로 확인할 수 있습니다.'
        ),
    },
    {
        'category': '기능문의', 'order': 2,
        'question': '담보 한눈표의 넉넉·적정·부족은 어떻게 보나요?',
        'answer': (
            "먼저 '설정 > 보장 기준'에서 내 기준을 정해 주세요. 기준을 정하면 담보별로 "
            '넉넉·적정·부족을 색으로 바로 볼 수 있어요. 기준을 정하기 전에는 보유한 금액만 '
            '담백하게 보여드립니다.'
        ),
    },
    {
        'category': '기능문의', 'order': 3,
        'question': COMPARE_FAQ_QUESTION,
        'answer': COMPARE_FAQ_ANSWER,
    },
    {
        'category': '기능문의', 'order': 4,
        'question': '고객에게 상담 예약 링크는 어떻게 보내나요?',
        'answer': (
            "'일정 > 예약 가용시간 관리'에서 상담 가능한 시간을 정하면 예약 링크가 만들어져요. "
            '링크를 복사해 고객에게 보내면, 고객이 빈 시간을 골라 예약하고 설계사님이 수락하면 '
            '확정됩니다.'
        ),
    },
    {
        'category': '요금결제', 'order': 5,
        'question': '지금 이용 요금은 어떻게 되나요?',
        'answer': (
            '현재는 무료로 이용하실 수 있어요. 요금제가 새로 생기면 이 공지와 화면에서 '
            '미리 알려드리겠습니다.'
        ),
    },
    {
        'category': '개인정보·보안', 'order': 6,
        'question': '제가 등록한 고객 정보는 안전한가요?',
        'answer': (
            '네. 고객 정보는 설계사님 계정에만 보이도록 분리되어 있어요. 다른 설계사는 볼 수 '
            '없습니다. 고객에게 보내는 공유 화면도 필요한 정보만 담기고, 민감한 내용은 빠집니다.'
        ),
    },
    {
        'category': '계정', 'order': 7,
        'question': '설계사가 팀에 합류하면 Manager로 어떻게 바뀌나요?',
        'answer': (
            '내 영입 링크로 합류한 첫 설계사가 계정을 연결하면 Manager 역할이 자동으로 열립니다. '
            '이용 중인 Plus는 그대로 유지되고 결제일, 쿠폰, 사용량도 바뀌지 않습니다.'
        ),
    },
]


class Command(BaseCommand):
    help = '실서비스용 공지·FAQ 시드(멱등, get_or_create — 기존 편집 보존)'

    def handle(self, *args, **options):
        # 작성자 = 관리자 우선, 없으면 슈퍼유저, 그것도 없으면 첫 사용자.
        author = (
            User.objects.filter(profile__is_admin=True).order_by('id').first()
            or User.objects.filter(is_superuser=True).order_by('id').first()
            or User.objects.order_by('id').first()
        )
        if author is None:
            self.stdout.write(
                '작성자(관리자) 계정이 없어 공지/FAQ 시드를 건너뜁니다. '
                '관리자 생성 후 다시 실행하면 채워집니다.'
            )
            return

        now = timezone.now()
        created_n = created_f = 0
        with transaction.atomic():
            Notice.objects.filter(
                title='인파를 시작합니다',
                body=LEGACY_WELCOME_NOTICE_BODY,
            ).update(body=WELCOME_NOTICE_BODY)
            Faq.objects.filter(
                question=LEGACY_COMPARE_FAQ_QUESTION,
                answer=LEGACY_COMPARE_FAQ_ANSWER,
            ).update(
                question=COMPARE_FAQ_QUESTION,
                answer=COMPARE_FAQ_ANSWER,
            )

            for n in NOTICES:
                _, created = Notice.objects.get_or_create(
                    title=n['title'],
                    defaults={
                        'author': author,
                        'body': n['body'],
                        'is_pinned': n.get('is_pinned', False),
                        'is_published': True,
                        'published_at': now,
                    },
                )
                created_n += int(created)
            for f in FAQS:
                _, created = Faq.objects.get_or_create(
                    question=f['question'],
                    defaults={
                        'author': author,
                        'category': f['category'],
                        'answer': f['answer'],
                        'order': f['order'],
                        'is_published': True,
                    },
                )
                created_f += int(created)

        self.stdout.write(
            self.style.SUCCESS(f'공지 {created_n}건, FAQ {created_f}건 신규 생성(기존은 보존).')
        )
