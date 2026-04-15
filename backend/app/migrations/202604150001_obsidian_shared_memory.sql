ALTER TABLE agents ADD COLUMN memory_scopes_json JSON;
ALTER TABLE agents ADD COLUMN shared_domains_json JSON;
ALTER TABLE agents ADD COLUMN vault_write_mode VARCHAR(40) NOT NULL DEFAULT 'structured_direct_write';
ALTER TABLE agents ADD COLUMN promotion_policy VARCHAR(40) NOT NULL DEFAULT 'manual';

CREATE TABLE IF NOT EXISTS shared_memory_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_agent VARCHAR(100) NOT NULL,
    source_session_id INTEGER REFERENCES chat_sessions(id),
    scope VARCHAR(40) NOT NULL,
    domain VARCHAR(40),
    title VARCHAR(200) NOT NULL,
    target_path TEXT NOT NULL,
    proposal_path TEXT NOT NULL,
    expected_checksum VARCHAR(64),
    current_checksum VARCHAR(64),
    source_uri TEXT,
    conflict_reason VARCHAR(60) NOT NULL DEFAULT 'checksum_mismatch',
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    proposed_content TEXT NOT NULL,
    note_metadata_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    applied_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_shared_memory_proposals_status
    ON shared_memory_proposals(status, created_at DESC);
