-- Quran page-based reading log
CREATE TABLE IF NOT EXISTS quran_readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_date DATE NOT NULL,
    start_page INTEGER NOT NULL CHECK(start_page >= 1 AND start_page <= 604),
    end_page INTEGER NOT NULL CHECK(end_page >= 1 AND end_page <= 604),
    note TEXT,
    source VARCHAR(40) NOT NULL DEFAULT 'api',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_quran_readings_date ON quran_readings(local_date);

-- Single-row bookmark tracking current reading position
CREATE TABLE IF NOT EXISTS quran_bookmark (
    id INTEGER PRIMARY KEY CHECK(id = 1),
    current_page INTEGER NOT NULL DEFAULT 1 CHECK(current_page >= 1 AND current_page <= 604),
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

INSERT OR IGNORE INTO quran_bookmark (id, current_page) VALUES (1, 1);
