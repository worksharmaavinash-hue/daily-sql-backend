from pydantic import BaseModel
from typing import List, Dict, Optional, Any
from uuid import UUID
from datetime import date

class ProblemCreate(BaseModel):
    title: str
    difficulty: str
    description: str
    estimated_time_minutes: int
    challenge_type: str = "sql"  # "sql" | "python" | "pyspark" | "python_dsa"

class DatasetCreate(BaseModel):
    table_name: str
    schema_sql: Optional[str] = None
    seed_sql: Optional[str] = None
    column_types: Dict[str, str] = {}
    seed_data_json: Optional[Dict] = None

class SolutionCreate(BaseModel):
    reference_query: Optional[str] = None
    reference_code: Optional[str] = None
    function_name: Optional[str] = None  # DSA only: e.g. "twoSum", "maxSubArray"
    starter_code: Optional[str] = None   # DSA only: full function stub shown to users, e.g. "def twoSum(nums: List[int], target: int) -> List[int]:"
    order_sensitive: bool = False
    notes: Optional[str] = None

class TestCaseCreate(BaseModel):
    input_data: dict       # {"args": [[1,2,3], 9]} — positional args matching function signature
    expected: Any          # any JSON-serializable value: int, list[int], str, bool, etc.
    is_hidden: bool = True # false = sample (shown to user), true = hidden (grading only)
    label: Optional[str] = None
    order_index: int = 0

class DailyPracticeCreate(BaseModel):
    date: date  # YYYY-MM-DD
    easy_problem_id: UUID
    medium_problem_id: UUID
    advanced_problem_id: UUID
    python_easy_problem_id: Optional[UUID] = None
    python_medium_problem_id: Optional[UUID] = None
    python_advanced_problem_id: Optional[UUID] = None
    pyspark_easy_problem_id: Optional[UUID] = None
    pyspark_medium_problem_id: Optional[UUID] = None
    pyspark_advanced_problem_id: Optional[UUID] = None
    dsa_easy_problem_id: Optional[UUID] = None
    dsa_medium_problem_id: Optional[UUID] = None
    dsa_advanced_problem_id: Optional[UUID] = None

class WhitelistCreate(BaseModel):
    email: str

class WhitelistBulkCreate(BaseModel):
    emails: List[str]
