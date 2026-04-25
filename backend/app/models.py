"""LifeOS data models - SQLAlchemy ORM + Pydantic schemas."""

import enum
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.config import settings


class ActionStatus(str, enum.Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"
    FAILED = "failed"


class ProviderName(str, enum.Enum):
    OPENROUTER = "openrouter"
    NVIDIA = "nvidia"
    GOOGLE = "google"
    OPENAI = "openai"


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="You are a helpful assistant.")
    provider: Mapped[str] = mapped_column(String(50), default="openrouter")
    model: Mapped[str] = mapped_column(String(100), default="openrouter/free")
    fallback_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    fallback_model: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    discord_channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    cadence: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    speech_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    tts_engine: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    tts_model_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    voice_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    default_language: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    voice_instructions: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    preview_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    voice_params_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    reference_audio_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    voice_visible_in_runtime_picker: Mapped[bool] = mapped_column(Boolean, default=True)
    workspace_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    workspace_paths_json: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    workspace_delete_requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    memory_scopes_json: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    shared_domains_json: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    vault_write_mode: Mapped[str] = mapped_column(String(40), default="structured_direct_write")
    promotion_policy: Mapped[str] = mapped_column(String(40), default="manual")

    @property
    def workspace_paths(self) -> list[str]:
        raw = self.workspace_paths_json or []
        values = [str(path) for path in raw if str(path).strip()]
        return values or [str(settings.workspace_repo_root_path)]

    @property
    def memory_scopes(self) -> list[str]:
        raw = self.memory_scopes_json or []
        values = [str(value).strip() for value in raw if str(value).strip()]
        return values or ["shared_global", "shared_domain", "agent_private", "session"]

    @property
    def shared_domains(self) -> list[str]:
        raw = self.shared_domains_json or []
        return [str(value).strip() for value in raw if str(value).strip()]


