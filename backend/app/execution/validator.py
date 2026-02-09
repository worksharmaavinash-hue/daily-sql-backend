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

    if not lowered.strip().startswith(("select", "with")):
        raise ValueError("Only SELECT queries are allowed")

    return True
