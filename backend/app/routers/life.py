"""Life items and agenda router."""

from sqlalchemy import select

from app.database import async_session
from fastapi import APIRouter, Depends, HTTPException, Query

from app.models import (
    CommitmentCaptureRequest,
    CommitmentCaptureResponse,
    DailyFocusCoachResponse,
    DailyLogCreate,
    DailyLogResponse,
    DailyScorecardResponse,
    GoalProgressResponse,
    IntakeCaptureRequest,
    IntakeCaptureResponse,
    IntakeEntryResponse,
    IntakeEntryUpdate,
    IntakePromoteRequest,
    IntakePromoteResponse,
    LifeCheckinCreate,
    LifeCheckinResponse,
    LifeItemCreate,
    LifeItemResponse,
    LifeItemSnoozeRequest,
    NextPrayerResponse,
    RescuePlanResponse,
    SleepProtocolResponse,
    LifeItemUpdate,
    TodayAgendaResponse,
    WeeklyCommitmentReviewResponse,
    LifeItem,
    ScheduledJobResponse,
)
from app.security import require_api_token
from app.services.chat_sessions import create_session, generate_title_from_prompts
from app.services.commitment_coach import get_daily_focus_coach, get_weekly_commitment_review
from app.services.commitments import get_commitment_timezone, upsert_follow_up_job
from app.services.intake import (
    get_intake_entry,
    get_latest_intake_entry_for_session,
    list_intake_entries,
    promote_intake_entry,
    update_intake_entry,
)
from app.services.life import (
    add_checkin,
    create_life_item,
    get_goal_progress,
    get_today_agenda,
    list_life_items,
    log_daily_signal,
    snooze_life_item,
    update_life_item,
)
from app.services.orchestrator import handle_message

router = APIRouter()
COMMITMENT_AGENT_NAME = "commitment-capture"


def _should_promote_commitment_entry(entry, *, due_at) -> bool:
    if not entry or entry.linked_life_item_id:
        return False
    if entry.status == "ready":
        return True
    if entry.status != "clarifying" or due_at is None:
        return False
    payload = dict(entry.promotion_payload_json or {})
    title = str(payload.get("title") or entry.title or "").strip()
    kind = str(payload.get("kind") or entry.kind or "").strip().lower()
    domain = str(payload.get("domain") or entry.domain or "").strip().lower()
    if len(title) < 3:
        return False
    return kind in {"commitment", "task", "habit", "routine"} and bool(domain)


@router.get("/items", response_model=list[LifeItemResponse], dependencies=[Depends(require_api_token)])
async def get_items(
    domain: str | None = Query(default=None),
    status: str | None = Query(default=None),
):
    items = await list_life_items(domain=domain, status=status)
    return [LifeItemResponse.model_validate(item) for item in items]


