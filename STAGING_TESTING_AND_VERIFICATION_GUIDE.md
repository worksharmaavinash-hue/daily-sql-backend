# Daily SQL — Staging Testing, Webhook & Verification Guide

This checklist guides you step-by-step through setting up, testing, and verifying all newly implemented features in your **Staging / Test Environment** (`docker-compose.staging.yml`).

---

## 📑 Summary of Checklist Phases

1. [Phase 1: Start Staging Stack, Run Migrations & Seed Questions](#phase-1-start-staging-stack-run-migrations--seed-questions)
2. [Phase 2: Global 30-Day Launch Trial Activation](#phase-2-global-30-day-launch-trial-activation)
3. [Phase 3: New User 7-Day Free Trial Verification](#phase-3-new-user-7-day-free-trial-verification)
4. [Phase 4: Early User Lifetime Coupon Generation & Redemption](#phase-4-early-user-lifetime-coupon-generation--redemption)
5. [Phase 5: Free Tier vs Paid Tier Question Access Gating](#phase-5-free-tier-vs-paid-tier-question-access-gating)
6. [Phase 6: Cashfree Payment Flow & Webhook Testing](#phase-6-cashfree-payment-flow--webhook-testing)
7. [Phase 7: Production Go-Live Checklist](#phase-7-production-go-live-checklist)

---

## Phase 1: Start Staging Stack, Run Migrations & Seed Questions

### 1.1 Start Staging Docker Containers
```bash
# In daily-sql-backend directory
docker compose -f docker-compose.staging.yml up -d --build
```

### 1.2 Apply Database Schema & Subscription Migrations
```bash
# Run schema and subscription table migrations inside staging API container
docker exec -it dailysql_api_test python app/create_tables.py
```
*Or pipe the standalone SQL script directly into PostgreSQL:*
```bash
docker exec -i dailysql_postgres_test psql -U postgres -d dailysql < migration_subscriptions.sql
```

### 1.3 Seed 110 Questions (50 SQL + 30 Python + 30 PySpark)
```bash
docker exec -it dailysql_api_test python app/seed_curriculum.py
```

**Verify seeded questions in DB:**
```bash
docker exec -it dailysql_postgres_test psql -U postgres -d dailysql -c "SELECT challenge_type, count(*), min(row_number), max(row_number) FROM core.problems GROUP BY challenge_type;"
```
*Expected Output: `sql (50, row_number 1..50)`, `python (30)`, `pyspark (30)`.*

---

## Phase 2: Global 30-Day Launch Trial Activation

When you launch, you want **all existing registered users** to enjoy **30 days of full, unrestricted access**.

### 2.1 Activate Launch Trial via Admin API or SQL

**Option A: Via Admin API**
```bash
curl -X POST "http://localhost:8001/admin/launch-config" \
  -H "X-Admin-Secret: admin_secret" \
  -H "Content-Type: application/json" \
  -d '{
    "is_active": true,
    "trial_days": 30,
    "new_user_trial_days": 7,
    "coupon_grace_days": 2
  }'
```

**Option B: Directly via SQL in PostgreSQL**
```bash
docker exec -i dailysql_postgres_test psql -U postgres -d dailysql -c "
UPDATE core.launch_config 
SET is_active = TRUE, 
    trial_days = 30, 
    trial_start = NOW(), 
    trial_end = NOW() + INTERVAL '30 days',
    new_user_trial_days = 7,
    coupon_grace_days = 2
WHERE id = 1;
"
```

### 2.2 Verify Launch Trial Status
```bash
curl http://localhost:8001/api/coupons/launch-status
```
*Expected JSON:*
```json
{
  "is_active": true,
  "trial_days": 30,
  "trial_end": "2026-09-24T...",
  "days_remaining": 30,
  "is_currently_running": true
}
```

### 2.3 Verification Check
- Log in with any existing user account.
- Visit `/profile` — The membership card shows **`Launch Trial (Full Access)`** with emerald badge.
- Open SQL questions `31` to `50`, Python questions, or PySpark questions — queries execute with full access.

---

## Phase 3: New User 7-Day Free Trial Verification

Any **new user** who signs up during or after the launch trial automatically gets a **7-Day Personal Free Trial**.

### 3.1 Test New User Registration
1. Go to `http://localhost:3000/signup`.
2. Register a new test account: `newuser_test@example.com`.
3. Complete the OTP verification.

### 3.2 Verify Trial Attributes in DB
```bash
docker exec -it dailysql_postgres_test psql -U postgres -d dailysql -c "
SELECT email, plan, trial_type, trial_expires_at, trial_expires_at > NOW() AS is_trial_active 
FROM core.users 
WHERE email = 'newuser_test@example.com';
"
```
*Expected Output:*
- `trial_type`: `new_signup`
- `trial_expires_at`: Exactly 7 days from signup date.
- `is_trial_active`: `t` (true).

### 3.3 Verify Frontend Display
- Navbar User Dropdown shows: **`7-DAY TRIAL`** in emerald.
- User Profile shows: **`7-Day Trial (Full Access)`** with expiration date.
- All 110 questions are fully executable.

---

## Phase 4: Early User Lifetime Coupon Generation & Redemption

Selected early users receive unique, single-use coupons granting permanent **Lifetime VIP access**.

### 4.1 Generate Early User Coupons & Export CSV
```bash
# Runs coupon generator for existing users with 32-day validity (30 days trial + 2 days grace)
docker exec -it dailysql_api_test python generate_coupons.py --days 32 --csv /app/early_users_coupons.csv
```

**Inspect generated coupons:**
```bash
docker exec -it dailysql_api_test head -n 10 /app/early_users_coupons.csv
```
*Example record:*
```csv
email,username,full_name,coupon_code,plan_granted,expires_at,status
early_user@example.com,earlybird,Early Adopter,DSQL-LT-7K9M2P4X,lifetime,2026-09-26T...,active
```

### 4.2 Test Coupon Redemption Scenarios

#### Scenario A: Successful Redemption (Matching Email)
1. Log in as `early_user@example.com`.
2. Navigate to `http://localhost:3000/redeem` (or `/profile` coupon box).
3. Enter the coupon code: `DSQL-LT-7K9M2P4X`.
4. Click **"Unlock Lifetime Plan"**.
5. **Expected Result**:
   - Screen displays: *"Lifetime VIP Plan activated successfully! 🎉"*
   - In DB, `core.users.plan` updates to `'lifetime'`.
   - `core.coupons.is_used` becomes `true` with timestamp.

#### Scenario B: Rejection on Email Mismatch
1. Log in as a different user: `stranger@example.com`.
2. Try redeeming `early_user@example.com`'s code `DSQL-LT-7K9M2P4X`.
3. **Expected Result**:
   - Request is rejected with HTTP 400: *"This coupon code was issued for a different email address."*

#### Scenario C: Rejection on Duplicate Redemption (Single-Use Enforced)
1. Try redeeming `DSQL-LT-7K9M2P4X` a second time on the same account.
2. **Expected Result**:
   - Request is rejected with HTTP 400: *"This coupon code has already been redeemed."*

---

## Phase 5: Free Tier vs Paid Tier Question Access Gating

When a user has **no active trial** and **no paid plan** (standard Free Tier user):

### 5.1 Free Tier Access Rules
| Challenge Track | Question Numbers | Access Allowed? |
|---|---|---|
| **SQL** | `1` to `30` | ✅ **Yes** (Free Tier Allowance) |
| **SQL** | `31` to `50` | 🔒 **No** (Requires Pro / Lifetime Plan) |
| **Python** | `1` to `30` | 🔒 **No** (Requires Pro / Lifetime Plan) |
| **PySpark** | `1` to `30` | 🔒 **No** (Requires Pro / Lifetime Plan) |
| **Daily Practice** | Today's Daily Set | ✅ **Yes** (Free for all) |

### 5.2 Testing Free Tier Gating
1. Set a test user back to the free tier (reset trial):
   ```bash
   docker exec -it dailysql_postgres_test psql -U postgres -d dailysql -c "
   UPDATE core.users 
   SET plan = 'free', trial_expires_at = NULL, trial_type = NULL 
   WHERE email = 'free_user@example.com';
   "
   ```
2. Disable the global launch trial temporarily for this test:
   ```bash
   docker exec -it dailysql_postgres_test psql -U postgres -d dailysql -c "UPDATE core.launch_config SET is_active = FALSE WHERE id = 1;"
   ```
3. Test query executions:
   - Run SQL problem #5 (`row_number = 5`) -> **Executes successfully**.
   - Run SQL problem #35 (`row_number = 35`) -> Returns **403 Forbidden**: *"Question #35 requires an active subscription or trial"*.
   - Run Python problem #1 -> Returns **403 Forbidden**.
4. Re-enable launch trial after verification.

---

## Phase 6: Cashfree Payment Flow & Webhook Testing

### 6.1 Configure Sandbox Environment Variables in Staging `.env`
```env
CASHFREE_APP_ID=TEST_YOUR_APP_ID
CASHFREE_SECRET_KEY=TEST_YOUR_SECRET_KEY
CASHFREE_ENV=sandbox
FRONTEND_URL=http://localhost:3000
```

### 6.2 Test End-to-End Checkout via Browser
1. Log in to Daily SQL and visit `http://localhost:3000/payment`.
2. Choose **Yearly Pro (₹1,499)** or **Lifetime VIP (₹4,999)** and click **"Pay"**.
3. Cashfree Drop-in Checkout opens in a modal.
4. **Use Cashfree Sandbox Test Credentials**:
   - **Test Card**: `4706131211212123` | Expiry: `03/2028` | CVV: `123` | OTP: `111000`
   - **Test UPI**: `testsuccess@gocash`
5. Upon completion, Cashfree redirects to `http://localhost:3000/payment/success?order_id=...`.
6. Backend automatically verifies the order status (`GET /pg/orders/{order_id}`) with Cashfree API and updates DB:
   - `core.subscriptions.status` = `'active'`
   - `core.users.plan` = `'yearly'` / `'lifetime'`

---

### 6.3 Cashfree Webhook Configuration & Testing

#### A. Configure Webhook in Cashfree Merchant Dashboard
1. Log in to [Cashfree Sandbox Dashboard](https://sandbox.cashfree.com/merchant/).
2. Navigate to: **Payment Gateway → Developers → Webhooks**.
3. Click **Add Webhook Endpoint**:
   - **Endpoint URL**: `https://<your-staging-backend-domain>/api/payments/webhook`
   - **Events to Subscribe**:
     - `PAYMENT_SUCCESS_WEBHOOK`
     - `PAYMENT_FAILED_WEBHOOK`
     - `PAYMENT_USER_DROPPED_WEBHOOK`
   - **API Version**: `2025-01-01` (Recommended)

#### B. Simulating Webhook Delivery with HMAC Signature via Python
You can simulate a Cashfree webhook delivery to your staging endpoint using this test script:

```python
import hmac
import hashlib
import base64
import time
import requests
import json

SECRET_KEY = "TEST_YOUR_SECRET_KEY"
WEBHOOK_URL = "http://localhost:8001/api/payments/webhook"

payload = {
    "data": {
        "order": {
            "order_id": "order_test_12345",
            "order_amount": 1499.00,
            "order_currency": "INR",
            "order_tags": {"user_id": "<USER_UUID>", "plan_id": "yearly"}
        },
        "payment": {
            "cf_payment_id": "pay_test_9999",
            "payment_status": "SUCCESS",
            "payment_amount": 1499.00,
            "payment_time": "2026-08-23T14:30:00+05:30"
        }
    },
    "event_time": "2026-08-23T14:30:00+05:30",
    "type": "PAYMENT_SUCCESS_WEBHOOK"
}

raw_body = json.dumps(payload, separators=(',', ':'))
timestamp = str(int(time.time()))

# Calculate HMAC-SHA256 Signature
signature_data = f"{timestamp}{raw_body}".encode('utf-8')
expected_signature = base64.b64encode(
    hmac.new(SECRET_KEY.encode('utf-8'), signature_data, hashlib.sha256).digest()
).decode('utf-8')

headers = {
    "Content-Type": "application/json",
    "x-webhook-timestamp": timestamp,
    "x-webhook-signature": expected_signature,
    "x-webhook-version": "2025-01-01"
}

resp = requests.post(WEBHOOK_URL, data=raw_body, headers=headers)
print(f"Webhook Response ({resp.status_code}):", resp.json())
```

---

## Phase 7: Production Go-Live Checklist

Before switching to live production traffic, complete this mandatory checklist:

- [ ] **Domain Whitelisting**: Whitelist `https://dailysql.in` on the Cashfree Production Dashboard (**Payment Gateway → Settings → Whitelisted Domains**). Checkout will fail in production without HTTPS domain whitelisting.
- [ ] **Production Keys**: Update production environment variables:
  - `CASHFREE_APP_ID=PROD_...`
  - `CASHFREE_SECRET_KEY=PROD_...`
  - `CASHFREE_ENV=production`
- [ ] **Production Webhooks**: Register `https://api.dailysql.in/api/payments/webhook` on the production dashboard.
- [ ] **Webhook Firewall Whitelist**: Whitelist Cashfree Production IPs if behind a firewall:
  - `52.66.101.190`, `3.109.102.144`, `18.60.134.245`, `18.60.183.142`
- [ ] **Server-Side Re-Verification**: Confirm payment updates rely solely on server-side `verify-order` & webhook HMAC signatures, never on frontend client parameters.
- [ ] **Automated Subscription Sweeper**: Ensure `core.expire_stale_subscriptions()` is scheduled in background tasks to sweep expired subscriptions.
