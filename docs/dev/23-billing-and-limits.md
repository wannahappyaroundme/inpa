# 인파(Inpa) — 요금제 & 사용량 한도

> 정본: `docs/dev/23-billing-and-limits.md` · 작성일 2026-06-19
> 상위 문서: `dev/02`(데이터모델) · `dev/04`(빌드계획) · `dev/06`(MVP 슬라이스) · `dev/11`(인증)
> 가시성 매트릭스 원칙: 설계사는 **본인 사용량만**, 관리자는 **전체 관리**. 테넌트 = 설계사 1인.

---

## 0. 이 문서가 잠그는 것

| # | 영역 | 결정 내용 |
|---|---|---|
| 1 | 요금제 구조 | Free / Plus 2단계 Freemium. 기능은 전부 열되 월 횟수 제한 |
| 2 | 차단 방식 | 한도 초과 = 업그레이드 안내(soft block). 분석 결과 자체를 차단하지 않음 |
| 3 | 과금 시점 | 베타 = 무차감 운영. Plus 과금 ON은 Phase 1.5(첫 유료 전환 게이트) |
| 4 | 데이터 모델 | `Plan` · `Subscription` · `UsageMeter` 3개 모델 신규 |
| 5 | 결제 처리 | MVP 수동(계좌이체/구두 확인). 자동 결제 PG 연동은 openGaps에 명시 |
| 6 | 가시성 | 설계사 본인 사용량 + 관리자 전체 — OwnedQuerySetMixin 스코프 준수 |

**레드라인**
- 한도 도달 = 기능 차단 X. **항상 안내 + 업그레이드 유도**. 이미 진행 중인 분석은 완료시킨 후 안내.
- 유료 결제 전 기능을 제한하는 게이트는 반드시 PM 명시 승인이 필요하다(사용자 신뢰 훼손 위험).
- 결제 금액·요금 변경은 관리자가 직접 DB에서 수정하는 방식(MVP). 코드 배포 없이 운영 가능해야 한다.

---

## 1. 요금제 구조

### 1.1 플랜 2종

| 구분 | Free | Plus |
|---|---|---|
| **대상** | 신규·체험 설계사 | 헤비유저 (발굴 루틴 정착 후) |
| **월 요금** | 0원 | 29,000원/월 (추정, openGaps 참조) |
| **결제** | 없음 | MVP = 수동 확인 후 관리자 수동 활성화 |
| **기능 접근** | 전체 기능 열림 | 전체 기능 열림 |
| **차이** | 월 사용 횟수 제한 | 횟수 대폭 확장 또는 무제한 |
| **초과 시** | 업그레이드 안내 소프트 블록 | 없음 (무제한 or 대용량 한도) |

> **원칙**: 기능을 잠그지 않는다. 신입 설계사가 처음 쓸 때 "이 기능은 유료" 벽을 만나면 이탈한다. Free에서 가치를 충분히 경험한 뒤 헤비유저가 됐을 때 자연스럽게 업그레이드한다.

### 1.2 월 사용 한도 (action별)

| Action 코드 | 설명 | Free/월 | Plus/월 | 비고 |
|---|---|---|---|---|
| `ocr` | 증권 OCR 분석 1건 | **10건** | 200건 | AI 호출 비용이 가장 큼 |
| `ai_compare` | 갈아타기 비교안내서 생성 1건 | **5건** | 100건 | §97 Phase 1.5 이후 활성화 |
| `analysis` | AI 내러티브/인사이트 생성 1건 | **10건** | 200건 | 히트맵 텍스트 요약·AI 메시지 포함 |
| `promotion` | 판촉물 주문 1건 | **5건** | 100건 | Phase 1.5 이후 활성화 |
| `share_link` | 공유링크 생성 1건 | **무제한** | 무제한 | 북극성 계측 = 차단 금지 |
| `customer_add` | 고객 등록 1건 | **무제한** | 무제한 | 발굴 funnel 진입 = 차단 금지 |

> 수치는 모두 **(추정)** — 베타 운영 데이터 실측 전 가설이다. 운영 3개월 후 코호트 분석으로 조정한다.
> `share_link` · `customer_add`는 절대 차단하지 않는다. 북극성 첫 곱(발송×열람)이 막히면 제품 자체가 죽는다.

