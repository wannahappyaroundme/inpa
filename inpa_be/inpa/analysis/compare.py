"""갈아타기(승환) 비교 — 보유(portfolio_type=1) vs 제안(portfolio_type=2) 담보별 비교표.

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
from django.conf import settings
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from inpa.analysis.switch_verdict import compute_verdict
from inpa.billing.credit import LimitExceeded, check_and_consume, log_claude_usage
from inpa.core.permissions import IsEmailVerified
from inpa.customers.models import Customer, PlannerBaseline

# ★ AI 초안 면책 — 절대 변경 금지(정직성 레드라인). "심의 완료/안전" 류 보증 문구 금지.
COMPARE_DISCLAIMER = (
    '본 비교 자료는 AI가 생성한 초안입니다. 최종 책임은 보험을 권유하는 설계사에게 있으며, '
    '실제 계약 전 약관·청약서 원문과 보장 조건을 반드시 직접 확인하십시오. '
    '인파는 보험을 중개·권유하지 않습니다.'
)

# 발행 하드블록 사유 (COMPARE_PUBLISH_ENABLED=False)
PUBLISH_BLOCKED_REASON = '§97 법무 확정 전 발행 금지'


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


def _aggregate_side(insurance_list):
    """한 측(보유 또는 제안) 보험 목록 → (summary, {coverage_name: amount}) 집계.

    summary: {monthly_premiums, total_premiums} — 보험이 0건이면 둘 다 None.
    coverage_amounts: 표준 담보(AnalysisDetail.name) 별 보장금액 합(case.assurance_amount).
      ★ 순수 사실 집계 — AI 불필요. 담보명은 case.detail.analysis_detail(표준 담보) 기준.
    """
    if not insurance_list:
        return {'monthly_premiums': None, 'total_premiums': None}, {}

    monthly = 0
    total = 0.0
    coverage_amounts = {}

    for ci in insurance_list:
        if ci.monthly_premiums is not None:
            monthly += ci.monthly_premiums
        if ci.total_premiums is not None:
            total += ci.total_premiums

        for case in ci.case_list.all():
            amount = case.assurance_amount or 0
            if amount <= 0:
                continue
            # 표준 담보명으로 귀속 (한 케이스가 여러 표준 담보에 매핑될 수 있음 → 각각 합산).
            std_names = [ad.name for ad in case.detail.analysis_detail.all()]
            if not std_names:
                # 표준 담보 매핑이 없으면 카탈로그 담보명으로 폴백(사실 표시 유지).
                std_names = [case.detail.name]
            for name in std_names:
                coverage_amounts[name] = coverage_amounts.get(name, 0) + amount

    summary = {
        'monthly_premiums': monthly,
        'total_premiums': round(total) if total else 0,
    }
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


def _generate_guide_draft(customer, current_summary, proposed_summary, rows):
    """Claude(settings.CLAUDE_MODEL_PARSE) 로 §97 6요건 구조 비교안내서 초안 생성.

    호출 전제: settings.COMPARE_AI_ENABLED=True + check_and_consume 통과(호출자 책임).
    실패(키 없음/패키지 없음/API 오류) 시 None 반환 → 호출자가 guide_enabled 처리.

    Returns:
        (guide_text, usage) | (None, None)
    """
    api_key = getattr(settings, 'CLAUDE_API_KEY', '')
    if not api_key:
        print('[compare] CLAUDE_API_KEY not configured')
        return None, None

    try:
        import anthropic
    except ImportError:
        print('[compare] anthropic package not installed')
        return None, None

    model_id = getattr(settings, 'CLAUDE_MODEL_PARSE', 'claude-opus-4-8')

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
        return text, usage
    except Exception as e:  # API 오류는 비교표(사실) 응답을 깨뜨리지 않는다
        print(f'[compare] guide generation error: {e}')
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
    """갈아타기 비교표 + (게이트 시) AI 비교안내서 초안.

    GET/POST /api/v1/customers/<customer_pk>/compare/

    응답(계약 — BE/FE 정확히 일치):
      {
        mode, current:{monthly_premiums, total_premiums},
        proposed:{monthly_premiums, total_premiums},
        rows:[{coverage, current_amount, proposed_amount, delta}],
        verdict:{decision(KEEP|SWITCH|NEUTRAL), reason, customer_net_benefit_estimate, disclaimer},
        switch_warnings:[{type, label, detail, amount}],   # ★ 설계사 내부 전용(공유뷰 누수 금지)
        guide_draft, guide_enabled, publishable(=false),
        publish_blocked_reason, disclaimer
      }
    """

    def _respond(self, request, customer_pk):
        customer = self._get_customer(customer_pk)

        base_qs = (
            customer.customer_insurance_list
            .prefetch_related('case_list__detail__analysis_detail')
        )
        current_list = [ci for ci in base_qs if ci.portfolio_type == 1]
        proposed_list = [ci for ci in base_qs if ci.portfolio_type == 2]

        current_summary, current_amounts = _aggregate_side(current_list)
        proposed_summary, proposed_amounts = _aggregate_side(proposed_list)
        rows = _build_rows(current_amounts, proposed_amounts)
        mode = _mode_for_customer(customer)

        # ── 갈아타기 KEEP/SWITCH 판정 (★ 설계사 내부면 전용 — 고객 공유뷰엔 절대 미노출) ──
        # 결정론 계산(Claude 호출 없음). switch_warnings(해지손실 등) + 보수적 verdict.
        verdict = compute_verdict(
            current_list, proposed_list, current_summary, proposed_summary, rows)

        # ── AI 비교안내서 초안 — COMPARE_AI_ENABLED=True 일 때만 ────────────
        guide_draft = None
        guide_enabled = False
        if getattr(settings, 'COMPARE_AI_ENABLED', False):
            # 한도 차감(ai_compare) — 초과 시 402. 베타 무차감 스위치는 credit.py 가 처리.
            try:
                check_and_consume(request.user, 'ai_compare')
            except LimitExceeded as exc:
                return _credit_exhausted_response(exc, request.user)

            text, usage = _generate_guide_draft(
                customer, current_summary, proposed_summary, rows)
            if text is not None:
                guide_draft = text
                guide_enabled = True
                log_claude_usage(
                    'compare_guide',
                    getattr(settings, 'CLAUDE_MODEL_PARSE', 'claude-opus-4-8'),
                    usage,
                )

        return Response({
            'mode': mode,
            'current': current_summary,
            'proposed': proposed_summary,
            'rows': rows,
            'guide_draft': guide_draft,
            'guide_enabled': guide_enabled,
            # ── 설계사 내부 판정(planner_internal) — 공유뷰 누수 금지 ──
            'verdict': {
                'decision': verdict['decision'],
                'reason': verdict['reason'],
                'customer_net_benefit_estimate': verdict['customer_net_benefit_estimate'],
                'disclaimer': verdict['disclaimer'],
            },
            'switch_warnings': verdict['switch_warnings'],
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
                'detail': '발행 기능은 §97 법무 확정 후 구현 예정입니다.',
                'code': 'compare_publish_not_implemented',
                'publishable': False,
            },
            status=status.HTTP_501_NOT_IMPLEMENTED,
        )
