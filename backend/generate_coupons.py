#!/usr/bin/env python3
"""
Daily SQL — Lifetime Coupon Generator for Early Users
"""
import os
import sys
import argparse
import asyncio
import csv
import secrets
import string
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional

try:
    import asyncpg
except ImportError:
    print("Installing asyncpg...")
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "asyncpg"])
    import asyncpg


def load_env_file(filepath: str):
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))

load_env_file(".env.local")
load_env_file(".env")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgres://postgres:postgres@localhost:5432/dailysql"
)


def generate_coupon_code() -> str:
    clean_alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
    suffix = "".join(secrets.choice(clean_alphabet) for _ in range(8))
    return f"DSQL-LT-{suffix}"


async def get_db_connection():
    try:
        return await asyncpg.connect(DATABASE_URL)
    except Exception as e:
        if "@postgres:" in DATABASE_URL:
            local_url = DATABASE_URL.replace("@postgres:", "@localhost:")
            return await asyncpg.connect(local_url)
        raise e


async def run_generator(
    emails: Optional[List[str]] = None,
    email_file: Optional[str] = None,
    days_valid: int = 32,
    output_file: str = "early_users_coupons.csv",
):
    print("=" * 65)
    print("  Daily SQL — Early User Lifetime Coupon Generator")
    print("=" * 65)

    conn = await get_db_connection()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=days_valid)

    try:
        target_list: List[Dict[str, Any]] = []

        if email_file:
            if not os.path.exists(email_file):
                print(f"[Error] File not found: {email_file}")
                return
            with open(email_file, "r", encoding="utf-8") as f:
                emails = [line.strip().lower() for line in f if line.strip() and "@" in line]

        if emails and len(emails) > 0:
            clean_emails = [e.strip().lower() for e in emails if e.strip()]
            print(f"\n[+] Fetching user details for {len(clean_emails)} specified email(s)...")
            rows = await conn.fetch(
                """
                SELECT user_id, email, username, full_name, plan
                FROM core.users
                WHERE LOWER(email) = ANY($1)
                """,
                clean_emails,
            )
            found_map = {r["email"].lower(): dict(r) for r in rows}
            for em in clean_emails:
                if em in found_map:
                    target_list.append(found_map[em])
                else:
                    target_list.append({
                        "user_id": None,
                        "email": em,
                        "username": "unregistered",
                        "full_name": "",
                        "plan": "free",
                    })
        else:
            print("\n[+] Querying all existing users without Lifetime plan...")
            rows = await conn.fetch(
                """
                SELECT user_id, email, username, full_name, plan, created_at
                FROM core.users
                WHERE plan != 'lifetime'
                ORDER BY created_at ASC
                """
            )
            target_list = [dict(r) for r in rows]

        if not target_list:
            print("[!] No eligible users found.")
            return

        print(f"[+] Generating coupons for {len(target_list)} user(s)...")
        print(f"[+] Validity: {days_valid} days (Expires on {expires_at.strftime('%Y-%m-%d %H:%M:%S UTC')})\n")

        results = []
        for u in target_list:
            email = u["email"].lower().strip()
            user_id = u.get("user_id")

            existing = await conn.fetchrow(
                """
                SELECT code, email, expires_at, is_used
                FROM core.coupons
                WHERE LOWER(email) = $1 AND is_used = FALSE
                """,
                email,
            )

            if existing:
                code = existing["code"]
                exp = existing["expires_at"] or expires_at
                status_msg = "Existing (Unused)"
            else:
                code = generate_coupon_code()
                exp = expires_at
                await conn.execute(
                    """
                    INSERT INTO core.coupons (code, email, user_id, plan_granted, is_used, expires_at)
                    VALUES ($1, $2, $3, 'lifetime', FALSE, $4)
                    ON CONFLICT (code) DO NOTHING
                    """,
                    code,
                    email,
                    user_id,
                    exp,
                )
                status_msg = "Created"

            results.append({
                "email": email,
                "username": u.get("username") or "",
                "full_name": u.get("full_name") or "",
                "coupon_code": code,
                "plan_granted": "lifetime",
                "expires_at": exp.strftime("%Y-%m-%d %H:%M:%S UTC") if exp else "Never",
                "status": status_msg,
            })

        with open(output_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=["email", "username", "full_name", "coupon_code", "plan_granted", "expires_at", "status"],
            )
            writer.writeheader()
            writer.writerows(results)

        print(f"✅ Successfully processed {len(results)} coupon(s)!")
        print(f"📁 Output file saved: {os.path.abspath(output_file)}\n")

        print("-" * 85)
        print(f"{'Email':<30} | {'Username':<15} | {'Coupon Code':<20} | {'Status'}")
        print("-" * 85)
        for r in results[:15]:
            print(f"{r['email']:<30} | {r['username'] or '-':<15} | {r['coupon_code']:<20} | {r['status']}")
        if len(results) > 15:
            print(f"... and {len(results) - 15} more rows in {output_file}")
        print("-" * 85)

    finally:
        await conn.close()


def main():
    parser = argparse.ArgumentParser(description="Generate unique lifetime coupons for early users.")
    parser.add_argument("--days", type=int, default=32, help="Coupon validity in days (default: 32)")
    parser.add_argument("--output", type=str, default="early_users_coupons.csv", help="Output CSV filename")
    parser.add_argument("--emails", nargs="+", help="Specific email addresses to generate coupons for")
    parser.add_argument("--file", type=str, help="Text file containing one email per line")

    args = parser.parse_args()
    asyncio.run(
        run_generator(
            emails=args.emails,
            email_file=args.file,
            days_valid=args.days,
            output_file=args.output,
        )
    )


if __name__ == "__main__":
    main()
