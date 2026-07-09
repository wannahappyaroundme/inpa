# Manager 요금제 팀 기능 권한 게이트 — Spec

> 2026-07-09. PM 지시("팀 기능을 manager 요금제로 바꿔줘"). 현재 팀/매니저 기능은 인증 설계사 누구나 무료 사용 → Manager 요금제(code='manager', 19,900원) 가입자만 쓰게 게이트.

## 핵심 설계 판단
- **게이트는 만들되 기본 비활성(dormant)**: `MANAGER_PLAN_GATE_ENABLED` env 플래그, **default False**. 이유: 베타 중엔 Manager 결제자 0명(수동 계좌이체·FREE_TIER_UNLIMITED=True)이라 지금 켜면 전원 팀기능 잠김. 코드베이스 관례(`COMPARE_AI_ENABLED` = ship dormant, 유료 전환 시 env로 flip, 재배포 무관). FREE_TIER_UNLIMITED(쿼터 우회)과는 **독립**(이건 capability 게이트).
- **plan 코드 하드체크 대신 capability 필드**: `Plan.can_use_team` bool 추가(관리자가 Django Admin에서 재배포 없이 조정 가능, 나중에 다른 플랜에도 부여 가능). seed_billing이 manager 플랜만 True.

## 현재 상태 (탐사)
- 게이트 대상 BE: `GET /api/v1/manager/dashboard/`(accounts/manager.py::ManagerDashboardView) · `POST /api/v1/manager/invite-link/`(accounts/invite.py::TeamInviteLinkView). 둘 다 현재 `[IsAuthenticated, IsEmailVerified]`만. `GET /api/v1/manager/invite-info/`는 **공개 유지**(가입 시 초대장 조회, 초대받는 사람 토큰 기반).
- billing: `Plan.PLAN_CODE`에 'manager' 존재. `Subscription`(user OneToOne, plan, status, expires_at, `is_plus()` 미사용). `credit.py::check_and_consume`가 Subscription 조회 패턴(인라인). `RuntimeConfig.free_tier_unlimited`.
- Manager 플랜: seed_billing이 생성(19900, 한도 Plus와 동일). **capability 필드 없음**(설명만 팀관리 명시).
- 권한: `core/permissions.py`(IsOwner/IsAdmin/IsEmailVerified 패턴). 402 응답 shape = `compare.py::_credit_exhausted_response`({detail, code, membership, limit, used}, HTTP 402).
- FE: `/manager`(app/manager/page.tsx, useAuthGuard만) + nav(app-nav.tsx:95 `managed_agents_count>0`이면 노출) + upgrade-modal(PLAN_PRICING에 plus/super만, manager 없음). `getMyPlan()`(usage에서 파생).

## 설계

### 1. BE — capability 필드 + 헬퍼 (billing 마이그레이션, additive)
- `Plan.can_use_team = BooleanField(default=False)`. seed_billing: manager 플랜 `defaults`에 `can_use_team=True`(get_or_create라 기존 편집 보존; 신규 생성 시만). 재시드로 기존 manager 행에 True 보장하려면 seed_billing에서 manager는 `can_use_team`을 명시 set(다른 필드처럼 get_or_create defaults + 이미 존재 시 update 없이 두되, 최초 도입이라 True 반영 필요 → seed에서 manager.can_use_team를 항상 True로 보정하는 1줄).
- `billing/credit.py::user_can_use_team(user) -> bool`: 활성·미만료 Subscription의 `plan.can_use_team` (없으면 free → False). 게이트 OFF면 항상 True(아래 뷰에서 처리).

### 2. BE — 게이트 (뷰 레벨, 부드러운 402/403)
- `settings.MANAGER_PLAN_GATE_ENABLED = env.bool(default=False)`.
- `ManagerDashboardView.get` + `TeamInviteLinkView.post` 시작에: `if settings.MANAGER_PLAN_GATE_ENABLED and not user_can_use_team(request.user): return Response({code:'manager_plan_required', detail:'팀 관리는 Manager 요금제에서 이용할 수 있어요.', plan:'manager'}, status=402)`. 402(업그레이드 유도, 402 관례 재사용) 또는 403 — 402 채택(업그레이드 모달 트리거와 일관). 게이트 OFF(기본)면 현행 그대로.
- `invite-info`는 무변경(공개).

### 3. FE — 업그레이드 안내
- `lib/api.ts`: manager API 호출이 402 `manager_plan_required` 받으면 ApiError.code로 구분.
- `/manager` 페이지: dashboard 조회가 `manager_plan_required`면 대시보드 대신 **'Manager 요금제 안내' 카드**(팀 기능 소개 + 업그레이드 CTA → 기존 계좌이체 데스크/upgrade-modal). nav는 현행(managed_agents_count>0) 유지하되, 게이트 시 페이지에서 안내.
- `components/upgrade-modal.tsx` `PLAN_PRICING`에 manager(19900, VAT 별도) 추가 + capability 안내 문구(팀 관리 전용). §6 카피(투자·부담↓·딱 맞음, em-dash 금지).
- 카피: 부정형 금지("이용할 수 없어요" 대신 "Manager 요금제에서 팀을 관리할 수 있어요" + 자기적격 CTA).

### 4. 테스트 (BE)
- 게이트 OFF(기본): 인증 설계사 누구나 dashboard 200 + invite-link 200(현행 보존 회귀).
- 게이트 ON(`@override_settings(MANAGER_PLAN_GATE_ENABLED=True)`) + Manager 플랜 없음: dashboard 402 `manager_plan_required`, invite-link 402.
- 게이트 ON + 활성 Manager 구독: 200.
- 게이트 ON + 만료 Manager 구독: 402(만료 무효).
- invite-info는 게이트와 무관 공개 유지.
- seed_billing: manager 플랜 `can_use_team=True`, free/plus/super는 False(단 super는? PM 확정 전까지 False — Manager 전용).
- FREE_TIER_UNLIMITED와 독립(둘 다 조합해도 게이트는 MANAGER_PLAN_GATE_ENABLED만 따름).

### 마이그레이션 / 컴플라이언스
- 마이그레이션 1(billing: Plan.can_use_team). additive.
- **기본 비활성이라 현행 동작 무변경**(베타 사용자 잠김 없음). 유료 전환 시 env flip.
- 고객 대면 무변경. §6 카피. 개인정보 무관(집계 대시보드는 기존 그대로).
