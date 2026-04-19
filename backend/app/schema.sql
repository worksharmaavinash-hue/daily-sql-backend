CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.problems (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    description TEXT NOT NULL,
    estimated_time_minutes INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS core.problem_datasets (
    id UUID PRIMARY KEY,
    problem_id UUID REFERENCES core.problems(id),
    table_name TEXT NOT NULL,
    schema_sql TEXT NOT NULL,
    seed_sql TEXT NOT NULL,
    sample_rows JSONB NOT NULL,
    column_types JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS core.problem_solutions (
    problem_id UUID REFERENCES core.problems(id),
    reference_query TEXT NOT NULL,
    order_sensitive BOOLEAN DEFAULT FALSE,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS core.daily_practice (
    date DATE PRIMARY KEY,
    easy_problem_id UUID REFERENCES core.problems(id),
    medium_problem_id UUID REFERENCES core.problems(id),
    advanced_problem_id UUID REFERENCES core.problems(id)
);

CREATE TABLE IF NOT EXISTS core.attempts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    problem_id UUID NOT NULL,
    attempt_date DATE NOT NULL,
    status TEXT CHECK (status IN ('correct', 'incorrect', 'error')) NOT NULL,
    execution_time_ms INT,
    created_at TIMESTAMP DEFAULT now(),

    UNIQUE (user_id, problem_id, attempt_date)
);

CREATE TABLE IF NOT EXISTS core.streaks (
    user_id UUID PRIMARY KEY,
    current_streak INT NOT NULL DEFAULT 0,
    last_active_date DATE
);

-- Main User Profile Table
CREATE TABLE IF NOT EXISTS core.users (
    user_id UUID PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT,                              -- NULL for OAuth-only users
    auth_provider TEXT NOT NULL DEFAULT 'email',       -- 'email' | 'google'
    provider_id TEXT,                                  -- Google's `sub` claim for OAuth users
    full_name TEXT,
    occupation TEXT,
    job_role TEXT,
    experience_years INTEGER,
    avatar_url TEXT,
    onboarding_completed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- NEW: Table for saving the user's best/latest successful solution
CREATE TABLE IF NOT EXISTS core.user_solutions (
    user_id UUID NOT NULL,
    problem_id UUID NOT NULL,
    submitted_query TEXT NOT NULL,
    execution_time_ms INT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, problem_id)
);

-- NEW: Per-user likes on problems (dislike repurposed as feedback trigger, not stored)
CREATE TABLE IF NOT EXISTS core.problem_votes (
    user_id    UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
    problem_id UUID NOT NULL REFERENCES core.problems(id) ON DELETE CASCADE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, problem_id)
);

-- NEW: Discussion comments on problems (2-level nesting: comment -> reply only)
CREATE TABLE IF NOT EXISTS core.comments (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id UUID NOT NULL REFERENCES core.problems(id) ON DELETE CASCADE,
    user_id    UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
    parent_id  UUID REFERENCES core.comments(id) ON DELETE CASCADE,
    body       TEXT NOT NULL CHECK (char_length(body) >= 1 AND char_length(body) <= 2000),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS comments_problem_id_idx ON core.comments(problem_id);
CREATE INDEX IF NOT EXISTS comments_parent_id_idx ON core.comments(parent_id);

-- NEW: User feedback (from FAB or dislike button)
CREATE TABLE IF NOT EXISTS core.feedback (
    id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id    UUID REFERENCES core.users(user_id) ON DELETE SET NULL,
    email      TEXT,
    rating     SMALLINT CHECK (rating IN (1, 2, 3)),
    message    TEXT,
    source     TEXT NOT NULL DEFAULT 'fab' CHECK (source IN ('fab', 'dislike')),
    problem_id UUID REFERENCES core.problems(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Whitelist for authorized emails
CREATE TABLE IF NOT EXISTS core.whitelist (
    email TEXT PRIMARY KEY,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

