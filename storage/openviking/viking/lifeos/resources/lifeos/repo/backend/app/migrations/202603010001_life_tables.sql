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

INSERT OR IGNORE INTO user_profile (
    id, timezone, city, country, prayer_method, work_shift_start, work_shift_end,
    quiet_hours_start, quiet_hours_end, nudge_mode
) VALUES (
    1, 'Africa/Casablanca', 'Casablanca', 'Morocco', 2, '14:00', '00:00', '23:00', '06:00', 'moderate'
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
    recurrence_rule VARCHAR(100),
    source_agent VARCHAR(100),
    risk_level VARCHAR(20) NOT NULL DEFAULT 'low',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_life_items_domain_status ON life_items(domain, status);
CREATE INDEX IF NOT EXISTS idx_life_items_due_at ON life_items(due_at);

CREATE TABLE IF NOT EXISTS life_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    life_item_id INTEGER NOT NULL,
    result VARCHAR(20) NOT NULL,
    note TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(life_item_id) REFERENCES life_items(id)
);

CREATE INDEX IF NOT EXISTS idx_life_checkins_item ON life_checkins(life_item_id);
