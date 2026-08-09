from app.execution.engines.postgres_engine import PostgresEngine
from app.execution.engines.mysql_engine import MySQLEngine
from app.execution.engines.python_engine import PythonEngine
from app.execution.engines.pyspark_engine import PySparkEngine

def get_engine(challenge_type: str, sql_dialect: str = "postgresql"):
    if challenge_type == "sql":
        if sql_dialect == "mysql":
            return MySQLEngine()
        return PostgresEngine()
    elif challenge_type in ("python", "python_dsa"):
        return PythonEngine()
    elif challenge_type == "pyspark":
        return PySparkEngine()
    raise ValueError(f"Unknown challenge type: {challenge_type}")