---

## 2. 데이터 모델

### 2.1 전체 관계도

```
Plan (요금제 정의)
 └─ Subscription (설계사 ↔ 플랜 구독 상태)
       ↑ FK
    User (설계사)
       ↑ FK
    UsageMeter (월 action별 카운터)
```

### 2.2 Plan 모델

```python
class Plan(models.Model):
    """
    요금제 정의 테이블. 관리자가 DB에서 직접 관리.
    코드 배포 없이 한도·가격 변경 가능.
    """
    PLAN_CODE = (
        ('free',  'Free'),
        ('plus',  'Plus'),
    )

    code         = models.CharField(max_length=20, unique=True, choices=PLAN_CODE)
    display_name = models.CharField(max_length=50)           # 화면 표시명 (예: "무료", "Plus")
    price_krw    = models.PositiveIntegerField(default=0)    # 월 요금 (원). Free=0
    description  = models.TextField(blank=True)              # 관리자 메모

    # action별 월 한도 — null = 무제한 sentinel (is_unlimited 판별, remaining==0 아님)
    # 정본 크레딧 kind 4종(dev/02 §16)과 1:1 대응
    limit_ocr        = models.PositiveIntegerField(null=True, default=10)   # ocr
    limit_ai_compare = models.PositiveIntegerField(null=True, default=5)    # ai_compare
    limit_analysis   = models.PositiveIntegerField(null=True, default=10)   # analysis
    limit_promotion  = models.PositiveIntegerField(null=True, default=5)    # promotion
    # share_link / customer_add = 제한 없음 → 필드 없음

    is_active    = models.BooleanField(default=True)         # 비활성화 시 신규 가입 불가
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '요금제'

    def get_limit(self, action: str) -> int | None:
        """action 코드로 한도 조회. None이면 무제한(is_unlimited 처리, remaining==0 아님)."""
        field = f'limit_{action}'
        return getattr(self, field, None)
```

### 2.3 Subscription 모델

```python
class Subscription(models.Model):
    """
    설계사 1인 ↔ 플랜 구독 상태.
    MVP에서는 관리자가 수동으로 status를 'active'로 바꿔 Plus를 활성화한다.
    자동 결제 PG 연동 시 이 모델에 pg_subscription_id 필드를 추가한다.
    """
    STATUS = (
        ('active',    '활성'),
        ('cancelled', '해지'),
        ('expired',   '만료'),
        ('trial',     '체험'),   # 향후 무료 체험 기간용 hook
    )

    user          = models.OneToOneField(
                        'auth.User', on_delete=models.CASCADE,
                        related_name='subscription'
                    )
    plan          = models.ForeignKey(Plan, on_delete=models.PROTECT)
    status        = models.CharField(max_length=20, choices=STATUS, default='active')
    started_at    = models.DateTimeField(auto_now_add=True)
    expires_at    = models.DateTimeField(null=True, blank=True)  # null = 무기한(Free)
    cancelled_at  = models.DateTimeField(null=True, blank=True)
    # PG 연동 hook (MVP 미사용, 자동 결제 때 채움)
    pg_subscription_id = models.CharField(max_length=100, blank=True, default='')

    class Meta:
        verbose_name = '구독'

    def is_plus(self) -> bool:
        return self.plan.code == 'plus' and self.status == 'active'
```

**가입 시 자동 생성**: `post_save` signal 또는 `create_user` 유틸에서 Free Plan Subscription을 자동 생성한다. 설계사가 가입한 순간 Subscription 레코드가 없으면 안 된다.

### 2.4 UsageMeter 모델

```python
class UsageMeter(models.Model):
    """
    설계사 × action × 월 — 사용 카운터.
    매월 1일 0시 reset (cron 또는 조회 시 lazy reset).
    """
    # 정본 크레딧 kind 4종 (dev/02 §12.3, §16) — Plan.limit_* 필드와 1:1 대응
    ACTION_CHOICES = (
        ('ocr',        'OCR 증권 분석'),
        ('ai_compare', 'AI 비교안내서'),
        ('analysis',   'AI 분석·메시지'),
        ('promotion',  '판촉물 주문'),
    )

    user       = models.ForeignKey('auth.User', on_delete=models.CASCADE,
                                   related_name='usage_meters')
    action     = models.CharField(max_length=30, choices=ACTION_CHOICES)
    year_month = models.CharField(max_length=7)   # 예: "2026-06" (YYYY-MM)
    count      = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user', 'action', 'year_month')
        verbose_name   = '사용량 미터'
        indexes        = [
            models.Index(fields=['user', 'year_month']),
        ]

    @classmethod
    def current_month(cls) -> str:
        from django.utils import timezone
        return timezone.now().strftime('%Y-%m')
```