@router.post("/items", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def post_item(data: LifeItemCreate):
    item = await create_life_item(data)
    return LifeItemResponse.model_validate(item)


@router.put("/items/{item_id}", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def put_item(item_id: int, data: LifeItemUpdate):
    item = await update_life_item(item_id, data)
    if not item:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeItemResponse.model_validate(item)


@router.post("/items/{item_id}/snooze", response_model=LifeItemResponse, dependencies=[Depends(require_api_token)])
async def post_snooze_item(item_id: int, data: LifeItemSnoozeRequest):
    item = await snooze_life_item(
        item_id,
        due_at=data.due_at,
        timezone_name=data.timezone,
        source=data.source,
        note=data.note,
    )
    if not item:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeItemResponse.model_validate(item)


@router.post(
    "/items/{item_id}/checkin",
    response_model=LifeCheckinResponse,
    dependencies=[Depends(require_api_token)],
)
async def post_checkin(item_id: int, data: LifeCheckinCreate):
    checkin, item = await add_checkin(item_id, data)
    if not checkin:
        raise HTTPException(status_code=404, detail="Life item not found")
    return LifeCheckinResponse.model_validate(checkin)


@router.post("/daily-log", response_model=DailyLogResponse, dependencies=[Depends(require_api_token)])
async def post_daily_log(data: DailyLogCreate):
    try:
        result = await log_daily_signal(data)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return DailyLogResponse(
        kind=result["kind"],
        message=result["message"],
        scorecard=DailyScorecardResponse.model_validate(result["scorecard"]),
        rescue_plan=RescuePlanResponse.model_validate(result["rescue_plan"]),
        sleep_protocol=SleepProtocolResponse.model_validate(result["sleep_protocol"]) if result.get("sleep_protocol") else None,
        streaks=result.get("streaks") or [],
        trend_summary=result.get("trend_summary"),
    )


@router.get("/today", response_model=TodayAgendaResponse, dependencies=[Depends(require_api_token)])
async def get_today():
    agenda = await get_today_agenda()
    return TodayAgendaResponse(
        timezone=agenda["timezone"],
        now=agenda["now"],
        top_focus=[LifeItemResponse.model_validate(item) for item in agenda["top_focus"]],
        due_today=[LifeItemResponse.model_validate(item) for item in agenda["due_today"]],
        overdue=[LifeItemResponse.model_validate(item) for item in agenda["overdue"]],
        domain_summary=agenda["domain_summary"],
        intake_summary=agenda.get("intake_summary") or {},
        ready_intake=[IntakeEntryResponse.model_validate(item) for item in agenda.get("ready_intake") or []],
        scorecard=DailyScorecardResponse.model_validate(agenda["scorecard"]) if agenda.get("scorecard") else None,
        next_prayer=NextPrayerResponse.model_validate(agenda["next_prayer"]) if agenda.get("next_prayer") else None,
        rescue_plan=RescuePlanResponse.model_validate(agenda["rescue_plan"]) if agenda.get("rescue_plan") else None,
        sleep_protocol=SleepProtocolResponse.model_validate(agenda["sleep_protocol"]) if agenda.get("sleep_protocol") else None,
        streaks=agenda.get("streaks") or [],
        trend_summary=agenda.get("trend_summary"),
    )


@router.get(
    "/items/{item_id}/progress",
    response_model=GoalProgressResponse,
    dependencies=[Depends(require_api_token)],
)
async def get_item_progress(item_id: int):
    result = await get_goal_progress(item_id)
    if not result:
        raise HTTPException(status_code=404, detail="Life item not found")
    return GoalProgressResponse.model_validate(result)


@router.get("/inbox", response_model=list[IntakeEntryResponse], dependencies=[Depends(require_api_token)])
async def get_inbox(
    status: str | None = Query(default=None),
    session_id: int | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
):
    rows = await list_intake_entries(status=status, session_id=session_id, limit=limit)
    return [IntakeEntryResponse.model_validate(row) for row in rows]


@router.post("/inbox/capture", response_model=IntakeCaptureResponse, dependencies=[Depends(require_api_token)])
async def capture_inbox(data: IntakeCaptureRequest):
    message = (data.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_id = data.session_id
    if data.new_session:
        title = generate_title_from_prompts([message])
        session = await create_session(agent_name="intake-inbox", title=title)
        session_id = session.id

    result = await handle_message(
        agent_name="intake-inbox",
        user_message=message,
        approval_policy="never",
        source=data.source or "api",
        session_id=session_id,
        session_enabled=True,
    )
    if result.get("error_code") == "session_not_found":
        raise HTTPException(status_code=404, detail=result["response"])
    if result.get("error_code") == "memory_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])

    entry = None
    if result.get("session_id"):
        entry = await get_latest_intake_entry_for_session(
            result["session_id"],
            source_agent="intake-inbox",
        )

    return IntakeCaptureResponse(
        response=result["response"],
        session_id=result.get("session_id"),
        session_title=result.get("session_title"),
        entry=IntakeEntryResponse.model_validate(entry) if entry else None,
    )


@router.post("/commitments/capture", response_model=CommitmentCaptureResponse, dependencies=[Depends(require_api_token)])
async def capture_commitment(data: CommitmentCaptureRequest):
    message = (data.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="Message is required")

    session_id = data.session_id
    if data.new_session:
        title = generate_title_from_prompts([message])
        session = await create_session(agent_name=COMMITMENT_AGENT_NAME, title=title)
        session_id = session.id

    result = await handle_message(
        agent_name=COMMITMENT_AGENT_NAME,
        user_message=message,
        approval_policy="never",
        source=data.source or "api",
        session_id=session_id,
        session_enabled=True,
    )
    if result.get("error_code") == "session_not_found":
        raise HTTPException(status_code=404, detail=result["response"])
    if result.get("error_code") == "memory_unavailable":
        raise HTTPException(status_code=503, detail=result["response"])

    entry = None
    if result.get("session_id"):
        entry = await get_latest_intake_entry_for_session(
            result["session_id"],
            source_agent=COMMITMENT_AGENT_NAME,
        )

    life_item = None
    follow_up_job = None
    auto_promoted = False
    effective_timezone = await get_commitment_timezone(data.timezone)
    if entry and entry.linked_life_item_id:
        if data.due_at is not None:
            await update_life_item(
                entry.linked_life_item_id,
                LifeItemUpdate(due_at=data.due_at, status="open"),
            )
        async with async_session() as db:
            item_result = await db.execute(select(LifeItem).where(LifeItem.id == entry.linked_life_item_id))
            life_item = item_result.scalar_one_or_none()
        if life_item:
            follow_up_job = await upsert_follow_up_job(
                life_item.id,
                timezone_name=effective_timezone,
                target_channel=data.target_channel,
                target_channel_id=data.target_channel_id,
            )
            async with async_session() as db:
                refreshed = await db.execute(select(LifeItem).where(LifeItem.id == life_item.id))
                life_item = refreshed.scalar_one_or_none()
    elif entry and _should_promote_commitment_entry(entry, due_at=data.due_at):
        overrides = {}
        if data.due_at is not None:
            overrides["due_at"] = data.due_at
        entry, life_item = await promote_intake_entry(entry.id, overrides=overrides)
        auto_promoted = bool(life_item)
        if life_item:
            follow_up_job = await upsert_follow_up_job(
                life_item.id,
                timezone_name=effective_timezone,
                target_channel=data.target_channel,
                target_channel_id=data.target_channel_id,
            )
            async with async_session() as db:
                refreshed = await db.execute(select(LifeItem).where(LifeItem.id == life_item.id))
                life_item = refreshed.scalar_one_or_none()

    needs_follow_up = bool(entry and entry.status == "clarifying")
    return CommitmentCaptureResponse(
        response=result["response"],
        session_id=result.get("session_id"),
        session_title=result.get("session_title"),
        entry=IntakeEntryResponse.model_validate(entry) if entry else None,
        life_item=LifeItemResponse.model_validate(life_item) if life_item else None,
        follow_up_job=ScheduledJobResponse.model_validate(follow_up_job) if follow_up_job else None,
        auto_promoted=auto_promoted,
        needs_follow_up=needs_follow_up,
    )


@router.get("/inbox/{entry_id}", response_model=IntakeEntryResponse, dependencies=[Depends(require_api_token)])
async def get_inbox_entry(entry_id: int):
    entry = await get_intake_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakeEntryResponse.model_validate(entry)


@router.put("/inbox/{entry_id}", response_model=IntakeEntryResponse, dependencies=[Depends(require_api_token)])
async def put_inbox_entry(entry_id: int, data: IntakeEntryUpdate):
    entry = await update_intake_entry(entry_id, data)
    if not entry:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakeEntryResponse.model_validate(entry)


@router.post(
    "/inbox/{entry_id}/promote",
    response_model=IntakePromoteResponse,
    dependencies=[Depends(require_api_token)],
)
async def promote_inbox_entry(entry_id: int, data: IntakePromoteRequest):
    entry, item = await promote_intake_entry(entry_id, overrides=data.model_dump(exclude_unset=True))
    if not entry or not item:
        raise HTTPException(status_code=404, detail="Inbox entry not found")
    return IntakePromoteResponse(
        entry=IntakeEntryResponse.model_validate(entry),
        life_item=LifeItemResponse.model_validate(item),
    )


@router.get("/coach/daily-focus", response_model=DailyFocusCoachResponse, dependencies=[Depends(require_api_token)])
async def get_daily_focus():
    return DailyFocusCoachResponse.model_validate(await get_daily_focus_coach())


@router.get("/coach/weekly-review", response_model=WeeklyCommitmentReviewResponse, dependencies=[Depends(require_api_token)])
async def get_weekly_review():
    return WeeklyCommitmentReviewResponse.model_validate(await get_weekly_commitment_review())
