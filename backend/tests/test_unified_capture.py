from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.database import async_session
from app.models import CaptureCorrection, CaptureItemPlan, CapturePlan, LifeItem, RawCapture, ScheduledJob, SharedMemoryProposal, UnifiedCaptureRequest
from app.routers.life import capture_life

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "capture_uat_transcripts.json").read_text(encoding="utf-8"))


def _plan_item(
    *,
    title: str,
    summary: str,
    user_intent: str,
    destination: str,
    domain: str,
    kind: str,
    source_span: str,
    due_at: str | None = None,
    due_expression: str | None = None,
    recurrence: str | None = None,
    should_schedule_reminder: bool = False,
    should_appear_in_focus: bool = False,
    needs_clarification: bool = False,
    questions: list[str] | None = None,
    confidence: float = 0.9,
    reasoning_summary: str = "",
    item_id: int | None = None,
) -> dict:
    payload = {
        "title": title,
        "summary": summary,
        "user_intent": user_intent,
        "destination": destination,
        "domain": domain,
        "kind": kind,
        "due_at": due_at,
        "due_expression": due_expression,
        "recurrence": recurrence,
        "should_schedule_reminder": should_schedule_reminder,
        "should_appear_in_focus": should_appear_in_focus,
        "needs_clarification": needs_clarification,
        "questions": questions or [],
        "confidence": confidence,
        "reasoning_summary": reasoning_summary,
        "source_span": source_span,
    }
    if item_id is not None:
        payload["id"] = item_id
    return payload


def _plan_doc(*items: dict, residue: list[str] | None = None, summary: str = "", confidence: float = 0.9) -> dict:
    return {
        "items": list(items),
        "uncaptured_residue": residue or [],
        "overall_confidence": confidence,
        "user_visible_summary": summary or f"Captured {len(items)} item(s).",
    }


def _critic_doc(final_plan: dict, *, approved: bool = True, issues: list[str] | None = None, summary: str = "") -> dict:
    return {
        "approved": approved,
        "issues": issues or [],
        "critic_summary": summary or "Looks good.",
        "final_plan": final_plan,
    }


def _json_reply(payload: dict) -> str:
    return json.dumps(payload)


