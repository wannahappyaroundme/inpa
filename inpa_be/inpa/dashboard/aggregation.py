"""월별 실적(actual) 계산 — 저장 없이 on-demand. 추후 연동 시 이 계산식만 교체.

meetings   = 이번달 'FA(대면) 단계에 처음 도달한 고객' 수(Customer.fa_reached_at).
             예약 확정(booking.Meeting) 개수와 무관. 같은 고객 재이동은 중복 카운트 안 함.
premium    = 이번달 등록 증권의 월보험료 합(CustomerInsurance) — '등록 기준' 프록시(신규계약 한정 아님)
new_customers = 이번달 신규 고객 수(Customer)
※ 예상 월급(income)은 산출 소스가 없어 수동값만(MonthlyGoal.target_income).
"""
import datetime

from django.db.models import Count, Sum

from inpa.customers.models import Customer
from inpa.insurances.models import CustomerInsurance
from inpa.dashboard.models import MonthlyGoal


def compute_actuals(user, year_month):
    """year_month='YYYY-MM' → {meetings, premium, new_customers}."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    # '이번 달 미팅' = 이번 달에 FA(meeting)에 처음 도달한 고객 수(fa_reached_at 기준).
    meetings = Customer.objects.filter(
        owner=user, fa_reached_at__year=y, fa_reached_at__month=m).count()
    premium = CustomerInsurance.objects.filter(
        customer__owner=user, created_at__year=y, created_at__month=m
    ).aggregate(s=Sum('monthly_premiums'))['s'] or 0
    new_customers = Customer.objects.filter(
        owner=user, created_at__year=y, created_at__month=m).count()
    return {'meetings': meetings, 'premium': int(premium), 'new_customers': new_customers}


def _prev_ym(year_month):
    """'YYYY-MM' → 직전 달 'YYYY-MM'."""
    y, m = int(year_month[:4]), int(year_month[5:7])
    m -= 1
    if m == 0:
        m, y = 12, y - 1
    return f'{y:04d}-{m:02d}'


def _delta(cur, prev):
    """전월 대비 증감 — {'pct': int|None, 'dir': 'up'|'down'|'flat'}.

    prev==0: cur>0이면 +100%/up, 아니면 None/flat(분모 0 표기 회피).
    """
    if prev == 0:
        return {'pct': 100, 'dir': 'up'} if cur > 0 else {'pct': None, 'dir': 'flat'}
    pct = round((cur - prev) / prev * 100)
    return {'pct': pct, 'dir': 'up' if pct > 0 else 'down' if pct < 0 else 'flat'}


def compute_deltas(user, year_month, cur=None):
    """이번 달 vs 전월 실적 증감(%) — new_customers/meetings/premium. KPI 카드 배지용.

    프론트가 화면에서 (이번달-지난달)/지난달 계산을 하지 않도록 백엔드에서 내려준다(스펙 §5).
    cur 를 넘기면 이번 달 actuals 재계산을 생략(중복 쿼리 회피).
    """
    cur = cur or compute_actuals(user, year_month)
    prev = compute_actuals(user, _prev_ym(year_month))
    return {k: _delta(cur[k], prev[k]) for k in ('new_customers', 'meetings', 'premium')}


def recent_months(n=6, today=None):
    """오래된→최근 순 'YYYY-MM' n개 (막대 추이용)."""
    today = today or datetime.date.today()
    y, m = today.year, today.month
    out = []
    for _ in range(n):
        out.append(f'{y:04d}-{m:02d}')
        m -= 1
        if m == 0:
            m, y = 12, y - 1
    return list(reversed(out))


def compute_trend(user, n=6):
    """최근 n개월 막대 추이 — [{ym, premium, new_customers, meetings, target_premium}].

    target_premium: 해당 월에 설계사가 설정한 MonthlyGoal.target_premium. 미설정이면 null.
    """
    months = recent_months(n)
    # 한 번의 IN 쿼리로 전체 범위 목표 가져오기 — N+1 방지
    goal_map = {
        g.year_month: g.target_premium
        for g in MonthlyGoal.objects.filter(owner=user, year_month__in=months)
    }
    return [
        {'ym': ym, **compute_actuals(user, ym), 'target_premium': goal_map.get(ym)}
        for ym in months
    ]


def compute_funnel(user):
    """영업 4단계 퍼널(011) — sales_stage별 고객 카운트. 4키 항상 포함."""
    counts = dict(
        Customer.objects.filter(owner=user)
        .values_list('sales_stage')
        .annotate(c=Count('id'))
    )
    return {k: counts.get(k, 0) for k in (
        Customer.STAGE_DB, Customer.STAGE_CONTACT,
        Customer.STAGE_MEETING, Customer.STAGE_CONTRACT,
    )}


def compute_portfolio_breakdown(user, today=None):
    """보유계약 유지현황 도넛(sample_1) — at_risk/watch/stable/unknown 카운트.

    churn 레이더와 같은 판정(_assess)을 재사용해 일관성 보장. 보유(portfolio_type=1)만 대상.
    """
    from inpa.insurances.churn import _assess  # 순환 import 회피 — 함수 내부 lazy
    today = today or datetime.date.today()
    qs = CustomerInsurance.objects.select_related('customer').filter(
        customer__owner=user, portfolio_type=1)
    # 회차(계약일 자동계산) 단계별 분포. 연체/미납(자동 인지 불가)은 쓰지 않음.
    #   at_risk = 초기(13회차 미만, 환수 민감) / watch = 정착중(13~24) / stable = 25회차+ / unknown = 회차 미상
    buckets = {'at_risk': 0, 'watch': 0, 'stable': 0, 'unknown': 0}
    for ci in qs:
        _, _, stage, _ = _assess(ci, today)
        if stage == 'safe':
            buckets['stable'] += 1
        elif stage == 'pre_25':
            buckets['watch'] += 1
        elif stage == 'pre_13':
            buckets['at_risk'] += 1
        else:
            buckets['unknown'] += 1
    return buckets


# ── 계약 유지율(1/2/3년) — PM 06.24. 추정 라벨 강제(회사 전산이 권위) ──────────
def _parse_ymd(s):
    """'YYYY-MM-DD'|'YYYY.MM.DD'|'YYYY/MM/DD' → date 또는 None."""
    if not s:
        return None
    for fmt in ('%Y-%m-%d', '%Y.%m.%d', '%Y/%m/%d'):
        try:
            return datetime.datetime.strptime(str(s).strip(), fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _years_between(d0, d1):
    """d0~d1 만 년수(정수). d1 ≥ d0 가정."""
    y = d1.year - d0.year
    if (d1.month, d1.day) < (d0.month, d0.day):
        y -= 1
    return y


def compute_retention(user, today=None):
    """보유계약 1/2/3년 유지율(추정).

    분모(reached) = 계약일이 N년 이상 지난 보유계약(=N년 평가 가능 모수).
    분자(survived) = 그 중 N년 도달 시점까지 미해지(해지일이 계약일+N년 이후 포함).
    rate(%) = survived/reached 반올림. reached==0이면 None(평가 불가).
    """
    today = today or datetime.date.today()
    rows = list(CustomerInsurance.objects
                .filter(customer__owner=user, portfolio_type=1)
                .values('contract_date', 'is_cancelled', 'cancelled_at'))
    # 해지 입력이 하나도 없으면 유지율이 무조건 100%로 보여 오해 소지 → has_cancellation_data 로 구분.
    out = {'has_cancellation_data': any(r['is_cancelled'] for r in rows)}
    for n in (1, 2, 3):
        reached = survived = 0
        for r in rows:
            cd = _parse_ymd(r['contract_date'])
            if cd is None or _years_between(cd, today) < n:
                continue
            reached += 1
            if not r['is_cancelled']:
                survived += 1
            else:
                cad = _parse_ymd(r['cancelled_at'])
                if cad is not None and _years_between(cd, cad) >= n:
                    survived += 1
        out[f'y{n}'] = {
            'rate': round(survived / reached * 100) if reached else None,
            'reached': reached,
            'survived': survived,
        }
    return out


# ── 관리직 ROI 환산(추정) — PM 06.24. 가설 변수, 광고 단정 금지 ──────────────
ROI_HOURS_SAVED_PER_AGENT_MONTH = 6   # 1인당 월 절약(OCR·AI비교·분석 자동화 가설)
ROI_HOURS_PER_CONSULT = 1.5           # 상담 1건 준비+진행 시간


def compute_team_roi(agent_count):
    """팀 절약시간 → 추가 상담 건수 환산(추정). 광고엔 '추정'·범위로만 사용."""
    team_hours = agent_count * ROI_HOURS_SAVED_PER_AGENT_MONTH
    extra_consults = round(team_hours / ROI_HOURS_PER_CONSULT)
    return {
        'agent_count': agent_count,
        'hours_saved_per_agent': ROI_HOURS_SAVED_PER_AGENT_MONTH,
        'team_hours_saved': team_hours,
        'extra_consults': extra_consults,
        'note': '시간 절약 가설에 기반한 추정치예요(보장 아님). 팀 규모·업무 구성에 따라 달라집니다.',
    }
