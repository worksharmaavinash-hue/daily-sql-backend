from fastapi import APIRouter, HTTPException, Depends, Header
from pydantic import BaseModel
import json
from app.execution.validator import validate_code
from app.db import get_pool
from app.execution.schema_manager import (
    setup_execution_schema,
    teardown_execution_schema,
    apply_execution_limits
)
from app.execution.problem_guard import ensure_problem_exists
from app.execution.runner import execute_user_query, QueryExecutionError
from app.execution.engines.mysql_engine import MySQLEngine
from app.execution.judge import compare_results, compare_dsa_results
from app.attempts.service import record_attempt
from app.streaks.service import update_streak
from app.auth.jwt import verify_jwt, verify_jwt_optional
from app.rate_limit.limiter import rate_limit
from app.execution.engines import get_engine
from app.payments.subscription_service import has_active_subscription
from app.payments.dependencies import is_free_daily_sql_problem
from typing import Optional
import time
from app.metrics import (
    EXECUTION_DURATION_SECONDS,
    SUBMISSION_TOTAL,
    ACTIVE_EXECUTIONS,
    CHALLENGE_ATTEMPTS,
    PROBLEM_COMPLETIONS,
    PAYWALL_ENCOUNTERS,
)

FREE_TIER_SQL_LIMIT = 30  # First N SQL problems accessible to free users

router = APIRouter(prefix="/execute", tags=["execution"])

class ExecuteRequest(BaseModel):
    problem_id: str
    query: str
    mode: str = "submit"       # "run" | "submit" — only meaningful for python_dsa
    sql_dialect: str = "postgresql"  # "postgresql" | "mysql" — only meaningful for sql


