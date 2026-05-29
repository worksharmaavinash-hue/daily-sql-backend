from abc import ABC, abstractmethod

class BaseExecutionEngine(ABC):
    @abstractmethod
    async def run(self, code: str, problem_id: str, conn, datasets: dict) -> dict:
        """
        Executes code and returns standardized result dict:
        {
            "columns": [...],
            "rows": [[...]],
            "execution_time_ms": int,
            "error": Optional[str]
        }
        """
        pass