### 2.5 모델 간 관계 요약

| 관계 | 설명 |
|---|---|
| `User` 1 → 1 `Subscription` | 설계사 1인은 구독 1개 (Free 또는 Plus) |
| `Subscription` N → 1 `Plan` | 여러 설계사가 같은 Plan 참조 |
| `User` 1 → N `UsageMeter` | action × 월 조합으로 카운터 행 생성 |

---

## 3. 사용량 계측 훅 (UseLimit 서비스)

모든 AI 기능 호출은 **반드시 이 훅을 통과**해야 한다. 직접 Claude API를 호출하는 뷰/서비스는 코드리뷰에서 리젝한다.

> **포팅 연결**: foliio `weapon/membership/credit.py:_check_and_consume(user, kind)` 를 인파 크레딧 kind 정본 4종(`ocr`·`ai_compare`·`analysis`·`promotion`)으로 매핑해 확장한다. `kind` 파라미터가 4종과 동일하도록 리네임 후 `UsageMeter` 모델과 연결. 상세 포팅 지점: `dev/03-porting-map` §membership 참조.

> **베타 스위치**: `settings.py`에 `FREE_TIER_UNLIMITED = env.bool('FREE_TIER_UNLIMITED', default=False)` 환경변수를 추가한다. `True`(베타 기간)이면 `_check_and_consume` 내부에서 한도 체크를 전부 우회(무차감 통과). 정식 출시 시 `False` flip. Plan 한도 상향 대신 이 스위치를 사용해 베타 운영과 과금 기준을 분리한다.

### 3.1 _check_and_consume (핵심 유틸 — foliio credit.py 확장)

```python
# inpa/membership/credit.py
# foliio weapon/membership/credit.py:_check_and_consume 을 인파 4종 kind로 확장한 버전

from django.conf import settings
from django.db import transaction
from .models import UsageMeter, Subscription

class LimitExceeded(Exception):
    """한도 초과. API는 402 Payment Required로 응답, FE는 업그레이드 유도 모달."""
    def __init__(self, action: str, current: int, limit: int):
        self.action  = action
        self.current = current
        self.limit   = limit

def _check_and_consume(user, kind: str) -> dict:
    """
    foliio credit.py:_check_and_consume 확장판.
    kind ∈ {'ocr', 'ai_compare', 'analysis', 'promotion'} (정본 4종, dev/02 §16)
    사용 전 호출. 한도 초과 시 LimitExceeded raise.
    한도 이내이면 카운터 +1 후 반환.

    베타 스위치: settings.FREE_TIER_UNLIMITED=True 이면 한도 체크 전부 우회(무차감).

    반환값:
      {
        "action": str,
        "count": int,        # 증가 후 현재 값
        "limit": int | None, # None = 무제한 sentinel
        "remaining": int | None,
      }
    """
    # 베타 무차감 스위치
    if getattr(settings, 'FREE_TIER_UNLIMITED', False):
        return {'action': kind, 'count': 0, 'limit': None, 'remaining': None}

    sub  = getattr(user, 'subscription', None)
    plan = sub.plan if sub else _get_free_plan()
    ym   = UsageMeter.current_month()
    lim  = plan.get_limit(kind)   # None = 무제한 sentinel

    with transaction.atomic():
        meter, _ = UsageMeter.objects.select_for_update().get_or_create(
            user=user, action=kind, year_month=ym,
            defaults={'count': 0}
        )

        if lim is not None and meter.count >= lim:
            raise LimitExceeded(action=kind, current=meter.count, limit=lim)

        meter.count += 1
        meter.save(update_fields=['count', 'updated_at'])

    remaining = (lim - meter.count) if lim is not None else None
    return {'action': kind, 'count': meter.count, 'limit': lim, 'remaining': remaining}

def _get_free_plan():
    from .models import Plan
    return Plan.objects.get(code='free')
```