class TTSModelRegistry(Base):
    __tablename__ = "tts_model_registry"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    engine: Mapped[str] = mapped_column(String(50), nullable=False)
    model_id: Mapped[str] = mapped_column(String(100), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    supports_en: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    supports_fr: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_ar: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_voice_id: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_voice_instructions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_reference_audio: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_emotion_control: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    supports_streaming: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    quality_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="balanced")
    latency_tier: Mapped[str] = mapped_column(String(20), nullable=False, default="fast")
    vram_estimate_mb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    license_label: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class VoiceSession(Base):
    __tablename__ = "voice_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guild_id: Mapped[str] = mapped_column(String(32), nullable=False)
    channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    session_key: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    generation: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    queue_policy: Mapped[str] = mapped_column(String(20), nullable=False, default="replace")
    active_request_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    active_model_id: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    agent_name: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    job_type: Mapped[str] = mapped_column(String(40), nullable=False, default="agent_nudge")
    schedule_type: Mapped[str] = mapped_column(String(20), nullable=False, default="cron")
    cron_expression: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Casablanca")
    notification_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="channel")
    target_channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    target_channel_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    prompt_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    expect_reply: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    follow_up_after_minutes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_status: Mapped[Optional[str]] = mapped_column(String(30), nullable=True)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class JobRunLog(Base):
    __tablename__ = "job_run_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("scheduled_jobs.id"), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notification_channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    notification_channel_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    notification_message_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reply_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    awaiting_reply_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    no_reply_follow_up_sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ContextEvent(Base):
    __tablename__ = "context_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="api")
    source_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("scheduled_jobs.id"), nullable=True)
    job_run_id: Mapped[Optional[int]] = mapped_column(ForeignKey("job_run_logs.id"), nullable=True)
    life_item_id: Mapped[Optional[int]] = mapped_column(ForeignKey("life_items.id"), nullable=True)
    discord_channel_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    discord_message_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    discord_reply_message_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    discord_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    domain: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="new")
    metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    curated_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ChatSession(Base):
    __tablename__ = "chat_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New chat")
    prompt_seed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
    last_message_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class ChatSessionArchive(Base):
    __tablename__ = "chat_session_archives"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id"), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    title: Mapped[str] = mapped_column(String(160), nullable=False, default="New chat")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="api")
    reason: Mapped[str] = mapped_column(String(40), nullable=False, default="manual_delete")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    message_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    snapshot_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    restored_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class PendingAction(Base):
    __tablename__ = "pending_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action_type: Mapped[str] = mapped_column(String(50), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[ActionStatus] = mapped_column(
        SAEnum(ActionStatus), default=ActionStatus.PENDING
    )
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    discord_message_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    reviewed_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    review_source: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class WorkspaceArchiveEntry(Base):
    __tablename__ = "workspace_archive_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="agent")
    operation_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="completed")
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    display_path: Mapped[str] = mapped_column(Text, nullable=False)
    root_path: Mapped[str] = mapped_column(Text, nullable=False)
    archive_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    target_existed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    checksum_before: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    details_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    pending_action_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("pending_actions.id"),
        nullable=True,
    )
    restored_from_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("workspace_archive_entries.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class SharedMemoryProposal(Base):
    __tablename__ = "shared_memory_proposals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    source_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chat_sessions.id"),
        nullable=True,
    )
    scope: Mapped[str] = mapped_column(String(40), nullable=False)
    domain: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    target_path: Mapped[str] = mapped_column(Text, nullable=False)
    proposal_path: Mapped[str] = mapped_column(Text, nullable=False)
    expected_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    current_checksum: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_uri: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    conflict_reason: Mapped[str] = mapped_column(String(60), nullable=False, default="checksum_mismatch")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    proposed_content: Mapped[str] = mapped_column(Text, nullable=False)
    note_metadata_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    api_key_env: Mapped[str] = mapped_column(String(100), nullable=False)
    base_url: Mapped[str] = mapped_column(String(200), nullable=False)
    default_model: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class MemoryEntry(Base):
    __tablename__ = "memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    session_id: Mapped[Optional[int]] = mapped_column(ForeignKey("chat_sessions.id"), nullable=True)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class UserProfile(Base):
    __tablename__ = "user_profile"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    timezone: Mapped[str] = mapped_column(String(64), default="Africa/Casablanca")
    city: Mapped[str] = mapped_column(String(64), default="Casablanca")
    country: Mapped[str] = mapped_column(String(64), default="Morocco")
    prayer_method: Mapped[int] = mapped_column(Integer, default=2)
    work_shift_start: Mapped[str] = mapped_column(String(5), default="14:00")
    work_shift_end: Mapped[str] = mapped_column(String(5), default="00:00")
    quiet_hours_start: Mapped[str] = mapped_column(String(5), default="23:00")
    quiet_hours_end: Mapped[str] = mapped_column(String(5), default="06:00")
    nudge_mode: Mapped[str] = mapped_column(String(20), default="moderate")
    sleep_bedtime_target: Mapped[str] = mapped_column(String(5), default="23:30")
    sleep_wake_target: Mapped[str] = mapped_column(String(5), default="07:30")
    sleep_caffeine_cutoff: Mapped[str] = mapped_column(String(5), default="15:00")
    sleep_wind_down_checklist_json: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    data_start_date: Mapped[date] = mapped_column(nullable=False)
    default_timezone: Mapped[str] = mapped_column(String(64), default="Africa/Casablanca")
    autonomy_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approval_required_for_mutations: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RuntimeState(Base):
    __tablename__ = "runtime_state"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LifeItem(Base):
    __tablename__ = "life_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    domain: Mapped[str] = mapped_column(String(20), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="task")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="open")
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    start_date: Mapped[Optional[date]] = mapped_column(nullable=True)
    recurrence_rule: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    risk_level: Mapped[str] = mapped_column(String(20), default="low")
    follow_up_job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    priority_score: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    priority_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    priority_factors_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    context_links_json: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(JSON, nullable=True)
    last_prioritized_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class LifeCheckin(Base):
    __tablename__ = "life_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    life_item_id: Mapped[int] = mapped_column(ForeignKey("life_items.id"), nullable=False)
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class DailyScorecard(Base):
    __tablename__ = "daily_scorecards"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    local_date: Mapped[date] = mapped_column(nullable=False, unique=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Casablanca")
    sleep_hours: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sleep_summary_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    meals_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    training_status: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    hydration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    shutdown_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    protein_hit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    family_action_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    top_priority_completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    rescue_status: Mapped[str] = mapped_column(String(20), nullable=False, default="watch")
    notes_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class IntakeEntry(Base):
    __tablename__ = "intake_entries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    source_agent: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    source_session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("chat_sessions.id"),
        nullable=True,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    domain: Mapped[str] = mapped_column(String(20), nullable=False, default="planning")
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="idea")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="raw")
    desired_outcome: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_action: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    follow_up_questions_json: Mapped[Optional[list[str]]] = mapped_column(JSON, nullable=True)
    structured_data_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    promotion_payload_json: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)
    linked_life_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("life_items.id"),
        nullable=True,
    )
    last_agent_response: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class PrayerWindow(Base):
    __tablename__ = "prayer_windows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    local_date: Mapped[date] = mapped_column(nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    city: Mapped[str] = mapped_column(String(64), nullable=False)
    country: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    prayer_name: Mapped[str] = mapped_column(String(20), nullable=False)
    starts_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    ends_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    hijri_month: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_ramadan: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_payload_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class PrayerCheckin(Base):
    __tablename__ = "prayer_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prayer_window_id: Mapped[int] = mapped_column(ForeignKey("prayer_windows.id"), nullable=False)
    status_raw: Mapped[str] = mapped_column(String(20), nullable=False)
    status_scored: Mapped[str] = mapped_column(String(20), nullable=False)
    reported_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="api")
    discord_user_id: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_retroactive: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retro_reason: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class PrayerReminder(Base):
    __tablename__ = "prayer_reminders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    prayer_window_id: Mapped[int] = mapped_column(ForeignKey("prayer_windows.id"), nullable=False)
    channel_name: Mapped[str] = mapped_column(String(100), nullable=False)
    discord_message_id: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    sent_at_utc: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    deadline_nudge_sent_at_utc: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class DeenHabit(Base):
    __tablename__ = "deen_habits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    local_date: Mapped[date] = mapped_column(nullable=False)
    habit_type: Mapped[str] = mapped_column(String(30), nullable=False)
    value_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="api")
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class QuranReading(Base):
    __tablename__ = "quran_readings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    local_date: Mapped[date] = mapped_column(nullable=False)
    start_page: Mapped[int] = mapped_column(Integer, nullable=False)
    end_page: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="api")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class QuranBookmark(Base):
    __tablename__ = "quran_bookmark"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False, default=1)
    current_page: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )



