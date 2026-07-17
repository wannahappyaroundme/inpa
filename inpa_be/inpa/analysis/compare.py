"""비교 분석 — 담보별로 두 세트를 나란히 정리하는 중립 시각화(사실 비교표).

★ 2026-07-09 재정의(PM 지시, §97 부당승환 리스크 축소): 인파는 KEEP/SWITCH 판정을
  산출하지 않는다. 이 파일은 사실(rows/summary)만 계산해 응답하고, 어느 쪽이 나은지는
  설계사가 정한다. 비교 대상도 더 이상 '보유(portfolio_type=1) vs 제안(portfolio_type=2)'
  로 고정되지 않는다 — side_a_ids/side_b_ids 로 고객이 가진 임의의 두 세트(제안 vs 제안,
  증권 vs 증권 포함)를 자유롭게 비교할 수 있다(§ 하위호환 섹션 참고).

엔드포인트 (config/urls.py → /api/v1/ 마운트, analysis/urls.py 배선):
  GET/POST /api/v1/customers/<customer_pk>/compare/        CustomerCompareView
  POST     /api/v1/customers/<customer_pk>/compare/publish/ CustomerComparePublishView

★ 준법 게이트 (CLAUDE.md 정직성 레드라인 · dev/09 중개금지 · dev/02 §16 · §97 부당승환):
  1) 비교표(rows)는 ★AI 없이 순수 데이터 — 보유/제안 담보의 사실 금액 + delta 만 계산.
     COMPARE_AI_ENABLED 와 무관하게 지금 완전 동작한다.
  2) AI 비교안내서 초안은 settings.COMPARE_AI_ENABLED=True 일 때만 생성한다.
     - check_and_consume(user, 'ai_compare') 로 한도 차감 → 초과 시 402.
     - Claude(settings.CLAUDE_MODEL_PARSE) 로 §97 6요건 구조 초안 생성.
     - log_claude_usage('compare_guide') 로 관리자 비용 로깅.
     - False면 guide_draft=null · guide_enabled=false (기능은 열되 산출물 없음).
     ★ AI 초안 면책 고정 — disclaimer 는 항상 "AI 초안·최종책임 설계사".
  3) 발행(publish)은 settings.COMPARE_PUBLISH_ENABLED=False 이면 403 하드블록.
     publishable 은 항상 false 로 응답한다(고객 발송 = §97 법무 확정 전 금지).

mode(neutral|graded): 히트맵과 동일 게이트 — 살아있는 PlannerBaseline(baseline_source!=null)이
  없으면 neutral. 비교표 자체는 mode 무관하게 사실만 표시한다(부족/충분 단정은 비교표에 없음).

owner 격리: 부모 Customer 를 owner 스코프 쿼리로 잡는다(없으면 404 = 존재 자체 은폐).
  CustomerInsurance 는 customer__owner 경유 소유자 전용이므로 customer 필터로 격리 완결.
"""
import logging

from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.analysis.switch_verdict import compute_switch_warnings
from inpa.billing.credit import LimitExceeded, check_and_consume, log_claude_usage
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer, PlannerBaseline

logger = logging.getLogger(__name__)

# ★ AI 초안 면책 — 절대 변경 금지(정직성 레드라인). "심의 완료/안전" 류 보증 문구 금지.
COMPARE_DISCLAIMER = (
    '본 비교 자료는 AI가 생성한 초안입니다. 최종 책임은 보험을 권유하는 설계사에게 있으며, '
    '실제 계약 전 약관·청약서 원문과 보장 조건을 반드시 직접 확인하십시오. '
    '인파는 보험을 중개·권유하지 않습니다.'
)

# 발행 하드블록 사유 (COMPARE_PUBLISH_ENABLED=False)
PUBLISH_BLOCKED_REASON = '법무 검토 완료 전 발행 금지'