### 3.2 뷰에서 사용 패턴

```python
# 예: OCR detect 뷰
from inpa.membership.credit import _check_and_consume, LimitExceeded

class InsuranceDetectView(APIView):
    permission_classes = [IsAuthenticated, IsOwner]

    def post(self, request, *args, **kwargs):
        customer_id = request.data.get('customer_id')

        # 1. 국외이전 동의 게이트 (412)
        # Customer는 User 1:N 관계 → customer_id로 특정 고객을 조회 후 확인
        try:
            customer = Customer.objects.get(pk=customer_id, owner=request.user)
        except Customer.DoesNotExist:
            return Response(status=404)

        if not customer.consent_overseas_at:
            return Response({'reason': 'CONSENT_OVERSEAS_REQUIRED'}, status=412)

        # 2. 사용량 게이트 (한도 초과 시 402 Payment Required)
        try:
            usage = _check_and_consume(request.user, 'ocr')
        except LimitExceeded as e:
            return Response({
                'detail': '이번 달 한도를 모두 사용했어요.',
                'code': 'credit_exhausted',
                'kind': e.action,
                'membership': getattr(request.user.subscription.plan, 'code', 'free'),
                'limit': e.limit,
                'used': e.current,
                'upgrade_url': '/settings/billing',
            }, status=402)

        # 3. 실제 처리
        ...
```

> **consent_overseas 접근 경로 주의**: `Customer`는 `User`에 대해 1:N 관계(`Customer.owner = FK User`). 단일 `request.user.customer`는 존재하지 않는다. 반드시 `customer_id`(요청 파라미터 또는 URL 파라미터)로 `Customer.objects.get(pk=..., owner=request.user)` 후 `customer.consent_overseas_at` 접근해야 한다(`OwnedQuerySetMixin` + `IsOwner` 스코프 준수).

### 3.3 월 리셋 방식

**lazy reset** 방식 채택 (MVP에서 cron 불필요):
- `UsageMeter.year_month`가 현재 월과 다르면 그 행은 과거 데이터 → `get_or_create`에서 새 행 생성됨 = 자동 0 리셋.
- 과거 행은 삭제하지 않는다 (사용량 히스토리 보존, 관리자 분석용).
- 실제 삭제가 필요하면 분기 1회 cron으로 `year_month < 3개월 전` 행 정리.

---

## 4. API

### 4.1 본인 사용량 조회

```
GET /api/v1/billing/usage/
Authorization: Token <token>
```

응답:
```json
{
  "plan": {
    "code": "free",
    "display_name": "무료",
    "price_krw": 0
  },
  "subscription": {
    "status": "active",
    "expires_at": null
  },
  "year_month": "2026-06",
  "usage": [
    {
      "action": "ocr",
      "label": "증권 OCR 분석",
      "count": 4,
      "limit": 10,
      "remaining": 6
    },
    {
      "action": "ai_compare",
      "label": "AI 비교안내서",
      "count": 1,
      "limit": 5,
      "remaining": 4
    },
    {
      "action": "analysis",
      "label": "AI 분析·메시지",
      "count": 3,
      "limit": 10,
      "remaining": 7
    },
    {
      "action": "promotion",
      "label": "판촉물 주문",
      "count": 0,
      "limit": 5,
      "remaining": 5
    }
  ]
}
```

**권한**: `IsAuthenticated`. 본인 데이터만 반환 (서버가 `request.user`로 스코프).

### 4.2 관리자 — 전체 사용량 조회

```
GET /api/v1/admin/billing/usage/?user_id=<id>&year_month=2026-06
Authorization: Token <admin_token>
```

응답: 동일 구조 + `user` 필드 추가. 필터 없으면 전체 설계사 페이지네이션.

### 4.3 관리자 — 구독 수동 변경 (MVP 과금 활성화 게이트)

```
PATCH /api/v1/admin/billing/subscription/<user_id>/
Authorization: Token <admin_token>

{
  "plan_code": "plus",
  "status": "active",
  "expires_at": "2026-07-19T00:00:00Z"
}
```

