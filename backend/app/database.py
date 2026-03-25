"""LifeOS Database - async SQLAlchemy with SQLite migrations."""

from pathlib import Path
import sqlite3

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# Ensure database URL uses async driver.
db_url = settings.database_url
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
            job_cols = {row[1] for row in cur.execute("PRAGMA table_info(scheduled_jobs)").fetchall()}
            if "description" not in job_cols:
                cur.execute("ALTER TABLE scheduled_jobs ADD COLUMN description TEXT")
        if "life_items" in existing_tables:
            life_cols = {row[1] for row in cur.execute("PRAGMA table_info(life_items)").fetchall()}
            if "start_date" not in life_cols:
                cur.execute("ALTER TABLE life_items ADD COLUMN start_date DATE")
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

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {row[0] for row in cur.execute("SELECT version FROM schema_migrations").fetchall()}

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
        DeenHabit,
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
