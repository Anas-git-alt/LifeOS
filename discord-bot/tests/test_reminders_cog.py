import pytest

from bot.cogs.reminders import RemindersCog


class _Ctx:
    def __init__(self):
        self.sent_messages: list[str] = []

    async def send(self, message: str):
        self.sent_messages.append(message)


@pytest.fixture
def cog(monkeypatch):
    cog = RemindersCog.__new__(RemindersCog)
    cog.bot = object()
    cog.owner_ids = set()
    return cog


@pytest.mark.asyncio
async def test_sleep_quick_log_posts_daily_log(monkeypatch, cog):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"message": "Logged sleep. Meals 0 | water 0 | train unset | priorities 0 | rescue watch"}

    monkeypatch.setattr("bot.cogs.reminders.api_post", _fake_api_post)
    ctx = _Ctx()

    await cog.log_sleep_quick.callback(cog, ctx, details="7.5 bed 23:30 wake 07:10 slept better")

    assert calls == [
        (
            "/life/daily-log",
            {
                "kind": "sleep",
                "hours": 7.5,
                "bedtime": "23:30",
                "wake_time": "07:10",
                "note": "slept better",
            },
        )
    ]
    assert "Logged sleep." in ctx.sent_messages[-1]


@pytest.mark.asyncio
async def test_meal_quick_log_infers_protein(monkeypatch, cog):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"message": "Logged meal. Meals 2 | water 0 | train unset | priorities 0 | rescue watch"}

    monkeypatch.setattr("bot.cogs.reminders.api_post", _fake_api_post)
    ctx = _Ctx()

    await cog.log_meal_quick.callback(cog, ctx, details="2 protein shake")

    assert calls == [
        (
            "/life/daily-log",
            {"kind": "meal", "count": 2, "note": "protein shake", "protein_hit": True},
        )
    ]
    assert "Logged meal." in ctx.sent_messages[-1]


@pytest.mark.asyncio
async def test_training_quick_log_parses_status(monkeypatch, cog):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"message": "Logged training. Meals 0 | water 0 | train rest | priorities 0 | rescue watch"}

    monkeypatch.setattr("bot.cogs.reminders.api_post", _fake_api_post)
    ctx = _Ctx()

    await cog.log_training_quick.callback(cog, ctx, details="rest sore today")

    assert calls == [
        (
            "/life/daily-log",
            {"kind": "training", "status": "rest", "note": "sore today"},
        )
    ]
    assert "train rest" in ctx.sent_messages[-1]


@pytest.mark.asyncio
async def test_water_and_shutdown_quick_logs(monkeypatch, cog):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"message": f"Logged {payload['kind']}. Meals 0 | water 2 | train unset | priorities 0 | rescue watch"}

    monkeypatch.setattr("bot.cogs.reminders.api_post", _fake_api_post)
    ctx = _Ctx()

    await cog.log_water_quick.callback(cog, ctx, details="2 after walk")
    await cog.log_shutdown_quick.callback(cog, ctx, note="tomorrow planned")

    assert calls == [
        (
            "/life/daily-log",
            {"kind": "hydration", "count": 2, "note": "after walk"},
        ),
        (
            "/life/daily-log",
            {"kind": "shutdown", "done": True, "note": "tomorrow planned"},
        ),
    ]
    assert "Logged hydration." in ctx.sent_messages[0]
    assert "Logged shutdown." in ctx.sent_messages[1]


@pytest.mark.asyncio
async def test_family_and_priority_quick_logs(monkeypatch, cog):
    calls = []

    async def _fake_api_post(path: str, payload: dict):
        calls.append((path, payload))
        return {"message": f"Logged {payload['kind']}. Meals 0 | water 0 | train unset | priorities 1 | rescue ok"}

    monkeypatch.setattr("bot.cogs.reminders.api_post", _fake_api_post)
    ctx = _Ctx()

    await cog.log_family_quick.callback(cog, ctx, note="called parents")
    await cog.log_priority_quick.callback(cog, ctx, note="shipped invoice")

    assert calls == [
        (
            "/life/daily-log",
            {"kind": "family", "done": True, "note": "called parents"},
        ),
        (
            "/life/daily-log",
            {"kind": "priority", "count": 1, "note": "shipped invoice"},
        ),
    ]
    assert "Logged family." in ctx.sent_messages[0]
    assert "Logged priority." in ctx.sent_messages[1]
