from pydantic import BaseModel
from typing import List, Dict, Optional
from uuid import UUID
from datetime import date

class ProblemCreate(BaseModel):
    title: str
    difficulty: str
    description: str
    estimated_time_minutes: int

class DatasetCreate(BaseModel):
    table_name: str
    schema_sql: str
    seed_sql: str
    sample_rows: List[Dict]

class SolutionCreate(BaseModel):
    reference_query: str
    order_sensitive: bool = False
    notes: Optional[str] = None

class DailyPracticeCreate(BaseModel):
    date: date  # YYYY-MM-DD
    easy_problem_id: UUID
    medium_problem_id: UUID
    advanced_problem_id: UUID