@router.post("")
async def execute_query(
    payload: ExecuteRequest,
    user: Optional[dict] = Depends(verify_jwt_optional)
):
    # 0️⃣ Rate Limit (only for logged-in users for now)
    if user:
        await rate_limit(user["user_id"])

    pool = await get_pool()

    async with pool.acquire() as conn:
        schema_name = None
        engine_label = None
        exec_start_time = None
        try:
            # 1️⃣ Validate problem
            await ensure_problem_exists(conn, payload.problem_id)

            # Fetch problem details to check challenge_type and row_number
            prob_row = await conn.fetchrow(
                "SELECT challenge_type, row_number, difficulty FROM core.problems WHERE id = $1",
                payload.problem_id
            )
            if not prob_row:
                raise HTTPException(status_code=404, detail="Problem not found")

            challenge_type = prob_row["challenge_type"]
            raw_row = prob_row["row_number"]
            if (raw_row is None or raw_row <= 0) and challenge_type == "sql":
                count_before = await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM core.problems
                    WHERE challenge_type = 'sql'
                      AND (created_at < (SELECT created_at FROM core.problems WHERE id = $1)
                           OR (created_at = (SELECT created_at FROM core.problems WHERE id = $1) AND id <= $1))
                    """,
                    payload.problem_id,
                )
                row_num = count_before or 1
            else:
                row_num = raw_row or 0

            # 1.2️⃣ Subscription / access guard
            is_daily_problem = await is_free_daily_sql_problem(conn, payload.problem_id)

            is_non_sql = challenge_type != "sql"
            is_beyond_free = row_num > FREE_TIER_SQL_LIMIT
            needs_paid = (is_non_sql or is_beyond_free) and not is_daily_problem
            if needs_paid:
                is_paid = False
                if user:
                    is_paid = await has_active_subscription(conn, user["user_id"])
                if not is_paid:
                    PAYWALL_ENCOUNTERS.labels(feature="non_sql_track" if is_non_sql else "practice_limit").inc()
                    raise HTTPException(
                        status_code=403,
                        detail="subscription_required",
                    )

            # 1.1️⃣ Validate code
            try:
                validate_code(payload.query, challenge_type)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))

            # 1.5 Check User Profile (Onboarding)
            if user:
                profile_exists = await conn.fetchval(
                    "SELECT onboarding_completed FROM core.users WHERE user_id = $1",
                    user["user_id"]
                )
                if not profile_exists:
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": "PROFILE_REQUIRED",
                        "diff_reason": "Please complete your profile details to start practicing.",
                        "test_summary": None,
                    }

            # ==========================================
            # 2️⃣ Branch by challenge type & track execution
            # ==========================================
            engine_label = payload.sql_dialect if challenge_type == 'sql' else challenge_type
            ACTIVE_EXECUTIONS.labels(engine=engine_label).inc()
            exec_start_time = time.perf_counter()

            if challenge_type == 'sql':
                # ── SQL Flow (PostgreSQL or MySQL) ────────────────────────────
                dialect = payload.sql_dialect  # 'postgresql' | 'mysql'

                if dialect == 'mysql':
                    # ── MySQL path ─────────────────────────────────────────
                    # Verify the problem has dual-dialect support
                    has_mysql = await conn.fetchval(
                        """
                        SELECT 1 FROM core.problem_datasets
                        WHERE problem_id = $1 AND mysql_schema_sql IS NOT NULL
                        LIMIT 1
                        """,
                        payload.problem_id
                    )
                    if not has_mysql:
                        return {
                            "status": "error",
                            "user": None,
                            "expected": None,
                            "error": "This problem does not support MySQL dialect",
                            "diff_reason": None,
                            "test_summary": None,
                        }

                    mysql_engine = MySQLEngine()
                    user_result = await mysql_engine.run(payload.query, payload.problem_id, conn)

                    if user_result.get("error"):
                        return {
                            "status": "error",
                            "user": None,
                            "expected": None,
                            "error": user_result["error"],
                            "diff_reason": None,
                            "test_summary": None,
                        }

                    sol_row = await conn.fetchrow(
                        "SELECT reference_query, mysql_reference_query, order_sensitive FROM core.problem_solutions WHERE problem_id = $1",
                        payload.problem_id
                    )
                    if not sol_row:
                        return {
                            "status": "error",
                            "user": user_result,
                            "expected": None,
                            "error": "Configuration Error: Reference solution not found",
                            "diff_reason": None,
                            "test_summary": None,
                        }

                    # Use mysql_reference_query if set; fall back to reference_query
                    effective_ref = sol_row["mysql_reference_query"] or sol_row["reference_query"]
                    expected_result = await mysql_engine.run(effective_ref, payload.problem_id, conn)

                else:
                    # ── PostgreSQL path (existing, unchanged) ──────────────
                    schema_name = await setup_execution_schema(conn, payload.problem_id)
                    await apply_execution_limits(conn)
                    user_result = await execute_user_query(conn, payload.query)

                    sol_row = await conn.fetchrow(
                        "SELECT reference_query, mysql_reference_query, order_sensitive FROM core.problem_solutions WHERE problem_id = $1",
                        payload.problem_id
                    )
                    if not sol_row:
                        return {
                            "status": "error",
                            "user": user_result,
                            "expected": None,
                            "error": "Configuration Error: Reference solution not found",
                            "diff_reason": None,
                            "test_summary": None,
                        }

                    expected_result = await execute_user_query(conn, sol_row["reference_query"])

                is_correct, reason = compare_results(
                    user_result,
                    expected_result,
                    order_sensitive=sol_row["order_sensitive"]
                )

                if user:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=user_result["execution_time_ms"],
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                user_result["execution_time_ms"]
                            )
                    except Exception as e:
                        print(f"Stats recording error: {e}")

                if exec_start_time and engine_label:
                    duration = time.perf_counter() - exec_start_time
                    EXECUTION_DURATION_SECONDS.labels(engine=engine_label).observe(duration)
                    CHALLENGE_ATTEMPTS.labels(challenge_type=challenge_type).inc()
                    SUBMISSION_TOTAL.labels(engine=engine_label, status="correct" if is_correct else "wrong_answer").inc()
                    if is_correct:
                        diff_val = prob_row.get("difficulty") if prob_row else "Medium"
                        PROBLEM_COMPLETIONS.labels(difficulty=diff_val or "Medium", challenge_type=challenge_type).inc()

                return {
                    "status": "correct" if is_correct else "incorrect",
                    "user": {
                        "columns": user_result["columns"],
                        "rows": user_result["rows"],
                        "execution_time_ms": user_result["execution_time_ms"],
                    },
                    "expected": {
                        "columns": expected_result["columns"],
                        "rows": expected_result["rows"],
                    },
                    "error": None,
                    "diff_reason": None if is_correct else reason,
                    "test_summary": None,
                }

            elif challenge_type == 'python_dsa':
                # ── Python DSA Flow ──────────────────────────────────────────
                is_run_mode = (payload.mode == "run")

                # Fetch test cases — "run" mode fetches only sample (non-hidden) cases
                test_case_rows = await conn.fetch(
                    """
                    SELECT input_data, expected, label, is_hidden
                    FROM core.problem_test_cases
                    WHERE problem_id = $1
                      AND (NOT $2 OR is_hidden = false)
                    ORDER BY order_index, created_at
                    """,
                    payload.problem_id,
                    is_run_mode,
                )

                if not test_case_rows:
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": "Configuration Error: No test cases found for this problem.",
                        "diff_reason": None,
                        "test_summary": None,
                    }

                test_cases = [
                    {
                        "input_data": (json.loads(r["input_data"]) if isinstance(r["input_data"], str) else r["input_data"]),
                        "expected":   (json.loads(r["expected"])   if isinstance(r["expected"],   str) else r["expected"]),
                        "label":      r["label"],
                        "is_hidden":  r["is_hidden"],
                    }
                    for r in test_case_rows
                ]

                # Get function name from solution record
                sol_row = await conn.fetchrow(
                    "SELECT function_name FROM core.problem_solutions WHERE problem_id = $1",
                    payload.problem_id
                )
                function_name = (sol_row["function_name"] if sol_row and sol_row["function_name"] else "solve")

                # Run via Python engine (shared runner container, DSA mode)
                engine = get_engine(challenge_type)
                runner_result = await engine.run(
                    payload.query,
                    payload.problem_id,
                    conn,
                    {},
                    test_cases=test_cases,
                    function_name=function_name,
                )

                if runner_result.get("error"):
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": runner_result["error"],
                        "diff_reason": None,
                        "test_summary": None,
                    }

                # Merge input_data back from our test_cases list into the runner
                # results (the runner container only echoes back got/expected/error).
                raw_results = runner_result.get("results", [])
                for i, r in enumerate(raw_results):
                    if i < len(test_cases):
                        r["input_data"] = test_cases[i].get("input_data")

                is_correct, reason, test_summary = compare_dsa_results(raw_results)

                # Record attempt + update streak only on Submit mode
                if user and not is_run_mode:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=runner_result.get("execution_time_ms", 0),
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                runner_result.get("execution_time_ms", 0),
                            )
                    except Exception as e:
                        print(f"Stats recording error: {e}")

                if exec_start_time and engine_label:
                    duration = time.perf_counter() - exec_start_time
                    EXECUTION_DURATION_SECONDS.labels(engine=engine_label).observe(duration)
                    CHALLENGE_ATTEMPTS.labels(challenge_type=challenge_type).inc()
                    status_lbl = "dry_run" if is_run_mode else ("correct" if is_correct else "wrong_answer")
                    SUBMISSION_TOTAL.labels(engine=engine_label, status=status_lbl).inc()
                    if is_correct and not is_run_mode:
                        diff_val = prob_row.get("difficulty") if prob_row else "Medium"
                        PROBLEM_COMPLETIONS.labels(difficulty=diff_val or "Medium", challenge_type=challenge_type).inc()

                return {
                    # "run_result" signals the frontend this was a dry-run (no badge/streak update)
                    "status": "run_result" if is_run_mode else ("correct" if is_correct else "incorrect"),
                    "user": None,
                    "expected": None,
                    "error": None,
                    "diff_reason": reason,
                    "test_summary": test_summary,
                }

            else:
                # ── Python (Pandas) / PySpark Flow ───────────────────────────
                datasets = await conn.fetch(
                    "SELECT table_name, seed_data_json FROM core.problem_datasets WHERE problem_id = $1",
                    payload.problem_id
                )
                payload_data = {
                    d["table_name"]: (
                        json.loads(d["seed_data_json"]) if isinstance(d["seed_data_json"], str)
                        else d["seed_data_json"]
                    ) if d["seed_data_json"] is not None else {"columns": [], "rows": []}
                    for d in datasets
                }

                engine = get_engine(challenge_type)
                user_result = await engine.run(payload.query, payload.problem_id, conn, payload_data)

                sol_row = await conn.fetchrow(
                    "SELECT reference_output, order_sensitive FROM core.problem_solutions WHERE problem_id = $1", 
                    payload.problem_id
                )
                
                if not sol_row or not sol_row["reference_output"]:
                     return {
                        "status": "error",
                        "user": user_result if not user_result.get("error") else None,
                        "expected": None,
                        "error": "Configuration Error: Pre-computed reference output not found",
                        "diff_reason": None,
                        "test_summary": None,
                    }

                expected_result = sol_row["reference_output"]
                if isinstance(expected_result, str):
                    expected_result = json.loads(expected_result)

                if user_result.get("error"):
                    return {
                        "status": "error",
                        "user": None,
                        "expected": None,
                        "error": user_result["error"],
                        "diff_reason": None,
                        "test_summary": None,
                    }

                is_correct, reason = compare_results(
                    user_result, 
                    expected_result, 
                    order_sensitive=sol_row["order_sensitive"]
                )

                if user:
                    user_id = user["user_id"]
                    try:
                        await record_attempt(
                            conn,
                            user_id=user_id,
                            problem_id=payload.problem_id,
                            status="correct" if is_correct else "incorrect",
                            execution_time_ms=user_result["execution_time_ms"],
                            challenge_type=challenge_type
                        )
                        await update_streak(conn, user_id=user_id, was_correct=is_correct)
                        if is_correct:
                            await conn.execute(
                                """
                                INSERT INTO core.user_solutions (user_id, problem_id, submitted_query, execution_time_ms)
                                VALUES ($1, $2, $3, $4)
                                ON CONFLICT (user_id, problem_id) DO UPDATE SET
                                    submitted_query = EXCLUDED.submitted_query,
                                    execution_time_ms = EXCLUDED.execution_time_ms,
                                    created_at = NOW()
                                """,
                                user_id,
                                payload.problem_id,
                                payload.query,
                                user_result["execution_time_ms"]
                            )
                    except Exception as e:
                        print(f"Stats recording error: {e}")

                if exec_start_time and engine_label:
                    duration = time.perf_counter() - exec_start_time
                    EXECUTION_DURATION_SECONDS.labels(engine=engine_label).observe(duration)
                    CHALLENGE_ATTEMPTS.labels(challenge_type=challenge_type).inc()
                    SUBMISSION_TOTAL.labels(engine=engine_label, status="correct" if is_correct else "wrong_answer").inc()
                    if is_correct:
                        diff_val = prob_row.get("difficulty") if prob_row else "Medium"
                        PROBLEM_COMPLETIONS.labels(difficulty=diff_val or "Medium", challenge_type=challenge_type).inc()

                return {
                    "status": "correct" if is_correct else "incorrect",
                    "user": {
                        "columns": user_result["columns"],
                        "rows": user_result["rows"],
                        "execution_time_ms": user_result["execution_time_ms"],
                    },
                    "expected": {
                        "columns": expected_result["columns"],
                        "rows": expected_result["rows"],
                    },
                    "error": None,
                    "diff_reason": None if is_correct else reason,
                    "test_summary": None,
                }

        except QueryExecutionError as e:
            if exec_start_time and engine_label:
                duration = time.perf_counter() - exec_start_time
                EXECUTION_DURATION_SECONDS.labels(engine=engine_label).observe(duration)
                err_status = "timeout" if "timeout" in str(e).lower() else "runtime_error"
                SUBMISSION_TOTAL.labels(engine=engine_label, status=err_status).inc()

            return {
                "status": "error",
                "user": None,
                "expected": None,
                "error": str(e),
                "diff_reason": None,
                "test_summary": None,
            }

        except Exception as e:
            if exec_start_time and engine_label:
                duration = time.perf_counter() - exec_start_time
                EXECUTION_DURATION_SECONDS.labels(engine=engine_label).observe(duration)
                err_status = "oom" if "memory" in str(e).lower() else "runtime_error"
                SUBMISSION_TOTAL.labels(engine=engine_label, status=err_status).inc()

            import traceback
            traceback.print_exc()
            raise HTTPException(status_code=400, detail=str(e))

        finally:
            if engine_label:
                ACTIVE_EXECUTIONS.labels(engine=engine_label).dec()
            if schema_name:
                await teardown_execution_schema(conn, schema_name)