def _credit_exhausted_response(exc: LimitExceeded, user) -> Response:
    """LimitExceeded → 402 Payment Required (dev/02 §16 shape).

    FE는 402 + code='credit_exhausted' 수신 시 UpgradeGuideModal 표시.
    기능 자체를 차단하는 UI 는 사용하지 않는다(정직성 레드라인).
    """
    from inpa.billing.models import Subscription
    sub = Subscription.objects.select_related('plan').filter(user=user).first()
    membership = sub.plan.code if sub else 'free'
    return Response(
        {
            'detail': f'이번 달 한도({exc.limit}건)를 모두 사용했어요.',
            'code': 'credit_exhausted',
            'kind': exc.action,
            'membership': membership,
            'limit': exc.limit,
            'used': exc.current,
        },
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def _selected_ids(request, key):
    """비교에 포함할 보험 id 집합. 콤마구분 문자열(GET) 또는 배열(POST body) 허용.

    값이 없으면 None → '전체'(기존 동작, 하위호환). 값이 있으면 그 보험만 비교 대상.
    current_ids/proposed_ids(하위호환)와 side_a_ids/side_b_ids(신규, A/B 자유 비교) 모두
    이 헬퍼로 파싱한다.
    """
    raw = None
    data = getattr(request, 'data', None)
    if data is not None and data.get(key) is not None:
        raw = data.get(key)
    elif request.query_params.get(key):
        raw = request.query_params.get(key)
    if raw is None:
        return None
    parts = raw.split(',') if isinstance(raw, str) else (raw if isinstance(raw, (list, tuple)) else [])
    ids = set()
    for p in parts:
        try:
            ids.add(int(p))
        except (TypeError, ValueError):
            continue
    return ids  # 제공됐으면 빈 집합이라도 그대로(0개 선택 = 그쪽 0개 비교)


def _aggregate_side(insurance_list):
    """한 측(보유 또는 제안) 보험 목록 → (summary, {coverage_name: amount}) 집계.

    summary: {monthly_premiums, total_premiums, 월/총 갱신/비갱신/적립 분리} — 보험이 0건이면 None.
    coverage_amounts: 표준 담보(AnalysisDetail.name) 별 보장금액 합(case.assurance_amount).
      ★ 순수 사실 집계 — AI 불필요. 담보명은 case.detail.analysis_detail(표준 담보) 기준.

    ★ None 의미론: 각 키마다 non-null 소스가 0개 → 그 키는 None 유지(미상).
      (수동 입력 등) 한 쪽에서만 월보험료는 있는데 월갱신보험료=None 인 경우,
      집계 결과는 0 이 아니라 None 을 반환 → "알려지지 않음", 거짓이 아님.
    """
    keys = ('monthly_premiums', 'monthly_renewal_premium', 'monthly_non_renewal_premium',
            'monthly_earned_premium', 'total_premiums', 'total_renewal_premium',
            'total_non_renewal_premium', 'total_earned_premium')
    if not insurance_list:
        return {k: None for k in keys}, {}

    acc = {k: 0 for k in keys}
    has_nonnull = {k: False for k in keys}  # ★ 각 키별 non-null 여부 추적
    has_incomplete_composition = {k: False for k in keys}
    coverage_amounts = {}

    for ci in insurance_list:
        has_mixed_case_premiums = ci.has_mixed_case_premiums()
        for k in keys:
            v = getattr(ci, k, None)
            if (has_mixed_case_premiums
                    and k in ci.COVERAGE_PREMIUM_COMPOSITION_FIELDS):
                v = None
                has_incomplete_composition[k] = True
            if v is not None:
                acc[k] += v
                has_nonnull[k] = True
        for case in ci.case_list.all():
            amount = case.assurance_amount or 0
            if amount <= 0:
                continue
            # 표준 담보명으로 귀속 (한 케이스가 여러 표준 담보에 매핑될 수 있음 → 각각 합산).
            std_names = [ad.name for ad in case.effective_analysis_details()]
            if not std_names and case.mapping_source == 'global':
                # 표준 담보 매핑이 없으면 카탈로그 담보명으로 폴백(사실 표시 유지).
                std_names = [case.detail.name]
            for name in std_names:
                coverage_amounts[name] = coverage_amounts.get(name, 0) + amount

    # ★ 각 키마다 non-null 값이 없으면 None, 있으면 합계(반올림)
    summary = {}
    for k in keys:
        if has_incomplete_composition[k] or not has_nonnull[k]:
            summary[k] = None
        else:
            summary[k] = round(acc[k]) if isinstance(acc[k], float) else acc[k]

    return summary, coverage_amounts


def _build_rows(current_amounts, proposed_amounts):
    """보유/제안 담보 금액 dict → 계약 rows (담보명 순 정렬, delta=제안-보유).

    한쪽에만 있는 담보도 행으로 포함(없는 쪽은 null). delta 는 양쪽 다 값이 있을 때만 계산.
    """
    names = sorted(set(current_amounts) | set(proposed_amounts))
    rows = []
    for name in names:
        cur = current_amounts.get(name)
        prop = proposed_amounts.get(name)
        delta = (prop - cur) if (cur is not None and prop is not None) else None
        rows.append({
            'coverage': name,
            'current_amount': cur,
            'proposed_amount': prop,
            'delta': delta,
        })
    return rows


def _mode_for_customer(customer):
    """히트맵과 동일 neutral/graded 게이트. 살아있는 baseline 있으면 graded."""
    has_live_baseline = (
        PlannerBaseline.objects
        .filter(owner=customer.owner, is_active=True)
        .exclude(baseline_source__isnull=True)
        .exists()
    )
    return 'graded' if has_live_baseline else 'neutral'


def _generate_guide_draft(customer, current_summary, proposed_summary, rows, meta=None):
    """Claude(settings.CLAUDE_MODEL_PARSE) 로 §97 6요건 구조 비교안내서 초안 생성.

    호출 전제: settings.COMPARE_AI_ENABLED=True + check_and_consume 통과(호출자 책임).
    실패(키 없음/패키지 없음/API 오류) 시 None 반환 → 호출자가 guide_enabled 처리.

    Args:
        meta: ★ 선택 out-param(dict, 프리런치 #17). 성공·실패 outcome
            (success/no_key/package_missing/api_error) 을 채운다. None 이면 기존 동작과
            동일(부작용 없음 — 이 함수를 직접 mock 하는 기존 테스트 하위호환).

    Returns:
        (guide_text, usage) | (None, None)
    """
    def _set_meta(**kwargs):
        if meta is not None:
            meta.update(kwargs)

    api_key = getattr(settings, 'CLAUDE_API_KEY', '')
    if not api_key:
        logger.warning('[compare] CLAUDE_API_KEY not configured')
        _set_meta(outcome='no_key')
        return None, None

    model_id = getattr(settings, 'CLAUDE_MODEL_PARSE', '')
    if not model_id:
        logger.warning('[compare] CLAUDE_MODEL_PARSE not configured')
        _set_meta(outcome='no_model')
        return None, None

    try:
        import anthropic
    except ImportError:
        logger.warning('[compare] anthropic package not installed')
        _set_meta(outcome='package_missing')
        return None, None

    # 비교표(사실)를 텍스트로 직렬화 — 프롬프트 입력. 모든 금액은 이미 서버가 계산한 사실값.
    rows_text = '\n'.join(
        f"- {r['coverage']}: 보유 {r['current_amount']}, 제안 {r['proposed_amount']}, "
        f"증감 {r['delta']}"
        for r in rows
    ) or '(비교 가능한 공통 담보 없음)'

    user_prompt = (
        '아래는 한 고객의 기존 보유 보험과 신규 제안 보험을 담보별로 비교한 사실 데이터입니다.\n'
        '이 데이터만 근거로, 보험업법 제97조(부당 승환계약 방지)가 요구하는 비교안내 6요건을 '
        '구조에 맞춰 한국어 초안으로 작성하세요.\n\n'
        f"[보유 요약] 월 보험료 {current_summary['monthly_premiums']}, "
        f"총 보험료 {current_summary['total_premiums']}\n"
        f"[제안 요약] 월 보험료 {proposed_summary['monthly_premiums']}, "
        f"총 보험료 {proposed_summary['total_premiums']}\n"
        f"[담보별 비교]\n{rows_text}\n"
    )

    system_prompt = (
        '당신은 보험설계사의 비교안내서 초안을 돕는 보조 도구입니다.\n'
        '## 절대 규칙\n'
        '- 제공된 사실 데이터에 없는 보장금액·보험료·수치를 절대 만들어내지 마세요.\n'
        '- "이 보험이 더 좋다/유리하다/가입하세요" 같은 권유·단정 표현을 쓰지 마세요. '
        '인파는 보험을 중개·권유하지 않습니다.\n'
        '- "심의 완료", "안전", "보장됨" 같은 보증성 표현을 쓰지 마세요.\n'
        '- 최종 판단과 책임은 설계사에게 있음을 전제로, 비교 사실만 6요건 구조로 정리하세요.\n\n'
        '## 보험업법 §97 비교안내 6요건 구조 (각 항목 제목 + 사실 기반 서술)\n'
        '1. 기존계약과 신계약의 보장내용 비교\n'
        '2. 기존계약과 신계약의 보험료 비교\n'
        '3. 기존계약 해지 시 손실 가능성(해약환급금/사업비 등)\n'
        '4. 신계약의 청약철회·품질보증 등 소비자 권리\n'
        '5. 기존계약 유지 시의 이점\n'
        '6. 전환 시 유의사항 및 최종 확인 필요사항\n'
    )

    timeout_seconds = 90.0
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds, max_retries=3)
    try:
        message = client.messages.create(
            model=model_id,
            max_tokens=2048,
            system=[{'type': 'text', 'text': system_prompt,
                     'cache_control': {'type': 'ephemeral'}}],
            messages=[{'role': 'user', 'content': user_prompt}],
        )
        text = message.content[0].text.strip()
        usage = getattr(message, 'usage', None)
        _set_meta(outcome='success')
        return text, usage
    except Exception as e:  # API 오류는 비교표(사실) 응답을 깨뜨리지 않는다. 예외 타입만(내용 미포함).
        logger.warning('[compare] guide generation error: %s', type(e).__name__)
        _set_meta(outcome='api_error')
        return None, None


