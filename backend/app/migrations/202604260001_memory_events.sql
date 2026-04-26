CREATE TABLE IF NOT EXISTS memory_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    source_agent VARCHAR(100),
    source_session_id INTEGER,
    event_type VARCHAR(40) NOT NULL DEFAULT 'user_fact',
    domain VARCHAR(20),
    kind VARCHAR(30),
    title VARCHAR(300) NOT NULL,
    summary TEXT,
    raw_text TEXT NOT NULL,
    tags_json JSON,
    entities_json JSON,
    linked_life_item_id INTEGER,
    linked_intake_entry_id INTEGER,
    linked_job_id INTEGER,
    source_uri TEXT,
    checksum VARCHAR(64),
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(source_session_id) REFERENCES chat_sessions(id),
    FOREIGN KEY(linked_life_item_id) REFERENCES life_items(id),
    FOREIGN KEY(linked_intake_entry_id) REFERENCES intake_entries(id)
);

CREATE INDEX IF NOT EXISTS idx_memory_events_created
    ON memory_events(created_at DESC, id DESC);

CREATE INDEX IF NOT EXISTS idx_memory_events_links
    ON memory_events(linked_life_item_id, linked_intake_entry_id, source_session_id);

CREATE INDEX IF NOT EXISTS idx_memory_events_domain_kind
    ON memory_events(domain, kind, event_type);
