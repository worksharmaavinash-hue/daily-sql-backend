def compare_results(user_result, expected_result, order_sensitive=False):
    """
    Compare user execution result with expected result.
    Returns (is_correct, diff_reason)
    """
    
    # 1. Check schemas/columns match
    # Normalizing columns? For now assume strict match needed or at least length match.
    # Usually we want column names to match or just values?
    # LeetCode usually requires specific column names.
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