class _CustomerScopedCompareMixin:
    """부모 Customer 를 owner 격리 쿼리로 잡는 공통 베이스(없으면 404)."""
    permission_classes = [IsAuthenticated, IsEmailVerified]

    def _is_admin(self):
        profile = getattr(self.request.user, 'profile', None)
        return bool(getattr(profile, 'is_admin', False))

    def _get_customer(self, customer_pk):
        qs = Customer.objects.all()
        if not self._is_admin():
            qs = qs.filter(owner=self.request.user)
        try:
            return qs.get(pk=customer_pk)
        except Customer.DoesNotExist:
            raise NotFound('고객을 찾을 수 없습니다.')


class CustomerCompareView(_CustomerScopedCompareMixin, APIView):
    """비교표(나란히 정리) + (게이트 시) AI 비교안내서 초안.

    GET/POST /api/v1/customers/<customer_pk>/compare/

    응답(계약 — BE/FE 정확히 일치):
      {
        mode, current:{monthly_premiums, total_premiums},
        proposed:{monthly_premiums, total_premiums},
        rows:[{coverage, current_amount, proposed_amount, delta}],
        switch_warnings:[{type, label, detail, amount}],   # ★ 설계사 내부 전용(공유뷰 누수 금지)
                                                            #   판정 아님 — 중립 확인 사항(해지
                                                            #   손실 추정·면책 리셋·이율 변동)
        guide_draft, guide_enabled, publishable(=false),
        publish_blocked_reason, disclaimer
      }

    ★ 2026-07-09: 응답에 `verdict`(KEEP/SWITCH/NEUTRAL) 키가 없다 — 인파는 판정을 산출하지
      않는다. 어느 쪽이 나은지는 설계사가 정한다(§97 리스크 축소, PM 지시).

    비교 대상 선택 파라미터(둘 다 GET 쿼리 또는 POST body, 콤마구분/배열 허용):
      - side_a_ids / side_b_ids (신규): 고객 소유 CustomerInsurance id 임의 두 집합.
        portfolio_type 무관 — 제안 vs 제안, 증권 vs 증권도 가능. 응답의 current=A측,
        proposed=B측(키는 하위호환 위해 유지, 의미는 'A측/B측').
      - current_ids / proposed_ids (하위호환): side_a_ids/side_b_ids 가 전혀 없을 때만
        적용 — 보유(portfolio_type=1)/제안(portfolio_type=2) 중 선택한 것만 비교.
      - 아무 파라미터도 없으면 기존 동작 그대로: 보유 전체=A측, 제안 전체=B측.
    """

    def _respond(self, request, customer_pk):
        customer = self._get_customer(customer_pk)

        base_qs = (
            customer.customer_insurance_list
            .analysis_ready()
            .prefetch_related(
                'case_list__detail__analysis_detail',
                'case_list__analysis_detail_override',
                'case_list__detail__chart_detail')
        )
        all_list = list(base_qs)

        # ── A/B 사이드 구성(PM 07.09 재정의) ──────────────────────────────────
        # side_a_ids/side_b_ids 가 오면 portfolio_type 무관하게 고객 소유 보험 중
        # 임의의 두 집합을 A/B 로 비교(제안 vs 제안·증권 vs 증권 등 자유 비교).
        # 없으면 하위호환: 보유(portfolio_type=1)/제안(portfolio_type=2) 분리 +
        # current_ids/proposed_ids 선택(PM 06.29, 기존 동작 그대로).
        side_a_sel = _selected_ids(request, 'side_a_ids')
        side_b_sel = _selected_ids(request, 'side_b_ids')
        if side_a_sel is not None or side_b_sel is not None:
            by_id = {ci.id: ci for ci in all_list}
            current_list = [by_id[i] for i in (side_a_sel or set()) if i in by_id]
            proposed_list = [by_id[i] for i in (side_b_sel or set()) if i in by_id]
        else:
            current_list = [ci for ci in all_list if ci.portfolio_type == 1]
            proposed_list = [ci for ci in all_list if ci.portfolio_type == 2]

            cur_sel = _selected_ids(request, 'current_ids')
            prop_sel = _selected_ids(request, 'proposed_ids')
            if cur_sel is not None:
                current_list = [ci for ci in current_list if ci.id in cur_sel]
            if prop_sel is not None:
                proposed_list = [ci for ci in proposed_list if ci.id in prop_sel]

        current_summary, current_amounts = _aggregate_side(current_list)
        proposed_summary, proposed_amounts = _aggregate_side(proposed_list)

        # 보험별 요금(InsuranceFeeSerializer) 추가 — 지역 import(순환 방지)
        from inpa.insurances.serializers import InsuranceFeeSerializer
        current_summary['insurances'] = InsuranceFeeSerializer(current_list, many=True).data
        proposed_summary['insurances'] = InsuranceFeeSerializer(proposed_list, many=True).data

        rows = _build_rows(current_amounts, proposed_amounts)
        mode = _mode_for_customer(customer)

        # ── 확인해야 할 사항 (★ 설계사 내부면 전용 — 고객 공유뷰엔 절대 미노출) ──────
        # 판정(KEEP/SWITCH)이 아니라 중립 사실(해지환급 손실 추정·면책 리셋·이율 변동)만
        # 계산한다(Claude 호출 없음, 결정론). 2026-07-09: verdict 산출·응답 포함은 제거.
        switch_warnings, _cancellation_loss = compute_switch_warnings(
            current_list, proposed_list)

        # ── AI 비교안내서 초안 — COMPARE_AI_ENABLED=True 일 때만 ────────────
        guide_draft = None
        guide_enabled = False
        if getattr(settings, 'COMPARE_AI_ENABLED', False):
            # 한도 차감(ai_compare) — 초과 시 402. 베타 무차감 스위치는 credit.py 가 처리.
            try:
                check_and_consume(request.user, 'ai_compare')
            except LimitExceeded as exc:
                return _credit_exhausted_response(exc, request.user)

            guide_meta = {}
            text, usage = _generate_guide_draft(
                customer, current_summary, proposed_summary, rows, meta=guide_meta)
            if text is not None:
                guide_draft = text
                guide_enabled = True
            # ★ 프리런치 #17: 성공·실패 모두 기록(과거엔 성공 시에만 로깅 — 실패 관측 불가였음).
            #   guide_meta 는 _generate_guide_draft 를 직접 mock 하는 기존 테스트에서는 비어 있을
            #   수 있으므로(부작용 없음), text 유무로 안전한 fallback outcome 을 둔다.
            outcome = guide_meta.get('outcome') or ('success' if text is not None else 'api_error')
            log_claude_usage(
                'compare_guide',
                getattr(settings, 'CLAUDE_MODEL_PARSE', ''),
                usage,
                user=request.user,
                outcome=outcome,
            )

        return Response({
            'mode': mode,
            'current': current_summary,
            'proposed': proposed_summary,
            'rows': rows,
            'guide_draft': guide_draft,
            'guide_enabled': guide_enabled,
            # ── 확인해야 할 사항(중립 사실, planner_internal) — 공유뷰 누수 금지 ──
            # ★ 2026-07-09: verdict(판정) 키는 응답에서 완전히 제거됐다. 인파는 KEEP/SWITCH
            #   를 산출하지 않는다 — 남는 것은 설계사가 검토할 중립 사실뿐이다.
            'switch_warnings': switch_warnings,
            # ★ 발행은 항상 차단 — 고객 발송 하드블록(§97 법무 확정 전).
            'publishable': False,
            'publish_blocked_reason': PUBLISH_BLOCKED_REASON,
            'disclaimer': COMPARE_DISCLAIMER,
        })

    def get(self, request, customer_pk):
        return self._respond(request, customer_pk)

    def post(self, request, customer_pk):
        # POST 도 동일 비교 동작(FE 가 양쪽 메서드 모두 호출 — 계약 명시).
        return self._respond(request, customer_pk)


