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

# 블로그 Markdown의 화면 비노출 목적지. 완성된 표준 문법만 가려서, 깨진 Markdown은
# 원문 그대로 검사한다. 링크 문구와 이미지 대체 문구는 치환 결과에 남는다.
_REFERENCE_DEFINITION_RE = re.compile(
    r'^[ \t]{0,3}\[(?P<label>[^\]\n]+)\]:[ \t]*(?P<destination>.*?)[ \t]*$'
)
_FENCE_OPEN_RE = re.compile(r'(?m)^ {0,3}(?P<fence>`{3,}|~{3,})[^\n]*(?:\n|$)')
_AUTOLINK_RE = re.compile(r'<https?://[^<>\s]+>', re.IGNORECASE)
_RAW_HTTP_URL_RE = re.compile(r'https?://[^\s<>]+', re.IGNORECASE)


def _skip_horizontal_space(text, index):
    while index < len(text) and text[index] in ' \t':
        index += 1
    return index


def _destination_end(text, start):
    """Return the first character after a valid Markdown destination."""
    if start < len(text) and text[start] == '<':
        index = start + 1
        while index < len(text):
            if text[index] == '\\' and index + 1 < len(text):
                index += 2
                continue
            if text[index] == '>':
                return index + 1
            if text[index] in '<\r\n':
                return None
            index += 1
        return None

    depth = 0
    index = start
    while index < len(text):
        char = text[index]
        if char == '\\' and index + 1 < len(text):
            index += 2
            continue
        if char in ' \t\r\n':
            break
        if char == '(':
            depth += 1
        elif char == ')':
            if depth == 0:
                break
            depth -= 1
        index += 1
    if depth:
        return None
    return index


def _title_end(text, start):
    if start >= len(text) or text[start] not in '"\'(':
        return None
    closing = ')' if text[start] == '(' else text[start]
    index = start + 1
    while index < len(text):
        if text[index] == '\\' and index + 1 < len(text):
            index += 2
            continue
        if text[index] == closing:
            return index + 1
        if text[index] in '\r\n':
            return None
        index += 1
    return None


def _valid_reference_destination(text):
    if not text:
        return False
    destination_end = _destination_end(text, 0)
    if destination_end is None or destination_end == 0:
        return False
    if destination_end == len(text):
        return True
    title_start = _skip_horizontal_space(text, destination_end)
    if title_start == destination_end:
        return False
    title_end = _title_end(text, title_start)
    if title_end is None:
        return False
    return _skip_horizontal_space(text, title_end) == len(text)


def _inline_link_end(text, destination_start):
    destination_start = _skip_horizontal_space(text, destination_start)
    if destination_start < len(text) and text[destination_start] == ')':
        return destination_start + 1
    destination_end = _destination_end(text, destination_start)
    if destination_end is None or destination_end == destination_start:
        return None
    if destination_end < len(text) and text[destination_end] == ')':
        return destination_end + 1
    title_start = _skip_horizontal_space(text, destination_end)
    if title_start == destination_end:
        return None
    if title_start < len(text) and text[title_start] == ')':
        return title_start + 1
    title_end = _title_end(text, title_start)
    if title_end is None:
        return None
    closing = _skip_horizontal_space(text, title_end)
    if closing < len(text) and text[closing] == ')':
        return closing + 1
    return None


def _strip_reference_definitions(text):
    definitions = set()
    visible_lines = []
    for line in text.splitlines(keepends=True):
        content = line.rstrip('\r\n')
        line_ending = line[len(content):]
        matched = _REFERENCE_DEFINITION_RE.fullmatch(content)
        if matched and _valid_reference_destination(matched.group('destination')):
            definitions.add(' '.join(matched.group('label').split()).casefold())
            visible_lines.append(line_ending)
        else:
            visible_lines.append(line)
    return ''.join(visible_lines), definitions


def _is_escaped(text, index):
    backslashes = 0
    index -= 1
    while index >= 0 and text[index] == '\\':
        backslashes += 1
        index -= 1
    return bool(backslashes % 2)


def _code_token(index):
    return f'\x00COPYGUARD_CODE_{index}\x00'


def _label_token(index):
    return f'\x00COPYGUARD_LABEL_{index}\x00'


