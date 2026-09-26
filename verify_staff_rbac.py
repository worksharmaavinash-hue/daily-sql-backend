import sys
import os
import uuid
import datetime

# Add app path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))

from app.auth.jwt import (
    create_staff_token,
    create_access_token,
    _decode_token,
    JWT_SECRET,
)

def test_rbac_token_claims():
    print("Testing Staff & Customer Token Differentiation...")
    
    # 1. Staff Token (Writer)
    writer_id = str(uuid.uuid4())
    writer_token = create_staff_token(
        staff_id=writer_id,
        email="writer@dailysql.com",
        full_name="Staff Writer",
        role="writer"
    )
    writer_payload = _decode_token(writer_token)
    assert writer_payload["token_type"] == "staff"
    assert writer_payload["role"] == "writer"
    assert writer_payload["admin"] is False
    print("✅ Writer staff token created with correct claims.")

    # 2. Staff Token (Admin)
    admin_id = str(uuid.uuid4())
    admin_token = create_staff_token(
        staff_id=admin_id,
        email="admin@dailysql.com",
        full_name="Platform Admin",
        role="admin"
    )
    admin_payload = _decode_token(admin_token)
    assert admin_payload["token_type"] == "staff"
    assert admin_payload["role"] == "admin"
    assert admin_payload["admin"] is True
    print("✅ Admin staff token created with correct claims.")

    # 3. Regular Consumer Token
    consumer_id = str(uuid.uuid4())
    consumer_token = create_access_token(user_id=consumer_id, email="user@example.com")
    consumer_payload = _decode_token(consumer_token)
    assert consumer_payload.get("token_type") != "staff"
    assert consumer_payload.get("admin") is False
    print("✅ Consumer user token isolated from staff claims.")

    print("\nAll Staff RBAC token tests PASSED! 🚀")

if __name__ == "__main__":
    test_rbac_token_claims()
