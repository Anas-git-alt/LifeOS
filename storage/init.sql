-- LifeOS schema reference (actual upgrades are applied by backend/app/database.py migrations)

CREATE TABLE IF NOT EXISTS agents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name VARCHAR(100) UNIQUE NOT NULL,
    description TEXT DEFAULT '',
    system_prompt TEXT DEFAULT 'You are a helpful assistant.',
    provider VARCHAR(50) DEFAULT 'openrouter',
    model VARCHAR(100) DEFAULT 'openrouter/free',
    fallback_provider VARCHAR(50),
    fallback_model VARCHAR(100),
    discord_channel VARCHAR(100),
    cadence VARCHAR(50),
    enabled BOOLEAN DEFAULT 1,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    config_json JSON
);

CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name VARCHAR(100) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    summary TEXT NOT NULL,
    details TEXT,
    status VARCHAR(20) DEFAULT 'PENDING',
    risk_level VARCHAR(20) DEFAULT 'low',
    discord_message_id VARCHAR(50),
    reviewed_by VARCHAR(120),
    review_source VARCHAR(40),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at DATETIME,
    result TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name VARCHAR(100) NOT NULL,
    action VARCHAR(200) NOT NULL,
    details TEXT,
    status VARCHAR(50) NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provider_configs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider VARCHAR(50) UNIQUE NOT NULL,
    api_key_env VARCHAR(100) NOT NULL,
    base_url VARCHAR(200) NOT NULL,
    default_model VARCHAR(100) NOT NULL,
    enabled BOOLEAN DEFAULT 1
);

CREATE TABLE IF NOT EXISTS memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL,
    content TEXT NOT NULL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_profile (
    id INTEGER PRIMARY KEY,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Casablanca',
    city VARCHAR(64) NOT NULL DEFAULT 'Casablanca',
    country VARCHAR(64) NOT NULL DEFAULT 'Morocco',
    prayer_method INTEGER NOT NULL DEFAULT 2,
    work_shift_start VARCHAR(5) NOT NULL DEFAULT '14:00',
    work_shift_end VARCHAR(5) NOT NULL DEFAULT '00:00',
    quiet_hours_start VARCHAR(5) NOT NULL DEFAULT '23:00',
    quiet_hours_end VARCHAR(5) NOT NULL DEFAULT '06:00',
    nudge_mode VARCHAR(20) NOT NULL DEFAULT 'moderate',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS life_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    domain VARCHAR(20) NOT NULL,
    kind VARCHAR(20) NOT NULL DEFAULT 'task',
    title VARCHAR(300) NOT NULL,
    notes TEXT,
    priority VARCHAR(20) NOT NULL DEFAULT 'medium',
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    due_at DATETIME,
    start_date DATE,
    recurrence_rule VARCHAR(100),
    source_agent VARCHAR(100),
    risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
    follow_up_job_id INTEGER,
    priority_score INTEGER NOT NULL DEFAULT 50,
    priority_reason TEXT,
    priority_factors_json JSON,
    context_links_json JSON,
    last_prioritized_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS life_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    life_item_id INTEGER NOT NULL,
    result VARCHAR(20) NOT NULL,
    note TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(life_item_id) REFERENCES life_items(id)
);
