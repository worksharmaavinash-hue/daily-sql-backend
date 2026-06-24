from app.execution.engines.postgres_engine import PostgresEngine
from app.execution.engines.python_engine import PythonEngine
from app.execution.engines.pyspark_engine import PySparkEngine

def get_engine(challenge_type: str):
    if challenge_type == 'sql':
        return PostgresEngine()
    elif challenge_type == 'python':
        return PythonEngine()
    elif challenge_type == 'pyspark':
        return PySparkEngine()
    raise ValueError(f"Unknown challenge type: {challenge_type}")
