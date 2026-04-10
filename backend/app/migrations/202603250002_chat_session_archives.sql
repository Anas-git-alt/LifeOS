CREATE TABLE IF NOT EXISTS chat_session_archives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL REFERENCES chat_sessions(id),
    agent_name VARCHAR(100) NOT NULL,
    title VARCHAR(160) NOT NULL DEFAULT 'New chat',
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    reason VARCHAR(40) NOT NULL DEFAULT 'manual_delete',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    message_count INTEGER NOT NULL DEFAULT 0,
    snapshot_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    restored_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_chat_session_archives_agent_created
    ON chat_session_archives(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_session_archives_session_status
    ON chat_session_archives(session_id, status, expires_at DESC);

CREATE INDEX IF NOT EXISTS idx_chat_sessions_agent_deleted
    ON chat_sessions(agent_name, deleted_at);
