"""LifeOS data models - SQLAlchemy ORM + Pydantic schemas."""

import enum
from datetime import date, datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum as SAEnum,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


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
    model: Mapped[str] = mapped_column(String(100), default="openrouter/auto")
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
    cron_expression: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Africa/Casablanca")
    target_channel: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    prompt_template: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    paused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    approval_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    created_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    config_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    next_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(timezone.utc)
    )


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


class AgentCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful assistant."
    provider: str = "openrouter"
    model: str = "openrouter/auto"
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


class ChatMessageResponse(BaseModel):
    id: int
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
    created_at: datetime
    updated_at: datetime

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
    cron_expression: str
    timezone: str = "Africa/Casablanca"
    target_channel: Optional[str] = None
    prompt_template: Optional[str] = None
    enabled: bool = True
    paused: bool = False
    approval_required: bool = True
    source: str = "manual"
    created_by: Optional[str] = None
    config_json: Optional[dict] = None


class ScheduledJobUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    agent_name: Optional[str] = None
    job_type: Optional[str] = None
    cron_expression: Optional[str] = None
    timezone: Optional[str] = None
    target_channel: Optional[str] = None
    prompt_template: Optional[str] = None
    enabled: Optional[bool] = None
    paused: Optional[bool] = None
    approval_required: Optional[bool] = None
    source: Optional[str] = None
    created_by: Optional[str] = None
    config_json: Optional[dict] = None


class ScheduledJobResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    agent_name: Optional[str]
    job_type: str
    cron_expression: str
    timezone: str
    target_channel: Optional[str]
    prompt_template: Optional[str]
    enabled: bool
    paused: bool
    approval_required: bool
    source: str
    created_by: Optional[str]
    config_json: Optional[dict]
    last_run_at: Optional[datetime]
    next_run_at: Optional[datetime]
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
    created_at: datetime

    class Config:
        from_attributes = True


class ProposedActionPayload(BaseModel):
    summary: str
    details: dict[str, Any]
    requested_by: Optional[str] = None
    source: str = "api"


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


class LifeItemUpdate(BaseModel):
    title: Optional[str] = None
    notes: Optional[str] = None
    priority: Optional[str] = None
    status: Optional[str] = None
    due_at: Optional[datetime] = None
    recurrence_rule: Optional[str] = None
    risk_level: Optional[str] = None


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
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


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


class TodayAgendaResponse(BaseModel):
    timezone: str
    now: datetime
    top_focus: list[LifeItemResponse]
    due_today: list[LifeItemResponse]
    overdue: list[LifeItemResponse]
    domain_summary: dict[str, int]


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
