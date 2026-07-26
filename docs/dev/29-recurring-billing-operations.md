# Recurring Billing Operations

## Safety state

Production deploys the schema and code with all payment gates closed:

```text
BILLING_CARD_REGISTRATION_ENABLED=false
BILLING_RECURRING_CHARGE_ENABLED=false
BILLING_WEBHOOK_RECONCILIATION_ENABLED=false
FREE_TIER_UNLIMITED=true
```

An administrator cannot open a capability past a closed environment gate. The
effective recurring-charge gate requires all of the following:

1. KICC credentials and token encryption are configured.
2. The environment card-registration gate is open.
3. The runtime card-registration switch is open.
4. The environment reconciliation gate is open.
5. The runtime reconciliation switch is open.
6. Both environment and runtime `FREE_TIER_UNLIMITED` values are false.
7. The environment recurring-charge gate is open.
8. The runtime recurring-charge switch is open.

Do not reverse this order. Card registration must never open before status
query, cancellation, and billing-key deletion can be operated.

## KICC endpoints

Use only HTTPS endpoints from the KICC merchant contract:

```text
Sandbox API:    https://testpgapi.easypay.co.kr
Production API: https://pgapi.easypay.co.kr
```

The adapter owns these server-to-server paths:

```text
POST /api/ep9/trades/webpay            registration window
POST /api/ep9/trades/approval          billing-key issue
POST /api/trades/approval/batch        recurring approval
POST /api/trades/retrieveTransaction   status query
POST /api/trades/revise                full cancellation
POST /api/trades/removeBatchKey        billing-key deletion
```

KICC references:

- https://docs.kicc.co.kr/en/docs/online-payment/common/api-domain/
- https://docs.kicc.co.kr/en/docs/online-payment/billing/register-window/
- https://docs.kicc.co.kr/en/docs/online-payment/billing/payment/
- https://docs.kicc.co.kr/en/docs/online-payment/management/query-status/
- https://docs.kicc.co.kr/en/docs/online-payment/management/cancel/
- https://docs.kicc.co.kr/en/docs/online-payment/billing/delete-key/

## Render environment

Set the following on the Render web, worker, and 15-minute reconciliation cron.
Use one environment group so values cannot drift between processes:

```text
KICC_MALL_ID=<KICC_MERCHANT_ID>
KICC_CLIENT_SECRET=<KICC_MESSAGE_AUTH_SECRET>
KICC_API_BASE_URL=https://testpgapi.easypay.co.kr
PAYMENT_TOKEN_ENCRYPTION_KEY=<FERNET_KEY>
PAYMENT_TOKEN_KEY_VERSION=v1
BILLING_NOTICE_DEVICE_HMAC_KEY=<RANDOM_HMAC_KEY>

BILLING_CARD_REGISTRATION_ENABLED=false
BILLING_RECURRING_CHARGE_ENABLED=false
BILLING_WEBHOOK_RECONCILIATION_ENABLED=false
FREE_TIER_UNLIMITED=true

BACKEND_BASE_URL=https://inpa-be.onrender.com
FRONTEND_BASE_URL=https://www.inpa.kr
```

Generate independent Fernet and HMAC keys. Never reuse Django `SECRET_KEY`,
KICC secrets, or recording-storage keys. Never put any of these values in
Vercel, `NEXT_PUBLIC_*`, Git, logs, screenshots, or support messages.

Vercel needs no payment secret. It uses the existing
`NEXT_PUBLIC_API_BASE=https://inpa-be.onrender.com/api/v1`.

## Deployment and pilot order

1. Keep all environment gates closed and `FREE_TIER_UNLIMITED=true`.
2. Deploy migrations and application code.
3. Check `GET https://inpa-be.onrender.com/healthz/`.
4. Confirm the reconciliation cron runs every 15 minutes with:

   ```text
   billing reconciliation queued due=... unknown=... revocation=...
   ```

5. In `/admin/billing`, confirm environment readiness, runtime switches,
   unknown orders, pending billing-key deletion, and `계측 확인 필요`.
6. Configure sandbox credentials and change only
   `KICC_API_BASE_URL=https://testpgapi.easypay.co.kr`.
7. Open the environment card and reconciliation gates. Keep recurring approval
   and paid quotas closed.
8. In `/admin/billing`, open the card-registration and reconciliation runtime
   switches.
9. Issue a one-month coupon with one allowed use to a dedicated test planner.
10. Complete the full sandbox matrix below.
11. Repeat with two- and three-month coupons, including month-end and leap-year
    dates.
12. Obtain KICC production credentials and change the base URL to
    `https://pgapi.easypay.co.kr`.
