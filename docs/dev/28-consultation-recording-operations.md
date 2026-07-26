# Consultation Recording Operations

## Safety state

- Production defaults stay closed:
  - `CONSULTATION_RECORDING_ENABLED=false`
  - `CONSULTATION_AI_SUMMARY_ENABLED=false`
- Runtime switches and per-user pilot access are additional gates. All gates must
  be open for a planner to use the corresponding feature.
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
Object lifecycle: consultation-recordings/ after 6 days, secondary maximum-7-day guard
```

Keep public access disabled. Add CORS for the exact production origin above.
Add preview origins only while testing, then remove them.

Success signal:

1. A presigned part `PUT` returns 200 and exposes an `ETag` header.
2. A presigned play `GET` works before expiry.
3. Direct bucket URLs remain inaccessible.
4. An unfinished multipart upload is removed after one day.
5. The lifecycle rule removes an object before the stated seven-day maximum.

## Environment variables

Set these independently for every Render web, worker, and consultation-cleanup
service that touches recordings:

```text
CONSULTATION_RECORDING_ENABLED=false
CONSULTATION_AI_SUMMARY_ENABLED=false
CONSULTATION_STORAGE_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
CONSULTATION_STORAGE_ACCESS_KEY_ID=<R2_ACCESS_KEY_ID>
CONSULTATION_STORAGE_SECRET_ACCESS_KEY=<R2_SECRET_ACCESS_KEY>
CONSULTATION_STORAGE_BUCKET=inpa-consultation-recordings
CONSULTATION_STORAGE_REGION=auto
CONSULTATION_RETENTION_HOURS=168
CONSULTATION_RETENTION_SAFETY_MINUTES=30
CONSULTATION_MAX_DURATION_SECONDS=3600
CONSULTATION_MAX_BYTES=104857600
CONSULTATION_UPLOAD_PART_BYTES=8388608
CONSULTATION_SUMMARY_ACTIVE_LIMIT=1
CONSULTATION_SUMMARY_MODEL=<ANTHROPIC_MODEL_ID>
CLOVA_SPEECH_INVOKE_URL=<CLOVA_DOMAIN_INVOKE_URL>
CLOVA_SPEECH_SECRET_KEY=<CLOVA_SECRET_KEY>
BACKEND_BASE_URL=https://inpa-be.onrender.com
```

Secrets belong in Render secret environment values. Never place them in Git,
Vercel public variables, browser code, logs, or support tickets.

## Deployment order

1. Keep both environment gates closed.
2. Deploy the database migration and application code.
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
8. Open the environment gate for a preview/pilot environment only.
9. Add individual pilot planner accounts in `/admin/consultations`.
10. Open the runtime recording switch.

## AI summary pilot

The summary worker uses the shared PostgreSQL database as its coordination
authority. Every run is one-to-one with a recording, and every recording is
already bound to one owner and one customer. A database lease plus
`CONSULTATION_SUMMARY_ACTIVE_LIMIT=1` prevents two Render processes from
submitting different provider jobs for the same source. Provider job tokens are
stored before polling, and a delivered callback only wakes that exact run. The
callback body is never treated as a transcript.

Before enabling summaries:

1. Keep `CONSULTATION_AI_SUMMARY_ENABLED=false`.
2. Set CLOVA Speech, Anthropic model, private R2, and HTTPS
   `BACKEND_BASE_URL` variables on both web and worker.
3. Confirm the worker consumes `consultation_summaries`.
4. Confirm one Chrome WebM recording is converted to mono 16 kHz WAV and CLOVA
   reaches `COMPLETED`.
5. Confirm the saved memo contains only the four bullet sections and remains
   editable.
6. Confirm the database contains token counts and status only, not transcript
   or masked transcript fields.
7. Revoke each of the three current customer consents during processing and
   confirm no memo is created.
8. Delete a source during processing and confirm late provider results are
   discarded.
9. Retry a callback and worker delivery and confirm the provider submit and
   memo counts both remain one.
10. Enable only one planner's `summary_allowed` pilot access, then open the
    runtime summary switch.

An unknown provider receipt becomes `ambiguous` and is never submitted again.
The planner can write or edit a direct memo, but that recording cannot request
a second AI summary.

## Deletion checks

The application cleanup selects rows only with server-stamped `expires_at`, a
source-present status, and a non-null exact UUID key. It never uses user-editable
memo or date fields.

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
