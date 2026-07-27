# Release 3 Task 4 report

## Changed

- Standardized the comparison result surface on `왼쪽 구성` and `오른쪽 구성`: monthly and total premiums, renewal/non-renewal table defaults, coverage legend, chart accessibility text, table headers, selector guidance, and customer copy all share these labels.
- Extended `CompareBarChart` with `labelA` and `labelB` props. The page passes the exact values used by its visible legend, so screen-reader output and rendered labels cannot diverge.
- Kept the existing neutral color tokens (`--existing`, `--proposal`) and API compatibility fields (`current`, `proposed`) unchanged.
- Made export availability explicitly require a successful result for the current selection snapshot, no active comparison load, and no insurance-list refresh error. Stale selections therefore cannot invoke clipboard copying.
- Preserved the existing clipboard-failure guidance.

## TDD evidence

- RED: the focused Vitest run failed exactly because the chart and premium table still emitted `증권 A` and `증권 B`.
- GREEN: updated component defaults and page labels made the focused comparison and overlap-selection suites pass. The overlap suite now proves stale-result copy invokes the clipboard zero times and a fresh copy failure retains the existing user guidance.

## Verified by

- `npm run test:run -- components/__tests__/neutral-policy-comparison.test.tsx components/__tests__/multi-policy-overlap-selection.test.tsx` — 2 files, 13 tests passed.
- `npx tsc --noEmit` — passed.
- `npm run lint:copy` — 265 files checked, 0 violations.
- `git diff --check` — passed.

## Unverified

- `npm run build` was not run for this scoped label/copy task; the parent release integration should retain its broader build gate.
