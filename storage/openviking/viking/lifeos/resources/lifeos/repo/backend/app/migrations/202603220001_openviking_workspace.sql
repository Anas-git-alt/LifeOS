ALTER TABLE agents ADD COLUMN workspace_enabled BOOLEAN NOT NULL DEFAULT 0;
ALTER TABLE agents ADD COLUMN workspace_paths_json JSON;
ALTER TABLE agents ADD COLUMN workspace_delete_requires_approval BOOLEAN NOT NULL DEFAULT 1;

CREATE TABLE IF NOT EXISTS workspace_archive_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name VARCHAR(100) NOT NULL,
    source VARCHAR(40) NOT NULL DEFAULT 'agent',
    operation_type VARCHAR(40) NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'completed',
    target_path TEXT NOT NULL,
    display_path TEXT NOT NULL,
    root_path TEXT NOT NULL,
    archive_path TEXT,
    target_existed BOOLEAN NOT NULL DEFAULT 0,
    checksum_before VARCHAR(64),
    details_json JSON,
    pending_action_id INTEGER REFERENCES pending_actions(id),
    restored_from_id INTEGER REFERENCES workspace_archive_entries(id),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_workspace_archive_entries_agent_created
    ON workspace_archive_entries(agent_name, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_workspace_archive_entries_pending
    ON workspace_archive_entries(pending_action_id);
