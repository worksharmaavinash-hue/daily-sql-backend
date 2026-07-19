def compare_results(user_result, expected_result, order_sensitive=False):
    """
    Compare user execution result with expected result.
    Used for SQL, Python (Pandas), and PySpark problems.
    Returns (is_correct, diff_reason)
    """

    # 1. Check schemas/columns match
    if user_result["columns"] != expected_result["columns"]:
        return False, f"Column mismatch. Expected {expected_result['columns']}, got {user_result['columns']}"

    user_rows = user_result["rows"]
    exp_rows = expected_result["rows"]

    if len(user_rows) != len(exp_rows):
        return False, f"Row count mismatch. Expected {len(exp_rows)}, got {len(user_rows)}"

    if not order_sensitive:
        # Sort both for comparison if order doesn't matter
        # lists are not hashable, so we sort by tuple conversion
        try:
            user_rows = sorted(map(tuple, user_rows))
            exp_rows = sorted(map(tuple, exp_rows))
        except Exception:
            # Fallback if types are not sortable easily
            pass

    if user_rows != exp_rows:
        return False, "Row data mismatch. Your results do not match the expected output."

    return True, None


def compare_dsa_results(results: list):
    """
    Compare DSA test case execution results.
    Used exclusively for python_dsa problems.

    Args:
        results: list of per-test-case result dicts from the runner.
                 Each has: passed, got, expected, label, is_hidden, error (optional)

    Returns:
        (is_correct, diff_reason, test_summary_for_client)

    Visibility rules:
        - Sample tests (is_hidden=False): show full got vs expected on failure
        - Hidden tests (is_hidden=True):  show got but mask expected as "hidden"
        - All tests passing: no masking needed (nothing to spoil)
    """
    total = len(results)
    passed_count = sum(1 for r in results if r.get("passed"))
    is_correct = (passed_count == total)
    diff_reason = None if is_correct else f"{passed_count}/{total} test cases passed."

    client_results = []
    for r in results:
        is_hidden = r.get("is_hidden", False)
        passed = r.get("passed", False)
        client_result = {
            "passed": passed,
            "label": r.get("label"),
            "is_hidden": is_hidden,
            "error": r.get("error"),
            "got": r.get("got"),
            # Hidden tests: show expected only if they passed (no spoiling), mask on failure
            "expected": r.get("expected") if (not is_hidden or passed) else "hidden",
        }
        client_results.append(client_result)

    test_summary = {
        "passed": passed_count,
        "total": total,
        "results": client_results,
    }

    return is_correct, diff_reason, test_summary
