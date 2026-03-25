PRAGMA foreign_keys=OFF;

ALTER TABLE scheduled_jobs RENAME TO scheduled_jobs_old;

CREATE TABLE scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(120) NOT NULL,
    description TEXT,
    agent_name VARCHAR(100),
    job_type VARCHAR(40) NOT NULL DEFAULT 'agent_nudge',
    schedule_type VARCHAR(20) NOT NULL DEFAULT 'cron',
    cron_expression VARCHAR(120),
    run_at DATETIME,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Casablanca',
    notification_mode VARCHAR(20) NOT NULL DEFAULT 'channel',
    target_channel VARCHAR(100),
    target_channel_id VARCHAR(32),
    prompt_template TEXT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    paused BOOLEAN NOT NULL DEFAULT 0,
    approval_required BOOLEAN NOT NULL DEFAULT 1,
    source VARCHAR(40) NOT NULL DEFAULT 'manual',
    created_by VARCHAR(120),
    config_json JSON,
    last_run_at DATETIME,
    next_run_at DATETIME,
    completed_at DATETIME,
    last_status VARCHAR(30),
    last_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO scheduled_jobs (
    id,
    name,
    description,
    agent_name,
    job_type,
    schedule_type,
    cron_expression,
    run_at,
    timezone,
    notification_mode,
    target_channel,
    target_channel_id,
    prompt_template,
    enabled,
    paused,
    approval_required,
    source,
    created_by,
    config_json,
    last_run_at,
    next_run_at,
    completed_at,
    last_status,
    last_error,
    created_at,
    updated_at
)
SELECT
    id,
    name,
    description,
    agent_name,
    job_type,
    'cron',
    cron_expression,
    NULL,
    timezone,
    'channel',
    target_channel,
    NULL,
    prompt_template,
    enabled,
    paused,
    approval_required,
    source,
    created_by,
    config_json,
    last_run_at,
    next_run_at,
    NULL,
    last_status,
    last_error,
    created_at,
    updated_at
FROM scheduled_jobs_old;

DROP TABLE scheduled_jobs_old;

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_agent ON scheduled_jobs(agent_name);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled, paused);

PRAGMA foreign_keys=ON;