class ExperimentRun(Base):
    """Persistent record of a shadow-router experiment run."""

    __tablename__ = "experiment_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    primary_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    primary_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    shadow_provider: Mapped[str] = mapped_column(String(50), nullable=False)
    shadow_model: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    primary_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    shadow_score: Mapped[float] = mapped_column(nullable=False, default=0.0)
    shadow_latency_ms: Mapped[float] = mapped_column(nullable=False, default=0.0)
    cost_estimate: Mapped[float] = mapped_column(nullable=False, default=0.0)
    shadow_wins: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promoted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    promotion_approved: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful assistant."
    provider: str = "openrouter"
    model: str = "openrouter/free"
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    discord_channel: Optional[str] = None
    cadence: Optional[str] = None
    enabled: bool = True
    config_json: Optional[dict] = None
    speech_enabled: bool = False
    tts_engine: Optional[str] = None
    tts_model_id: Optional[str] = None
    voice_id: Optional[str] = None
    default_language: Optional[Literal["en", "fr", "ar"]] = None
    voice_instructions: Optional[str] = None
    preview_text: Optional[str] = None
    voice_params_json: Optional[dict[str, Any]] = None
    reference_audio_path: Optional[str] = None
    voice_visible_in_runtime_picker: bool = True
    workspace_enabled: bool = False
    workspace_paths: list[str] = Field(default_factory=lambda: [str(settings.workspace_repo_root_path)])
    workspace_delete_requires_approval: bool = True
    memory_scopes: list[str] = Field(
        default_factory=lambda: ["shared_global", "shared_domain", "agent_private", "session"]
    )
    shared_domains: list[str] = Field(default_factory=list)
    vault_write_mode: str = "structured_direct_write"
    promotion_policy: str = "manual"


class AgentUpdate(BaseModel):
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    provider: Optional[str] = None
    model: Optional[str] = None
    fallback_provider: Optional[str] = None
    fallback_model: Optional[str] = None
    discord_channel: Optional[str] = None
    cadence: Optional[str] = None
    enabled: Optional[bool] = None
    config_json: Optional[dict] = None
    speech_enabled: Optional[bool] = None
    tts_engine: Optional[str] = None
    tts_model_id: Optional[str] = None
    voice_id: Optional[str] = None
    default_language: Optional[Literal["en", "fr", "ar"]] = None
    voice_instructions: Optional[str] = None
    preview_text: Optional[str] = None
    voice_params_json: Optional[dict[str, Any]] = None
    reference_audio_path: Optional[str] = None
    voice_visible_in_runtime_picker: Optional[bool] = None
    workspace_enabled: Optional[bool] = None
    workspace_paths: Optional[list[str]] = None
    workspace_delete_requires_approval: Optional[bool] = None
    memory_scopes: Optional[list[str]] = None
    shared_domains: Optional[list[str]] = None
    vault_write_mode: Optional[str] = None
    promotion_policy: Optional[str] = None


class AgentResponse(BaseModel):
    id: int
    name: str
    description: str
    system_prompt: str
    provider: str
    model: str
    fallback_provider: Optional[str]
    fallback_model: Optional[str]
    discord_channel: Optional[str]
    cadence: Optional[str]
    enabled: bool
    created_at: datetime
    config_json: Optional[dict]
    speech_enabled: bool
    tts_engine: Optional[str]
    tts_model_id: Optional[str]
    voice_id: Optional[str]
    default_language: Optional[str]
    voice_instructions: Optional[str]
    preview_text: Optional[str]
    voice_params_json: Optional[dict[str, Any]]
    reference_audio_path: Optional[str]
    voice_visible_in_runtime_picker: bool
    workspace_enabled: bool
    workspace_paths: list[str]
    workspace_delete_requires_approval: bool
    memory_scopes: list[str]
    shared_domains: list[str]
    vault_write_mode: str
    promotion_policy: str

    class Config:
        from_attributes = True


class ActionResponse(BaseModel):
    id: int
    agent_name: str
    action_type: str
    summary: str
    details: Optional[str]
    status: ActionStatus
    risk_level: str = "low"
    discord_message_id: Optional[str]
    reviewed_by: Optional[str]
    review_source: Optional[str]
    created_at: datetime
    resolved_at: Optional[datetime]
    result: Optional[str]

    class Config:
        from_attributes = True


class ApprovalDecision(BaseModel):
    action_id: int
    approved: bool
    reason: Optional[str] = None
    reviewed_by: Optional[str] = None
    source: str = "webui"


class ChatRequest(BaseModel):
    agent_name: str
    message: str
    approval_policy: str = "auto"
    session_id: Optional[int] = None


class ChatResponse(BaseModel):
    agent_name: str
    response: str
    pending_action_id: Optional[int] = None
    risk_level: str = "low"
    session_id: Optional[int] = None
    session_title: Optional[str] = None
    warnings: list[str] = Field(default_factory=list)
    grounding: Optional[dict[str, Any]] = None


class ChatSessionCreate(BaseModel):
    title: Optional[str] = None


class ChatSessionUpdate(BaseModel):
    title: str


class ChatSessionResponse(BaseModel):
    id: int
    agent_name: str
    title: str
    prompt_seed_count: int
    created_at: datetime
    updated_at: datetime
    last_message_at: Optional[datetime]

    class Config:
        from_attributes = True


class ChatSessionArchiveActionRequest(BaseModel):
    source: str = "api"


class ChatSessionArchiveResponse(BaseModel):
    id: int
    session_id: int
    agent_name: str
    title: str
    source: str
    reason: str
    status: str
    message_count: int
    created_at: datetime
    expires_at: datetime
    restored_at: Optional[datetime]

    class Config:
        from_attributes = True


class ChatMessageResponse(BaseModel):
    id: str
    role: str
    content: str
    timestamp: datetime

    class Config:
        from_attributes = True


class ProfileUpdate(BaseModel):
    timezone: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None
    prayer_method: Optional[int] = None
    work_shift_start: Optional[str] = None
    work_shift_end: Optional[str] = None
    quiet_hours_start: Optional[str] = None
    quiet_hours_end: Optional[str] = None
    nudge_mode: Optional[str] = None
    sleep_bedtime_target: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    sleep_wake_target: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    sleep_caffeine_cutoff: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    sleep_wind_down_checklist: Optional[list[str]] = None