class CustomerComparePublishView(_CustomerScopedCompareMixin, APIView):
    """비교안내서 발행(고객 발송) — ★ 하드블록.

    POST /api/v1/customers/<customer_pk>/compare/publish/

    settings.COMPARE_PUBLISH_ENABLED=False 이면 403 으로 차단한다.
    §97(부당승환) 법무 확정 전까지 고객 발송 금지 — 정직성 레드라인(원탭 자동발송 없음).
    """

    def post(self, request, customer_pk):
        # owner 격리 먼저(없으면 404) — 존재 은폐 우선.
        self._get_customer(customer_pk)

        if not getattr(settings, 'COMPARE_PUBLISH_ENABLED', False):
            return Response(
                {
                    'detail': PUBLISH_BLOCKED_REASON,
                    'code': 'compare_publish_blocked',
                    'publishable': False,
                    'publish_blocked_reason': PUBLISH_BLOCKED_REASON,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # 게이트가 열린 경우의 실제 발행 로직은 §97 법무 확정 후 라운드에서 구현.
        # 지금은 게이트가 열려도 발행 미구현임을 명시(거짓 성공 금지).
        return Response(
            {
                'detail': '발행 기능은 법무 검토 완료 후 구현 예정입니다.',
                'code': 'compare_publish_not_implemented',
                'publishable': False,
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
