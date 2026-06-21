"""미팅 예약 메시지 템플릿 — 설계사별 커스텀(빈 값이면 기본). BE가 인증 경로에서만 렌더."""

DEFAULT_BOOKING_MSG_TEMPLATE = (
    '안녕하세요 {고객명}님, {설계사명}입니다.\n'
    '편하신 시간에 상담 일정을 직접 잡으실 수 있어요. 아래 링크에서 시간을 선택해 주세요.\n'
    '{링크}'
)


def render_booking_message(template, customer_name, planner_name, url):
    """{고객명}{설계사명}{링크} 치환. template이 비면 기본 템플릿 사용."""
    text = template or DEFAULT_BOOKING_MSG_TEMPLATE
    return (text
            .replace('{고객명}', customer_name or '고객')
            .replace('{설계사명}', planner_name or '담당 설계사')
            .replace('{링크}', url))
