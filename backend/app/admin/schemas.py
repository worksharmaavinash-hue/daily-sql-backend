from pydantic import BaseModel
from typing import List, Dict, Optional
from uuid import UUID
from datetime import date

class ProblemCreate(BaseModel):
    title: str
    difficulty: str
    description: str
    estimated_time_minutes: int
    challenge_type: str = "sql"  # "sql" | "python" | "pyspark"

class DatasetCreate(BaseModel):
    table_name: str
    schema_sql: Optional[str] = None
    seed_sql: Optional[str] = None
    column_types: Dict[str, str] = {}
    seed_data_json: Optional[Dict] = None

class SolutionCreate(BaseModel):
    reference_query: Optional[str] = None
    reference_code: Optional[str] = None
    order_sensitive: bool = False
    notes: Optional[str] = None

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

class WhitelistCreate(BaseModel):
    email: str

class WhitelistBulkCreate(BaseModel):
    emails: List[str]
