"""권유 단어 서버측 가드 (#23, §97·금소법 자동 방어 — dev/14).

고객 대면 응답의 '고정 카피 필드'(코드가 넣는 문자열: disclaimer 등)에
권유·승환 유도 단어가 섞이면 logger.error 로 관측한다. ★ 고객 화면은 절대
깨지 않는다(로그만) — 데이터 필드(고객 이름·담보명·금액)는 검사 대상 아님(오탐 방지).

FE 쪽 대응 가드: inpa_fe/scripts/check-copy.js (고객 대면 라우트 한정 CI 게이트).
"""
import logging
import re

logger = logging.getLogger(__name__)

# FE check-copy.js 의 고객 대면 금지 패턴과 동일 세트 (§97 부당승환·금소법 권유 규제).
ADVICE_PATTERNS = (
    re.compile(r'추천(?!인)'),          # '추천인'(referrer)은 정당한 단어 → 제외
    re.compile(r'갈아타'),
    re.compile(r'해지하(세요|시는 게|시길)'),
    re.compile(r'더 유리'),
    re.compile(r'가입하세요'),
    re.compile(r'전환하세요'),
)


def contains_advice_words(text):
    """text 에 권유 단어가 있으면 첫 매치 문자열, 없으면 None."""
    if not text:
        return None
    for pat in ADVICE_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(0)
    return None


def warn_if_advice_words(fields, where):
    """고정 카피 필드 dict {필드명: 문자열} 검사 — 발견 시 logger.error (응답은 그대로).

    반환: 발견된 (필드명, 매치어) 리스트 (테스트 단언용).
    """
    hits = []
    for name, text in fields.items():
        matched = contains_advice_words(text)
        if matched:
            hits.append((name, matched))
            logger.error(
                '권유 단어 가드: 고객 대면 고정 카피에 금지어 감지 — where=%s field=%s word=%r '
                '(§97·금소법, 화면은 유지·카피 수정 필요)', where, name, matched)
    return hits


# ─── 블로그(인파 노트) 게시 전 카피 검사 (비차단 경고) ──────────────

# em-dash(U+2014) — PM 규칙상 사용자 대면 카피 금지("AI 티가 난다"). 콤마/마침표/괄호로.
EM_DASH = '—'


def scan_blog_content(fields):
    """PM 작성 블로그 콘텐츠 게시 전 카피 검사 — 비차단 경고 리스트 반환.

    인파 최초로 카피 가드가 'DB에 저장되는 PM 작성 콘텐츠'에 닿는 지점.
    저장을 막지 않고(경고만) 게시 응답에 함께 실어 편집자가 다듬도록 돕는다.

    Args:
        fields: {필드명: 문자열} — 보통 title/body/excerpt.

    Returns:
        [{'field': str, 'issue': 'em_dash'|'advice_word', 'match': str}, ...]
        (비어 있으면 문제 없음)
    """
    warnings = []
    for name, text in fields.items():
        if not text:
            continue
        if EM_DASH in text:
            warnings.append({'field': name, 'issue': 'em_dash', 'match': EM_DASH})
        matched = contains_advice_words(text)
        if matched:
            warnings.append({'field': name, 'issue': 'advice_word', 'match': matched})
    return warnings
