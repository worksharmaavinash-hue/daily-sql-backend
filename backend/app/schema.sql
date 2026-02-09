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
    sample_rows JSONB NOT NULL
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
