import re

FORBIDDEN_KEYWORDS = [
    "insert", "update", "delete",
    "drop", "alter", "truncate",
    "copy", "create", "grant", "revoke"
]

def validate_sql(sql: str):
    lowered = sql.lower()

    for keyword in FORBIDDEN_KEYWORDS:
        if re.search(rf"\b{keyword}\b", lowered):
            raise ValueError(f"Usage of '{keyword.upper()}' is not allowed")

    # Strip single-line comments (-- ...) before checking query type,
    # so a leading comment like "-- Write your query for: ..." doesn't block execution.
    stripped_for_type_check = re.sub(r'--[^\n]*', '', lowered).strip()

    if not stripped_for_type_check.startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed")

    return True
