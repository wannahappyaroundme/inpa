# Spec: 시드 안전화 — identity-true upsert + 부팅 경로 무해화 + 손상 복구 (LB-1 fix)

> Launch-blocking #2 (panel order position 2). Problem (audit LB-1, twice-confirmed): `seed_normalization` runs on EVERY Render boot (deploys AND free-tier cold-start wakes) and delete-recreates the [표준] coverage tree with new PKs. CASCADE severs (a) all `InsuranceDetail.analysis_detail` M2M links the heatmap aggregates — previously scanned customers' held amounts silently drop to 0 — and (b) ALL `NormalizationDict` rows including `admin_verified`/`ocr_learned` (FK via `std_detail`). "Idempotent" is count-true, identity-false.

## Decisions (locked)

1. **Upsert, never delete.** Rewrite `inpa_be/inpa/analysis/management/commands/seed_normalization.py`:
   - Tree: walk STANDARD_TREE with `get_or_create` keyed on the natural key (parent FK + name), updating only non-key attrs. Existing rows keep their PKs → M2M links and NormalizationDict FKs survive. NEVER rename [표준] leaves (PlannerBaseline presets are name-bound).
   - Seed dictionary rows: `update_or_create` keyed on (alias, target std path) restricted to `source='seed'`. NEVER touch `admin_verified` / `ocr_learned` rows in any code path.
   - Deletion: no automatic pruning. Leaves/dict rows missing from code are LOGGED as orphans; an explicit `--prune` flag (default OFF, never used in deploy) may remove seed-source rows only.
2. **Boot-path no-op via version marker.** New tiny model `analysis.SeedMarker` (`key` unique CharField, `version` CharField, `updated_at` auto) — one PG-safe migration. `seed_normalization` and `seed_jobs` (the two destructive/heavy ones) declare a data-version constant (bump manually when seed DATA changes; start at `v1`). On run: marker matches → log "이미 최신" and exit 0 (boot becomes cheap and harmless); `--force` bypasses. Other seeds (billing/boards/promotion — already edit-preserving) stay unchanged.
3. **`seed_jobs` keeps its file-SSOT prune semantics** (documented design) but only executes when the marker version changes; add the marker check only, do not redesign.
4. **Damage repair command** `repair_analysis_links` (new, in analysis app): for every `InsuranceDetail` used by any `CustomerInsuranceDetail` that has zero `analysis_detail` links, re-resolve via the existing bridge (`coverage_bridge.resolve_std_detail` / `COVERAGE_KEYWORDS` matching on the stored name — reuse the exact resolution used at OCR persist, do not invent new matching) and re-link. Flags: `--dry-run` (default prints what would link, count summary) and `--apply`. Idempotent. This undoes the historical severing in prod.
5. **render.yaml:** startCommand chain unchanged (markers make it safe). Add a comment noting the marker guard + that `repair_analysis_links --apply` must be run ONCE via Render Shell after this deploys (PM runbook line goes in README at deploy time, not now).
6. **Out of scope:** moving seeds to Render preDeployCommand (revisit when H-4 paid instance lands), normalization data changes, admin UI.

## Gotchas to respect (CLAUDE.md §7 + memory)

- SQLite-vs-PG: migration defaults/lengths must pass PG; CI runs SQLite only, so keep the migration trivial.
- Substring-matching traps live in dict DATA, not logic — `repair_analysis_links` must reuse the existing resolution path verbatim.
- `update_fields`+save-hook trap does not apply here (management commands), but keep `@transaction.atomic` per command run.
- Do NOT quote or open samples/, benchmark/, root data/.

## Tests (BE, analysis/tests.py + customers/insurances where fitting)

1. Re-run safety: seed → create a fake scanned detail linked to a [표준] leaf + one `admin_verified` dict row → run `seed_normalization` again (--force) → leaf PK unchanged, M2M link intact, admin_verified row intact, seed rows updated not duplicated (counts stable).
2. Marker: second run without --force exits without touching DB (query-count or marker assertion); --force runs; version bump runs.
3. Orphan logging: remove one leaf from an injected mini-tree constant (monkeypatch) → run → row NOT deleted, orphan logged; with --prune → seed-source rows removed, admin_verified untouched.
4. `repair_analysis_links`: sever a link artificially → dry-run reports it, --apply restores it, second --apply is a no-op.
5. Full suite green: `python manage.py test inpa`.

## Verification gates before reporting done

- `python manage.py check` + full BE suite green (paste real tails). Migration count = 1 (SeedMarker only).
- Local end-to-end proof: run `seed_normalization` twice in a row against a seeded local DB with a linked detail; show held-amount aggregation (calculate path or direct M2M assert) unchanged after the second run.
- Report: files changed, migration list, before/after test counts, orphan/prune semantics summary, exact Render-Shell repair command line for the PM runbook.
