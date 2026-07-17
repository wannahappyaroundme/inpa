# Insurance Document Pseudonymization Design

## Decision

Use document-local, irreversible pseudonyms before any external AI call. The same source value is replaced consistently inside one job (`[고객_1]`, `[전화_1]`, `[계약번호_1]`), but the source-to-token map exists only inside the disposable PDF child process and is destroyed with that process. Never persist, log, return, or transmit the map or raw extracted text.

This replaces simple `***` masking because stable aliases preserve within-document relationships without making the original value recoverable. Reversible tokenization is rejected because it creates a key-management and breach-recovery burden that Inpa does not need.

## Evidence and launch gate

The local-only inventory of `samples/` contains 155 PDFs in 136 unique SHA clusters. The first 36 clusters are the development partition; the remaining 100 clusters were frozen as holdout. After the synthetic security matrices and independent review passed, the latest code completed the 36-cluster development run with 36 successes, zero detectable privacy residue, zero safe failures, nine automatic reviews, and 27 manual source-page reviews. The relevant code was then frozen at SHA-256 `5e5a173940cea63f7546402de5b0aa2e2a3d7c2c1fa5cfd62584bb5b96615b67`.

Without changing that code or tuning rules, the single completed 100-cluster holdout run produced 100 successes, zero detectable privacy residue, zero protocol/resource/direct/unexpected failures, 31 automatic reviews, and 69 manual source-page reviews. Both runs had zero provider and network calls, zero new temporary artifacts, and an unchanged private inventory of 164 files and 84,414,173 bytes. An earlier holdout command was aborted before aggregate output; it produced zero usable results and caused zero rule tuning. These are privacy-boundary results, not proof of coverage-extraction accuracy and not authorization to enable production external calls.

The audit also found two duplicate copies of one mixed PDF whose first two image cover pages had no text while the following eight coverage-table pages were extractable. A single blank/image page must not reject an otherwise analyzable document.

## Data flow and trust boundaries

1. The private original PDF stays in the job-scoped exact storage key.
2. The disposable resource-limited child process opens the PDF and extracts page lines. Raw lines never cross the child protocol boundary.
3. One document-scoped pseudonymizer replaces direct identifiers and labeled identity values with category counters. It retains an in-memory map only long enough to keep repeated values consistent across pages.
4. An independent identity pass removes any still-uncertain identity line locally. It returns only exact page/line coordinates and counts. The raw line never crosses the child boundary. A quarantined identity-only line is telemetry; a quarantined line containing an amount, premium, period, or coverage signal requires manual source-page review.
5. A final residual scanner examines every remaining pseudonymized line. A probable direct identifier or unredacted labeled value, an invalid coordinate proof, or a formerly text-bearing page made entirely blank fails the whole document with `PII_REDACTION_UNCERTAIN` before any provider call.
6. Only pseudonymized `MaskedLine` and `CoverageCandidate` contracts plus validated counts and coordinates leave the child process. Filenames, PDF metadata, storage keys, raw quarantined lines, and source-to-token maps are not part of the protocol.
7. Immediately before the provider call, the worker rechecks current customer-self consent, current attempt/status, and requires `residual_scan_passed is True`. Any other value fails before provider invocation.
8. The structured provider response is scanned again. A raw direct identifier or any non-alias value after an identifier label in an allowed string field fails with `PROVIDER_PII_OUTPUT`. Identifier-labeled non-alias values fail even when they appear in safe source text. A role-bearing value is allowed only when it contains document-local aliases or its complete normalized value occurs as an exact substring of child-proven pseudonymized source text. Missing grounding context fails closed. The adapter and worker independently apply the same rule before any review draft is created.

The current overseas-transfer consent and feature gate remain mandatory. Pseudonymization reduces exposure; it does not replace legal consent.

## Identifier policy

Pseudonymize globally detectable values:

- full and partially redacted resident IDs, including Unicode dash variants;
- mobile and landline phone numbers;
- email addresses;
- bank/card/account and business-registration numbers when their label or strong format is present.

Pseudonymize label-bound values, including values separated by blank lines or page boundaries:

- contractor, insured, beneficiary, subscriber, customer, representative, planner, recruiter, and person names;
- home/work addresses and locations;
- policy number, contract number, customer number, certificate number, application number, planner/recruiter identifier, and license/registration identifier;
- birth date and other labeled identity dates that are not required for coverage-table extraction.