def _protect_code(text):
    """Replace valid fenced/inline code with tokens and return exact source segments."""
    code_segments = []
    visible = []
    cursor = 0
    while matched := _FENCE_OPEN_RE.search(text, cursor):
        visible.append(text[cursor:matched.start()])
        fence = matched.group('fence')
        closing_re = re.compile(
            rf'(?m)^ {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*(?:\n|$)'
        )
        closing = closing_re.search(text, matched.end())
        block_end = closing.end() if closing else len(text)
        code_segments.append(text[matched.start():block_end])
        visible.append(_code_token(len(code_segments) - 1))
        cursor = block_end
    visible.append(text[cursor:])
    text = ''.join(visible)

    visible = []
    cursor = 0
    while True:
        opening = text.find('`', cursor)
        if opening < 0:
            break
        run_end = opening
        while run_end < len(text) and text[run_end] == '`':
            run_end += 1
        if _is_escaped(text, opening):
            visible.append(text[cursor:run_end])
            cursor = run_end
            continue
        run_length = run_end - opening
        search_at = run_end
        closing_end = None
        while (closing := text.find('`', search_at)) >= 0:
            candidate_end = closing
            while candidate_end < len(text) and text[candidate_end] == '`':
                candidate_end += 1
            if candidate_end - closing == run_length:
                closing_end = candidate_end
                break
            search_at = candidate_end
        if closing_end is None:
            visible.append(text[cursor:run_end])
            cursor = run_end
            continue
        visible.append(text[cursor:opening])
        code_segments.append(text[opening:closing_end])
        visible.append(_code_token(len(code_segments) - 1))
        cursor = closing_end
    visible.append(text[cursor:])
    return ''.join(visible), code_segments


def _label_end(text, start):
    depth = 1
    index = start + 1
    while index < len(text):
        if text[index] == '\\' and index + 1 < len(text):
            index += 2
            continue
        if text[index] == '[':
            depth += 1
        elif text[index] == ']':
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _normalize_reference(label):
    return ' '.join(label.split()).casefold()


def _strip_link_destinations(text, definitions, labels):
    visible = []
    cursor = 0
    index = 0
    while index < len(text):
        syntax_start = index
        if text[index] == '!' and index + 1 < len(text) and text[index + 1] == '[':
            label_start = index + 1
        elif text[index] == '[':
            label_start = index
        else:
            index += 1
            continue
        if _is_escaped(text, label_start):
            index = label_start + 1
            continue
        label_end = _label_end(text, label_start)
        if label_end is None:
            index = label_start + 1
            continue
        label = text[label_start + 1:label_end]
        destination_start = label_end + 1
        if destination_start < len(text) and text[destination_start] == '(':
            link_end = _inline_link_end(text, destination_start + 1)
            if link_end is not None:
                visible.append(text[cursor:syntax_start])
                labels.append(_strip_link_destinations(label, definitions, labels))
                visible.append(_label_token(len(labels) - 1))
                cursor = link_end
                index = link_end
                continue
        elif destination_start < len(text) and text[destination_start] == '[':
            reference_end = _label_end(text, destination_start)
            if reference_end is not None:
                reference = text[destination_start + 1:reference_end] or label
                if _normalize_reference(reference) in definitions:
                    visible.append(text[cursor:syntax_start])
                    labels.append(_strip_link_destinations(label, definitions, labels))
                    visible.append(_label_token(len(labels) - 1))
                    cursor = reference_end + 1
                    index = cursor
                    continue
        index = label_start + 1
    visible.append(text[cursor:])
    return ''.join(visible)


def _markdown_visible_text(text):
    """Copyguard input with non-rendered Markdown/URL destinations removed."""
    visible, code_segments = _protect_code(text)
    visible, definitions = _strip_reference_definitions(visible)
    labels = []
    visible = _strip_link_destinations(visible, definitions, labels)
    visible = _AUTOLINK_RE.sub('', visible)
    visible = _RAW_HTTP_URL_RE.sub('', visible)
    for index in reversed(range(len(labels))):
        label = labels[index]
        visible = visible.replace(_label_token(index), label)
    for index, code in enumerate(code_segments):
        visible = visible.replace(_code_token(index), code)
    return visible


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
        visible_text = _markdown_visible_text(text) if name == 'body' else text
        if EM_DASH in visible_text:
            warnings.append({'field': name, 'issue': 'em_dash', 'match': EM_DASH})
        matched = contains_advice_words(visible_text)
        if matched:
            warnings.append({'field': name, 'issue': 'advice_word', 'match': matched})
    return warnings
