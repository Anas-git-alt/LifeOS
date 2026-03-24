CREATE TABLE IF NOT EXISTS prayer_windows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_date DATE NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    city VARCHAR(64) NOT NULL,
    country VARCHAR(64) NOT NULL,
    method INTEGER NOT NULL DEFAULT 2,
    prayer_name VARCHAR(20) NOT NULL,
    starts_at_utc DATETIME NOT NULL,
    ends_at_utc DATETIME NOT NULL,
    hijri_month INTEGER NOT NULL DEFAULT 1,
    is_ramadan BOOLEAN NOT NULL DEFAULT 0,
    source_payload_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prayer_windows_unique
ON prayer_windows(local_date, prayer_name, timezone, city, country, method);

CREATE INDEX IF NOT EXISTS idx_prayer_windows_date
ON prayer_windows(local_date);

CREATE INDEX IF NOT EXISTS idx_prayer_windows_ends
ON prayer_windows(ends_at_utc);

CREATE TABLE IF NOT EXISTS prayer_checkins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prayer_window_id INTEGER NOT NULL,
    status_raw VARCHAR(20) NOT NULL,
    status_scored VARCHAR(20) NOT NULL,
    reported_at_utc DATETIME NOT NULL,
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    discord_user_id VARCHAR(32),
    note TEXT,
    is_retroactive BOOLEAN NOT NULL DEFAULT 0,
    retro_reason VARCHAR(80),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(prayer_window_id) REFERENCES prayer_windows(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prayer_checkins_window
ON prayer_checkins(prayer_window_id);

CREATE INDEX IF NOT EXISTS idx_prayer_checkins_reported
ON prayer_checkins(reported_at_utc);

CREATE TABLE IF NOT EXISTS prayer_reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prayer_window_id INTEGER NOT NULL,
    channel_name VARCHAR(100) NOT NULL,
    discord_message_id VARCHAR(50),
    sent_at_utc DATETIME NOT NULL,
    deadline_nudge_sent_at_utc DATETIME,
    FOREIGN KEY(prayer_window_id) REFERENCES prayer_windows(id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prayer_reminders_window
ON prayer_reminders(prayer_window_id);

CREATE TABLE IF NOT EXISTS deen_habits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_date DATE NOT NULL,
    habit_type VARCHAR(30) NOT NULL,
    value_json JSON,
    done BOOLEAN NOT NULL DEFAULT 0,
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    note TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_deen_habits_type_date
ON deen_habits(habit_type, local_date);