class ProfileResponse(BaseModel):
    id: int
    timezone: str
    city: str
    country: str
    prayer_method: int
    work_shift_start: str
    work_shift_end: str
    quiet_hours_start: str
    quiet_hours_end: str
    nudge_mode: str
    sleep_bedtime_target: str
    sleep_wake_target: str
    sleep_caffeine_cutoff: str
    sleep_wind_down_checklist: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_sleep_profile_fields(cls, value: Any):
        if isinstance(value, dict):
            data = dict(value)
            if "sleep_wind_down_checklist" not in data:
                data["sleep_wind_down_checklist"] = data.get("sleep_wind_down_checklist_json") or []
            return data

        return {
            "id": value.id,
            "timezone": value.timezone,
            "city": value.city,
            "country": value.country,
            "prayer_method": value.prayer_method,
            "work_shift_start": value.work_shift_start,
            "work_shift_end": value.work_shift_end,
            "quiet_hours_start": value.quiet_hours_start,
            "quiet_hours_end": value.quiet_hours_end,
            "nudge_mode": value.nudge_mode,
            "sleep_bedtime_target": value.sleep_bedtime_target,
            "sleep_wake_target": value.sleep_wake_target,
            "sleep_caffeine_cutoff": value.sleep_caffeine_cutoff,
            "sleep_wind_down_checklist": getattr(value, "sleep_wind_down_checklist_json", None) or [],
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

    class Config:
        from_attributes = True


class SystemSettingsUpdate(BaseModel):
    data_start_date: Optional[str] = Field(
        default=None,
        description="Inclusive YYYY-MM-DD. Data before this date is ignored in reporting.",
    )
    default_timezone: Optional[str] = None
    autonomy_enabled: Optional[bool] = None
    approval_required_for_mutations: Optional[bool] = None


class SystemSettingsResponse(BaseModel):
    id: int
    data_start_date: str
    default_timezone: str
    autonomy_enabled: bool
    approval_required_for_mutations: bool
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ScheduledJobCreate(BaseModel):
    name: str
    description: Optional[str] = None
    agent_name: Optional[str] = None
    job_type: str = "agent_nudge"
    schedule_type: Optional[Literal["cron", "once"]] = None
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: str = "Africa/Casablanca"
    notification_mode: Literal["channel", "silent"] = "channel"
    target_channel: Optional[str] = None
    target_channel_id: Optional[str] = None
    prompt_template: Optional[str] = None
    enabled: bool = True
    paused: bool = False
    approval_required: bool = True
    expect_reply: bool = False
    follow_up_after_minutes: Optional[int] = None
    source: str = "manual"
    created_by: Optional[str] = None
    config_json: Optional[dict] = None

    @model_validator(mode="after")
    def validate_schedule(self) -> "ScheduledJobCreate":
        if self.schedule_type is None:
            self.schedule_type = "once" if self.run_at and not self.cron_expression else "cron"
        if self.schedule_type == "cron":
            if not (self.cron_expression or "").strip():
                raise ValueError("cron_expression is required for cron jobs")
            self.run_at = None
        else:
            if self.run_at is None:
                raise ValueError("run_at is required for one-time jobs")
            self.cron_expression = None
        return self


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_name: Optional[str] = None
    job_type: Optional[str] = None
    schedule_type: Optional[Literal["cron", "once"]] = None
    cron_expression: Optional[str] = None
    run_at: Optional[datetime] = None
    timezone: Optional[str] = None
    notification_mode: Optional[Literal["channel", "silent"]] = None
    target_channel: Optional[str] = None
    target_channel_id: Optional[str] = None
    prompt_template: Optional[str] = None
    enabled: Optional[bool] = None
    paused: Optional[bool] = None
    approval_required: Optional[bool] = None
    expect_reply: Optional[bool] = None
    follow_up_after_minutes: Optional[int] = None
    source: Optional[str] = None
    created_by: Optional[str] = None
    config_json: Optional[dict] = None


class ScheduledJobResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    agent_name: Optional[str]
    job_type: str
    schedule_type: str
    cron_expression: Optional[str]
    run_at: Optional[datetime]
    timezone: str
    notification_mode: str
    target_channel: Optional[str]
    target_channel_id: Optional[str]
    prompt_template: Optional[str]
    enabled: bool
    paused: bool
    approval_required: bool
    expect_reply: bool
    follow_up_after_minutes: Optional[int]
    source: str
    created_by: Optional[str]
    config_json: Optional[dict]
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
    completed_at: Optional[datetime]
    last_status: Optional[str]
    last_error: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class JobRunLogResponse(BaseModel):
    id: int
    job_id: int
    started_at: datetime
    finished_at: datetime
    status: str
    message: Optional[str]
    error: Optional[str]
    notification_channel: Optional[str]
    notification_channel_id: Optional[str]
    notification_message_id: Optional[str]
    reply_count: int
    awaiting_reply_until: Optional[datetime]
    no_reply_follow_up_sent_at: Optional[datetime]
    created_at: datetime

    class Config:
        from_attributes = True


class ProposedActionPayload(BaseModel):
    summary: str
    details: dict[str, Any]
    requested_by: Optional[str] = None
    source: str = "api"


class WorkspaceArchiveEntryResponse(BaseModel):
    id: int
    agent_name: str
    source: str
    operation_type: str
    status: str
    target_path: str
    display_path: str
    root_path: str
    archive_path: Optional[str]
    target_existed: bool
    checksum_before: Optional[str]
    details_json: Optional[dict[str, Any]]
    pending_action_id: Optional[int]
    restored_from_id: Optional[int]
    created_at: datetime
    resolved_at: Optional[datetime]

    class Config:
        from_attributes = True


class SharedMemorySearchHit(BaseModel):
    title: str
    path: str
    scope: str
    domain: Optional[str] = None
    score: Optional[float] = None
    source: str
    snippet: str = ""
    uri: Optional[str] = None


class SharedMemorySearchResponse(BaseModel):
    query: str
    scope: Optional[str] = None
    domain: Optional[str] = None
    hits: list[SharedMemorySearchHit] = Field(default_factory=list)


class SharedMemoryPromoteRequest(BaseModel):
    agent_name: str
    title: str
    content: str
    scope: Literal["shared_global", "shared_domain", "agent_private"] = "shared_domain"
    domain: Optional[str] = None
    session_id: Optional[int] = None
    source_uri: Optional[str] = None
    target_path: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    owners: list[str] = Field(default_factory=list)
    confidence: Optional[str] = None
    verified_at: Optional[str] = None
    expected_checksum: Optional[str] = None
    managed_by: str = "lifeos"
    status: str = "active"


class SharedMemoryPromoteResponse(BaseModel):
    status: str
    target_path: str
    proposal_id: Optional[int] = None
    proposal_path: Optional[str] = None
    archive_entry_ids: list[int] = Field(default_factory=list)
    checksum: Optional[str] = None
    note_uri: Optional[str] = None


class SharedMemoryProposalResponse(BaseModel):
    id: int
    source_agent: str
    source_session_id: Optional[int]
    scope: str
    domain: Optional[str]
    title: str
    target_path: str
    proposal_path: str
    expected_checksum: Optional[str]
    current_checksum: Optional[str]
    source_uri: Optional[str]
    conflict_reason: str
    status: str
    proposed_content: str
    note_metadata_json: Optional[dict[str, Any]]
    created_at: datetime
    applied_at: Optional[datetime]

    class Config:
        from_attributes = True


class SharedMemoryProposalApplyRequest(BaseModel):
    source_agent: str = "webui"


class ContextEventResponse(BaseModel):
    id: int
    event_type: str
    source: str
    source_agent: Optional[str]
    source_session_id: Optional[int]
    job_id: Optional[int]
    job_run_id: Optional[int]
    life_item_id: Optional[int]
    discord_channel_id: Optional[str]
    discord_message_id: Optional[str]
    discord_reply_message_id: Optional[str]
    discord_user_id: Optional[str]
    title: Optional[str]
    summary: Optional[str]
    raw_text: str
    domain: str
    status: str
    metadata_json: Optional[dict[str, Any]]
    created_at: datetime
    curated_at: Optional[datetime]

    class Config:
        from_attributes = True


class MeetingIntakeRequest(BaseModel):
    summary: str
    title: Optional[str] = None
    domain: Optional[str] = None
    source: str = "api"
    source_agent: str = "wiki-curator"
    session_id: Optional[int] = None
    tags: list[str] = Field(default_factory=list)


class MeetingIntakeResponse(BaseModel):
    event: ContextEventResponse
    proposals: list[SharedMemoryProposalResponse] = Field(default_factory=list)
    intake_entry_ids: list[int] = Field(default_factory=list)


class ContextEventCurateResponse(BaseModel):
    event: ContextEventResponse
    proposals: list[SharedMemoryProposalResponse] = Field(default_factory=list)
    intake_entry_ids: list[int] = Field(default_factory=list)


class JobReplyIntakeRequest(BaseModel):
    notification_message_id: str
    reply_text: str
    discord_channel_id: Optional[str] = None
    discord_reply_message_id: Optional[str] = None
    discord_user_id: Optional[str] = None
    source: str = "discord_reply"


class JobReplyIntakeResponse(BaseModel):
    event: ContextEventResponse
    job_id: int
    job_run_id: int
    life_checkin_id: Optional[int] = None
    life_checkin_result: Optional[str] = None
    proposals: list[SharedMemoryProposalResponse] = Field(default_factory=list)


class LifeItemCreate(BaseModel):
    domain: str
    title: str
    kind: str = "task"
    notes: Optional[str] = None
    priority: str = "medium"
    due_at: Optional[datetime] = None
    start_date: Optional[str] = None
    recurrence_rule: Optional[str] = None
    source_agent: Optional[str] = None
    risk_level: str = "low"
    priority_score: int = Field(default=50, ge=0, le=100)
    priority_reason: Optional[str] = None
    priority_factors: Optional[dict[str, Any]] = None
    context_links: Optional[list[dict[str, Any]]] = None
    last_prioritized_at: Optional[datetime] = None


class LifeItemUpdate(BaseModel):
    domain: Optional[str] = None
    kind: Optional[str] = None
    title: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    risk_level: Optional[str] = None
    follow_up_job_id: Optional[int] = None
    priority_score: Optional[int] = Field(default=None, ge=0, le=100)
    priority_reason: Optional[str] = None
    priority_factors: Optional[dict[str, Any]] = None
    context_links: Optional[list[dict[str, Any]]] = None
    last_prioritized_at: Optional[datetime] = None


class LifeItemResponse(BaseModel):
    id: int
    domain: str
    kind: str
    title: str
    notes: Optional[str]
    priority: str
    status: str
    due_at: Optional[datetime]
    start_date: Optional[str] = None
    recurrence_rule: Optional[str]
    source_agent: Optional[str]
    risk_level: str
    follow_up_job_id: Optional[int] = None
    priority_score: int = 50
    priority_reason: Optional[str] = None
    priority_factors: Optional[dict[str, Any]] = None
    context_links: list[dict[str, Any]] = Field(default_factory=list)
    last_prioritized_at: Optional[datetime] = None
    focus_reason: Optional[str] = None
    follow_up_due_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_life_item_fields(cls, value: Any):
        if isinstance(value, dict):
            data = dict(value)
            if "priority_factors" not in data:
                data["priority_factors"] = data.get("priority_factors_json")
            if "context_links" not in data:
                data["context_links"] = data.get("context_links_json") or []
            return data

        return {
            "id": value.id,
            "domain": value.domain,
            "kind": value.kind,
            "title": value.title,
            "notes": value.notes,
            "priority": value.priority,
            "status": value.status,
            "due_at": value.due_at,
            "start_date": value.start_date.isoformat() if getattr(value, "start_date", None) else None,
            "recurrence_rule": value.recurrence_rule,
            "source_agent": value.source_agent,
            "risk_level": value.risk_level,
            "follow_up_job_id": getattr(value, "follow_up_job_id", None),
            "priority_score": getattr(value, "priority_score", 50),
            "priority_reason": getattr(value, "priority_reason", None),
            "priority_factors": getattr(value, "priority_factors_json", None),
            "context_links": getattr(value, "context_links_json", None) or [],
            "last_prioritized_at": getattr(value, "last_prioritized_at", None),
            "focus_reason": getattr(value, "focus_reason", None),
            "follow_up_due_at": getattr(value, "follow_up_due_at", None),
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

    class Config:
        from_attributes = True


class IntakeEntryUpdate(BaseModel):
    title: Optional[str] = None
    summary: Optional[str] = None
    domain: Optional[str] = None
    kind: Optional[str] = None
    status: Optional[str] = None
    desired_outcome: Optional[str] = None
    next_action: Optional[str] = None
    follow_up_questions: Optional[list[str]] = None
    promotion_payload: Optional[dict[str, Any]] = None


class IntakeEntryResponse(BaseModel):
    id: int
    source: str
    source_agent: Optional[str]
    source_session_id: Optional[int]
    raw_text: str
    title: Optional[str]
    summary: Optional[str]
    domain: str
    kind: str
    status: str
    desired_outcome: Optional[str]
    next_action: Optional[str]
    follow_up_questions: list[str] = Field(default_factory=list)
    structured_data: Optional[dict[str, Any]] = None
    promotion_payload: Optional[dict[str, Any]] = None
    linked_life_item_id: Optional[int]
    last_agent_response: Optional[str]
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_intake_fields(cls, value: Any):
        if isinstance(value, dict):
            data = dict(value)
            if "follow_up_questions" not in data:
                data["follow_up_questions"] = data.get("follow_up_questions_json") or []
            if "structured_data" not in data:
                data["structured_data"] = data.get("structured_data_json")
            if "promotion_payload" not in data:
                data["promotion_payload"] = data.get("promotion_payload_json")
            return data

        followups = list(getattr(value, "follow_up_questions_json", None) or [])
        structured = getattr(value, "structured_data_json", None)
        promotion = getattr(value, "promotion_payload_json", None)
        return {
            "id": value.id,
            "source": value.source,
            "source_agent": value.source_agent,
            "source_session_id": value.source_session_id,
            "raw_text": value.raw_text,
            "title": value.title,
            "summary": value.summary,
            "domain": value.domain,
            "kind": value.kind,
            "status": value.status,
            "desired_outcome": value.desired_outcome,
            "next_action": value.next_action,
            "follow_up_questions": followups,
            "structured_data": structured,
            "promotion_payload": promotion,
            "linked_life_item_id": value.linked_life_item_id,
            "last_agent_response": value.last_agent_response,
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

    class Config:
        from_attributes = True


class IntakeCaptureRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    new_session: bool = False
    source: str = "api"


class IntakeCaptureResponse(BaseModel):
    response: str
    session_id: Optional[int] = None
    session_title: Optional[str] = None
    entry: Optional[IntakeEntryResponse] = None
    entries: list[IntakeEntryResponse] = Field(default_factory=list)
    life_items: list[LifeItemResponse] = Field(default_factory=list)
    wiki_proposals: list[SharedMemoryProposalResponse] = Field(default_factory=list)
    auto_promoted_count: int = 0


class CommitmentCaptureRequest(BaseModel):
    message: str
    raw_message: Optional[str] = None
    session_id: Optional[int] = None
    new_session: bool = False
    source: str = "api"
    due_at: Optional[datetime] = None
    timezone: Optional[str] = None
    target_channel: Optional[str] = None
    target_channel_id: Optional[str] = None


class CommitmentCaptureResponse(BaseModel):
    response: str
    session_id: Optional[int] = None
    session_title: Optional[str] = None
    entry: Optional[IntakeEntryResponse] = None
    life_item: Optional[LifeItemResponse] = None
    follow_up_job: Optional[ScheduledJobResponse] = None
    auto_promoted: bool = False
    needs_follow_up: bool = False


class UnifiedCaptureRequest(BaseModel):
    message: str
    session_id: Optional[int] = None
    new_session: bool = True
    source: str = "api"
    route_hint: Optional[Literal["auto", "intake", "commitment", "memory"]] = "auto"
    due_at: Optional[datetime] = None
    timezone: Optional[str] = None
    target_channel: Optional[str] = None
    target_channel_id: Optional[str] = None


class UnifiedCaptureResponse(BaseModel):
    route: Literal["intake", "commitment", "memory"]
    response: str
    session_id: Optional[int] = None
    session_title: Optional[str] = None
    entry: Optional[IntakeEntryResponse] = None
    entries: list[IntakeEntryResponse] = Field(default_factory=list)
    life_item: Optional[LifeItemResponse] = None
    life_items: list[LifeItemResponse] = Field(default_factory=list)
    follow_up_job: Optional[ScheduledJobResponse] = None
    wiki_proposals: list[SharedMemoryProposalResponse] = Field(default_factory=list)
    event: Optional[ContextEventResponse] = None
    auto_promoted_count: int = 0
    needs_follow_up: bool = False
    needs_answer_count: int = 0


class IntakePromoteRequest(BaseModel):
    title: Optional[str] = None
    kind: Optional[str] = None
    domain: Optional[str] = None
    priority: Optional[str] = None
    due_at: Optional[datetime] = None
    start_date: Optional[str] = None
    notes: Optional[str] = None


class IntakePromoteResponse(BaseModel):
    entry: IntakeEntryResponse
    life_item: LifeItemResponse


class LifeCheckinCreate(BaseModel):
    result: str = Field(description="done | partial | missed")
    note: Optional[str] = None


class LifeCheckinResponse(BaseModel):
    id: int
    life_item_id: int
    result: str
    note: Optional[str]
    timestamp: datetime

    class Config:
        from_attributes = True


class LifeItemSnoozeRequest(BaseModel):
    due_at: datetime
    timezone: Optional[str] = None
    source: str = "api"
    note: Optional[str] = None


class DailyScorecardResponse(BaseModel):
    id: int
    local_date: date
    timezone: str
    sleep_hours: Optional[float] = None
    sleep_summary: Optional[dict[str, Any]] = None
    meals_count: int
    training_status: Optional[str] = None
    hydration_count: int
    shutdown_done: bool
    protein_hit: bool
    family_action_done: bool
    top_priority_completed_count: int
    rescue_status: str
    notes: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _normalize_daily_scorecard_fields(cls, value: Any):
        if isinstance(value, dict):
            data = dict(value)
            if "sleep_summary" not in data:
                data["sleep_summary"] = data.get("sleep_summary_json")
            if "notes" not in data:
                data["notes"] = data.get("notes_json") or {}
            return data

        return {
            "id": value.id,
            "local_date": value.local_date,
            "timezone": value.timezone,
            "sleep_hours": value.sleep_hours,
            "sleep_summary": getattr(value, "sleep_summary_json", None),
            "meals_count": value.meals_count,
            "training_status": value.training_status,
            "hydration_count": value.hydration_count,
            "shutdown_done": value.shutdown_done,
            "protein_hit": value.protein_hit,
            "family_action_done": value.family_action_done,
            "top_priority_completed_count": value.top_priority_completed_count,
            "rescue_status": value.rescue_status,
            "notes": getattr(value, "notes_json", None) or {},
            "created_at": value.created_at,
            "updated_at": value.updated_at,
        }

    class Config:
        from_attributes = True


class NextPrayerResponse(BaseModel):
    name: str
    starts_at: datetime
    ends_at: datetime


class RescuePlanResponse(BaseModel):
    status: str
    headline: str
    actions: list[str] = Field(default_factory=list)


class SleepProtocolResponse(BaseModel):
    bedtime_target: str
    wake_target: str
    caffeine_cutoff: str
    wind_down_checklist: list[str] = Field(default_factory=list)
    sleep_hours_logged: Optional[float] = None
    bedtime_logged: Optional[str] = None
    wake_time_logged: Optional[str] = None


class AccountabilityMetricResponse(BaseModel):
    key: str
    label: str
    current_streak: int
    hits_last_7: int
    today_status: Literal["hit", "miss", "pending"]


class AccountabilityTrendDayResponse(BaseModel):
    date: date
    hits: int
    total: int
    completion_pct: int


class AccountabilityTrendSummaryResponse(BaseModel):
    window_days: int
    average_completion_pct: int
    best_day: Optional[AccountabilityTrendDayResponse] = None
    recent_days: list[AccountabilityTrendDayResponse] = Field(default_factory=list)


class DailyFocusCoachResponse(BaseModel):
    primary_item_id: Optional[int] = None
    why_now: str
    first_step: str
    defer_ids: list[int] = Field(default_factory=list)
    nudge_copy: str
    fallback_used: bool = False


class WeeklyCommitmentReviewResponse(BaseModel):
    wins: list[str] = Field(default_factory=list)
    stale_commitments: list[str] = Field(default_factory=list)
    repeat_blockers: list[str] = Field(default_factory=list)
    promises_at_risk: list[str] = Field(default_factory=list)
    simplify_next_week: list[str] = Field(default_factory=list)
    fallback_used: bool = False


class DailyLogCreate(BaseModel):
    kind: Literal["sleep", "meal", "training", "hydration", "shutdown", "family", "priority"]
    note: Optional[str] = None
    count: Optional[int] = Field(default=None, ge=1)
    done: Optional[bool] = None
    status: Optional[Literal["done", "rest", "missed"]] = None
    hours: Optional[float] = Field(default=None, ge=0, le=24)
    bedtime: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    wake_time: Optional[str] = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    protein_hit: Optional[bool] = None


class DailyLogResponse(BaseModel):
    kind: str
    message: str
    scorecard: DailyScorecardResponse
    rescue_plan: RescuePlanResponse
    sleep_protocol: Optional[SleepProtocolResponse] = None
    streaks: list[AccountabilityMetricResponse] = Field(default_factory=list)
    trend_summary: Optional[AccountabilityTrendSummaryResponse] = None


class TodayAgendaResponse(BaseModel):
    timezone: str
    now: datetime
    top_focus: list[LifeItemResponse]
    due_today: list[LifeItemResponse]
    overdue: list[LifeItemResponse]
    domain_summary: dict[str, int]
    intake_summary: dict[str, int] = Field(default_factory=dict)
    ready_intake: list[IntakeEntryResponse] = Field(default_factory=list)
    memory_review: list[SharedMemoryProposalResponse] = Field(default_factory=list)
    scorecard: Optional[DailyScorecardResponse] = None
    next_prayer: Optional[NextPrayerResponse] = None
    rescue_plan: Optional[RescuePlanResponse] = None
    sleep_protocol: Optional[SleepProtocolResponse] = None
    streaks: list[AccountabilityMetricResponse] = Field(default_factory=list)
    trend_summary: Optional[AccountabilityTrendSummaryResponse] = None


class PrayerWindowResponse(BaseModel):
    prayer_name: str
    starts_at: datetime
    ends_at: datetime


class PrayerScheduleTodayResponse(BaseModel):
    date: str
    timezone: str
    city: str
    country: str
    hijri_month: int
    is_ramadan: bool
    next_prayer: Optional[str]
    windows: list[PrayerWindowResponse]


class PrayerCheckinRequest(BaseModel):
    prayer_window_id: Optional[int] = Field(default=None, gt=0)
    prayer_date: str
    prayer_name: Literal["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    status: Literal["on_time", "late", "missed"]
    source: str = "command"
    discord_user_id: Optional[str] = None
    note: Optional[str] = None


class PrayerRetroactiveCheckinRequest(BaseModel):
    prayer_window_id: Optional[int] = Field(default=None, gt=0)
    prayer_date: str
    prayer_name: Literal["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    status: Literal["on_time", "late", "missed"]
    note: Optional[str] = None
    source: str = "command"
    discord_user_id: Optional[str] = None


class PrayerCheckinResponse(BaseModel):
    prayer_date: str
    prayer_name: str
    status_raw: str
    status_scored: str
    is_retroactive: bool
    reported_at_utc: datetime


class QuranHabitRequest(BaseModel):
    date: str
    juz: int = Field(ge=1, le=30)
    pages: int = Field(default=0, ge=0, le=20)
    note: Optional[str] = None


class QuranReadingRequest(BaseModel):
    start_page: Optional[int] = Field(default=None, ge=1, le=604)
    end_page: int = Field(ge=1, le=604)
    note: Optional[str] = None
    source: str = "api"


class QuranReadingResponse(BaseModel):
    id: int
    local_date: str
    start_page: int
    end_page: int
    pages_read: int
    note: Optional[str]
    source: str

    class Config:
        from_attributes = True


class QuranProgressResponse(BaseModel):
    current_page: int
    total_pages: int = 604
    pages_read_total: int
    completion_pct: float
    recent_readings: list[QuranReadingResponse]


class QuranBookmarkResponse(BaseModel):
    current_page: int


class TahajjudHabitRequest(BaseModel):
    date: Optional[str] = None
    done: bool


class AdhkarHabitRequest(BaseModel):
    date: Optional[str] = None
    period: Literal["morning", "evening"]
    done: bool


class HabitLogResponse(BaseModel):
    id: int
    local_date: str
    habit_type: str
    done: bool


class PrayerWeeklySummaryResponse(BaseModel):
    start_date: str
    end_date: str
    total_prayers: int
    on_time: int
    late: int
    missed: int
    unknown: int
    retroactive_count: int
    on_time_rate: float
    completion_rate: float
    is_ramadan: bool
    quran_pages_total: int
    quran_juz_max: int
    tahajjud_done: int
    tahajjud_target: int
    adhkar_morning_done: int
    adhkar_evening_done: int
    guidance: list[str]


class PrayerDayStatus(BaseModel):
    date: str
    prayers: dict[str, Optional[str]]  # {Fajr: on_time|late|missed|unknown|null, ...}
    window_ids: dict[str, Optional[int]]  # {Fajr: 42, ...}


class PrayerDashboardResponse(BaseModel):
    days: list[PrayerDayStatus]
    summary: dict[str, Any]  # on_time_count, late_count, etc.


class PrayerCheckinEditRequest(BaseModel):
    prayer_date: str
    prayer_name: Literal["Fajr", "Dhuhr", "Asr", "Maghrib", "Isha"]
    status: Literal["on_time", "late", "missed"]
    note: Optional[str] = None


class GoalProgressResponse(BaseModel):
    item: LifeItemResponse
    days_since_start: Optional[int]
    checkin_count: int
    done_count: int
    partial_count: int
    missed_count: int
    checkins: list[dict]


class TTSModelCapabilityResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    engine: str
    model_id: str
    display_name: str
    supports_languages: list[str]
    supports_voice_id: bool = False
    supports_voice_instructions: bool = False
    supports_reference_audio: bool = False
    supports_emotion_control: bool = False
    supports_streaming: bool = False
    quality_tier: str = "balanced"
    latency_tier: str = "fast"
    vram_estimate_mb: Optional[int] = None
    license_label: Optional[str] = None
    enabled: bool = True


class TTSPayload(BaseModel):
    agent_name: str
    text: str
    language: Optional[Literal["en", "fr", "ar"]] = None
    queue_policy: Literal["replace", "append"] = "replace"
    runtime_overrides: Optional[dict[str, Any]] = None


class TTSSynthesizeResponse(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    request_id: str
    model_id: str
    engine: str
    sample_rate_hz: int
    audio_b64_wav: str
    cached: bool = False
    duration_ms: int


class TTSPreviewRequest(BaseModel):
    agent_name: str
    text: Optional[str] = None
    language: Optional[Literal["en", "fr", "ar"]] = None


class TTSHealthResponse(BaseModel):
    status: str
    warm_model_key: Optional[str]
    queue_depth: int
    active_request_id: Optional[str]
    cache_entries: int
    policy: dict[str, Any]


class VoiceSessionStartRequest(BaseModel):
    guild_id: str
    channel_id: str
    agent_name: str
    queue_policy: Literal["replace", "append"] = "replace"


class VoiceSessionResponse(BaseModel):
    session_id: int
    session_key: str
    guild_id: str
    channel_id: str
    agent_name: str
    status: str
    generation: int
    queue_policy: str


class VoiceSessionInterruptRequest(BaseModel):
    reason: Optional[str] = None


class VoiceSessionStopRequest(BaseModel):
    reason: Optional[str] = None
