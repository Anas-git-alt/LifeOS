CREATE TABLE IF NOT EXISTS system_settings (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    data_start_date DATE NOT NULL DEFAULT '2026-03-02',
    default_timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Casablanca',
    autonomy_enabled BOOLEAN NOT NULL DEFAULT 1,
    approval_required_for_mutations BOOLEAN NOT NULL DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scheduled_jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(120) NOT NULL,
    agent_name VARCHAR(100),
    job_type VARCHAR(40) NOT NULL DEFAULT 'agent_nudge',
    cron_expression VARCHAR(120) NOT NULL,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Casablanca',
    target_channel VARCHAR(100),
    prompt_template TEXT,
    enabled BOOLEAN NOT NULL DEFAULT 1,
    paused BOOLEAN NOT NULL DEFAULT 0,
    approval_required BOOLEAN NOT NULL DEFAULT 1,
    source VARCHAR(40) NOT NULL DEFAULT 'manual',
    created_by VARCHAR(120),
    config_json JSON,
    last_run_at DATETIME,
    next_run_at DATETIME,
    last_status VARCHAR(30),
    last_error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_agent ON scheduled_jobs(agent_name);
CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled, paused);

CREATE TABLE IF NOT EXISTS job_run_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id INTEGER NOT NULL,
    started_at DATETIME NOT NULL,
    finished_at DATETIME NOT NULL,
    status VARCHAR(30) NOT NULL,
    message TEXT,
    error TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(job_id) REFERENCES scheduled_jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_job_run_logs_job_created ON job_run_logs(job_id, created_at DESC);