> **MVP 결제 흐름**: 설계사가 Plus 업그레이드 요청 → 관리자가 계좌이체 확인 → 이 API(또는 Django admin)에서 subscription 수동 변경 → 설계사 화면에서 즉시 Plus 전환 확인.

### 4.4 한도 초과 공통 응답 (402 Payment Required)

> **결정**: 한도 초과 HTTP 상태는 **402 Payment Required**(업그레이드 유도). 429 Too Many Requests 표기는 폐기. (dev/02 §16 정본)

```json
{
  "detail": "이번 달 한도(10건)를 모두 사용했어요.",
  "code": "credit_exhausted",
  "kind": "ocr",
  "membership": "free",
  "limit": 10,
  "used": 10,
  "upgrade_url": "/settings/billing"
}
```

FE는 이 402를 받으면 `UpgradeGuideModal`을 띄운다. 에러 메시지·차단 UI는 사용하지 않는다.

---

## 5. 화면 & UX

### 5.1 사용량 현황 화면 (`/settings/billing`)

- **위치**: 설정 > 요금제 & 사용량
- **접근**: 설계사 본인만 (`IsAuthenticated` + `IsOwner`). 타인 사용량 접근 불가.

화면 구성 (action 코드 = 정본 4종, dev/02 §16):
```
[현재 플랜: 무료]          [Plus 업그레이드]

이번 달 사용량 (2026년 6월)
─────────────────────────────────────────
증권 OCR 분析(ocr)        [====      ]  4 / 10건
AI 비교안내서(ai_compare)  [==        ]  1 / 5건
AI 분析·메시지(analysis)   [===       ]  3 / 10건
판촉물 주문(promotion)     [          ]  0 / 5건
─────────────────────────────────────────
공유링크 생성   무제한
고객 등록       무제한

매월 1일 초기화됩니다.
```

### 5.2 한도 초과 시 UX (소프트 블록)

한도 도달 시 **기능을 차단하지 않는다**. 다음 두 가지 중 상황에 맞게 선택:

**방식 A — 인라인 배너** (해당 기능 카드 위)
```
이번 달 OCR 분석 횟수(10건)를 모두 사용했습니다.
내달 1일에 초기화되거나 → [Plus로 업그레이드]하면 200건까지 사용 가능합니다.
```

**방식 B — 업그레이드 유도 모달** (기능 실행 시도 후)
```
[분석 시작] 버튼 클릭
   ↓
402 응답 수신 (code: credit_exhausted)
   ↓
모달 등장 (UpgradeGuideModal):
  "이번 달 OCR 분석 횟수를 모두 사용했어요.
   Plus로 업그레이드하면 200건까지 사용할 수 있습니다."
  [다음 달까지 대기]  [Plus 업그레이드 →]
```

> **레드라인**: 모달에 "심의완료", "안전한", "보장됩니다" 같은 카피 사용 금지.
> "업그레이드" CTA는 `/settings/billing`으로 이동 (팝업 결제 UI 아님, MVP는 수동).

### 5.3 Plus 업그레이드 안내 페이지 (`/settings/billing/upgrade`)

```
Plus 요금제 안내

[월 29,000원 / 매월 자동 갱신] (추정 — openGaps 참조)

포함:
- OCR 증권 분석   200건/월
- AI 비교안내서   100건/월
- AI 분석 내러티브 200건/월
- AI 카톡 메시지  100건/월

업그레이드 방법:
1. 아래 계좌로 월 이용료를 송금해주세요.
2. 입금자명에 가입 이메일 앞 5자리를 적어주세요.
3. 24시간 내 플랜이 업그레이드됩니다.

[은행명] [계좌번호] (관리자 admin 설정)

문의: hello.fingo.official@gmail.com
```

> MVP는 PG 없음. 수동 확인 후 관리자가 구독 변경. Phase 1.5 이후 PG 자동화.

---

## 6. 관리자 페이지

관리자는 Django Admin + 전용 API로 전체 설계사의 구독·사용량을 관리한다.

### 6.1 Django Admin 등록 모델

