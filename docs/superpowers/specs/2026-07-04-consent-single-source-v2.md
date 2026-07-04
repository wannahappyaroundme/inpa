# Spec: 동의 문구 단일 소스화 + 버전 스탬프 + 재동의 게이트 (LB-2 fix, 동의 v2)

> Launch-blocking #1 from `docs/prelaunch-review/` (panel execution order position 1; compliance persona sequenced it ahead of everything).
> Problem (audit LB-2): the /c overseas-consent item and the OCR consent modal still claim "보유 기간: 처리 후 즉시 삭제" for data sent to Claude, contradicting the corrected privacy policy ("Anthropic의 데이터 처리·보관 정책에 따름 · 학습 미사용"). Production consents are being recorded against a false retention claim; /d's overseas checkbox states no retention at all. Cross-border consent under PIPA must state the recipient's retention accurately.

## Decisions (locked, do not re-litigate)

1. **Single source:** new module `inpa_be/inpa/customers/consent_texts.py` — `CONSENT_TEXTS_VERSION = "v2-2026-07-04"` + per-scope dict `{scope: {title, body, retention}}` for scopes overseas_medical(국외이전) / personal_info / third_party / marketing. Correct overseas retention wording: **"보유 기간: Anthropic의 데이터 처리·보관 정책에 따릅니다(입력 정보는 AI 학습에 사용되지 않아요)."** Match the tone/wording of `inpa_fe/app/legal/privacy/page.tsx:79,84` (which is already correct — do NOT touch legal pages).
2. **Public read endpoint:** `GET /api/v1/consent-texts/` (AllowAny, ScopedRateThrottle reuse an existing generous scope, plain JSON `{version, texts}`). FE surfaces render from it with a LOCAL FALLBACK equal to the v2 wording (never the old one).
3. **BE surfaces use the module directly:** `customers/public_consent.py` (/c GET items) replaces its hardcoded strings; `insurances/self_diagnosis.py` unchanged flow but any rendered consent text (if server-provided) comes from the module.
4. **Version stamping:** every `ConsentLog` create stamps `doc_version = CONSENT_TEXTS_VERSION` (surfaces: /c POST, /d submit, /p intro lead, planner-attested create). `ConsentLog.doc_version` ALREADY EXISTS as a CharField — verify; if absent, add migration (CharField, default "", blank). Mind the SQLite-vs-PG trap for any migration.
5. **Re-consent gate (the compliance teeth):** new helper `customers/consent_texts.py::has_current_overseas_consent(customer) -> bool` = exists ConsentLog(customer, scope=overseas, subject=customer_self, revoked-null-safe, doc_version == CONSENT_TEXTS_VERSION). The two Claude gates — OCR upload 412 check in `insurances/views.py:~335` and medical create 412 in `customers/views.py:~221` — switch from `consent_overseas_at is None` to `not has_current_overseas_consent(customer)`. Effect: consents collected under the old wording no longer open NEW Claude calls until the customer re-consents via a fresh /c or /d (v2 text). Existing stored analyses stay untouched. Keep the 412 code `CONSENT_OVERSEAS_REQUIRED` unchanged; ADD field `"reason": "reconsent"` in the 412 body when an older-version consent exists (vs `"reason": "missing"` when none), so FE can phrase it well.
6. **`consent_overseas_at` field semantics unchanged** (display/history). Do not migrate or clear it. The gate simply stops trusting it alone.
7. **FE:**
   - `lib/api.ts`: `getConsentTexts()` + types; extend the OCR 412 handling only if needed (code already routes to the consent modal).
   - `components/ocr-upload.tsx:~345`: replace the hardcoded "처리 후 즉시 삭제" line with text from `getConsentTexts()` (fallback = v2 wording). When 412 reason=reconsent, the pre-upload consent prompt copy becomes positive-framed: e.g. "동의 안내문이 새로워졌어요. 고객에게 동의 링크를 다시 보내면 바로 분석할 수 있어요." (NO negative/blame phrasing).
   - `app/d/[ref]/page.tsx` overseas checkbox (~line 270 area): append the retention sentence from consent-texts (fallback inline v2 wording).
   - `/c` page renders items from the BE GET already — verify it displays the new body/retention untouched.
8. **Out of scope:** consent revoke endpoint (that is LB item #10), cron/retention deletion, re-consent notifications/nudge lists, legal pages, README/CLAUDE.md changelog (done at deploy time by the orchestrator).

## Redlines (project standing rules — violating any = review failure)

- Customer-facing copy: benefit + next action only; NO negative framing ("불가", "안 됩니다", "준비 중"), NO em-dash (—) in rendered strings, plain easy Korean.
- planner_attested consents must STILL never satisfy the gate (regression-test it).
- Legacy consent-token compat (bare-int token → overseas scope) must keep working (`customers/tokens.py` untouched).
- Never hardcode Claude model ids; no new env flags needed.

## Tests (BE, add to existing suites)

1. `GET /consent-texts/` returns version + all scopes, correct retention wording (assert "즉시 삭제" ABSENT, "Anthropic" present).
2. /c POST stamps doc_version=v2; /d submit stamps v2; planner-attested create stamps v2.
3. OCR upload gate: (a) no consent → 412 reason=missing; (b) old-version customer_self consent (create log with doc_version="") → 412 reason=reconsent; (c) fresh v2 customer_self consent → passes gate (mock/skip actual Claude call as existing tests do); (d) planner_attested v2 consent → still 412.
4. Medical gate same version logic (with ANALYZE_MEDICAL_ENABLED override as existing tests do).
5. Existing suites stay green: full `python manage.py test inpa` must pass (455+ tests).

## Verification gates (before reporting done)

- `python manage.py check` clean; full BE suite green; grep confirms "즉시 삭제" no longer appears in `inpa_be/inpa/**` nor `inpa_fe/{app,components}/**` rendered strings.
- FE: `npm run build` + `npm run lint:copy` green.
- Report: files changed, migration count (expect 0 or 1), test totals before/after, the exact new wording rendered on each of the 3 surfaces.
