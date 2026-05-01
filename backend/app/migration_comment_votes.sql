-- Add table for comment likes/dislikes
CREATE TABLE IF NOT EXISTS core.comment_votes (
    user_id    UUID NOT NULL REFERENCES core.users(user_id) ON DELETE CASCADE,
    comment_id UUID NOT NULL REFERENCES core.comments(id) ON DELETE CASCADE,
    vote_type  SMALLINT NOT NULL CHECK (vote_type IN (1, -1)), -- 1 for like, -1 for dislike
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    PRIMARY KEY (user_id, comment_id)
);
