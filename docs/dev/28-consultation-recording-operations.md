# Consultation Recording Operations

## Safety state

- Production defaults stay closed:
  - `CONSULTATION_RECORDING_ENABLED=false`
  - `CONSULTATION_AI_SUMMARY_ENABLED=false`
- Runtime switches and per-user pilot access are additional gates. All gates must
  be open for a planner to use the corresponding feature.
- The current `v2-30d` policy is exactly 720 hours and 30 days. A different
  `CONSULTATION_RETENTION_HOURS` value is a startup error while the recording
  environment gate is open. Existing `v1-7d` rows keep their stamped expiry.
- Recording objects contain no planner or customer identity in their key:
  `consultation-recordings/<recording_uuid>/source`.
- Application rows are scoped by owner, customer, and recording UUID. Object
  storage is shared across web instances so a retry can continue on another
  server without creating a second recording.

## Cloudflare R2 bucket

Create a dedicated private bucket. Do not reuse the general media bucket.

```text
Bucket: inpa-consultation-recordings
Prefix: consultation-recordings/
AllowedOrigins: https://www.inpa.kr
AllowedMethods: PUT, GET, HEAD
AllowedHeaders: content-type
ExposeHeaders: ETag
Multipart abort: 1 day
Object lifecycle: consultation-recordings/ after 30 days
```

Keep public access disabled. Add CORS for the exact production origin above.
Add preview origins only while testing, then remove them.

Success signal:

1. A presigned part `PUT` returns 200 and exposes an `ETag` header.
2. A presigned play `GET` works before expiry.
3. Direct bucket URLs remain inaccessible.
4. An unfinished multipart upload is removed after one day.
5. Application cleanup removes a v2 object after its exact 30-day expiry. The
   bucket lifecycle uses the same 30-day value as a second deletion path.

## Environment variables

Set these independently for every Render web, worker, and consultation-cleanup
service that touches recordings:

```text
CONSULTATION_RECORDING_ENABLED=false
CONSULTATION_AI_SUMMARY_ENABLED=false
CONSULTATION_SHOWCASE_PILOT_ENABLED=false
CONSULTATION_PRESIGN_TTL_SECONDS=600
CONSULTATION_STORAGE_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CONSULTATION_STORAGE_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
CONSULTATION_STORAGE_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
CONSULTATION_STORAGE_BUCKET=inpa-consultation-recordings
CONSULTATION_STORAGE_REGION=auto
CONSULTATION_RETENTION_HOURS=720
CONSULTATION_RETENTION_SAFETY_MINUTES=30
CONSULTATION_MAX_DURATION_SECONDS=3600
CONSULTATION_MAX_BYTES=104857600
CONSULTATION_UPLOAD_PART_BYTES=8388608
CONSULTATION_SUMMARY_ACTIVE_LIMIT=1
CONSULTATION_STT_PROVIDER=openai
CONSULTATION_SUMMARY_PROVIDER=openai
CONSULTATION_AI_REQUEST_TIMEOUT_SECONDS=180
OPENAI_API_KEY=<OPENAI_SERVER_KEY>
OPENAI_TRANSCRIPTION_MODEL=<OPENAI_COMPARISON_TRANSCRIPTION_MODEL>
OPENAI_CONSULTATION_TRANSCRIPTION_MODEL=gpt-4o-transcribe-diarize
OPENAI_COMPARISON_MODEL=<OPENAI_SUMMARY_MODEL>
# 선택값. 비우면 OPENAI_COMPARISON_MODEL을 사용한다.
OPENAI_CONSULTATION_SUMMARY_MODEL=
BACKEND_BASE_URL=https://inpa-be.onrender.com
```

Secrets belong in Render secret environment values. Never place them in Git,
Vercel public variables, browser code, logs, or support tickets.

The worker converts the private source to a 16 kHz mono, 32 kbps MP3 before
calling the transcription endpoint. This keeps a 60-minute meeting below the
audio upload limit while preserving the original private R2 object unchanged.
The raw audio is sent to OpenAI for transcription. Only after transcription
does Inpa remove known names, phone numbers, email addresses, resident numbers,
and account-number patterns before sending text to the summary model. Neither
the raw transcript nor the masked transcript is stored in the database or logs.

## v2 retention preflight

Before applying the migration or opening the recording gate, run this read-only
query against production PostgreSQL:

```sql
BEGIN TRANSACTION READ ONLY;

SELECT
    retention_hours_snapshot,
    retention_days_snapshot,
    COUNT(*) AS row_count
FROM consultation_recording
WHERE retention_policy_version = 'v2-30d'
  AND (
      retention_hours_snapshot IS DISTINCT FROM 720
      OR retention_days_snapshot IS DISTINCT FROM 30
  )
GROUP BY retention_hours_snapshot, retention_days_snapshot
ORDER BY retention_hours_snapshot, retention_days_snapshot;

ROLLBACK;
```

Success signal: zero rows. This query does not change live data.

If any row is returned, keep `CONSULTATION_RECORDING_ENABLED=false` and stop
the rollout. Do not silently rewrite its policy version, snapshot, or
`expires_at`; the stamped expiry remains the deletion authority for that
existing row. Record only the affected recording UUIDs and timestamps in the
restricted incident log, identify how they were created, and agree on customer
notice or other remediation with the PM/privacy owner before reopening the
gate. A corrected deploy may issue only new, exact 720-hour v2 rows.

