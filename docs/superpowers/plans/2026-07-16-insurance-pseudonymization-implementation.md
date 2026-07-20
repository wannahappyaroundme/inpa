# Insurance Document Pseudonymization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure only document-local pseudonymized insurance text can reach external AI, quarantine uncertain identity lines locally, route analysis-bearing omissions to explicit source-page review, and fail closed whenever privacy proof is incomplete.

**Architecture:** Extend the existing disposable PDF child with an isolated `DocumentPseudonymizer`, local uncertainty quarantine, and a separate final residual scanner. The child remains the only process that sees raw extracted lines; the parent receives pseudonymized line/candidate contracts plus validated counts and coordinates. The worker requires the literal residual proof before provider invocation. The structured provider adapter scans every allowed string leaf and grounds role-bearing values against child-proven pseudonymized line/candidate text; the worker repeats the same gate before persistence. The review/confirmation flow requires original-page checks for image-only or analysis-quarantined pages.

**Tech Stack:** Django 5.2 LTS, Python 3.11, resource-limited subprocess PDF parser, `pdfplumber`, Pydantic structured provider output, Django tests.

## Global Constraints

- Raw PDF text, filenames, storage keys, source values, and pseudonym maps never cross the child protocol or enter logs, tests, reports, git, or Sentry.
- Customer-self current-version overseas consent remains required immediately before the provider call.
- External AI, deployment, paid resources, and production feature-gate activation remain disabled during implementation and verification.
- Pseudonym rules preserve insurer, product, rider name, amount, premium, periods, renewal wording, and page/line coordinates. Uncertain analysis-bearing lines are removed locally and their pages are routed to manual source review.
- Private sample verification reports aggregate counts only and uses SHA-cluster partitions.

---

### Task P1: Document-local aliases, local quarantine, and fail-closed residual scanner

**Files:**
- Modify: `inpa_be/inpa/insurances/import_pdf_mask.py`
- Modify: `inpa_be/inpa/insurances/import_contract.py`
- Modify: `inpa_be/inpa/insurances/import_pdf_sandbox.py`
- Modify: `inpa_be/inpa/insurances/import_pdf.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf_mask.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf_sandbox.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf.py`

**Interfaces:**
- Consumes: `mask_page_lines(page_source_lines)` and the current masked-only child JSON protocol.
- Produces: `pseudonymize_page_lines(page_source_lines) -> PseudonymizedDocument`, where the document contains pseudonymized pages, category counts, exact quarantine coordinates/counts, and `residual_scan_passed`; no source map or raw quarantined line is exposed.

- [ ] **Step 1: Write failing alias and identifier tests**

Add exact tests for repeated names across page boundaries, normalized repeated phones/identifiers, contract/policy/customer numbers, planner/recruiter identifiers and names, addresses, birth dates, concurrent pseudonymizer isolation, and preservation of Korean coverage/amount/period text. Assert that neither the result nor `repr(result)` contains sentinel source values or a source map.

- [ ] **Step 2: Run the tests and record RED**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf_mask -v 2`

Expected: alias tokens and expanded identifier rules are absent.

- [ ] **Step 3: Implement one document-scoped pseudonymizer**

Create a small class whose instance owns category counters and normalized-value maps. Keep all maps private, use tokens such as `[고객_1]` and `[계약번호_1]`, and return only immutable pseudonymized pages plus category counts. Retain the linear pass and cross-page pending-label behavior.

- [ ] **Step 4: Add local uncertainty quarantine and an independent residual scan**

Remove still-uncertain identity lines inside the child and retain exact page/line coordinates only. Track the subset containing coverage, amount, premium, or period signals. Then scan all remaining pseudonymized lines for global direct-identifier formats and label-bound unredacted values. Raise `PDFImportError('PII_REDACTION_UNCERTAIN')` without including the match when residue remains or a formerly text-bearing page becomes entirely blank. Add the code to the parent safe-code allowlist and prove child JSON contains only safe counts, coordinates, and pseudonymized text.

- [ ] **Step 5: Run focused and affected tests**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf_mask inpa.insurances.test_import_pdf_sandbox inpa.insurances.test_import_pdf -v 2`

Expected: all tests pass; existing amount/period/candidate coordinates remain unchanged except identity tokens.

- [ ] **Step 6: Commit**

Commit: `security(보험): 문서별 가명화와 잔존 검사 추가`

### Task P2: Mixed PDF acceptance without scan false positives

**Files:**
- Modify: `inpa_be/inpa/insurances/import_contract.py`
- Modify: `inpa_be/inpa/insurances/import_pdf_sandbox.py`
- Modify: `inpa_be/inpa/insurances/import_pdf.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf_sandbox.py`
- Test: `inpa_be/inpa/insurances/test_import_pdf.py`

**Interfaces:**
- Consumes: Task P1 pseudonymized child result.
- Produces: `ExtractedPDF.image_only_pages`, quarantine coordinates, and analysis-quarantine coordinates, all validated by the parent protocol decoder.