async def _create_job(*, name: str, run_at: datetime | None = None) -> ScheduledJob:
    async with async_session() as db:
        row = ScheduledJob(
            name=name,
            description="capture reminder",
            agent_name="commitment-loop",
            job_type="life_follow_up",
            schedule_type="once",
            run_at=run_at,
            next_run_at=run_at,
            timezone="Africa/Casablanca",
            notification_mode="channel",
            source="capture-test",
            enabled=True,
            paused=False,
            approval_required=False,
            expect_reply=False,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _create_memory_proposal(payload) -> SharedMemoryProposal:
    async with async_session() as db:
        row = SharedMemoryProposal(
            source_agent=payload.agent_name,
            source_session_id=payload.session_id,
            scope=payload.scope,
            domain=payload.domain,
            title=payload.title,
            target_path=f"/vault/{payload.title.lower().replace(' ', '-')}.md",
            proposal_path=f"/vault/proposals/{payload.title.lower().replace(' ', '-')}.md",
            expected_checksum=None,
            current_checksum=None,
            source_uri=payload.source_uri,
            conflict_reason="review_required",
            status="pending",
            proposed_content=payload.content,
            note_metadata_json={},
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row


async def _fake_capture_meeting_summary(request):
    async with async_session() as db:
        event = SimpleNamespace(
            id=901,
            event_type="meeting_note",
            source=request.source,
            source_agent=request.source_agent,
            source_session_id=request.session_id,
            job_id=None,
            job_run_id=None,
            life_item_id=None,
            discord_channel_id=None,
            discord_message_id=None,
            discord_reply_message_id=None,
            discord_user_id=None,
            title=request.title,
            summary=request.summary,
            raw_text=request.summary,
            domain=request.domain or "planning",
            status="new",
            metadata_json={},
            created_at=datetime.now(timezone.utc),
            curated_at=None,
        )
        proposal = await _create_memory_proposal(
            SimpleNamespace(
                agent_name="wiki-curator",
                session_id=request.session_id,
                scope="shared_domain",
                domain=request.domain or "planning",
                title=request.title or "Meeting note",
                source_uri="lifeos://context-event/901",
                content=request.summary,
            )
        )
        return event, [proposal], []


async def _log_daily_signal(payload):
    kind = payload.kind
    if kind == "sleep":
        return {"message": "Logged sleep.", "kind": kind}
    if kind == "meal":
        return {"message": "Logged meal.", "kind": kind}
    if kind == "hydration":
        return {"message": "Logged hydration.", "kind": kind}
    if kind == "training":
        return {"message": f"Logged training {payload.status}.", "kind": kind}
    return {"message": f"Logged {kind}.", "kind": kind}


async def _log_prayer_checkin(_payload):
    return {"prayer_name": "Asr", "status_raw": "on_time"}


def _install_shared_side_effects(monkeypatch: pytest.MonkeyPatch):
    async def _fake_upsert_follow_up_job(item_id: int, reminder_at=None, **_kwargs):
        return await _create_job(name=f"Follow up item {item_id}", run_at=reminder_at)

    async def _fake_today_schedule():
        return {"date": "2026-04-28"}

    monkeypatch.setattr("app.services.capture_agentic.upsert_follow_up_job", _fake_upsert_follow_up_job)
    monkeypatch.setattr("app.services.capture_agentic.create_shared_memory_review_proposal", _create_memory_proposal)
    monkeypatch.setattr("app.services.capture_agentic.capture_meeting_summary", _fake_capture_meeting_summary)
    monkeypatch.setattr("app.services.capture_agentic.log_daily_signal", _log_daily_signal)
    monkeypatch.setattr("app.services.capture_agentic.get_today_schedule", _fake_today_schedule)
    monkeypatch.setattr("app.services.capture_agentic.log_prayer_checkin_retroactive", _log_prayer_checkin)


def _queue_llm(monkeypatch: pytest.MonkeyPatch, *responses: str):
    calls = {"prompts": []}
    queue = list(responses)

    async def _fake_chat_completion(messages, **_kwargs):
        calls["prompts"].append(messages[-1]["content"])
        if not queue:
            raise AssertionError("LLM queue exhausted")
        return queue.pop(0)

    monkeypatch.setattr("app.services.capture_agentic.chat_completion", _fake_chat_completion)
    return calls


async def _raw_capture_count() -> int:
    async with async_session() as db:
        result = await db.execute(select(RawCapture))
        return len(list(result.scalars().all()))


async def _latest_capture_plan() -> CapturePlan:
    async with async_session() as db:
        result = await db.execute(select(CapturePlan).order_by(CapturePlan.id.desc()))
        return result.scalars().first()


@pytest.mark.asyncio
async def test_promise_memory_habit_transcript_plans_three_items(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    planner = _plan_doc(
        _plan_item(
            title="Send the client invoice",
            summary="User promised to send the invoice tomorrow morning.",
            user_intent="commitment",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="tomorrow at 9am",
            should_schedule_reminder=True,
            should_appear_in_focus=True,
            source_span="I promised to send the client invoice tomorrow at 9am",
            reasoning_summary="Explicit promise with timing.",
        ),
        _plan_item(
            title="Client calls after Asr",
            summary="User prefers client calls after Asr.",
            user_intent="memory",
            destination="memory_review",
            domain="work",
            kind="preference",
            source_span="remember that I prefer client calls after Asr",
            reasoning_summary="Durable preference.",
        ),
        _plan_item(
            title="Nightly sleep routine",
            summary="User wants a stable nightly sleep routine again.",
            user_intent="habit",
            destination="life_item",
            domain="health",
            kind="habit",
            recurrence="nightly",
            should_appear_in_focus=False,
            source_span="I want a nightly sleep routine again",
            reasoning_summary="Habit to track.",
        ),
        summary="Captured 3 items: one promise, one memory, one habit.",
    )
    _queue_llm(monkeypatch, _json_reply(planner), _json_reply(_critic_doc(planner)))

    result = await capture_life(
        UnifiedCaptureRequest(message=FIXTURES["promise_memory_habit"], source="discord_capture", timezone="UTC")
    )

    assert result.route == "batch"
    assert result.raw_capture_id is not None
    assert result.capture_plan_id is not None
    assert [(item.user_intent, item.destination) for item in result.capture_plan.items] == [
        ("commitment", "life_item"),
        ("memory", "memory_review"),
        ("habit", "life_item"),
    ]
    assert len(result.captured_items) == 3
    assert len(result.life_items) == 2
    assert len(result.wiki_proposals) == 1
    assert result.follow_up_job is not None
    assert await _raw_capture_count() == 1
    plan_row = await _latest_capture_plan()
    assert plan_row.raw_capture_id == result.raw_capture_id


@pytest.mark.asyncio
async def test_reminder_wording_creates_scheduled_job(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    plan = _plan_doc(
        _plan_item(
            title="Submit tax return request",
            summary="Submit the HR request before Monday 4:30pm.",
            user_intent="reminder",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="Monday before 4:30pm",
            should_schedule_reminder=True,
            should_appear_in_focus=True,
            source_span=FIXTURES["reminder_wording"],
            reasoning_summary="Reminder with future deadline.",
        ),
        summary="Captured 1 reminder.",
    )
    _queue_llm(monkeypatch, _json_reply(plan), _json_reply(_critic_doc(plan)))

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["reminder_wording"], source="discord_capture"))

    assert result.capture_plan.items[0].user_intent == "reminder"
    assert result.capture_plan.items[0].destination == "life_item"
    assert result.follow_up_job is not None
    assert result.routed_results[0].status == "tracked"


@pytest.mark.asyncio
async def test_remember_that_transcript_creates_memory_review(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    plan = _plan_doc(
        _plan_item(
            title="Morning sunlight helps energy",
            summary="Morning sunlight resets user energy.",
            user_intent="memory",
            destination="memory_review",
            domain="health",
            kind="preference",
            source_span=FIXTURES["remember_that"],
            reasoning_summary="Durable user context.",
        ),
        summary="Captured 1 memory candidate.",
    )
    _queue_llm(monkeypatch, _json_reply(plan), _json_reply(_critic_doc(plan)))

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["remember_that"], source="discord_capture"))

    assert [(item.user_intent, item.destination) for item in result.capture_plan.items] == [("memory", "memory_review")]
    assert result.life_items == []
    assert len(result.wiki_proposals) == 1


@pytest.mark.asyncio
async def test_daily_log_bundle_updates_checkins(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    plan = _plan_doc(
        _plan_item(
            title="Sleep log",
            summary="User slept 7h with bedtime and wake time.",
            user_intent="daily_log",
            destination="daily_log",
            domain="health",
            kind="sleep",
            source_span="slept 7h bedtime 23:40 wake 07:10",
        ),
        _plan_item(
            title="Meal log",
            summary="Meal completed.",
            user_intent="daily_log",
            destination="daily_log",
            domain="health",
            kind="meal",
            source_span="meal done",
        ),
        _plan_item(
            title="Training log",
            summary="Training completed.",
            user_intent="daily_log",
            destination="daily_log",
            domain="health",
            kind="training",
            source_span="training done",
        ),
        _plan_item(
            title="Prayer log",
            summary="Asr prayed on time.",
            user_intent="daily_log",
            destination="daily_log",
            domain="deen",
            kind="prayer",
            source_span="prayed Asr on time",
        ),
        summary="Captured 4 daily logs.",
    )
    _queue_llm(monkeypatch, _json_reply(plan), _json_reply(_critic_doc(plan)))

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["daily_log_bundle"], source="discord_capture"))

    assert [item.destination for item in result.capture_plan.items] == ["daily_log", "daily_log", "daily_log", "daily_log"]
    assert any(signal == "sleep" for signal in result.logged_signals)
    assert any(signal == "meal" for signal in result.logged_signals)
    assert any(signal == "training:done" for signal in result.logged_signals)
    assert any(signal == "prayer:asr:on_time" for signal in result.logged_signals)


