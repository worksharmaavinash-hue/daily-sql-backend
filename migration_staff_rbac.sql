-- ============================================================
-- Migration: Staff Users & Role-Based Access Control (RBAC)
-- ============================================================

CREATE TABLE IF NOT EXISTS core.staff_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('writer', 'admin', 'superadmin')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    last_login_at TIMESTAMP WITH TIME ZONE,
    created_by UUID REFERENCES core.staff_users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS staff_users_email_idx ON core.staff_users (LOWER(email));
CREATE INDEX IF NOT EXISTS staff_users_role_idx ON core.staff_users (role);
CREATE INDEX IF NOT EXISTS staff_users_active_idx ON core.staff_users (is_active);