```python
# inpa/membership/admin.py

@admin.register(Plan)
class PlanAdmin(admin.ModelAdmin):
    # limit 필드명 = 정본 4종 (ocr / ai_compare / analysis / promotion, dev/02 §16)
    list_display  = ['code', 'display_name', 'price_krw',
                     'limit_ocr', 'limit_ai_compare',
                     'limit_analysis', 'limit_promotion', 'is_active']
    list_editable = ['limit_ocr', 'limit_ai_compare',
                     'limit_analysis', 'limit_promotion', 'price_krw']
    # 코드 배포 없이 한도·가격 직접 수정 가능 (베타: FREE_TIER_UNLIMITED 환경변수로 전역 우회)

@admin.register(Subscription)
class SubscriptionAdmin(admin.ModelAdmin):
    list_display   = ['user', 'plan', 'status', 'started_at', 'expires_at']
    list_filter    = ['plan', 'status']
    search_fields  = ['user__email']
    list_editable  = ['status', 'plan']
    # 수동 결제 확인 후 여기서 status='active', plan=Plus로 변경

@admin.register(UsageMeter)
class UsageMeterAdmin(admin.ModelAdmin):
    list_display   = ['user', 'action', 'year_month', 'count', 'updated_at']
    list_filter    = ['action', 'year_month']
    search_fields  = ['user__email']
    ordering       = ['-year_month', '-count']
```

### 6.2 관리자가 할 수 있는 것

| 작업 | 방법 | 비고 |
|---|---|---|
| Plus 수동 활성화 | Admin > Subscription > status=active, plan=Plus | 결제 확인 후 |
| 한도 일괄 변경 | Admin > Plan > limit 필드 직접 수정 | 전체 Free 설계사 한도 즉시 반영 |
| 특정 설계사 한도 예외 | Subscription을 Plus로 변경 (가격=0, 수동 관리) | 베타 설계사 무료 Plus 제공 |
| 월 사용량 조회 | Admin > UsageMeter 필터 | 코호트 분석, 베타 관찰 |
| 사용량 초기화 | UsageMeter 해당 행 삭제 (수동) | 테스트/CS 처리용 |

---

## 7. 권한 & 가시성

| 데이터 | 설계사(본인) | 설계사(타인) | 관리자 |
|---|---|---|---|
| 본인 구독 상태 | 읽기 O | X (403) | 읽기·쓰기 O |
| 본인 월 사용량 | 읽기 O | X (403) | 읽기 O |
| 전체 설계사 사용량 | X | X | 읽기 O |
| Plan 정의 | 읽기 O (공개 정보) | 읽기 O | 읽기·쓰기 O |
| Subscription 수정 | X (self-upgrade는 향후 PG 구현 후) | X | 쓰기 O |

**구현 원칙**:
- `GET /api/v1/billing/usage/`는 `request.user`로 자동 스코프 (파라미터로 타인 user_id 주입 불가).
- 관리자 엔드포인트는 `/api/v1/admin/` 접두사 + `IsAdminUser` permission 필수.
- `OwnedQuerySetMixin`은 UsageMeter / Subscription에도 동일 적용.

---

## 8. 컴플라이언스 & 면책

| 항목 | 처리 방식 |
|---|---|
| 결제 전 기능 설명 | 요금제 안내 페이지에 "AI 초안, 최종 책임은 설계사에게 있습니다" 면책 고정 |
| 환불 정책 | MVP 수동 결제 = 관리자 판단. 자동 PG 도입 시 약관 명시 필요 (openGaps) |
| 사용량 데이터 보존 | UsageMeter 행 영구 보존 (삭제 금지). 회원 탈퇴 시 익명화 처리 |
| 가격 변경 공지 | Plan 변경 전 가입 설계사에게 이메일 사전 공지 (30일 이상 권장) |
| 개인정보 | UsageMeter에는 action 카운터만 보존. 분석 내용(병력 등)은 미포함 |

---

## 9. 수용기준 (Acceptance Criteria)