@pytest.mark.asyncio
async def test_ambiguous_item_keeps_raw_capture_and_asks_follow_up(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    plan = _plan_doc(
        _plan_item(
            title="Admin thing with HR",
            summary="User mentioned an admin issue with vague timing.",
            user_intent="idea",
            destination="needs_answer",
            domain="work",
            kind="task",
            source_span=FIXTURES["ambiguous_item"],
            needs_clarification=True,
            questions=["What exact HR admin issue should LifeOS track, and by when?"],
            confidence=0.42,
            reasoning_summary="Meaningful but unclear.",
        ),
        summary="Captured raw message and held it for clarification.",
        confidence=0.42,
    )
    _queue_llm(monkeypatch, _json_reply(plan), _json_reply(_critic_doc(plan)))

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["ambiguous_item"], source="discord_capture"))

    assert result.raw_capture_id is not None
    assert result.needs_answer_count == 1
    assert result.capture_plan.items[0].destination == "needs_answer"
    assert result.entries[0].status == "clarifying"
    assert "What exact HR admin issue" in result.capture_plan.items[0].questions[0]
    async with async_session() as db:
        stored = await db.get(RawCapture, result.raw_capture_id)
    assert stored is not None
    assert stored.raw_text == FIXTURES["ambiguous_item"]


