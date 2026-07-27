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
        
        # Block dangerous function calls
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                if node.func.id in ('__import__', 'eval', 'exec', 'compile', 'open',
                                    'breakpoint', 'input', 'memoryview'):
                    raise ValueError(f"Use of '{node.func.id}()' is not allowed")
            
            # Block builtins/module-level execution functions
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ('__import__', 'system', 'popen', 'exec',
                                       'call', 'run', 'Popen'):
                    raise ValueError(f"Use of '.{node.func.attr}()' is not allowed")

        # Block attribute access to dunder methods (except common safe ones)
        if isinstance(node, ast.Attribute):
            if node.attr.startswith('__') and node.attr.endswith('__'):
                if node.attr not in ('__init__', '__str__', '__repr__', '__len__',
                                      '__getitem__', '__setitem__', '__contains__',
                                      '__iter__', '__next__', '__eq__', '__lt__',
                                      '__gt__', '__le__', '__ge__', '__ne__',
                                      '__add__', '__sub__', '__mul__', '__truediv__',
                                      '__mod__', '__pow__', '__hash__',
                                      '__enter__', '__exit__', '__name__'):
                    raise ValueError(f"Access to '{node.attr}' is not allowed")
                
    return True

def validate_code(code: str, challenge_type: str):
    if challenge_type == 'sql':
        return validate_sql(code)
    elif challenge_type in ('python', 'pyspark', 'python_dsa'):
        return validate_python(code)
    return True

