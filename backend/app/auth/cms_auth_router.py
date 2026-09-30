from datetime import datetime, timezone
import uuid
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Depends, Security
from pydantic import BaseModel, EmailStr
import bcrypt

from app.db import get_pool
from app.auth.jwt import (
    create_staff_token,
    require_staff_role,
    require_writer_or_admin,
    require_admin_only,
)

router = APIRouter(prefix="/cms/auth", tags=["cms-auth"])


# ── Password Hashing Helpers ──────────────────────────────────────────────────
def _hash_password(plain: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(plain.encode("utf-8"), salt).decode("utf-8")


def _verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


# ── Request / Response Models ─────────────────────────────────────────────────
class StaffLoginRequest(BaseModel):
    email: EmailStr
    password: str


class StaffLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    staff: dict


class StaffProfile(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: Optional[str] = None
    last_login_at: Optional[str] = None


class StaffCreateRequest(BaseModel):
    email: EmailStr
    password: str
    full_name: str
    role: str = "writer"  # 'writer' | 'admin'


class StaffUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None
    password: Optional[str] = None


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


# ── Staff Auth Endpoints ──────────────────────────────────────────────────────

@router.post("/login", response_model=StaffLoginResponse)
async def staff_login(data: StaffLoginRequest):
    """Authenticate a staff user (Writer/Admin/Superadmin) and issue a Staff JWT."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        staff = await conn.fetchrow(
            """
            SELECT id, email, hashed_password, full_name, role, is_active
            FROM core.staff_users
            WHERE LOWER(email) = LOWER($1)
            """,
            data.email,
        )

        if not staff:
            raise HTTPException(status_code=401, detail="Invalid staff credentials")

        if not staff["is_active"]:
            raise HTTPException(
                status_code=403,
                detail="Your staff account has been deactivated. Please contact an admin."
            )

        if not _verify_password(data.password, staff["hashed_password"]):
            raise HTTPException(status_code=401, detail="Invalid staff credentials")

        # Update last login timestamp
        now = datetime.now(timezone.utc)
        await conn.execute(
            "UPDATE core.staff_users SET last_login_at = $1 WHERE id = $2",
            now,
            staff["id"],
        )

        token = create_staff_token(
            staff_id=str(staff["id"]),
            email=staff["email"],
            full_name=staff["full_name"],
            role=staff["role"],
        )

        return {
            "access_token": token,
            "token_type": "bearer",
            "staff": {
                "id": str(staff["id"]),
                "email": staff["email"],
                "full_name": staff["full_name"],
                "role": staff["role"],
            },
        }


@router.get("/me")
async def get_current_staff(staff: dict = Depends(require_writer_or_admin)):
    """Return the profile and permissions of the currently logged-in staff member."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            """
            SELECT id, email, full_name, role, is_active, created_at, last_login_at
            FROM core.staff_users
            WHERE id = $1
            """,
            uuid.UUID(staff["staff_id"]),
        )
        if not record:
            raise HTTPException(status_code=404, detail="Staff record not found")

        return {
            "id": str(record["id"]),
            "email": record["email"],
            "full_name": record["full_name"],
            "role": record["role"],
            "is_active": record["is_active"],
            "created_at": record["created_at"].isoformat() if record["created_at"] else None,
            "last_login_at": record["last_login_at"].isoformat() if record["last_login_at"] else None,
        }


@router.post("/change-password")
async def change_staff_password(
    data: ChangePasswordRequest,
    staff: dict = Depends(require_writer_or_admin),
):
    """Allow current staff member to update their password."""
    if len(data.new_password) < 8:
        raise HTTPException(status_code=400, detail="New password must be at least 8 characters.")

    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "SELECT hashed_password FROM core.staff_users WHERE id = $1",
            uuid.UUID(staff["staff_id"]),
        )
        if not record or not _verify_password(data.current_password, record["hashed_password"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")

        new_hash = _hash_password(data.new_password)
        await conn.execute(
            "UPDATE core.staff_users SET hashed_password = $1, updated_at = NOW() WHERE id = $2",
            new_hash,
            uuid.UUID(staff["staff_id"]),
        )

    return {"message": "Password changed successfully."}


# ── Staff Management Endpoints (Admin Only) ───────────────────────────────────

@router.get("/staff")
async def list_staff_members(admin: dict = Depends(require_admin_only)):
    """List all staff accounts (Writers, Admins)."""
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT id, email, full_name, role, is_active, created_at, last_login_at
            FROM core.staff_users
            ORDER BY created_at DESC
            """
        )
        return [
            {
                "id": str(r["id"]),
                "email": r["email"],
                "full_name": r["full_name"],
                "role": r["role"],
                "is_active": r["is_active"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                "last_login_at": r["last_login_at"].isoformat() if r["last_login_at"] else None,
            }
            for r in rows
        ]


@router.post("/staff")
async def create_staff_member(
    data: StaffCreateRequest,
    admin: dict = Depends(require_admin_only),
):
    """Create a new staff member account (Admin only)."""
    if data.role not in ("writer", "admin", "superadmin"):
        raise HTTPException(status_code=400, detail="Invalid role. Must be 'writer' or 'admin'.")

    if len(data.password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters.")

    pool = await get_pool()
    async with pool.acquire() as conn:
        existing = await conn.fetchrow(
            "SELECT id FROM core.staff_users WHERE LOWER(email) = LOWER($1)",
            data.email,
        )
        if existing:
            raise HTTPException(status_code=409, detail="A staff account with this email already exists.")

        hashed = _hash_password(data.password)
        new_id = uuid.uuid4()
        await conn.execute(
            """
            INSERT INTO core.staff_users (id, email, hashed_password, full_name, role, is_active, created_by)
            VALUES ($1, $2, $3, $4, $5, true, $6)
            """,
            new_id,
            data.email.lower().strip(),
            hashed,
            data.full_name.strip(),
            data.role,
            uuid.UUID(admin["staff_id"]) if admin.get("staff_id") and admin["staff_id"] != "admin" else None,
        )

        return {
            "id": str(new_id),
            "email": data.email.lower().strip(),
            "full_name": data.full_name.strip(),
            "role": data.role,
            "message": f"Staff user ({data.role}) created successfully."
        }


@router.patch("/staff/{staff_id}")
async def update_staff_member(
    staff_id: str,
    data: StaffUpdateRequest,
    admin: dict = Depends(require_admin_only),
):
    """Update role, name, active status, or reset password of a staff member (Admin only)."""
    target_uuid = uuid.UUID(staff_id)
    pool = await get_pool()
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT id, email, role FROM core.staff_users WHERE id = $1", target_uuid)
        if not record:
            raise HTTPException(status_code=404, detail="Staff account not found.")

        updates = []
        params = []
        idx = 1

        if data.full_name is not None:
            updates.append(f"full_name = ${idx}")
            params.append(data.full_name.strip())
            idx += 1

        if data.role is not None:
            if data.role not in ("writer", "admin", "superadmin"):
                raise HTTPException(status_code=400, detail="Invalid role.")
            updates.append(f"role = ${idx}")
            params.append(data.role)
            idx += 1

        if data.is_active is not None:
            updates.append(f"is_active = ${idx}")
            params.append(data.is_active)
            idx += 1

        if data.password is not None and len(data.password) >= 8:
            updates.append(f"hashed_password = ${idx}")
            params.append(_hash_password(data.password))
            idx += 1

        if not updates:
            return {"message": "No updates specified."}

        updates.append("updated_at = NOW()")
        query = f"UPDATE core.staff_users SET {', '.join(updates)} WHERE id = ${idx}"
        params.append(target_uuid)

        await conn.execute(query, *params)

    return {"message": "Staff user updated successfully."}


@router.delete("/staff/{staff_id}")
async def delete_staff_member(
    staff_id: str,
    admin: dict = Depends(require_admin_only),
):
    """Delete a staff user account (Admin only)."""
    target_uuid = uuid.UUID(staff_id)
    # Prevent self-deletion
    if admin.get("staff_id") == staff_id:
        raise HTTPException(status_code=400, detail="You cannot delete your own staff account.")

    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("DELETE FROM core.staff_users WHERE id = $1", target_uuid)

    return {"message": "Staff member deleted successfully."}
