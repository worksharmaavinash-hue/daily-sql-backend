from fastapi import APIRouter, Depends, HTTPException, Query
from app.db import get_pool
from app.auth.jwt import verify_jwt, verify_jwt_optional
from pydantic import BaseModel, Field
from typing import Optional

router = APIRouter(tags=["comments"])


class CommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=2000)
    parent_id: Optional[str] = None


class CommentVote(BaseModel):
    vote_type: int = Field(..., description="1 for like, -1 for dislike")


@router.get("/problems/{problem_id}/comments")
async def get_comments(
    problem_id: str,
    count_only: bool = Query(False),
    limit: int = Query(30, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: Optional[dict] = Depends(verify_jwt_optional),
):
    """
    Get comments for a problem.
    - count_only=true: returns { count } quickly (used for the button badge)
    - otherwise: returns paginated top-level comments with nested replies
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        if count_only:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM core.comments WHERE problem_id = $1 AND parent_id IS NULL",
                problem_id
            )
            return {"count": count}

        # Fetch top-level comments
        top_rows = await conn.fetch(
            """
            SELECT
                c.id, c.body, c.created_at, c.parent_id, c.user_id,
                u.full_name, u.email,
                (SELECT COUNT(*) FROM core.comment_votes WHERE comment_id = c.id AND vote_type = 1) as likes,
                (SELECT COUNT(*) FROM core.comment_votes WHERE comment_id = c.id AND vote_type = -1) as dislikes,
                (SELECT vote_type FROM core.comment_votes WHERE comment_id = c.id AND user_id = $4) as user_vote
            FROM core.comments c
            JOIN core.users u ON c.user_id = u.user_id
            WHERE c.problem_id = $1 AND c.parent_id IS NULL
            ORDER BY c.created_at ASC
            LIMIT $2 OFFSET $3
            """,
            problem_id, limit, offset,
            current_user["user_id"] if current_user else None
        )

        top_ids = [str(r["id"]) for r in top_rows]

        # Fetch all replies in one query
        replies_map: dict = {}
        if top_ids:
            placeholders = ", ".join(f"${i+1}" for i in range(len(top_ids)))
            reply_rows = await conn.fetch(
                f"""
                SELECT
                    c.id, c.body, c.created_at, c.parent_id, c.user_id,
                    u.full_name, u.email,
                    (SELECT COUNT(*) FROM core.comment_votes WHERE comment_id = c.id AND vote_type = 1) as likes,
                    (SELECT COUNT(*) FROM core.comment_votes WHERE comment_id = c.id AND vote_type = -1) as dislikes,
                    (SELECT vote_type FROM core.comment_votes WHERE comment_id = c.id AND user_id = ${len(top_ids) + 1}) as user_vote
                FROM core.comments c
                JOIN core.users u ON c.user_id = u.user_id
                WHERE c.parent_id::text IN ({placeholders})
                ORDER BY c.created_at ASC
                """,
                *top_ids,
                current_user["user_id"] if current_user else None
            )
            for r in reply_rows:
                pid = str(r["parent_id"])
                if pid not in replies_map:
                    replies_map[pid] = []
                replies_map[pid].append({
                    "id": str(r["id"]),
                    "body": r["body"],
                    "created_at": r["created_at"].isoformat(),
                    "parent_id": str(r["parent_id"]),
                    "user": {
                        "full_name": r["full_name"] or r["email"].split("@")[0],
                        "initials": ((r["full_name"] or r["email"])[:2]).upper(),
                    },
                    "is_own": current_user is not None and str(r["user_id"]) == str(current_user["user_id"]),
                    "likes": r["likes"],
                    "dislikes": r["dislikes"],
                    "user_vote": r["user_vote"]
                })

        results = []
        for r in top_rows:
            cid = str(r["id"])
            replies = replies_map.get(cid, [])
            results.append({
                "id": cid,
                "body": r["body"],
                "created_at": r["created_at"].isoformat(),
                "parent_id": None,
                "user": {
                    "full_name": r["full_name"] or r["email"].split("@")[0],
                    "initials": ((r["full_name"] or r["email"])[:2]).upper(),
                },
                "reply_count": len(replies),
                "replies": replies,
                "is_own": current_user is not None and str(r["user_id"]) == str(current_user["user_id"]),
                "likes": r["likes"],
                "dislikes": r["dislikes"],
                "user_vote": r["user_vote"]
            })

    return results


@router.post("/problems/{problem_id}/comments", status_code=201)
async def post_comment(
    problem_id: str,
    payload: CommentCreate,
    current_user: dict = Depends(verify_jwt),
):
    """Post a new comment or reply. Replies are capped at depth 1 (no reply-to-reply)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        if payload.parent_id:
            parent = await conn.fetchrow(
                "SELECT id, parent_id, problem_id FROM core.comments WHERE id = $1",
                payload.parent_id
            )
            if not parent:
                raise HTTPException(status_code=404, detail="Parent comment not found")
            if str(parent["problem_id"]) != problem_id:
                raise HTTPException(status_code=400, detail="Parent comment belongs to a different problem")
            if parent["parent_id"] is not None:
                raise HTTPException(status_code=400, detail="Cannot reply to a reply (max 2 levels)")

        new_comment = await conn.fetchrow(
            """
            INSERT INTO core.comments (problem_id, user_id, parent_id, body)
            VALUES ($1, $2, $3, $4)
            RETURNING id, body, created_at, parent_id
            """,
            problem_id,
            current_user["user_id"],
            payload.parent_id,
            payload.body,
        )

        user = await conn.fetchrow(
            "SELECT full_name, email FROM core.users WHERE user_id = $1",
            current_user["user_id"]
        )

    return {
        "id": str(new_comment["id"]),
        "body": new_comment["body"],
        "created_at": new_comment["created_at"].isoformat(),
        "parent_id": str(new_comment["parent_id"]) if new_comment["parent_id"] else None,
        "user": {
            "full_name": user["full_name"] or user["email"].split("@")[0],
            "initials": ((user["full_name"] or user["email"])[:2]).upper(),
        },
        "reply_count": 0,
        "replies": [],
        "is_own": True,
    }


@router.delete("/comments/{comment_id}", status_code=204)
async def delete_comment(
    comment_id: str,
    current_user: dict = Depends(verify_jwt),
):
    """Delete own comment."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        comment = await conn.fetchrow(
            "SELECT user_id FROM core.comments WHERE id = $1",
            comment_id
        )
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")
        if str(comment["user_id"]) != str(current_user["user_id"]):
            raise HTTPException(status_code=403, detail="Cannot delete another user's comment")

        await conn.execute("DELETE FROM core.comments WHERE id = $1", comment_id)


@router.post("/comments/{comment_id}/vote")
async def toggle_vote(
    comment_id: str,
    payload: CommentVote,
    current_user: dict = Depends(verify_jwt),
):
    """
    Toggle a like/dislike on a comment.
    - If same vote exists: DELETE (toggle off)
    - If different vote exists: UPDATE
    - If no vote: INSERT
    """
    if payload.vote_type not in (1, -1):
        raise HTTPException(status_code=400, detail="Invalid vote type")

    pool = await get_pool()
    async with pool.acquire() as conn:
        # Check if comment exists
        exists = await conn.fetchval("SELECT 1 FROM core.comments WHERE id = $1", comment_id)
        if not exists:
            raise HTTPException(status_code=404, detail="Comment not found")

        # Check existing vote
        existing_vote = await conn.fetchval(
            "SELECT vote_type FROM core.comment_votes WHERE comment_id = $1 AND user_id = $2",
            comment_id, current_user["user_id"]
        )

        if existing_vote == payload.vote_type:
            # Toggle off
            await conn.execute(
                "DELETE FROM core.comment_votes WHERE comment_id = $1 AND user_id = $2",
                comment_id, current_user["user_id"]
            )
            return {"status": "removed"}
        elif existing_vote is not None:
            # Update vote type
            await conn.execute(
                "UPDATE core.comment_votes SET vote_type = $1 WHERE comment_id = $2 AND user_id = $3",
                payload.vote_type, comment_id, current_user["user_id"]
            )
            return {"status": "updated", "vote_type": payload.vote_type}
        else:
            # New vote
            await conn.execute(
                "INSERT INTO core.comment_votes (comment_id, user_id, vote_type) VALUES ($1, $2, $3)",
                comment_id, current_user["user_id"], payload.vote_type
            )
            return {"status": "added", "vote_type": payload.vote_type}