| AC | 기준 | 검증 방법 |
|---|---|---|
| AC-B1 | Free 설계사 `ocr` 10건 소진 → 11번째 호출 → **402** `credit_exhausted` | pytest + curl |
| AC-B2 | Plus 설계사 동일 호출 → 200건까지 통과 | pytest |
| AC-B3 | 402 응답에 `upgrade_url` 포함, `code=credit_exhausted`, `kind` 필드 포함 | assert response.data |
| AC-B4 | `GET /billing/usage/` → 타인 user_id 파라미터 주입 시 본인 데이터만 반환 | pytest (보안 격리) |
| AC-B5 | 월 변경 시 (`year_month` 변경) → count 자동 0 리셋(새 행 생성) | pytest |
| AC-B6 | `share_link` / `customer_add` 는 어떤 플랜에서도 차단 없음 | pytest |
| AC-B7 | 관리자 Admin > Subscription 수정 → 해당 설계사 `/billing/usage/` 즉시 Plus 반영 | 실측 (Admin 수정 → API 재호출) |
| AC-B8 | `UsageMeter._check_and_consume` race condition: 동시 요청 10건 → count 정확히 10 (select_for_update) | pytest concurrent |
| AC-B9 | `FREE_TIER_UNLIMITED=True` 설정 시 모든 action 한도 체크 우회(무차감 통과), `False` 시 정상 집계 | pytest (settings override) |

---

## 10. 빌드 순서

```
[Phase 1 — MVP 슬라이스 이후]
  Plan + Subscription + UsageMeter 모델 생성
  → makemigrations + migrate
  → 초기 데이터: Plan(free/plus) 시드
  → post_save signal: User 생성 시 Free Subscription 자동 생성
  → _check_and_consume 유틸(foliio credit.py 확장, dev/03) + LimitExceeded 예외 + FREE_TIER_UNLIMITED 스위치
  → OCR detect 뷰에 계측 훅 삽입 (kind='ocr')
  → GET /billing/usage/ 설계사 자가 조회
  → Django Admin 등록 (관리자 수동 운영 시작)
  → FE /settings/billing 사용량 현황 화면
  → 402 소프트 블록 + UpgradeGuideModal (FE)
  → 이메일 발송(Resend, dev/20): 구독 변경 안내 이메일

[Phase 1.5 — Plus 과금 ON]
  → 업그레이드 안내 페이지 (계좌이체 수동 안내)
  → Admin 구독 수동 변경 운영 루틴 확정 + FREE_TIER_UNLIMITED=False flip
  → AI 비교안내서 / 판촉물 주문 계측 훅 삽입 (kind='ai_compare' / 'promotion', Phase 1.5 활성화 시)

[Phase 2+ — 자동 결제 PG 연동] ← openGaps
  → PG 선택·계약 (토스페이먼츠/포트원 등)
  → Subscription.pg_subscription_id 활성화
  → 웹훅 기반 결제 상태 동기화
  → 환불·해지 자동화
  → 결제 영수증 이메일 발송
```

---

## openGaps (결정 필요 항목)

| # | 항목 | 기본값(현재) | 결정 필요 시점 |
|---|---|---|---|
| G1 | Plus 월 요금 확정 (현재 29,000원 추정) | 29,000원/월 | Phase 1.5 과금 ON 전 |
| G2 | 자동 결제 PG 선택 (토스페이먼츠 / 포트원 / 나이스페이 등) | MVP = 수동 계좌이체 | Phase 2 |
| G3 | 환불 정책 문안 및 부분환불(일할) 처리 방식 | 미결 (관리자 재량) | PG 도입 전 |
| G4 | ~~베타 기간 한도 무차감 운영 방식~~ **확정**: `FREE_TIER_UNLIMITED` 환경변수 스위치 채택(Plan 한도 상향·별도 Beta Plan 불필요). 베타=`True`, 정식=`False` flip. | `FREE_TIER_UNLIMITED=True` (베타 기본) | **확정 — 재결정 불필요** |
| G5 | 팀 플랜(Phase 3+) 구조 — 대표 1계정 + 소속 설계사 N명 공유 한도 vs 개별 구독 | 개별 구독 유지 | Phase 3 |
| G6 | 가격 변경 시 기존 가입자 처리 — 즉시 적용 vs 갱신월부터 | 갱신월부터 (보수적) | PG 도입 전 약관 명시 |
| G7 | UsageMeter 히스토리 보존 기간 및 정기 정리 cron 스케줄 | 무기한 보존 (MVP 단순화) | 6개월 운영 후 재검토 |
