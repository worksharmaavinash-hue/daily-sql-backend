"""
Prometheus Observability Metrics for DailySQL
Organized across 4 core layers:
1. Code Execution & Sandbox Health
2. API & Infrastructure Performance
3. Business & Product Metrics (Solvers, Streaks, Attempts)
4. Payments & Coupon Conversion
"""
from prometheus_client import Counter, Histogram, Gauge

# =====================================================================
# Layer 1: Code Execution & Sandbox Health
# =====================================================================

# Execution duration histogram by engine
EXECUTION_DURATION_SECONDS = Histogram(
    'dailysql_execution_duration_seconds',
    'Execution latency for code sandboxes in seconds',
    ['engine'],  # postgresql, mysql, python, pyspark, python_dsa
    buckets=[0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# Total submission outcomes by engine and status
SUBMISSION_TOTAL = Counter(
    'dailysql_submission_total',
    'Total code submissions partitioned by engine and execution status',
    ['engine', 'status']  # correct, wrong_answer, syntax_error, runtime_error, timeout, oom, dry_run
)

# Active execution runner depth (gauge)
ACTIVE_EXECUTIONS = Gauge(
    'dailysql_active_executions',
    'Number of currently executing queries or sandbox processes',
    ['engine']
)

# =====================================================================
# Layer 2: API & Infrastructure Performance
# =====================================================================

# Rate limiter 429 hits
RATE_LIMIT_HITS = Counter(
    'dailysql_rate_limit_hits_total',
    'Count of rate limit 429 rejections triggered',
    ['endpoint']
)

# Active database connections checked out of asyncpg pool
DB_POOL_ACTIVE = Gauge(
    'dailysql_db_pool_active_connections',
    'Active asyncpg database connections currently acquired'
)

# =====================================================================
# Layer 3: DailySQL Business & Product Metrics
# =====================================================================

# Active solvers gauge (updated on attempt)
ACTIVE_SOLVERS = Gauge(
    'dailysql_active_solvers_gauge',
    'Active unique solvers in the current monitoring window'
)

# Problem completions counter
PROBLEM_COMPLETIONS = Counter(
    'dailysql_problem_completions_total',
    'Successful problem completions by difficulty and challenge type',
    ['difficulty', 'challenge_type']
)

# Total challenge attempts
CHALLENGE_ATTEMPTS = Counter(
    'dailysql_challenge_attempts_total',
    'Total attempts submitted by challenge type',
    ['challenge_type']
)

# Streak metrics
ACTIVE_STREAKS = Gauge(
    'dailysql_active_streaks_total',
    'Current active user streak counter'
)

STREAK_FREEZE_USED = Counter(
    'dailysql_streak_freeze_used_total',
    'Total streak freeze redemptions count'
)

STREAK_BROKEN = Counter(
    'dailysql_streak_broken_total',
    'Total broken user streaks'
)

# =====================================================================
# Layer 4: Payments & Coupon Conversion
# =====================================================================

# Cashfree webhook events
CASHFREE_WEBHOOK_STATUS = Counter(
    'dailysql_cashfree_webhook_total',
    'Cashfree webhook callback events by outcome status',
    ['event_type', 'status']  # success, signature_error, failure
)

# Paywall encounters for free tier
PAYWALL_ENCOUNTERS = Counter(
    'dailysql_paywall_encounters_total',
    'Times users encountered paywall prompts by trigger feature',
    ['feature']  # practice_limit, non_sql_track, solution_preview
)

# Coupon activations
COUPON_REDEMPTIONS = Counter(
    'dailysql_coupon_redemptions_total',
    'Promotional and voucher coupon redemptions count',
    ['plan_granted']
)

# Checkout funnel
CHECKOUT_INITIATED = Counter(
    'dailysql_checkout_initiated_total',
    'Subscription checkouts initiated by plan',
    ['plan_id']
)

PAYMENT_SUCCESS = Counter(
    'dailysql_payment_success_total',
    'Payments completed and subscription activated',
    ['plan_id']
)