@pytest.mark.asyncio
async def test_mixed_message_does_not_silently_drop_meaningful_residue(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    plan = _plan_doc(
        _plan_item(
            title="Call Sam",
            summary="Call Sam tomorrow at 11.",
            user_intent="reminder",
            destination="life_item",
            domain="family",
            kind="task",
            due_expression="tomorrow at 11",
            should_schedule_reminder=True,
            should_appear_in_focus=True,
            source_span="remind me to call Sam tomorrow at 11",
        ),
        _plan_item(
            title="Sam hates voice notes",
            summary="Remember Sam dislikes voice notes.",
            user_intent="memory",
            destination="memory_review",
            domain="family",
            kind="preference",
            source_span="remember that he hates voice notes",
        ),
        residue=["there was also that weird landlord paperwork issue"],
        summary="Captured 2 items and left one residue fragment.",
    )
    _queue_llm(monkeypatch, _json_reply(plan), _json_reply(_critic_doc(plan)))

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["residue_guard"], source="discord_capture"))

    assert "landlord paperwork issue" in result.uncaptured_residue[0]
    assert result.capture_plan.uncaptured_residue == result.uncaptured_residue


@pytest.mark.asyncio
async def test_correction_memory_not_task_updates_state_and_saves_lesson(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    initial_plan = _plan_doc(
        _plan_item(
            title="Morning sunlight energy task",
            summary="Track morning sunlight as a task.",
            user_intent="task",
            destination="life_item",
            domain="health",
            kind="task",
            should_appear_in_focus=False,
            source_span=FIXTURES["remember_that"],
            reasoning_summary="Planner mistake for test.",
        ),
        summary="Captured 1 task.",
    )
    correction_plan = _plan_doc(
        _plan_item(
            title="Morning sunlight helps energy",
            summary="Durable user context about energy reset.",
            user_intent="memory",
            destination="memory_review",
            domain="health",
            kind="preference",
            source_span=FIXTURES["remember_that"],
            reasoning_summary="User correction says this is memory.",
            item_id=1,
        ),
        summary="Moved captured item into memory review.",
    )
    _queue_llm(
        monkeypatch,
        _json_reply(initial_plan),
        _json_reply(_critic_doc(initial_plan)),
        _json_reply(
            {
                "mode": "correction",
                "target_item_ids": [1],
                "lesson": "When the user says remember that and shares durable context, store memory not task.",
                "corrected_plan": correction_plan,
            }
        ),
    )

    first = await capture_life(UnifiedCaptureRequest(message=FIXTURES["remember_that"], source="discord_capture"))
    second = await capture_life(
        UnifiedCaptureRequest(
            message="no, that is memory not task",
            session_id=first.session_id,
            new_session=False,
            source="discord_capture_followup",
        )
    )

    assert second.route == "correction"
    assert second.capture_plan.items[0].destination == "memory_review"
    assert len(second.corrections) == 1
    async with async_session() as db:
        life_item = (await db.execute(select(LifeItem).order_by(LifeItem.id.asc()))).scalars().first()
        corrections = (await db.execute(select(CaptureCorrection))).scalars().all()
    assert life_item.status == "archived"
    assert len(corrections) == 1


@pytest.mark.asyncio
async def test_correction_make_it_a_reminder_creates_follow_up_job(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    initial_plan = _plan_doc(
        _plan_item(
            title="Pay contractor invoice",
            summary="Pay the contractor invoice tomorrow morning.",
            user_intent="task",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="tomorrow at 11am",
            source_span=FIXTURES["task_with_due"],
        ),
        summary="Captured 1 task.",
    )
    correction_plan = _plan_doc(
        _plan_item(
            title="Pay contractor invoice",
            summary="Reminder to pay the contractor invoice tomorrow morning.",
            user_intent="reminder",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="tomorrow at 11am",
            should_schedule_reminder=True,
            should_appear_in_focus=True,
            source_span=FIXTURES["task_with_due"],
            item_id=1,
        ),
        summary="Converted tracked task into reminder.",
    )
    _queue_llm(
        monkeypatch,
        _json_reply(initial_plan),
        _json_reply(_critic_doc(initial_plan)),
        _json_reply(
            {
                "mode": "correction",
                "target_item_ids": [1],
                "lesson": "If the user says make it a reminder, schedule follow-up on the tracked item.",
                "corrected_plan": correction_plan,
            }
        ),
    )

    first = await capture_life(UnifiedCaptureRequest(message=FIXTURES["task_with_due"], source="discord_capture"))
    second = await capture_life(
        UnifiedCaptureRequest(
            message="make it a reminder",
            session_id=first.session_id,
            new_session=False,
            source="discord_capture_followup",
        )
    )

    assert second.follow_up_job is not None
    assert second.life_items[0].id == first.life_items[0].id
    assert second.capture_plan.items[0].user_intent == "reminder"


@pytest.mark.asyncio
async def test_correction_dont_put_this_in_focus_updates_existing_item(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    initial_plan = _plan_doc(
        _plan_item(
            title="Finish deployment checklist",
            summary="Finish the checklist today before lunch.",
            user_intent="task",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="today before lunch",
            should_appear_in_focus=True,
            source_span=FIXTURES["focus_item"],
        ),
        summary="Captured 1 focus item.",
    )
    correction_plan = _plan_doc(
        _plan_item(
            title="Finish deployment checklist",
            summary="Finish the checklist today before lunch.",
            user_intent="task",
            destination="life_item",
            domain="work",
            kind="task",
            due_expression="today before lunch",
            should_appear_in_focus=False,
            source_span=FIXTURES["focus_item"],
            item_id=1,
        ),
        summary="Removed this item from focus.",
    )
    _queue_llm(
        monkeypatch,
        _json_reply(initial_plan),
        _json_reply(_critic_doc(initial_plan)),
        _json_reply(
            {
                "mode": "correction",
                "target_item_ids": [1],
                "lesson": "Do not keep corrected item in focus when user says so.",
                "corrected_plan": correction_plan,
            }
        ),
    )

    first = await capture_life(UnifiedCaptureRequest(message=FIXTURES["focus_item"], source="discord_capture"))
    second = await capture_life(
        UnifiedCaptureRequest(
            message="don't put this in focus",
            session_id=first.session_id,
            new_session=False,
            source="discord_capture_followup",
        )
    )

    assert second.life_items[0].id == first.life_items[0].id
    async with async_session() as db:
        stored = await db.get(LifeItem, first.life_items[0].id)
    assert stored.focus_eligible is False


@pytest.mark.asyncio
async def test_correction_forget_archives_item(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    initial_plan = _plan_doc(
        _plan_item(
            title="Book the visa appointment",
            summary="Book the visa appointment this week.",
            user_intent="task",
            destination="life_item",
            domain="planning",
            kind="task",
            should_appear_in_focus=True,
            source_span=FIXTURES["task_to_forget"],
        ),
        summary="Captured 1 task.",
    )
    correction_plan = _plan_doc(
        _plan_item(
            title="Book the visa appointment",
            summary="User no longer wants this tracked.",
            user_intent="correction",
            destination="no_action",
            domain="planning",
            kind="task",
            source_span=FIXTURES["task_to_forget"],
            item_id=1,
        ),
        summary="Archived captured item.",
    )
    _queue_llm(
        monkeypatch,
        _json_reply(initial_plan),
        _json_reply(_critic_doc(initial_plan)),
        _json_reply(
            {
                "mode": "correction",
                "target_item_ids": [1],
                "lesson": "When user says forget this, archive the tracked item.",
                "corrected_plan": correction_plan,
            }
        ),
    )

    first = await capture_life(UnifiedCaptureRequest(message=FIXTURES["task_to_forget"], source="discord_capture"))
    second = await capture_life(
        UnifiedCaptureRequest(
            message="forget this",
            session_id=first.session_id,
            new_session=False,
            source="discord_capture_followup",
        )
    )

    assert second.routed_results[0].destination == "no_action"
    async with async_session() as db:
        stored = await db.get(LifeItem, first.life_items[0].id)
    assert stored.status == "archived"


@pytest.mark.asyncio
async def test_prior_correction_lessons_feed_future_planning(monkeypatch):
    _install_shared_side_effects(monkeypatch)
    async with async_session() as db:
        raw = RawCapture(raw_text="remember that I prefer sunlight", source="discord_capture", session_id=None, status="processed")
        db.add(raw)
        await db.flush()
        plan = CapturePlan(raw_capture_id=raw.id, planner_model="test", critic_model="test", plan_json={}, critic_json={}, final_plan_json={}, confidence=0.8, status="corrected")
        db.add(plan)
        await db.flush()
        item = CaptureItemPlan(
            capture_plan_id=plan.id,
            title="Sunlight preference",
            summary="User prefers sunlight in the morning.",
            user_intent="task",
            destination="life_item",
            domain="health",
            kind="task",
            should_schedule_reminder=False,
            should_appear_in_focus=False,
            needs_clarification=False,
            questions_json=[],
            confidence=0.7,
            reasoning_summary="wrong for test",
            source_span="remember that I prefer sunlight",
            execution_status="tracked",
        )
        db.add(item)
        await db.flush()
        db.add(
            CaptureCorrection(
                raw_capture_id=raw.id,
                capture_item_plan_id=item.id,
                user_correction_text="no, that is memory not task",
                previous_plan_json={"items": [{"destination": "life_item", "user_intent": "task"}]},
                corrected_plan_json={"items": [{"destination": "memory_review", "user_intent": "memory"}]},
                lesson="When the user says remember that and shares durable context, store memory not task.",
            )
        )
        await db.commit()

    plan = _plan_doc(
        _plan_item(
            title="Morning sunlight helps energy",
            summary="Durable user context about energy reset.",
            user_intent="memory",
            destination="memory_review",
            domain="health",
            kind="preference",
            source_span=FIXTURES["remember_that"],
        ),
        summary="Captured 1 memory candidate.",
    )
    seen = {"planner_prompt": ""}

    async def _fake_chat_completion(messages, **_kwargs):
        prompt = messages[-1]["content"]
        if "LifeOS AI Capture Planner" in prompt:
            seen["planner_prompt"] = prompt
            return _json_reply(plan)
        return _json_reply(_critic_doc(plan))

    monkeypatch.setattr("app.services.capture_agentic.chat_completion", _fake_chat_completion)

    result = await capture_life(UnifiedCaptureRequest(message=FIXTURES["remember_that"], source="discord_capture"))

    assert "store memory not task" in seen["planner_prompt"]
    assert result.capture_plan.items[0].destination == "memory_review"
