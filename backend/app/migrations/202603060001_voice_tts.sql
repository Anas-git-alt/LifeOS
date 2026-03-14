CREATE TABLE IF NOT EXISTS tts_model_registry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    engine VARCHAR(50) NOT NULL,
    model_id VARCHAR(100) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    supports_en BOOLEAN NOT NULL DEFAULT 1,
    supports_fr BOOLEAN NOT NULL DEFAULT 0,
    supports_ar BOOLEAN NOT NULL DEFAULT 0,
    supports_voice_id BOOLEAN NOT NULL DEFAULT 0,
    supports_voice_instructions BOOLEAN NOT NULL DEFAULT 0,
    supports_reference_audio BOOLEAN NOT NULL DEFAULT 0,
    supports_emotion_control BOOLEAN NOT NULL DEFAULT 0,
    supports_streaming BOOLEAN NOT NULL DEFAULT 0,
    quality_tier VARCHAR(20) NOT NULL DEFAULT 'balanced',
    latency_tier VARCHAR(20) NOT NULL DEFAULT 'fast',
    vram_estimate_mb INTEGER,
    license_label VARCHAR(120),
    enabled BOOLEAN NOT NULL DEFAULT 1,
    config_json JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tts_model_registry_engine_model
    ON tts_model_registry(engine, model_id);

CREATE TABLE IF NOT EXISTS voice_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id VARCHAR(32) NOT NULL,
    channel_id VARCHAR(32) NOT NULL,
    session_key VARCHAR(100) NOT NULL UNIQUE,
    agent_name VARCHAR(100) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    generation INTEGER NOT NULL DEFAULT 1,
    queue_policy VARCHAR(20) NOT NULL DEFAULT 'replace',
    active_request_id VARCHAR(120),
    active_model_id VARCHAR(120),
    details_json JSON,
    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    ended_at DATETIME
);

CREATE INDEX IF NOT EXISTS idx_voice_sessions_guild_status
    ON voice_sessions(guild_id, status);
CREATE INDEX IF NOT EXISTS idx_voice_sessions_agent_status
    ON voice_sessions(agent_name, status);