13. Repeat the matrix with an internally authorized low-value production test.
14. Set environment and runtime `FREE_TIER_UNLIMITED=false`.
15. Open the environment recurring-charge gate, then its runtime switch.
16. Start with pilot planners only and watch the operations page after each
    billing date.

## Sandbox acceptance matrix

Record order IDs, internal statuses, provider response codes, and timestamps.
Never record card numbers, billing keys, customer details, or memo contents.

| Scenario | Expected Inpa result | Provider-call invariant |
|---|---|---|
| Card registration | Coupon becomes `redeemed`, agreement becomes `trialing`, encrypted token is active | One key issue |
| 1-month coupon | Access ends the day before the same calendar date next month | No approval during free period |
| 2/3-month coupon | First charge date is the same anchor date after 2/3 calendar months | No 30-day arithmetic |
| First-charge confirmation | Exact plan, VAT-inclusive amount, date, and masked card label are stored | No provider call |
| Approval | One `PaymentOrder`, one `PaymentAttempt`, active period advances one calendar month | One approval POST |
| Provider decline | User moves to Free, future approval stops, data remains | No automatic retry |
| Approval timeout | Order becomes `unknown`, access is finite for 24 hours | No second approval POST |
| Unknown recovery | Status query settles the original order | Query only |
| Approval found after 24h | Full cancellation is requested and user remains Free | Query then one cancel |
| User cancellation | Current access period remains, next charge is removed | Billing-key deletion only |
| Billing-key deletion timeout | Token stays `revocation_pending` with ciphertext intact | Retry deletion, never approval |

Success evidence:

1. The database has one order per `(agreement, cycle_sequence)`.
2. The database has one attempt per `(order, attempt_no)`.
3. Repeating the task or HTTP response recovery does not increase KICC approval
   calls.
4. A successful response matches merchant ID, request ID, order ID, amount, and
   message authentication before projection.
5. A Free transition leaves customer and memo row counts and content hashes
   unchanged.
6. `NorthStarEvent.payload` contains only approved enum and numeric fields.
7. `계측 확인 필요` remains zero during a healthy run.

## Unknown-payment handling

KICC requires a status query after approval timeout or network loss. Inpa never
blindly retries an approval:

1. The initial result becomes `unknown`.
2. Access is projected for at most 24 hours.
3. Reconciliation queries at approximately 5 minutes, 30 minutes, and 24 hours.
4. An approval found before 24 hours settles the original order.
5. A decline moves the user to Free and queues billing-key deletion.
6. An approval first found after 24 hours is fully canceled.
7. A still-unknown result after 24 hours ends temporary access and keeps the
   order visible to administrators.

If `계측 확인 필요` is above zero, compare `PaymentAttempt.started_at` with
content-free billing events. Do not re-run approval. Queue only the existing
unknown order from `/admin/billing`.

## Incident actions

### Approval or response-integrity incident

1. Close the runtime recurring-charge switch in `/admin/billing`.
2. If the administrator API is unavailable, set
   `BILLING_RECURRING_CHARGE_ENABLED=false` on Render and redeploy.
3. Leave reconciliation open so unknown payments can be queried and late
   approvals canceled.
4. Export only order IDs, result enums, amounts, and timestamps for comparison.
5. Resolve every unknown order before reopening approvals.

### Billing-key deletion incident

1. Keep recurring approval closed for affected agreements.
2. Leave tokens in `revocation_pending`; do not erase ciphertext before KICC
   confirms deletion.
3. Retry the existing token from `/admin/billing`.
4. Confirm token state becomes `revoked`, `revoked_at` is set, and ciphertext is
   empty.

### Key rotation

1. Add code support for the next `PAYMENT_TOKEN_KEY_VERSION`.
2. Deploy decryption support for both old and new versions.
3. Change the environment version and encryption key for newly issued tokens.
4. Re-encrypt existing active tokens in a controlled command.
5. Remove old-key support only after the active old-version count reaches zero.

Never replace `PAYMENT_TOKEN_ENCRYPTION_KEY` in place without this sequence.

## Rollback

Application rollback:

1. Close runtime recurring approval, then card registration.
2. Keep reconciliation running.
3. Roll Render and Vercel back to the previous verified revision.
4. Do not reverse billing migrations while payment orders, attempts, tokens, or
   consents exist.
5. Confirm `/healthz/`, `/admin/billing`, the unknown queue, and the
   reconciliation cron.

Commercial rollback:

1. Set runtime `FREE_TIER_UNLIMITED=true`.
2. Set environment `FREE_TIER_UNLIMITED=true` on the next controlled deploy.
3. Keep customer and memo data unchanged.
4. Stop future approvals and delete active billing keys through the normal
   provider-confirmed flow.

The code can be deployed to production while all payment capabilities remain
closed. Opening real payments requires the completed sandbox and production
evidence above.
