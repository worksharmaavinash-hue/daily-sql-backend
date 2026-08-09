CREATE SCHEMA IF NOT EXISTS core;

CREATE TABLE IF NOT EXISTS core.problems (
    id UUID PRIMARY KEY,
    title TEXT NOT NULL,
    difficulty TEXT NOT NULL,
    description TEXT NOT NULL,
    estimated_time_minutes INTEGER NOT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    challenge_type TEXT NOT NULL DEFAULT 'sql' CHECK (challenge_type IN ('sql', 'python', 'pyspark', 'python_dsa')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS core.problem_datasets (
    id UUID PRIMARY KEY,
    problem_id UUID REFERENCES core.problems(id),
    table_name TEXT NOT NULL,
    schema_sql TEXT NOT NULL,
    seed_sql TEXT NOT NULL,
    sample_rows JSONB NOT NULL,
    column_types JSONB NOT NULL DEFAULT '{}'::jsonb,
    seed_data_json JSONB
);

CREATE TABLE IF NOT EXISTS core.problem_solutions (
    problem_id UUID REFERENCES core.problems(id),
    reference_query TEXT,
    mysql_reference_query TEXT,
    reference_code TEXT,
    reference_output JSONB,
    order_sensitive BOOLEAN DEFAULT FALSE,
    notes TEXT,
    function_name TEXT,  -- DSA only: e.g. 'twoSum', 'maxSubArray'
    starter_code TEXT   -- DSA only: starter function template
);

CREATE TABLE IF NOT EXISTS core.daily_practice (
    date DATE PRIMARY KEY,
    easy_problem_id UUID REFERENCES core.problems(id),
    medium_problem_id UUID REFERENCES core.problems(id),
    advanced_problem_id UUID REFERENCES core.problems(id),
    python_easy_problem_id UUID REFERENCES core.problems(id),
    python_medium_problem_id UUID REFERENCES core.problems(id),
    python_advanced_problem_id UUID REFERENCES core.problems(id),
    pyspark_easy_problem_id UUID REFERENCES core.problems(id),
    pyspark_medium_problem_id UUID REFERENCES core.problems(id),
    pyspark_advanced_problem_id UUID REFERENCES core.problems(id),
    dsa_easy_problem_id UUID REFERENCES core.problems(id),
    dsa_medium_problem_id UUID REFERENCES core.problems(id),
    dsa_advanced_problem_id UUID REFERENCES core.problems(id)
);

-- Test cases for DSA (python_dsa) problems
CREATE TABLE IF NOT EXISTS core.problem_test_cases (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    problem_id  UUID NOT NULL REFERENCES core.problems(id) ON DELETE CASCADE,
    input_data  JSONB NOT NULL,  -- {"args": [[2,7,11,15], 9]} — positional args matching function signature
    expected    JSONB NOT NULL,  -- any JSON-serializable value: int, list, str, bool, etc.
    is_hidden   BOOLEAN DEFAULT TRUE,  -- false = sample (shown to user), true = hidden (grading only)
    label       TEXT,            -- e.g. "Example 1", "Edge case: empty array"
    order_index INT DEFAULT 0,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS problem_test_cases_problem_id_idx ON core.problem_test_cases(problem_id);

CREATE TABLE IF NOT EXISTS core.attempts (
    id UUID PRIMARY KEY,
    user_id UUID NOT NULL,
    problem_id UUID NOT NULL,
    attempt_date DATE NOT NULL,
    status TEXT CHECK (status IN ('correct', 'incorrect', 'error')) NOT NULL,
    execution_time_ms INT,
    challenge_type TEXT DEFAULT 'sql',
    created_at TIMESTAMP DEFAULT now()
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
    whatsapp_number TEXT,
    source TEXT,
    avatar_url TEXT,
    onboarding_completed BOOLEAN DEFAULT FALSE,
    username TEXT UNIQUE,
    is_public_profile BOOLEAN DEFAULT TRUE,
    bio TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    profile_updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
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

-- Waitlist for new users requesting access
CREATE TABLE IF NOT EXISTS core.waitlist (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    whatsapp_number TEXT NOT NULL,
    occupation TEXT,
    job_role TEXT,
    experience_years INTEGER,
    source TEXT,
    status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected')),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);


-- Likes/Dislikes for comments
CREATE TABLE IF NOT EXISTS core.comment_votes (
    user_id    UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
    comment_id UUID NOT NULL REFERENCES core.comments(id) ON DELETE CASCADE,
    vote_type  SMALLINT NOT NULL CHECK (vote_type IN (1, -1)), -- 1 for like, -1 for dislike
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, comment_id)
);

-- Tracking for WhatsApp group membership
CREATE TABLE IF NOT EXISTS core.wa_group_members (
    user_id   UUID PRIMARY KEY REFERENCES core.users(user_id) ON DELETE CASCADE,
    added_at  TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

