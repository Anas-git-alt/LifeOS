CREATE TABLE IF NOT EXISTS daily_scorecards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_date DATE NOT NULL UNIQUE,
    timezone VARCHAR(64) NOT NULL DEFAULT 'Africa/Casablanca',
    sleep_hours REAL,
    sleep_summary_json JSON,
    meals_count INTEGER NOT NULL DEFAULT 0,
    training_status VARCHAR(20),
    hydration_count INTEGER NOT NULL DEFAULT 0,
    shutdown_done BOOLEAN NOT NULL DEFAULT 0,
    protein_hit BOOLEAN NOT NULL DEFAULT 0,
    family_action_done BOOLEAN NOT NULL DEFAULT 0,
    top_priority_completed_count INTEGER NOT NULL DEFAULT 0,
    rescue_status VARCHAR(20) NOT NULL DEFAULT 'watch',
    notes_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_daily_scorecards_local_date ON daily_scorecards(local_date);
