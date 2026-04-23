CREATE TABLE IF NOT EXISTS context_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type VARCHAR(40) NOT NULL,
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    source_agent VARCHAR(100),
    source_session_id INTEGER REFERENCES chat_sessions(id),
    job_id INTEGER REFERENCES scheduled_jobs(id),
    job_run_id INTEGER REFERENCES job_run_logs(id),
    life_item_id INTEGER REFERENCES life_items(id),
    discord_channel_id VARCHAR(32),
    discord_message_id VARCHAR(50),
    discord_reply_message_id VARCHAR(50),
    discord_user_id VARCHAR(32),
    title VARCHAR(300),
    summary TEXT,
    raw_text TEXT NOT NULL,
    domain VARCHAR(20) NOT NULL DEFAULT 'planning',
    status VARCHAR(20) NOT NULL DEFAULT 'new',
    metadata_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    curated_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_context_events_type_created
    ON context_events(event_type, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_context_events_job_run
    ON context_events(job_run_id, created_at DESC);

