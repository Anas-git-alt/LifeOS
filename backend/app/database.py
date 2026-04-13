"""LifeOS Database - async SQLAlchemy with SQLite migrations."""

from pathlib import Path
import sqlite3

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Ensure database URL uses async driver.
db_url = settings.resolved_database_url
if db_url.startswith("sqlite:///") and "+aiosqlite" not in db_url:
    db_url = db_url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)

# Ensure storage directory exists for sqlite.
_db_path = db_url.split("sqlite+aiosqlite:///")[-1] if "sqlite" in db_url else ""
if _db_path:
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_async_engine(
    db_url,
    echo=False,
    connect_args={"check_same_thread": False},  # SQLite-specific
)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def _sqlite_path_from_db_url(url: str) -> str:
    if url.startswith("sqlite+aiosqlite:///"):
        return url.replace("sqlite+aiosqlite:///", "", 1)
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    return ""


def _table_columns(cur: sqlite3.Cursor, table_name: str) -> dict[str, tuple]:
    return {row[1]: row for row in cur.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _scheduled_jobs_requires_upgrade(columns: dict[str, tuple]) -> bool:
    required_columns = {
        "description",
        "schedule_type",
        "run_at",
        "notification_mode",
        "target_channel_id",
        "completed_at",
    }
    if any(column not in columns for column in required_columns):
        return True
    cron_expression = columns.get("cron_expression")
    return bool(cron_expression and cron_expression[3])


def _scheduled_jobs_select_expr(columns: dict[str, tuple], column: str, default_sql: str) -> str:
    return column if column in columns else default_sql


def _upgrade_scheduled_jobs_table(cur: sqlite3.Cursor, columns: dict[str, tuple]) -> None:
    cur.execute("DROP TABLE IF EXISTS scheduled_jobs_legacy")
    cur.execute("ALTER TABLE scheduled_jobs RENAME TO scheduled_jobs_legacy")
    cur.executescript(
        """
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
        """
    )
    schedule_type_expr = (
        "schedule_type"
        if "schedule_type" in columns
        else ("CASE WHEN run_at IS NOT NULL THEN 'once' ELSE 'cron' END" if "run_at" in columns else "'cron'")
    )
    cur.execute(
        f"""
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
            {_scheduled_jobs_select_expr(columns, "description", "NULL")},
            {_scheduled_jobs_select_expr(columns, "agent_name", "NULL")},
            {_scheduled_jobs_select_expr(columns, "job_type", "'agent_nudge'")},
            {schedule_type_expr},
            {_scheduled_jobs_select_expr(columns, "cron_expression", "NULL")},
            {_scheduled_jobs_select_expr(columns, "run_at", "NULL")},
            {_scheduled_jobs_select_expr(columns, "timezone", "'Africa/Casablanca'")},
            {_scheduled_jobs_select_expr(columns, "notification_mode", "'channel'")},
            {_scheduled_jobs_select_expr(columns, "target_channel", "NULL")},
            {_scheduled_jobs_select_expr(columns, "target_channel_id", "NULL")},
            {_scheduled_jobs_select_expr(columns, "prompt_template", "NULL")},
            {_scheduled_jobs_select_expr(columns, "enabled", "1")},
            {_scheduled_jobs_select_expr(columns, "paused", "0")},
            {_scheduled_jobs_select_expr(columns, "approval_required", "1")},
            {_scheduled_jobs_select_expr(columns, "source", "'manual'")},
            {_scheduled_jobs_select_expr(columns, "created_by", "NULL")},
            {_scheduled_jobs_select_expr(columns, "config_json", "NULL")},
            {_scheduled_jobs_select_expr(columns, "last_run_at", "NULL")},
            {_scheduled_jobs_select_expr(columns, "next_run_at", "NULL")},
            {_scheduled_jobs_select_expr(columns, "completed_at", "NULL")},
            {_scheduled_jobs_select_expr(columns, "last_status", "NULL")},
            {_scheduled_jobs_select_expr(columns, "last_error", "NULL")},
            {_scheduled_jobs_select_expr(columns, "created_at", "CURRENT_TIMESTAMP")},
            {_scheduled_jobs_select_expr(columns, "updated_at", "CURRENT_TIMESTAMP")}
        FROM scheduled_jobs_legacy
        """
    )
    cur.execute("DROP TABLE scheduled_jobs_legacy")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_agent ON scheduled_jobs(agent_name)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_scheduled_jobs_enabled ON scheduled_jobs(enabled, paused)")


def run_migrations() -> None:
    """Apply SQL migrations in backend/app/migrations."""
    sqlite_path = _sqlite_path_from_db_url(db_url)
    if not sqlite_path:
        return

    migrations_dir = Path(__file__).resolve().parent / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(sqlite_path)
    try:
        cur = conn.cursor()
        cur.execute("BEGIN")
        # Lightweight idempotent column upgrades for existing SQLite tables.
        existing_tables = {
            row[0] for row in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {row[0] for row in cur.execute("SELECT version FROM schema_migrations").fetchall()}
        if "pending_actions" in existing_tables:
            pending_cols = {
                row[1] for row in cur.execute("PRAGMA table_info(pending_actions)").fetchall()
            }
            if "risk_level" not in pending_cols:
                cur.execute("ALTER TABLE pending_actions ADD COLUMN risk_level VARCHAR(20) DEFAULT 'low'")
            if "reviewed_by" not in pending_cols:
                cur.execute("ALTER TABLE pending_actions ADD COLUMN reviewed_by VARCHAR(120)")
            if "review_source" not in pending_cols:
                cur.execute("ALTER TABLE pending_actions ADD COLUMN review_source VARCHAR(40)")
        if "memory" in existing_tables:
            memory_cols = {row[1] for row in cur.execute("PRAGMA table_info(memory)").fetchall()}
            if "session_id" not in memory_cols:
                cur.execute("ALTER TABLE memory ADD COLUMN session_id INTEGER")
        if "scheduled_jobs" in existing_tables:
            job_cols = _table_columns(cur, "scheduled_jobs")
            if _scheduled_jobs_requires_upgrade(job_cols):
                _upgrade_scheduled_jobs_table(cur, job_cols)
            if "202603250001_job_schedule_modes" not in applied:
                cur.execute("INSERT INTO schema_migrations(version) VALUES (?)", ("202603250001_job_schedule_modes",))
                applied.add("202603250001_job_schedule_modes")
        if "life_items" in existing_tables:
            life_cols = {row[1] for row in cur.execute("PRAGMA table_info(life_items)").fetchall()}
            if "start_date" not in life_cols:
                cur.execute("ALTER TABLE life_items ADD COLUMN start_date DATE")
        if "chat_sessions" in existing_tables:
            chat_session_cols = {row[1] for row in cur.execute("PRAGMA table_info(chat_sessions)").fetchall()}
            if "deleted_at" not in chat_session_cols:
                cur.execute("ALTER TABLE chat_sessions ADD COLUMN deleted_at DATETIME")
        if "agents" in existing_tables:
            agent_cols = {row[1] for row in cur.execute("PRAGMA table_info(agents)").fetchall()}
            if "speech_enabled" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN speech_enabled BOOLEAN NOT NULL DEFAULT 0")
            if "tts_engine" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN tts_engine VARCHAR(50)")
            if "tts_model_id" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN tts_model_id VARCHAR(100)")
            if "voice_id" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN voice_id VARCHAR(100)")
            if "default_language" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN default_language VARCHAR(8)")
            if "voice_instructions" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN voice_instructions TEXT")
            if "preview_text" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN preview_text TEXT")
            if "voice_params_json" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN voice_params_json JSON")
            if "reference_audio_path" not in agent_cols:
                cur.execute("ALTER TABLE agents ADD COLUMN reference_audio_path VARCHAR(255)")
            if "voice_visible_in_runtime_picker" not in agent_cols:
                cur.execute(
                    "ALTER TABLE agents ADD COLUMN voice_visible_in_runtime_picker BOOLEAN NOT NULL DEFAULT 1"
                )

        for file_path in sorted(migrations_dir.glob("*.sql")):
            version = file_path.stem
            if version in applied:
                continue
            # Fresh databases rely on ORM create_all() later in init_db(), so
            # table-rebuild migrations should be skipped when the legacy table
            # does not exist yet.
            if version == "202603250001_job_schedule_modes" and "scheduled_jobs" not in existing_tables:
                cur.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                applied.add(version)
                continue
            # Fresh databases also rely on ORM create_all() for the latest
            # agents table shape. Skip ALTER-based workspace migrations when
            # the base agents table does not exist yet.
            if version == "202603220001_openviking_workspace" and "agents" not in existing_tables:
                cur.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
                applied.add(version)
                continue
            sql = file_path.read_text(encoding="utf-8")
            cur.executescript(sql)
            cur.execute("INSERT INTO schema_migrations(version) VALUES (?)", (version,))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def init_db():
    """Run migrations then ensure ORM tables exist."""
    from app.models import (  # noqa: F401
        Agent,
        AuditLog,
        ChatSession,
        ChatSessionArchive,
        DeenHabit,
        IntakeEntry,
        LifeCheckin,
        LifeItem,
        JobRunLog,
        MemoryEntry,
        PendingAction,
        PrayerCheckin,
        PrayerReminder,
        PrayerWindow,
        ProviderConfig,
        QuranBookmark,
        QuranReading,
        RuntimeState,
        ScheduledJob,
        SystemSettings,
        TTSModelRegistry,
        UserProfile,
        VoiceSession,
        WorkspaceArchiveEntry,
    )

    run_migrations()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def get_db() -> AsyncSession:
    """Dependency for FastAPI routes."""
    async with async_session() as session:
        try:
            yield session
        finally:
            await session.close()
