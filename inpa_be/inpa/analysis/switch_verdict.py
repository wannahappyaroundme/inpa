"""갈아타기 KEEP/SWITCH 판정 — 설계사 내부 의사결정 근거(planner_internal 전용).

★ 절대 규칙(§97 부당승환 · dev/09 중개금지 · dev/14 노출면 분류):
  - 이 산출물(verdict, switch_warnings)은 '설계사 내부면'에만 노출한다.
    고객 공유뷰(analytics._build_share_payload)에는 절대 포함하지 않는다(누수 회귀 테스트로 강제).
  - 인파의 '권유·단정'이 아니라 '설계사가 검토할 사실 기반 근거'다. 카피는 단정 금지.
  - 결정론적 계산 — Claude 호출 없음(국외이전·AI가드레일·COMPARE_AI_ENABLED 무관). 금액은 모두 '추정'.
  - 보수적 편향: 불확실하면 KEEP(유지) — 부당승환을 '막는' 방향이 안전(§97 방어).

입력은 갈아타기 비교의 보유(portfolio_type=1)/제안(portfolio_type=2) CustomerInsurance 리스트.
손실 계산식은 vendored calculate.py 의 정의(기납입 - 해약환급금)와 동일하되, 그 파일은
핵심 자산 보존을 위해 건드리지 않고 여기서 최소 재현한다.
"""
import datetime

# ★ verdict 면책 — 변경 금지(정직성 레드라인). "심의 완료/안전/보장됨" 류 보증 표현 금지.
VERDICT_DISCLAIMER = (
    '이 판정은 입력된 정보로 자동 계산한 추정 근거이며, 인파의 권유가 아닙니다. '
    '해지환급금·기납입액은 보험사 확인이 필요하고, 최종 판단과 책임은 설계사에게 있습니다.'
)


def _prepaid_months(contract_date_str, today=None):
    """계약일 문자열 → 오늘까지 경과 개월수. 파싱 불가/없음이면 None."""
    if not contract_date_str:
        return None
    today = today or datetime.date.today()
    parsed = None
    for fmt in ('%Y.%m.%d', '%Y-%m-%d', '%Y/%m/%d'):
        try:
            parsed = datetime.datetime.strptime(contract_date_str, fmt).date()
            break
        except (ValueError, TypeError):
            parsed = None
    if parsed is None:
        return None
    months = (today.year - parsed.year) * 12 + (today.month - parsed.month)
    if today.day < parsed.day:
        months -= 1
    return max(0, months)


def _cancellation_loss_for(ci, today=None):
    """한 보유계약 해지손실 추정 = 기납입(경과개월×월보험료) - 해약환급금. 계산불가 시 None."""
    months = _prepaid_months(getattr(ci, 'contract_date', None), today=today)
    monthly = getattr(ci, 'monthly_premiums', None)
    if months is None or not monthly:
        return None
    prepaid = months * monthly
    refund = getattr(ci, 'cancellation_refund', None) or 0
    return max(0, prepaid - refund)


def compute_switch_warnings(current_list, has_proposed, today=None):
    """보유계약 리스트 → (switch_warnings 리스트, 합산 해지손실 or None)."""
    warnings = []
    loss_total = 0
    loss_known = False
    for ci in current_list:
        loss = _cancellation_loss_for(ci, today=today)
        if loss is not None:
            loss_total += loss
            loss_known = True

    if loss_known and loss_total > 0:
        warnings.append({
            'type': 'cancellation_loss',
            'label': '해지환급 손실(추정)',
            'detail': '기존 계약 해지 시 기납입액 대비 환급금이 적어 발생하는 손실 추정치',
            'amount': loss_total,
        })
    if has_proposed:
        warnings.append({
            'type': 'exemption_reset',
            'label': '면책기간 리셋',
            'detail': '신규 계약은 암 90일 등 면책·감액 기간이 다시 시작될 수 있음(약관 확인)',
            'amount': None,
        })
        warnings.append({
            'type': 'rate_change',
            'label': '예정이율·갱신조건 변동 가능',
            'detail': '오래된 계약일수록 예정이율이 높을 수 있어 해지 시 불리할 수 있음(약관 확인)',
            'amount': None,
        })
    return warnings, (loss_total if loss_known else None)


def _coverage_change(rows):
    """비교표 rows → (보장 개선 여부, 보장 축소/탈락 여부)."""
    improved = False
    reduced = False
    for r in rows:
        cur = r.get('current_amount')
        prop = r.get('proposed_amount')
        if prop is not None and (cur is None or prop > (cur or 0)):
            improved = True
        if cur is not None and (prop is None or prop < cur):
            reduced = True
    return improved, reduced


def compute_verdict(current_list, proposed_list, current_summary, proposed_summary, rows, today=None):
    """KEEP/SWITCH/NEUTRAL 결정론 판정 + 근거. planner_internal 전용 산출.

    Returns dict: {decision, reason, customer_net_benefit_estimate, switch_warnings, disclaimer}
    """
    has_proposed = bool(proposed_list)
    warnings, cancellation_loss = compute_switch_warnings(current_list, has_proposed, today=today)

    if not has_proposed:
        return {
            'decision': 'NEUTRAL',
            'reason': '제안(비교 대상) 보험이 없어 비교할 수 없습니다.',
            'customer_net_benefit_estimate': None,
            'switch_warnings': warnings,
            'disclaimer': VERDICT_DISCLAIMER,
        }

    cur_m = current_summary.get('monthly_premiums')
    prop_m = proposed_summary.get('monthly_premiums')
    premium_delta_annual = ((prop_m - cur_m) * 12) if (cur_m is not None and prop_m is not None) else None

    loss = cancellation_loss or 0
    # 1년 기준 추정 순손익: (보험료 덜 내는 만큼) - 해지손실. 양수=1년 내 이득, 음수=손해.
    net = None if premium_delta_annual is None else (-premium_delta_annual - loss)

    improved, reduced = _coverage_change(rows)

    # 보수적 규칙(불확실 → KEEP). reason 은 항상 '근거' 서술(권유·단정 금지).
    if reduced and loss > 0:
        decision = 'KEEP'
        reason = (
            f'전환 시 보장이 줄어드는 담보가 있고 해지손실(추정 {loss:,}원)이 발생합니다. '
            '유지를 우선 검토하세요.'
        )
    elif net is not None and net < 0 and not improved:
        decision = 'KEEP'
        reason = (
            f'보장 개선 근거가 약한데 1년 기준 순손익이 추정 {net:,}원(손해)입니다. '
            '유지가 유리할 수 있습니다.'
        )
    elif improved and (net is None or net >= 0):
        decision = 'SWITCH'
        reason = '보장이 개선되고 비용 측면 불리함이 크지 않습니다. 전환을 검토할 가치가 있습니다(설계사 확인).'
    else:
        decision = 'NEUTRAL'
        reason = '이익과 손실이 뚜렷하지 않습니다. 고객 상황(보장 우선순위·납입 여력)으로 판단하세요.'

    return {
        'decision': decision,
        'reason': reason,
        'customer_net_benefit_estimate': net,
        'switch_warnings': warnings,
        'disclaimer': VERDICT_DISCLAIMER,
    }
