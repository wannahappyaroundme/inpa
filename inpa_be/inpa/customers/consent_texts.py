"""동의 고지문 단일 소스 (LB-2 fix, 동의 v2).

동의 문구를 한 곳에서만 관리한다. 화면(설계사 /c, 셀프진단 /d, OCR 업로드 모달)과
감사 로그의 버전 스탬프가 모두 이 모듈을 참조한다.

★ 국외이전 보유 기간은 개인정보 처리방침(legal/privacy)과 반드시 일치해야 한다.
  Anthropic은 API 전송 데이터를 모델 학습에 사용하지 않으며(API 기본 정책), 구체적
  보관 기간은 Anthropic 정책을 따른다. 과거의 "처리 후 즉시 삭제" 문구는 사실과 달라
  폐기됐다 — 새 문구만 사용한다.

버전이 바뀌면 CONSENT_TEXTS_VERSION 을 올린다. 게이트(has_current_overseas_consent)는
이 버전과 일치하는 고객 본인 국외이전 동의가 있어야만 새 Claude 호출을 연다.
"""
from .models import ConsentLog

# 문구가 실질적으로 바뀔 때마다 올린다(YYYY-MM-DD). ConsentLog.doc_version(max_length=30)에 스탬프.
CONSENT_TEXTS_VERSION = 'v2-2026-07-04'

# scope → {title, body[], retention}. body/retention 모두 고객이 그대로 읽는 문구(쉬운 말·긍정 톤).
CONSENT_TEXTS = {
    ConsentLog.SCOPE_PERSONAL_INFO: {
        'title': '개인정보 수집·이용 (필수)',
        'body': [
            '수집 항목: 이름·연락처·생년월일 등 상담에 필요한 정보',
            '이용 목적: 보험 상담·계약 관리·고객 응대',
        ],
        'retention': '보유 기간: 거래 종료 후 관계 법령이 정한 기간',
    },
    ConsentLog.SCOPE_OVERSEAS_MEDICAL: {
        'title': '보험 정보 국외이전 (Claude API, 미국)',
        'body': [
            '이전 국가·수탁자: 미국 Anthropic(Claude API)',
            '이전 항목: 증권의 보험정보(담보·보험료 등)',
        ],
        'retention': ('보유 기간: Anthropic의 데이터 처리·보관 정책에 따릅니다'
                      '(입력 정보는 AI 학습에 사용되지 않아요).'),
    },
    ConsentLog.SCOPE_THIRD_PARTY: {
        'title': '제3자 제공·플랫폼 활용 (선택)',
        'body': [
            '제공받는 자: 인파(보장 분석·정리 플랫폼)',
            '제공 목적: 보장 분석·정리 자료 생성',
        ],
        'retention': '보유 기간: 동의를 철회하실 때까지',
    },
    ConsentLog.SCOPE_MARKETING: {
        'title': '마케팅·광고 정보 수신 (선택)',
        'body': [
            '이용 목적: 상품·이벤트 안내(문자·카카오톡 등)',
        ],
        'retention': '보유 기간: 동의를 철회하실 때까지',
    },
}


def consent_lines(scope):
    """공개 고지 화면(/c 등)에 뿌릴 줄 목록 = 본문 + 보유 기간. 알 수 없는 scope면 []."""
    meta = CONSENT_TEXTS.get(scope)
    if not meta:
        return []
    return list(meta['body']) + [meta['retention']]


def has_current_overseas_consent(customer):
    """현재 버전(CONSENT_TEXTS_VERSION)으로 받은 고객 본인 국외이전 동의가 살아있는가.

    구버전 문구로 받은 동의는 게이트를 열지 못한다 → 고객이 새 /c 또는 /d 로 재동의해야
    새 Claude 호출이 가능하다. 이미 저장된 분석 결과에는 영향 없음.
    설계사 대리(planner_attested) 동의는 여기서도 게이트를 열지 못한다.
    """
    if customer is None or customer.pk is None:
        return False
    return ConsentLog.objects.filter(
        customer=customer,
        scope=ConsentLog.SCOPE_OVERSEAS_MEDICAL,
        subject=ConsentLog.SUBJECT_CUSTOMER_SELF,
        revoked_at__isnull=True,
        doc_version=CONSENT_TEXTS_VERSION,
    ).exists()
