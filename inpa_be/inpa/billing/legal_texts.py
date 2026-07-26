"""결제 동의 문구의 단일 정본."""

INITIAL_BILLING_CONSENT_VERSION = 'v1-2026-07-26'
INITIAL_BILLING_CONSENT = {
    'title': '무료 이용과 카드 등록 확인',
    'items': [
        '표시된 날짜까지 무료로 이용합니다.',
        '첫 유료 결제 전에 결제일과 금액을 다시 확인합니다.',
        '다시 확인하지 않으면 결제하지 않고 무료 요금제로 전환합니다.',
        '설정의 결제 메뉴에서 언제든 다음 결제를 멈출 수 있습니다.',
    ],
}

FIRST_CHARGE_CONSENT_VERSION = 'v1-2026-07-26'
