import re
import ast

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

def validate_python(code: str):
    """
    Validate Python/PySpark code at AST level to detect syntax errors and block dangerous libraries.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise ValueError(f"Syntax Error in code: {str(e)}")

    BLOCKED_IMPORTS = {
        'os', 'subprocess', 'sys', 'socket', 'shutil',
        'importlib', 'ctypes', 'multiprocessing', 'threading',
        'builtins', 'eval', 'exec', '__import__'
    }
    
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                module_name = alias.name.split('.')[0]
                if module_name in BLOCKED_IMPORTS:
                    raise ValueError(f"Import of module '{module_name}' is not allowed for security reasons")
                
    return True

def validate_code(code: str, challenge_type: str):
    if challenge_type == 'sql':
        return validate_sql(code)
    elif challenge_type in ('python', 'pyspark'):
        return validate_python(code)
    return True

