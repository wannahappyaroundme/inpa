# Feature Extraction (Step 3)

> 22 personas raised **88 raw proposals**; Round 3 merged/killed them into **33 canonical features**. Verifier: every raw proposal accounted for (0 lost, 0 invented). "Survived to": R3 = in the final agreed list · R2 = survived critique but deferred/killed at convergence · R1 = killed by Round-2 critique.
> **Panel tier** is the debate outcome (Step 2). Final ranked tiers come from Step 4 quantitative scoring and will be appended below.

## Canonical feature table

| # | Feature | Description | Proposed by | Survived to | Status | Panel tier |
|---|---|---|---|---|---|---|
| 1 | **Single-source consent copy + versioned re-consent sweep** | One BE-served versioned consent-text source rendered by /c, the OCR consent modal, and /d (fixing the '즉시 삭제' drift, LB-2); consent-text version stamped onto every ConsentLog row; corrective re-consent notice pushed to the defective-consent cohort; shared-string approach extends check-copy.js so consent-copy drift becomes a CI failure. | Dr. Im Kyu-tae (Compliance), Park Ji-won (Investor), Moon Jae-hyun (Designer), Choi Ara (Designer) | R3 | partially built | launch-blocking |
| 2 | **Identity-true seed upsert, seeds off the boot path** | Rewrite seed_normalization (and seed_jobs semantics) as natural-key upserts that never delete coverage-tree leaves or NormalizationDict rows, and move the migrate+seed chain out of render.yaml startCommand into a deploy-only, version-stamped release step with a rollback runbook. | Seo Yeon-ju (Investor), Kang Min-ho (CEO), Oh Se-ra (PM), Baek Jun-seo (PM) 외 | R3 | partially built | launch-blocking |
| 3 | **Always-on backend for customer-facing links** | Pay for a Render always-on instance so /b, /d, /c, /p, /s and email-verify never hit a 30-60s cold start (H-4); replaces all keep-alive ping variants (residential-server and $0 external pings killed as unmonitored single points of failure). | Daniel Cho (Investor), Lee Ha-eun (CEO), Nina Kwon (PM), Ryu Chan-mi (Marketer) 외 | R3 | new | launch-blocking |
| 4 | **Nightly encrypted pg_dump + rehearsed restore + retention cycle** | Automated nightly encrypted pg_dump of Neon Postgres shipped to the founder's physical server (plus R2 media manifest and a NormalizationDict/admin-verified export), with a written restore runbook, a scheduled restore drill, separated key custody, and a rolling retention cycle disclosed in the 처리방침. | Park Ji-won (Investor), Baek Jun-seo (PM), Jeong Woo-jin (Developer), Amelia Son (Developer) 외 | R3 | new | launch-blocking |
| 5 | **Single scheduled job runner with dead-man heartbeat** | One management-command entry point fired by an external scheduler (GitHub Actions cron or founder's server) that powers the reminder producers, PIPA retention deletion (self-diagnosis lead PII, ConsentLog IPs, orphaned R2 media), and the nightly backup, each job emitting a dead-man's-switch heartbeat. | Amelia Son (Developer) | R3 | new | launch-blocking |
| 6 | **Reminder producer + 8am in-app morning digest** | Daily job on the runner generating birthday_soon, expiry_soon, consult_reminder, task_due (and share_unread) into the existing notification inbox, delivered as one 8am KST in-app digest; the email digest leg is deferred until Resend domain auth is verified end-to-end (H-8); /settings/reminders un-hides when this ships. | Daniel Cho (Investor), Kang Min-ho (CEO), Tommy Yoon (CEO), Oh Se-ra (PM) 외 | R3 | partially built | launch-blocking |
| 7 | **Launch trust sweep: purge demo data, fix placeholders, hide ghost surfaces** | One coordinated pass: deactivate the 4 live [DEMO] plans + demo accounts (LB-3, one Render-Shell session); resolve the landing '월 N건' placeholder (H-5); remove the 3 Kakao/Naver '준비 중' rows and dead in-pa.vercel.app references; hide the imageless 판촉물 storefront and /settings/reminders behind has-real-backing gates until producers/images exist; close the board-attachment dead-end. | Kang Min-ho (CEO), Lee Ha-eun (CEO), Oh Se-ra (PM), Nina Kwon (PM) 외 | R3 | partially built | launch-blocking |
| 8 | **/s never-dead CTA (tel: layer + tracked callback lead)** | When the planner has no WorkHour, the /s '담당 설계사에게 물어보기' CTA gets an instant tel:/copyable-contact layer (works in the KakaoTalk webview today) plus a tracked callback-request layer creating a lead and planner notification via the existing /d,/p plumbing; verify the planner phone exists in the PII-minimized payload. | Nina Kwon (PM), Moon Jae-hyun (Designer), Yang Mi-sook (Agent) | R3 | partially built | launch-blocking |
| 9 | **PII log scrub + legal identity fill** | Remove the 200-char raw-policy JSON stdout print on Claude parse failure, add a Django LOGGING config with PII redaction, and fill CPO name, 사업자등록번호, and 통신판매업 신고 on terms/privacy pages now that the business is registered. | Dr. Im Kyu-tae (Compliance) | R3 | new | launch-blocking |
| 10 | **Consent withdrawal endpoint + retention automation** | Implement /c-token and in-app consent revocation writing ConsentLog.revoked_at, plus scheduled deletion (riding the job runner) for never-converted self-diagnosis lead PII, ConsentLog raw IPs, and orphaned R2 media on account deletion. | Dr. Im Kyu-tae (Compliance) | R3 | partially built | launch-blocking |
| 11 | **Sentry + PII-safe error monitoring + synthetic probes** | Set SENTRY_DSN in render.yaml/Vercel, add FE error tracking, and run an external synthetic check exercising /healthz, a real /b booking link, and the email-verify path, so the stack's deliberately-silent failure modes (console email fallback, credit fail-open, /home catch-to-null) finally surface. | Jeong Woo-jin (Developer), Amelia Son (Developer) | R3 | partially built | launch-blocking |
| 12 | **계좌이체 billing desk + credible pricing surface** | A real ask-for-money path before KICC: confirmed Plus price, rewritten 402/UpgradeModal copy with bank-transfer instructions, 세금계산서/deposit-confirmation steps, coupon-code entry, and an admin flow a non-developer can run to record a payment and grant entitlement through the expiry-aware coupon engine. | Kang Min-ho (CEO), Tommy Yoon (CEO), Baek Jun-seo (PM), Han Do-yun (Designer) 외 | R3 | partially built | launch-blocking |
| 13 | **Meritz data provenance purge (phased)** | Phase 1 before launch: remove the 3 committed Meritz job-grade files from repo HEAD + tighten access. Phase 2 as one coordinated post-launch maintenance window: git-history rewrite plus KIDI/licensed re-sourcing with a kidi_cd natural-key bridge migration so seed_jobs sync/prune cannot delete the 707-row master or SET_NULL customer job codes. | Seo Yeon-ju (Investor) | R3 | new | launch-blocking |
| 14 | **Residual loading skeletons on token pages** | Ordinary branded loading/skeleton states on /b, /d, /c, /s designed for a 2-5 second residual wait after the warm path lands; the 30-60s designed wake screen and auto-retry are explicitly killed. | Choi Ara (Designer), Han Do-yun (Designer) | R3 | new | mvp-candidate |
| 15 | **Invited 계좌이체 paid pilot + founder concierge (Founding 20)** | 20-30 invited agents at full price via manual bank transfer: activity-selected hungry rookies plus one or two founding 지점, founder-led concierge onboarding (first 증권 upload, PlannerBaseline set, activation tracked via /admin/usage), fulfilled through the coupon rail; the free tier stays open as control and distribution substrate. | Park Ji-won (Investor), Daniel Cho (Investor), Lee Ha-eun (CEO), Tommy Yoon (CEO) | R3 | partially built | mvp-candidate |
| 16 | **Activation funnel instrumentation + UTM capture + dead-man funnel alarm** | Define activation (first policy analyzed + first customer-facing link sent within 7 days), instrument signup → first customer → first analysis → first shared link as a cohort funnel in the admin console on the existing analytics app; capture UTM/source at signup; alert when signups occur but email verifications flatline. | Daniel Cho (Investor), Oh Se-ra (PM), Ryu Chan-mi (Marketer) | R3 | partially built | mvp-candidate |
| 17 | **Claude per-call cost + parse-outcome telemetry** | One structured, PII-scrubbed record per Claude call at the single call gate: token cost in won, feature, user, parse outcome, and per-carrier unmatched-coverage rate surfaced in the admin console; replaces the raw stdout JSON print as failure data. Interim: Tommy's usage-metering + Anthropic-console spreadsheet for the pilot cohort. | Park Ji-won (Investor), Gu Bon-cheol (Developer) | R3 | partially built | mvp-candidate |
| 18 | **Golden-set normalization eval harness** | A CI-run labeled corpus (harvested from prod unmatched logs and concierge sessions, de-identified/provenance-clean, never from carrier documents or samples/) mapping real coverage names to standard-tree leaves, with an accuracy threshold gating dict and matcher changes. | Gu Bon-cheol (Developer) | R3 | new | mvp-candidate |
| 19 | **Daily call list (오늘 전화 리스트)** | A pull-based morning queue of ~10 customers ranked by 무접촉 days, 만기 proximity, and funnel stage, each with one-tap tel:/sms: and the matching 화법 prefill — pure assembly of shipped primitives (staleness cue, contact logs, stage deep-links). | Kwak Dong-hyun (Agent) | R3 | partially built | mvp-candidate |
| 20 | **KakaoTalk link preview cards (static first, per-token after warmth)** | OG title/description/image for /b, /d, /p links: static branded per-route cards served from Vercel at launch (zero BE dependency, adds /p's missing noindex meta), upgraded to per-agent personalized cards once the always-on path lands so Kakao's scraper never hits a sleeping BE; Kwak's IG Story half becomes a per-planner downloadable image kit; prewritten solicitation captions dropped. | Moon Jae-hyun (Designer), Kwak Dong-hyun (Agent) | R3 | new | mvp-candidate |
| 21 | **Truthful state matrix pass** | Distinct empty / loading / error / data-unavailable states per route: /home's catch-to-empty replaced with a visible retry state, and a heatmap zero-state that reads differently from 'no data yet' so a wiped analysis is noticed by the agent before their customer. | Choi Ara (Designer) | R3 | partially built | mvp-candidate |
| 22 | **SEO and crawl baseline** | robots.txt + sitemap.xml, the missing FE noindex on /p, and purge of dead in-pa.vercel.app references — a day of hygiene work. | Ryu Chan-mi (Marketer) | R3 | new | mvp-candidate |
| 23 | **Recommendation-word blacklist (CI + server-side share check)** | Extend check-copy.js RULES with a §97/금소법 blacklist (추천·갈아타·해지하세요·더 유리 and variants) on the 5 customer-facing surfaces, plus Cha's server-side render-time check on the /s share payload and any future AI-draft output, where free-typed 승환 language actually leaks. | Dr. Im Kyu-tae (Compliance) | R3 | partially built | mvp-candidate |
| 24 | **Team invite onboarding link (consent-clean)** | Manager generates one signup link that pre-sets Profile.manager and affiliation ONLY; the rookie chooses their share level (none/activity/full) themselves after signup, defaulting to none, so a whole 지점 can onboard in one education session without coerced consent. | Sophia Jang (Marketer), Cha Eun-bi (Agent) | R3 | new | mvp-candidate |
| 25 | **Multi-seat org code billing (지점 invoice, not a tier)** | Extend the admin coupon (plan/duration/max_redemptions already built) into an org-tagged N-seat code: a 지점장 pays one 계좌이체 invoice with 세금계산서, admin issues one code redeemable by N agents. The GA Team Plan 'manager seat tier' is collapsed into this: sell an invoice, don't build a tier; first sale = exactly one 지점, after the individual pilot shows activation. | Sophia Jang (Marketer), Seo Yeon-ju (Investor) | R3 | partially built | mvp-candidate |
| 26 | **Community dictionary feedback loop** | In-heatmap 'this 담보 looks wrong' flag routed into the existing admin unmatched-log/normalization review queue; contributor-credit gamification cut. | Lee Ha-eun (CEO) | R3 | partially built | post-launch |
| 27 | **Immutable comparison snapshot archive** | Point-in-time record of every shared comparison as a denormalized JSON blob on the existing share record (literal coverage names/figures, consent state, dict+matcher version stamp, timestamp), zero FKs to the standard tree, PII-minimized mirroring the /s payload, with a defined retention TTL and inclusion in withdrawal/deletion automation. | Cha Eun-bi (Agent) | R3 | new | post-launch |
| 28 | **Agent referral coupon loop** | Per-agent invite code granting a capped Plus-month coupon to both sides, triggered on the referred agent's first completed analysis (not email-verify), tagged for K-factor and 지점 attribution; goes live only once paid mode makes the coupon worth something. | Kim Tae-woo (Marketer) | R3 | new | post-launch |
| 29 | **Persistency module (13/25회차)** | Per-agent and team persistency rates elevated from the existing 유지 회차 타이머 and retention donut — contract-date arithmetic only, never 연체/미납/payment-status claims; the 만기/회차 reminder leg ships at launch via the reminder cron. | Seo Yeon-ju (Investor) | R2 | partially built | post-launch |
| 30 | **판촉물 real imagery + manager-facing page** | Finished product photos for the 7 seeded promotion samples (shot from real fulfilled orders, category-by-category as demand appears) plus a 지점장-facing marketing/consent-explainer section; the /p intro-card visual kit half was split out into the KakaoTalk preview-card workstream. | Han Do-yun (Designer), Sophia Jang (Marketer) | R2 | partially built | post-launch |
| 31 | **Paid-only launch via trial coupons** | Flip FREE_TIER_UNLIMITED off at launch with auto-issued 14-day Plus trial coupons for every signup, no perpetual free tier. | Tommy Yoon (CEO) | R1 | partially built | rejected |
| 32 | **Manager review queue for comparisons** | A pre-send manager approval step on a rookie's comparison before its customer-facing /s link can go out. | Cha Eun-bi (Agent) | R2 | new | rejected |
| 33 | **In-App 후기 Capture Engine** | Post-3rd-analysis testimonial prompt with coupon reward, feeding the landing page and community posts. | Kim Tae-woo (Marketer) | R2 | new | rejected |

## Panel rationale (from Round 3)

### Launch-Blocking
1. **Single-source consent copy + versioned re-consent sweep** — Compliance veto holder sequenced it FIRST, even ahead of LB-1: consents recorded on a retracted retention claim are defective under PIPA and the cohort compounds daily; the policy-versions admin already anchors versioning, so this is wiring plus a re-consent notice. Park conceded her sweep into the structural cure.
2. **Identity-true seed upsert, seeds off the boot path** — The LB-1 fix in the specific form the developers demanded: identity-preserving so admin_verified/ocr_learned dict rows (the acquirable IP) and existing heatmaps survive; seven near-duplicate proposals collapsed into one workstream. Jeong's condition adopted: code fix first, infra spend never cited as the LB-1 remediation.
3. **Always-on backend for customer-facing links** — Nine warm-link proposals converged on the paid instance after Amelia/Baek's SPOF argument killed the ping hacks (a dead ping silently restores cold starts with no monitoring under H-2) and Kang/Tommy's 'pay the seven dollars' framing won; combined with the seed fix it closes H-4 and LB-1's wake trigger together, before any field demo or invite push.
4. **Nightly encrypted pg_dump + rehearsed restore + retention cycle** — H-3 committed fix, $0 via founder fact 3; the panel adopted Baek's 'a backup you've never restored is a rumor' (the drill is the deliverable) and Dr. Im's condition that the backup box is a PIPA 개인정보처리시스템 needing encryption and a disclosed retention schedule so H-7 withdrawal stays real; Gu sequenced it before any further seed changes touch prod.
5. **Single scheduled job runner with dead-man heartbeat** — The audit's named root cause is that no scheduler exists anywhere in repo or render.yaml; the panel (Jeong, Baek, Gu withdrawing their own crons into it) agreed one primitive closes H-1, H-3, and the PIPA retention mediums together, with Baek's heartbeat folded in because this stack fails silent by habit (H-2).
6. **Reminder producer + 8am in-app morning digest** — H-1 is the committed CRM promise-keeper and nine personas proposed the same cron; Yang's 3,000-customer field evidence settled the digest-over-pings shape, and Oh Se-ra's condition (in-app first, email only after transport verification) was accepted so the fix does not itself ride a fail-silent path. The read side is fully built, so this is maximum value per line of code.
7. **Launch trust sweep: purge demo data, fix placeholders, hide ghost surfaces** — Nine overlapping cut/hide/fix proposals merged into one hours-scale pass; the hide-판촉물 camp beat the pre-launch imagery shoot (Tommy/Moon/Ara: hours vs weeks, and 'a prettier lie than 이미지 없음'), and the UI-may-only-show-real-states rule won unanimously as the cheapest trust protection at first touch.
8. **/s never-dead CTA (tel: layer + tracked callback lead)** — The audit's medium finding sits on the one page a customer holds in their own hand and the fix is wiring on plumbing that already fires; Moon conceded Nina's tel: fallback as layer one and Yang made 'no dead buttons on customer surfaces before launch' a condition of trading away her ping; Han's copy caution ('곧 연락드려요' must not promise third-party behavior) incorporated.
9. **PII log scrub + legal identity fill** — H-6 is a committed fix unblocked by founder fact 2, the stdout leak sits outside every disclosed retention boundary, and Dr. Im's veto condition — 통신판매업 신고 before the first won is charged even via 계좌이체 — makes this a hard precondition of the billing desk; no one contested it.
10. **Consent withdrawal endpoint + retention automation** — H-7 is a statutory PIPA right the UI already promises ('언제든 수신을 거부할 수 있어요'); fields and copy exist, only the mechanism is missing, and the retention jobs share the job-runner primitive so the marginal cost is low. Compliance veto voice; unchallenged in rounds 2-3.
11. **Sentry + PII-safe error monitoring + synthetic probes** — H-2 committed; SDK and init code already exist so this is configuration, and the panel repeatedly used 'no Sentry' as the reason other risks are invisible (H-1 silent death, funnel death, paid enforcement). The LOGGING-redaction half is shared work with the PII log scrub. Cheapest risk-per-hour on the register.
12. **계좌이체 billing desk + credible pricing surface** — Five proposals described the same missing piece of the audit's paid-flip cliff: the toggle, 402 wiring, and coupons are built, only the purchase motion and honest copy are absent, and founder fact 2 makes 계좌이체 the launch path. Dr. Im's sequencing binds it behind the legal-identity fill; Han's framing won — the manual step must look like an invoice, not a workaround.
13. **Meritz data provenance purge (phased)** — Park and Seo held the diligence-landmine line (provenance findings retrade deals) while Jeong and Gu's feasibility objections reshaped the mechanics: a naive filter-repo force-push over shared live branches plus a data-file swap into a sync/prune seeder would break prod, so the panel split it — cheap HEAD purge pre-launch, deliberate rewrite/re-source later.

### MVP candidate
14. **Residual loading skeletons on token pages** — Amelia's kill-shot on wake theater stood (no KakaoTalk webview user survives 60 seconds, auto-retry hammers two sync workers mid-boot) and Ara/Han conceded 'independent of infra' was the wrong frame; the salvageable skeleton half ships as polish layered on the always-on fix, not as the H-4 mitigation.
15. **Invited 계좌이체 paid pilot + founder concierge (Founding 20)** — The panel's replacement for the killed paid-only launch: same willingness-to-pay data with no funnel damage. Tommy's full-price/20-cap discipline beat Ha-eun's 100 discounted seats, Kwak's select-on-activity rule beat prestige recruiting, Sophia's founding-지점 density folded in; concierge sessions double as V0-dict verification and hand-collected disclosed testimonials.
16. **Activation funnel instrumentation + UTM capture + dead-man funnel alarm** — Three near-identical proposals merged; the north-star analytics substrate exists so this is wiring, and without it the panel cannot verify the launch-blocking fixes worked (H-2 corollary) or let usage data arbitrate the post-launch list. Ships in launch week rather than gating the door.
17. **Claude per-call cost + parse-outcome telemetry** — Gu's 'half an instrument' critique merged cost and quality into one logger at the same choke point: won-per-call alone cannot decide OCR_VERIFY's 2x spend, and unmatched-rate alone cannot price the ₩29,000 placeholder. Amelia defended it as the cheapest observability win; prerequisite data for pricing, the verify-flag decision, and the golden-set corpus.
18. **Golden-set normalization eval harness** — Seo underwrites the dict as the only acquirable IP and Ha-eun needs it as the merge gate for her community loop; Daniel's modification won on corpus sourcing (prod unmatched logs, not pre-launch hand-labeling) and Seo's provenance condition prevents recreating the Meritz exposure inside CI. Sequenced after the identity-true seed fix so verified rows stop being destroyed.
19. **Daily call list (오늘 전화 리스트)** — The most-defended new feature in Round 2 (Oh Se-ra, Nina, Ara, Yang, Cha all kept it): the best DAU lever on the board, immune to silent cron death because it renders at page load, and it differentiates against the real incumbent, KakaoTalk + Excel, on 'who do I call before ten'. Migration zero.
20. **KakaoTalk link preview cards (static first, per-token after warmth)** — Universally recognized as the customer's true first impression, rendered in the 단톡방 before any cold start bites, and differentiation no 토스 보험파트너 bare link offers. Nina/Ara's scraper-timeout objection set the static-first sequencing; Dr. Im's veto killed the prewritten captions (Inpa cannot author agent solicitation advertising subject to carrier/GA 심의).
21. **Truthful state matrix pass** — Moon funded it fully in Round 2 as 'the cheapest monitoring the product can ship' given H-2 and LB-1 wipes rendering as ordinary emptiness; kept as Ara's trade for conceding the wake screen. The heatmap and /home pieces ride launch week; the full route matrix follows.
22. **SEO and crawl baseline** — Kept with Kim Tae-woo's reframe accepted: this is trust plumbing and table-stakes hygiene, not an acquisition channel — 설계사 discovery lives in Naver 카페 and GA 교육 rooms, so no further content hours are diverted to Googlebot.
23. **Recommendation-word blacklist (CI + server-side share check)** — Closes §7's noted asymmetry (the never-recommends posture is guarded only by structure + human review; dev/14's automated blocker was never built) and LB-2 proved copy drifts. Cha Eun-bi's modification was adopted: the CI lint alone misses free-text, so the runtime payload check is the load-bearing half.
24. **Team invite onboarding link (consent-clean)** — The manager FK and 3-level consent exist with no adoption path (§3), and this is the prerequisite bridge for any org sale; Cha's PIPA objection to pre-set share consent inside a manager-sent link was accepted as a hard modification. Ships before the first 지점 pilot.
25. **Multi-seat org code billing (지점 invoice, not a tier)** — Daniel, Tae-woo, and Cha defended it as how money actually moves in a GA (thin code on verified coupon machinery, matches 계좌이체-first); Kang and Tommy's kill of the standalone GA tier was honored — agent-controlled 3-level consent means a 본부장 cannot be sold guaranteed visibility, so the tier died and only the billing rail survived, sequenced behind individual willingness-to-pay per Park and Oh Se-ra.

### Post-launch
26. **Community dictionary feedback loop** — Kept, but hard-sequenced by the developers: until the identity-true upsert lands, LB-1 CASCADE-deletes every accepted flag ('a suggestion box wired to a paper shredder' — Jeong), and Gu's golden-set gate must score each accepted alias so substring matching can't silently mis-route others (the 상피내암 bite). Credits cut per Kang.
27. **Immutable comparison snapshot archive** — Widely praised as the proposal that internalized LB-1's lesson and real 승환-dispute differentiation vs KakaoTalk+Excel, but rebuilt to Jeong's construction and sequenced by Amelia's rule: evidence stored in a system with no rehearsed restore is not evidence, and Seo/Dr. Im required a retention clock so it doesn't reverse the 'no PDFs persisted' PIPA asset. Builds after backups + seed fix.
28. **Agent referral coupon loop** — Every reviewer converged on the same two modifications: a Plus coupon is 'a coupon for air' while FREE_TIER_UNLIMITED is on (Ha-eun), and rewarding on email-verify rides a fail-silent, gameable trigger (Ryu, Tommy, Sophia); Seo added a conservative §98-style review given the project's prior rewards legal hold. Parked until the paid flip and warm links are live.
29. **Persistency module (13/25회차)** — Deferred over the proposer's carrier-alignment thesis: Kang's kill-shot stood — the audit says the timer deliberately dropped payment-status claims because carrier 전산 is the authority, so publishing persistency rates the GA's own system will contradict erodes the honesty moat; Kwak added the rookie segment gets near-zero value. Seo conceded at convergence: timer + cron carry the story at launch, module waits for usage data.
30. **판촉물 real imagery + manager-facing page** — Deferred at convergence: Tommy's kill ('days of design work on a surface no paying prospect asked for') and Ara's sharper point (studio images for goods ops has never produced are a prettier state lie) beat Han's launch-freeze-date compromise; the storefront hides at launch via the trust sweep and imagery tracks real orders post-launch.

### Rejected
31. **Paid-only launch via trial coupons** — Killed by an overwhelming unanswered volley: auto-issuance is unbuilt (coupons are admin-issued only), the flip fires the paid-flip cliff (stale 402 copy, placeholder price, no gateway) on 100% of a funnel facing free incumbents (토스 보험파트너, GA 전산, KakaoTalk+Excel), through enforcement that fails OPEN at three layers with no Sentry watching, before 통신판매업 신고 or a named CPO exist and on tainted LB-2 consent (Dr. Im). Tommy conceded on record; the intent survives in the billing desk + invited full-price pilot.
32. **Manager review queue for comparisons** — Killed at convergence despite Seo/Sophia's carrier-aligned defense: an Inpa-hosted approval log is discoverable evidence that the platform orchestrates 승환 distribution (Dr. Im, Park — the exact §97 tail risk §7's architecture avoids); there is no persisted artifact to queue (Nina, Ara — comparisons are computed on the fly, conceded by the proposer's own snapshot proposal); and a per-artifact manager view breaks the PII-masked owner-only model without a new consent basis (Baek). Cha conceded; the dispute-evidence need routes to the snapshot archive, with a GA-internal opt-in variant revisitable only after §8 gate 3.
33. **In-App 후기 Capture Engine** — Killed: coupon-for-후기 is compensated advertising requiring conspicuous 대가성 disclosure under 표시광고법 (Dr. Im, Park, Kang, Yang), uncurated quotes risk putting '갈아타기 성공' recommendation language on the most public surface, and soliciting praise while the dict is unverified V0 and LB-1 still wipes heatmaps harvests testimony the product can't stand behind (Ha-eun). Replacement agreed: the founder hand-collects ~20 consented, disclosure-labeled quotes through the concierge pilot; an automated engine is reconsidered only after a dict accuracy baseline exists.

## Appendix A — All 88 raw proposals → canonical feature

| Raw proposal (Round 1b) | Proposer | Status guess | → # |
|---|---|---|---|
| Versioned consent re-capture sweep | Park Ji-won (Investor) | partially built | 1 |
| Bank-transfer paid pilot cohort | Park Ji-won (Investor) | partially built | 15 |
| Claude unit-cost ledger | Park Ji-won (Investor) | new | 17 |
| Nightly pg_dump to owned server | Park Ji-won (Investor) | new | 4 |
| Always-on infra, seeds off boot | Daniel Cho (Investor) | new | 3 |
| Activation funnel instrumentation | Daniel Cho (Investor) | partially built | 16 |
| Bank-transfer paid pilot cohort | Daniel Cho (Investor) | partially built | 15 |
| Daily reminder producer cron | Daniel Cho (Investor) | partially built | 6 |
| Dictionary-as-Asset Seed Hardening | Seo Yeon-ju (Investor) | new | 2 |
| Meritz Data Provenance Purge | Seo Yeon-ju (Investor) | new | 13 |
| Persistency Module (13/25회차) | Seo Yeon-ju (Investor) | partially built | 29 |
| GA Team Plan (Manager Seat) | Seo Yeon-ju (Investor) | partially built | 25 |
| Wedge Lockdown: Boot-Safe Seeds | Kang Min-ho (CEO) | new | 2 |
| Bank-Transfer Paid Launch | Kang Min-ho (CEO) | partially built | 12 |
| Cut the Ghost Surfaces | Kang Min-ho (CEO) | new | 7 |
| One-Cron Reminder Producer | Kang Min-ho (CEO) | partially built | 6 |
| Founding 100 Power-Agent Program | Lee Ha-eun (CEO) | partially built | 15 |
| Community Dictionary Feedback Loop | Lee Ha-eun (CEO) | partially built | 26 |
| Warm-Path Guarantee for Public Links | Lee Ha-eun (CEO) | new | 3 |
| Cut-or-Commit Surface Sweep | Lee Ha-eun (CEO) | new | 7 |
| Bank-transfer checkout, day one | Tommy Yoon (CEO) | partially built | 12 |
| Paid-only launch via trial coupons | Tommy Yoon (CEO) | partially built | 31 |
| Founder concierge onboarding | Tommy Yoon (CEO) | new | 15 |
| Daily reminder cron job | Tommy Yoon (CEO) | new | 6 |
| Activation Funnel Instrumentation | Oh Se-ra (PM) | partially built | 16 |
| Seed-Free Boot + Keep-Warm | Oh Se-ra (PM) | new | 2 |
| Reminder Producer Cron | Oh Se-ra (PM) | partially built | 6 |
| Gate Empty Promotion Storefront | Oh Se-ra (PM) | partially built | 7 |
| Seeds out of the boot path | Baek Jun-seo (PM) | new | 2 |
| Backups that restore, on-prem | Baek Jun-seo (PM) | new | 4 |
| Reminder producer with heartbeat | Baek Jun-seo (PM) | partially built | 6 |
| 계좌이체 billing desk | Baek Jun-seo (PM) | partially built | 12 |
| Warm customer link paths | Nina Kwon (PM) | new | 3 |
| Morning reminder cron plus digest | Nina Kwon (PM) | partially built | 6 |
| Launch fiction sweep | Nina Kwon (PM) | new | 7 |
| Never-dead customer CTA on /s | Nina Kwon (PM) | partially built | 8 |
| Public Storefront Trust Sweep | Han Do-yun (Designer) | partially built | 7 |
| 판촉물 Catalog Real Imagery | Han Do-yun (Designer) | partially built | 30 |
| Branded Warm-Link Experience | Han Do-yun (Designer) | new | 14 |
| Credible Bank-Transfer Pricing Page | Han Do-yun (Designer) | partially built | 12 |
| Truthful state matrix pass | Choi Ara (Designer) | partially built | 21 |
| Public link wake screen | Choi Ara (Designer) | new | 14 |
| Single-source legal copy lint | Choi Ara (Designer) | partially built | 1 |
| Hide phantom surfaces gate | Choi Ara (Designer) | new | 7 |
| Warm-link token page pipeline | Moon Jae-hyun (Designer) | new | 3 |
| No dead ends on share view | Moon Jae-hyun (Designer) | partially built | 8 |
| Single-source consent copy module | Moon Jae-hyun (Designer) | partially built | 1 |
| KakaoTalk link preview cards | Moon Jae-hyun (Designer) | new | 20 |
| Keep-warm ping for public funnel | Ryu Chan-mi (Marketer) | new | 3 |
| SEO and crawl baseline | Ryu Chan-mi (Marketer) | new | 22 |
| 계좌이체 purchase flow v1 | Ryu Chan-mi (Marketer) | partially built | 12 |
| Funnel telemetry and dead-man alarm | Ryu Chan-mi (Marketer) | partially built | 16 |
| Agent Referral Coupon Loop | Kim Tae-woo (Marketer) | new | 28 |
| Keep-Warm Customer Link Path | Kim Tae-woo (Marketer) | new | 3 |
| 판촉물 Shelf: Real or Hidden | Kim Tae-woo (Marketer) | partially built | 7 |
| In-App 후기 Capture Engine | Kim Tae-woo (Marketer) | new | 33 |
| Multi-seat org code billing | Sophia Jang (Marketer) | partially built | 25 |
| Team invite onboarding link | Sophia Jang (Marketer) | new | 24 |
| Demo-proof boot path | Sophia Jang (Marketer) | new | 3 |
| 판촉물 showcase + manager page | Sophia Jang (Marketer) | partially built | 30 |
| Seed upsert off boot path | Jeong Woo-jin (Developer) | partially built | 2 |
| Nightly pg_dump to founder server | Jeong Woo-jin (Developer) | new | 4 |
| Reminder producer command | Jeong Woo-jin (Developer) | partially built | 6 |
| Sentry DSN plus LOGGING config | Jeong Woo-jin (Developer) | partially built | 11 |
| Seeds out of boot path | Amelia Son (Developer) | new | 2 |
| Nightly pg_dump to home server | Amelia Son (Developer) | new | 4 |
| Sentry DSN plus synthetic probes | Amelia Son (Developer) | partially built | 11 |
| Single scheduled job runner | Amelia Son (Developer) | partially built | 5 |
| Natural-key seed upsert off boot | Gu Bon-cheol (Developer) | partially built | 2 |
| Golden-set normalization eval harness | Gu Bon-cheol (Developer) | new | 18 |
| Unmatched-rate telemetry and failure capture | Gu Bon-cheol (Developer) | partially built | 17 |
| Nightly pg_dump to founder server | Gu Bon-cheol (Developer) | new | 4 |
| Morning Digest Reminder Engine | Yang Mi-sook (Agent) | partially built | 6 |
| Warm Customer Links Guarantee | Yang Mi-sook (Agent) | new | 3 |
| Customer-Surface Dead-Button Sweep | Yang Mi-sook (Agent) | partially built | 8 |
| 판촉물 Storefront: Fill or Hide | Yang Mi-sook (Agent) | partially built | 7 |
| Always-warm public lead links | Kwak Dong-hyun (Agent) | new | 3 |
| Daily call list (오늘 전화 리스트) | Kwak Dong-hyun (Agent) | partially built | 19 |
| Instagram-ready share kit | Kwak Dong-hyun (Agent) | partially built | 20 |
| 판촉물 images or hide the menu | Kwak Dong-hyun (Agent) | partially built | 7 |
| Manager review queue for comparisons | Cha Eun-bi (Agent) | new | 32 |
| Immutable comparison snapshot archive | Cha Eun-bi (Agent) | new | 27 |
| Team invite and share onboarding | Cha Eun-bi (Agent) | partially built | 24 |
| Reminder producer cron | Cha Eun-bi (Agent) | partially built | 6 |
| Consent copy single-source + re-consent sweep | Dr. Im Kyu-tae (Compliance) | partially built | 1 |
| Consent withdrawal endpoint + retention automation | Dr. Im Kyu-tae (Compliance) | partially built | 10 |
| Recommendation-word CI blacklist | Dr. Im Kyu-tae (Compliance) | partially built | 23 |
| PII log scrub + legal identity fill | Dr. Im Kyu-tae (Compliance) | new | 9 |

## Appendix B — Verifier classification notes

- **/s never-dead CTA (tel: layer + tracked callback lead)** — Tiered launch-blocking, but the audit classifies the dead /s CTA under MEDIUM ('/s share-view CTA silently does nothing'), and the entry's own reason admits it is 'the audit's medium finding'. The elevation rests on debate judgment (customer-held surface), not audit severity.
- **Meritz data provenance purge (phased)** — Audit lists the 3 committed Meritz job-grade files under MEDIUM ('policy drift + third-party data-licensing exposure if repo is ever shared'), not launch-blocking. Making even Phase 1 launch-blocking is an elevation driven by the investors' diligence argument, not by audit facts; the repo is private and nothing customer-facing depends on it at launch.
- **Identity-true seed upsert, seeds off the boot path** — Status 'partially built' is arguable: the seed commands exist and run every boot (that existence IS the LB-1 defect), but the natural-key upsert semantics, off-boot release step, version stamping, and rollback runbook are all new work; 5 of the 7 merged round-1 twins were labeled 'new'. 'New' would be equally or more defensible.
- **KakaoTalk link preview cards (static first, per-token after warmth)** — Status 'new' slightly understates existing assets: the audit's live probe shows correct OG/meta already served on the FE root, and the merged 'Instagram-ready share kit' was round-1 'partially built' (the /p intro card + introduction-card-share component exist as the visual-kit substrate). Per-token OG cards themselves are indeed unbuilt, so this is a judgment call, not a contradiction.
- **Agent referral coupon loop** — Status 'new' vs audit §3: the coupon machinery it rides (admin issue/redeem, expiry-aware entitlement, max_redemptions) is fully built and verified; only the per-agent code generation, trigger, and attribution tagging are new. 'Partially built' would match how sibling entries (e.g. multi-seat org code billing on the same coupon rail) were classified.
- **Launch trust sweep: purge demo data, fix placeholders, hide ghost surfaces** — Status 'partially built' is loose: the surfaces being fixed exist, but none of the sweep's actual deliverables (demo-plan deactivation, N-placeholder fix, has-real-backing gates, board-attachment closure) exist yet per the audit; the label reads as inherited from constituent proposals rather than audited state. Tier itself is well-grounded (LB-3 + H-5).

## Final ranked tiers (Step 4 — 22 personas × 30 features × 5 dimensions)

**Method.** 660 raw score rows in [scores.csv](scores.csv). Weighted dimension means (Compliance persona counts ×2 on Legal Safety; the 3 Developer personas count ×2 on Feasibility), aggregate = 45% Agent Value + 20% Revenue + 10% Legal Safety + 15% Feasibility + 10% Differentiation. **Legal veto check: 0 features flagged** (Compliance minimum score = 5; risky ideas had already been killed in Round 3).
**Tier rule (documented).** The 13 launch-blocking items are commitment-driven (the weighted formula intentionally under-values risk-removal work at 45% agent-value, so scores order execution but cannot demote them). Non-LB features: MVP = aggregate >= 5.0 and no dependency gate · Phase 2 = 4.0-5.0 or dependency-gated high scorers · Backlog = < 4.0 · Rejected = killed in Round 3.

### Score ranking (all 30)

| Rank | # | Feature | AgentVal | Revenue | Legal | Feas | Diff | Weighted |
|---|---|---|---|---|---|---|---|---|
| 1 | 19 | Daily call list (오늘 전화 리스트) | 9.1 | 7.0 | 9.0 | 8.3 | 6.6 | **8.31** |
| 2 | 6 | Reminder producer + 8am in-app morning digest | 8.8 | 6.7 | 9.0 | 7.2 | 4.5 | **7.72** |
| 3 | 3 | Always-on backend for customer-facing links | 8.1 | 5.3 | 9.9 | 10.0 | 1.7 | **7.37** |
| 4 | 15 | Invited 계좌이체 paid pilot + founder concierge (Founding 20) | 6.1 | 8.4 | 8.0 | 8.6 | 4.4 | **6.94** |
| 5 | 2 | Identity-true seed upsert, seeds off the boot path | 8.1 | 5.2 | 9.5 | 6.0 | 1.6 | **6.71** |
| 6 | 20 | KakaoTalk link preview cards (static first, per-token after warmth) | 7.1 | 4.6 | 7.7 | 8.0 | 6.3 | **6.71** |
| 7 | 29 | Persistency module (13/25회차) | 6.6 | 6.1 | 8.7 | 7.7 | 4.7 | **6.70** |
| 8 | 8 | /s never-dead CTA (tel: layer + tracked callback lead) | 6.9 | 4.5 | 8.4 | 8.0 | 4.8 | **6.51** |
| 9 | 24 | Team invite onboarding link (consent-clean) | 4.4 | 6.0 | 9.0 | 7.8 | 4.5 | **5.71** |
| 10 | 7 | Launch trust sweep: purge demo data, fix placeholders, hide ghost surfaces | 4.9 | 4.7 | 9.2 | 9.0 | 1.5 | **5.55** |
| 11 | 25 | Multi-seat org code billing (지점 invoice, not a tier) | 3.1 | 8.6 | 8.2 | 7.7 | 3.8 | **5.46** |
| 12 | 12 | 계좌이체 billing desk + credible pricing surface | 3.0 | 9.5 | 7.7 | 7.8 | 2.0 | **5.39** |
| 13 | 27 | Immutable comparison snapshot archive | 4.3 | 3.9 | 8.7 | 6.6 | 6.3 | **5.19** |
| 14 | 26 | Community dictionary feedback loop | 4.5 | 2.2 | 9.0 | 8.0 | 5.7 | **5.11** |
| 15 | 23 | Recommendation-word blacklist (CI + server-side share check) | 4.1 | 3.1 | 10.0 | 7.5 | 5.0 | **5.09** |
| 16 | 21 | Truthful state matrix pass | 5.3 | 2.3 | 9.5 | 7.1 | 2.2 | **5.09** |
| 17 | 14 | Residual loading skeletons on token pages | 4.4 | 2.2 | 9.9 | 9.0 | 2.3 | **4.98** |
| 18 | 5 | Single scheduled job runner with dead-man heartbeat | 4.5 | 3.1 | 9.2 | 7.6 | 1.1 | **4.79** |
| 19 | 18 | Golden-set normalization eval harness | 4.2 | 3.2 | 8.7 | 5.2 | 4.8 | **4.68** |
| 20 | 30 | 판촉물 real imagery + manager-facing page | 4.0 | 4.0 | 7.1 | 6.1 | 3.7 | **4.60** |
| 21 | 28 | Agent referral coupon loop | 3.2 | 5.2 | 7.3 | 6.9 | 3.2 | **4.59** |
| 22 | 11 | Sentry + PII-safe error monitoring + synthetic probes | 3.7 | 2.7 | 8.7 | 8.5 | 1.0 | **4.47** |
| 23 | 4 | Nightly encrypted pg_dump + rehearsed restore + retention cycle | 4.1 | 2.7 | 8.1 | 6.6 | 1.1 | **4.29** |
| 24 | 1 | Single-source consent copy + versioned re-consent sweep | 3.1 | 2.7 | 10.0 | 6.9 | 2.4 | **4.22** |
| 25 | 17 | Claude per-call cost + parse-outcome telemetry | 1.9 | 4.5 | 9.2 | 7.6 | 1.8 | **4.00** |
| 26 | 9 | PII log scrub + legal identity fill | 1.9 | 3.0 | 10.0 | 8.8 | 1.0 | **3.88** |
| 27 | 16 | Activation funnel instrumentation + UTM capture + dead-man funnel alarm | 1.7 | 4.6 | 9.0 | 7.5 | 1.3 | **3.84** |
| 28 | 10 | Consent withdrawal endpoint + retention automation | 2.5 | 2.1 | 10.0 | 6.4 | 1.8 | **3.68** |
| 29 | 22 | SEO and crawl baseline | 1.3 | 2.1 | 9.6 | 10.0 | 1.0 | **3.56** |
| 30 | 13 | Meritz data provenance purge (phased) | 1.6 | 1.2 | 9.3 | 4.6 | 1.0 | **2.68** |

### Tier: Launch-Blocking (13, in panel execution order)

#1 Single-source consent copy + versioned re-consent sweep → #2 Identity-true seed upsert → #3 Always-on backend for customer-facing links → #4 Nightly encrypted pg_dump + rehearsed restore + retention cycle → #11 Sentry + PII-safe error monitoring + synthetic probes → #5 Single scheduled job runner with dead-man heartbeat → #6 Reminder producer + 8am in-app morning digest → #7 Launch trust sweep: purge demo data → #9 PII log scrub + legal identity fill → #10 Consent withdrawal endpoint + retention automation → #12 계좌이체 billing desk + credible pricing surface → #8 /s never-dead CTA → #13 Meritz data provenance purge

### Tier: MVP (7)
#19 (8.31), #15 (6.94), #20 (6.71), #24 (5.71), #25 (5.46), #23 (5.09), #21 (5.09)

### Tier: Phase 2 (8)
#29 (6.70), #27 (5.19), #26 (5.11), #14 (4.98), #18 (4.68), #30 (4.60), #28 (4.59), #17 (4.00)

#29/#27/#26 scored MVP-level but stay Phase 2 on the panel's dependency gates (#26 needs the seed fix; #27 needs evidence-retention rules; #28 needs paid mode live).

### Tier: Backlog (2)
#16 (3.84), #22 (3.56) — score-driven placement; both are ~1-day hygiene jobs the panel wanted in launch week, so slot them opportunistically.

### Tier: Rejected (3, killed in Round 3 with reasons on record)
1. Paid-only launch via trial coupons — auto-issuance unbuilt + fires the paid-flip cliff on 100% of the funnel.
2. Manager review queue for comparisons — an Inpa-hosted approval log is discoverable evidence the platform orchestrates 승환 distribution (§97).
3. In-app 후기 capture engine — coupon-for-review is compensated advertising under 표시광고법.