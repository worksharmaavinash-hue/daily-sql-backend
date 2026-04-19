from fastapi import APIRouter, Depends
from app.db import get_pool
from app.auth.jwt import verify_jwt_optional
from pydantic import BaseModel
from typing import Optional

router = APIRouter(tags=["feedback"])


class FeedbackCreate(BaseModel):
    rating: Optional[int] = None   # 1=Bad, 2=Okay, 3=Great
    message: Optional[str] = None
    source: str = "fab"            # 'fab' | 'dislike'
    problem_id: Optional[str] = None
    email: Optional[str] = None    # for anonymous users


@router.post("/feedback", status_code=201)
async def submit_feedback(
    payload: FeedbackCreate,
    current_user: Optional[dict] = Depends(verify_jwt_optional),
):
    """Submit user feedback. Works for both authenticated and anonymous users."""
    if payload.source not in ("fab", "dislike"):
        payload.source = "fab"

    if payload.rating is not None and payload.rating not in (1, 2, 3):
        payload.rating = None

    pool = await get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            INSERT INTO core.feedback (user_id, email, rating, message, source, problem_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id, created_at
            """,
            current_user["user_id"] if current_user else None,
            payload.email if not current_user else None,
            payload.rating,
            payload.message,
            payload.source,
            payload.problem_id,
        )

    return {"id": str(row["id"]), "created_at": row["created_at"].isoformat()}