Preserve insurer, product, rider/coverage name, amount, premium, payment period, coverage period, renewal wording, and standard-coverage mapping terms. These are required for insurance analysis. High-precision, label-aware rules take precedence over aggressive free-text name guessing so Korean coverage names are not destroyed.

## Pseudonym semantics

- Tokens are deterministic only inside one parsed document and start at one for each category.
- Repeated normalized values receive the same token across pages. Phone/identifier normalization ignores punctuation; name/address normalization collapses spacing.
- Different jobs never share counters or maps, including concurrent jobs for the same planner.
- Tokens contain no hash or encoded source material.
- The child protocol may return counts by category, exact quarantine coordinates, and `residual_scan_passed=true`; it must never return the map, matched original, or context excerpt.
- Logs and Sentry may contain job UUID, outcome code, and category counts only.

## Mixed PDF and source-review rule

Reject `IMAGE_PDF` only when the document has no analyzable text anywhere. Preserve original page coordinates while skipping empty image-only pages. A mixed PDF with at least one text-bearing page proceeds.

The server validates exact, sorted, unique quarantine coordinates and derives `pages_requiring_manual_source_review` as the union of image-only pages and analysis-signal quarantine pages. Those pages are exposed without text in `source_review`. The review draft receives one fixed critical issue and the guidance “해당 페이지의 원문을 확인한 뒤, 필요한 담보를 직접 추가하거나 수정해 주세요.” Confirmation reuses `planner_confirmed_unread_pages` and remains blocked until the planner confirms that the original pages were checked. Identity-only quarantine does not by itself require source review. Page, character, and candidate limits remain fail-closed.

## Error handling

- `PII_REDACTION_UNCERTAIN`: residual direct identifier remains after local quarantine, the coordinate proof is invalid, the worker lacks the literal residual proof, or quarantine erases an entire formerly text-bearing page. Do not call AI, do not create a draft, and refund a consumed credit once through the existing system-failure path.
- `PROVIDER_PII_OUTPUT`: the structured provider output contains a probable raw identifier, a non-alias identifier-labeled value, or an ungrounded role-bearing value. Do not create a draft; retain no provider payload and use the existing safe failure/refund path.
- `IMAGE_PDF`: every page lacks analyzable text. Keep the existing manual-review guidance.

No error body includes the matched value, source line, filename, or PDF metadata.

## Verification

Hard gates before any real external sample evaluation:

- existing unit tests plus document-local alias consistency across page boundaries;
- policy/customer/planner identifier and representative-name regression cases derived from the private audit but rewritten as synthetic fixtures;
- false-positive anchors for Korean rider names, multi-amount rows, multiple periods, parenthesized riders, and renewal wording;
- mixed image-cover plus text-table PDF succeeds; fully image-only PDF still fails;
- provider-output scanner blocks injected identifiers in every schema-approved string leaf, requires role-bearing insurance facts to be grounded in child-proven pseudonymized source text, and keeps identifier labels fail-closed regardless of grounding;
- grounding normalization changes only whitespace layout and fullwidth parentheses; it does not rewrite aliases, Korean text, amounts, digits, or other punctuation;
- concurrent jobs prove no alias-map sharing;
- the 36-cluster development partition reports automatic-complete and human-review-required documents separately, with every successful document carrying the literal residual proof;
- quarantined analysis lines expose only validated coordinates and counts, create the fixed draft issue, and block confirmation until original pages are checked;
- the frozen 100-cluster holdout is run once only after independent review authorizes it, with zero provider/network calls and no rule tuning from its contents;
- raw sample text, filenames, and identifiers never enter git, test output, logs, reports, or external services.

The private corpus is split by unique SHA cluster, not filename: 36 development documents and 100 holdout documents. Duplicate hashes stay in the same partition. The completed holdout set was not used to tune rules and must not be rerun as another tuning cycle.

## Non-goals

- no reversible identity vault;
- no external call with the real sample corpus in this implementation;
- no relaxation of consent, tenancy, retention, or feature gates;
- no OCR engine for fully image-only PDFs in this change;
- no persistence of raw PDF text or a pseudonym lookup table.