After a customer withdrawal commits, the API issues no new play, download, or
multipart part URL and will not complete an existing upload. Encountering a
stale upload attempts an immediate multipart abort and exact-key deletion;
storage failure leaves the row in `deleting/retry_required` for retry.

A play or download URL issued before withdrawal can remain usable only until
its existing 300-second signature expires. This bounded window is the accepted
current policy; immediate revocation would require a separately designed
authenticated media proxy.

A multipart part URL issued before withdrawal can accept a `PUT` until the
withdrawal worker aborts that upload or the configured signature expires
(600 seconds by default). The server completion endpoint remains closed after
withdrawal, so those bytes cannot become a completed recording through the
application. Before opening the gate, verify abort behavior and the one-day
unfinished-multipart lifecycle in the real R2 bucket, then explicitly accept
this bounded window or lower the configured TTL.

## Deployment order

1. Keep all three environment gates closed.
2. Deploy the application code. This pilot adds no retention migration.
3. Verify `/healthz/`.
4. Confirm the cleanup cron runs every 15 minutes.
5. Configure the private R2 bucket and all consultation storage variables.
6. Run the read-only audit:

   ```bash
   python manage.py audit_consultation_storage
   ```

7. In `/admin/consultations`, confirm:
   - environment gate reflects the closed state;
   - active upload, source, deleted, overdue, and failure counts render;
   - the response and page contain no playback URL, customer name, memo text,
     storage key, transcript, or recording contents.
8. Open the recording, AI summary, and exact showcase pilot environment gates.
9. Add individual pilot planner accounts in `/admin/consultations`.
10. Open the runtime recording switch.

## AI summary pilot

The summary worker uses the shared PostgreSQL database as its coordination
authority. Every run is one-to-one with a recording, and every recording is
already bound to one owner and one customer. A database lease plus
`CONSULTATION_SUMMARY_ACTIVE_LIMIT=1` prevents two Render processes from
submitting different provider calls for the same source. An OpenAI call is
reserved before transmission; a timeout with unknown receipt becomes terminal
and is never submitted again.

Before enabling summaries:

1. Keep `CONSULTATION_AI_SUMMARY_ENABLED=false`.
2. Set the OpenAI server key, diarized transcription model, summary model,
   private R2, and HTTPS `BACKEND_BASE_URL` variables on both web and worker.
3. Confirm the worker consumes `consultation_summaries`.
4. Confirm one Chrome WebM recording is converted to mono 16 kHz WAV and
   OpenAI returns speaker-separated segments.
5. Confirm the saved memo contains only the four bullet sections and remains
   editable.
6. Confirm the database contains token counts and status only, not transcript
   or masked transcript fields.
7. Revoke each of the three current customer consents during processing and
   confirm no memo is created.
8. Delete a source during processing and confirm late provider results are
   discarded.
9. Redeliver the worker job and confirm the OpenAI call and memo counts both
   remain one.
10. Add only `test@inpa.kr` as a pilot, enable its recording and summary
    permissions, then open both runtime switches.
11. In `/admin/consultations`, confirm the separate showcase-pilot table shows
    provider, model, processing seconds, tokens, outcome, and estimated cost.
    It must not show the customer, audio, transcript, prompt, or memo body.

An unknown provider receipt becomes `ambiguous` and is never submitted again.
The planner can write or edit a direct memo, but that recording cannot request
a second AI summary.

## Deletion checks

The application cleanup selects rows only with server-stamped `expires_at`, a
source-present status, and a non-null exact UUID key. It never uses user-editable
memo or date fields.

Rows stamped `deleting/retry_required` are retried by the 15-minute cleanup
before their original expiry. A remaining multipart upload ID is aborted on
every retry, the first server-stamped deletion reason is preserved, and a late
failure cannot change a source already verified as deleted.

Run:

```bash
python manage.py cleanup_consultation_recordings
python manage.py audit_consultation_storage
```

Success signal:

- cleanup JSON reports `failed: 0`;
- audit reports `overdue_object_count: 0`;
- audit reports `orphan_object_count: 0`;
- R2 `HEAD` for a deleted exact key returns 404;
- an old presigned play URL no longer returns the object.

Three consecutive verified deletion failures automatically close the runtime
recording switch. Investigate the storage credentials, bucket policy, and
lifecycle rule before reopening it.

## Mobile pilot matrix

Record each result with device, OS, browser version, start/end time, recording
UUID, byte size, duration, and result. Never paste audio or customer identity
into the report.

| Scenario | iPhone Safari | Android Chrome | Expected |
|---|---|---|---|
| 60-minute recording | Required | Required | Stops at 60 minutes and completes |
| Incoming call | Required | Required | Finishes or provides a recoverable next action |
| Screen lock | Required | Required | No customer cross-link; exact session outcome recorded |
| App switch/background | Required | Required | Visible guidance; no duplicate session |
| Bluetooth change | Required | Required | Track-end finalizes the current recording |
| Wi-Fi to LTE | Required | Required | Same part number retries after 1s, 2s, 4s |
| Response lost then retry | Required | Required | Same `client_session_id` returns the same recording |
| Playback | Required | Required | Short-lived private URL only |
| Early delete | Required | Required | Source removed and `HEAD` returns 404 |

Production recording and AI summary gates stay closed until this matrix and the
deletion evidence are complete.
