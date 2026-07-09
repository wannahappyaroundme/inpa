"""Claude API 비용 추정 — 모델 계열(substring)별 단가 + 환율 (프리런치 리뷰 #17).

★ 정직성 레드라인(§6): 여기서 계산되는 cost_krw 는 어드민 관측용 **추정치**다.
  Anthropic 실제 청구서와 정확히 일치하지 않을 수 있다(환율·반올림·요금제 변동).
  원천 진실은 토큰수(ClaudeApiLog.input_tokens 등) — cost 는 그 파생값일 뿐이다.

단가(문서 docs/05·06 기준, USD / 1M 토큰):
  Opus   $5  in / $25 out
  Sonnet $3  in / $15 out
  Haiku  $1  in / $5  out
  prompt caching: cache_read = 입력단가 × 0.1 / cache_creation = 입력단가 × 1.25

모델 계열은 모델 id substring(opus/sonnet/haiku)으로 판별한다 — 정확한 버전 문자열이
바뀌어도(예: claude-opus-4-8 → claude-opus-5) 계열 단가만 있으면 계속 동작한다.
미상 모델(계열 판별 실패)은 opus(가장 비싼 단가)로 보수적 fallback.
"""
from decimal import Decimal

from django.conf import settings

MODEL_PRICING = {
    'opus': {'in_usd_per_mtok': Decimal('5'), 'out_usd_per_mtok': Decimal('25')},
    'sonnet': {'in_usd_per_mtok': Decimal('3'), 'out_usd_per_mtok': Decimal('15')},
    'haiku': {'in_usd_per_mtok': Decimal('1'), 'out_usd_per_mtok': Decimal('5')},
}
CACHE_READ_MULT = Decimal('0.1')
CACHE_WRITE_MULT = Decimal('1.25')
# 미상 모델 → 보수적(가장 비싼 계열) fallback. 추측 금지 원칙과 별개로, 비용 관측은
# 과소추정보다 과대추정이 안전(예산 경보가 늦게 울지 않도록).
_DEFAULT_FAMILY = 'opus'

_MTOK = Decimal(1_000_000)


def _resolve_family(model: str) -> str:
    """모델 id → 계열(opus/sonnet/haiku). substring 매칭, 미상은 opus."""
    name = (model or '').lower()
    for family in MODEL_PRICING:
        if family in name:
            return family
    return _DEFAULT_FAMILY


def _usage_tokens(usage) -> dict:
    """usage(Anthropic SDK 객체 / dict / None) → 4개 토큰 int. 안전 추출(비정상값=0)."""
    def _g(name):
        if usage is None:
            return 0
        val = usage.get(name, 0) if isinstance(usage, dict) else getattr(usage, name, 0)
        if not isinstance(val, (int, float)):
            return 0
        return int(val)

    return {
        'input_tokens': _g('input_tokens'),
        'output_tokens': _g('output_tokens'),
        'cache_read_input_tokens': _g('cache_read_input_tokens'),
        'cache_creation_input_tokens': _g('cache_creation_input_tokens'),
    }


def estimate_cost_krw(model: str, usage) -> Decimal:
    """토큰수 × 모델 계열 단가 × 환율 → 추정 비용(원, 소수 2자리).

    usage 가 None(호출 실패로 토큰 자체가 없음)이면 0.
    """
    if usage is None:
        return Decimal('0')

    tokens = _usage_tokens(usage)
    pricing = MODEL_PRICING[_resolve_family(model)]
    in_price = pricing['in_usd_per_mtok']
    out_price = pricing['out_usd_per_mtok']

    usd = (
        Decimal(tokens['input_tokens']) / _MTOK * in_price
        + Decimal(tokens['output_tokens']) / _MTOK * out_price
        + Decimal(tokens['cache_read_input_tokens']) / _MTOK * in_price * CACHE_READ_MULT
        + Decimal(tokens['cache_creation_input_tokens']) / _MTOK * in_price * CACHE_WRITE_MULT
    )
    usd_krw_rate = Decimal(str(getattr(settings, 'CLAUDE_USD_KRW_RATE', 1400.0)))
    return (usd * usd_krw_rate).quantize(Decimal('0.01'))