- [ ] **Step 1: Write failing mixed-document tests**

Test an image-only cover followed by text coverage pages, image-only internal/back pages, and an all-image document. Assert stable original page/line coordinates and non-sensitive image-only page counts.

- [ ] **Step 2: Run the tests and record RED**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf_sandbox inpa.insurances.test_import_pdf -v 2`

Expected: the mixed document currently fails with `IMAGE_PDF`.

- [ ] **Step 3: Change the document-level decision and source-review proof**

Collect page lines first, count pages without analyzable text, and raise `IMAGE_PDF` only when every page is empty. Skip empty-page line emission while preserving the source page number for later text lines. Strictly validate sorted, unique quarantine coordinates and derive `pages_requiring_manual_source_review` from image-only and analysis-quarantined pages. Add a fixed review issue and guidance, and reuse `planner_confirmed_unread_pages` so confirmation is blocked until the planner checks the original pages. Keep page, character, and candidate caps unchanged.

- [ ] **Step 4: Run focused and insurance regression tests**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_pdf_sandbox inpa.insurances.test_import_pdf inpa.insurances.test_import_worker -v 2`

Expected: mixed PDFs pass, all-image PDFs fail, worker behavior is unchanged.

- [ ] **Step 5: Commit**

Commit: `fix(보험): 혼합형 PDF의 보장표 추출 허용`

### Task P3: Provider-output privacy gate and private-corpus proof

**Files:**
- Modify: `inpa_be/inpa/insurances/import_claude.py`
- Modify: `inpa_be/inpa/insurances/import_contract.py`
- Modify: `inpa_be/inpa/insurances/import_services.py`
- Modify: `inpa_be/inpa/insurances/tasks.py`
- Test: `inpa_be/inpa/insurances/test_import_claude.py`
- Test: `inpa_be/inpa/insurances/test_import_draft_api.py`
- Test: `inpa_be/inpa/insurances/test_import_confirm.py`
- Test: `inpa_be/inpa/insurances/test_import_worker.py`
- Update: `.superpowers/sdd/real-sample-audit.md` (gitignored, aggregate only)

**Interfaces:**
- Consumes: strict parsed provider payload and Task P1 residual-scanner primitives.
- Produces: `assert_provider_payload_pii_safe(payload, safe_source_texts) -> None`, raising safe `ExtractionFailure('PROVIDER_PII_OUTPUT')` on any probable raw direct identifier, any non-alias identifier-label value, or any non-alias role-bearing value not grounded in child-proven pseudonymized source text. Also produces a validated `source_review` response with fixed issue/guidance for analysis-quarantined pages.

- [ ] **Step 1: Write failing structured-output privacy tests**

Inject resident ID, phone, email, labeled contract/customer/planner identifiers, names, lowercase identifiers, Hangul/Latin mixed identifiers, and newline-separated label values into each allowed provider string field. Assert no draft/result is created, no raw value appears in exception/log/Sentry, and the original billing month is refunded once through the existing system-failure path. Add worker tests proving only `residual_scan_passed is True` can reach the provider.

- [ ] **Step 2: Run the tests and record RED**

Run: `cd inpa_be && python manage.py test inpa.insurances.test_import_claude inpa.insurances.test_import_worker -v 2`

Expected: provider payloads are not yet scanned.

- [ ] **Step 3: Implement the provider-output gate**

Walk every schema-approved string value, reuse the direct-identifier scanner without label context excerpts, and reject every non-alias value following an identifier label regardless of character class, case, line break, or source grounding. For role-bearing values, allow document-local aliases or require the complete provider value, after whitespace collapse and fullwidth-parentheses normalization only, to occur as an exact substring of child-proven `text_masked` from lines/candidates. Missing source context fails closed. Apply the gate in both the provider adapter and worker before `validate_draft()` or persistence. Never log the payload or matched value.

- [ ] **Step 4: Run the private corpus gate locally**

After all synthetic privacy, wrapper, grounding, worker, and source-review matrices are green and independent review is complete, run the local audit against the 36-cluster development partition only when the root task explicitly authorizes it. Keep network disabled. Report automatic-complete and human-review-required documents separately, require the literal residual proof for every success, record aggregate category/count/page metrics only, keep duplicate hashes in one partition, and confirm source file count/bytes are unchanged. Do not call the provider. Keep the 100-cluster holdout frozen and do not run it until independent review explicitly authorizes one final evaluation.

- [ ] **Step 5: Run full verification**

Run: `cd inpa_be && python manage.py check`

Run: `cd inpa_be && python manage.py makemigrations --check --dry-run`

Run: `cd inpa_be && python manage.py test inpa -v 1`

Expected: zero check issues, no migration drift, and all backend tests pass.

- [ ] **Step 6: Independent security review and commit**

Review child protocol, residue scanners, logs/Sentry, consent barrier, concurrent job isolation, and the aggregate private-corpus report. Commit: `security(보험): AI 응답 개인정보 역검사 추가`.
