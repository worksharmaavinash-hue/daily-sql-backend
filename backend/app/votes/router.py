from fastapi import APIRouter, Depends, HTTPException
from app.db import get_pool
from app.auth.jwt import verify_jwt, verify_jwt_optional
from typing import Optional

router = APIRouter(tags=["votes"])


@router.get("/problems/{problem_id}/votes")
async def get_votes(problem_id: str, current_user: Optional[dict] = Depends(verify_jwt_optional)):
    """Get like count for a problem and whether the current user has voted."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        likes = await conn.fetchval(
            "SELECT COUNT(*) FROM core.problem_votes WHERE problem_id = $1",
            problem_id
        )
        user_has_voted = False
        if current_user:
            user_has_voted = await conn.fetchval(
                "SELECT EXISTS(SELECT 1 FROM core.problem_votes WHERE user_id = $1 AND problem_id = $2)",
                current_user["user_id"], problem_id
            )
    return {"likes": likes, "user_has_voted": user_has_voted}


@router.post("/problems/{problem_id}/votes")
async def toggle_vote(problem_id: str, current_user: dict = Depends(verify_jwt)):
    """Toggle like on a problem. Call again to un-like."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM core.problem_votes WHERE user_id = $1 AND problem_id = $2)",
            current_user["user_id"], problem_id
        )
        if existing:
            await conn.execute(
                "DELETE FROM core.problem_votes WHERE user_id = $1 AND problem_id = $2",
                current_user["user_id"], problem_id
            )
            action = "unliked"
        else:
            await conn.execute(
                "INSERT INTO core.problem_votes (user_id, problem_id) VALUES ($1, $2)",
                current_user["user_id"], problem_id
            )
            action = "liked"

        likes = await conn.fetchval(
            "SELECT COUNT(*) FROM core.problem_votes WHERE problem_id = $1",
            problem_id
        )

    return {"action": action, "likes": likes, "user_has_voted": action == "liked"}
