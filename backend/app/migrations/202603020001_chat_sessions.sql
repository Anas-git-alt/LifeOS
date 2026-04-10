CREATE TABLE IF NOT EXISTS chat_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name VARCHAR(100) NOT NULL,
    title VARCHAR(160) NOT NULL DEFAULT 'New chat',
    prompt_seed_count INTEGER NOT NULL DEFAULT 0,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    last_message_at DATETIME,
    deleted_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_agent_last_message
    ON chat_sessions(agent_name, last_message_at DESC);
