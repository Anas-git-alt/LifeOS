"""Minimal API integration tests for settings + jobs."""

from uuid import uuid4

from fastapi.testclient import TestClient

from app.config import settings
from app.main import app


def _headers() -> dict:
    return {"X-LifeOS-Token": settings.api_secret_key}


def test_settings_and_jobs_api_flow():
    with TestClient(app) as client:
        settings_resp = client.get("/api/settings/", headers=_headers())
        assert settings_resp.status_code == 200
        baseline = settings_resp.json()
        assert "data_start_date" in baseline

        update_resp = client.put(
            "/api/settings/",
            headers=_headers(),
            json={"data_start_date": "2026-03-02", "default_timezone": "Africa/Casablanca"},
        )
        assert update_resp.status_code == 200
        assert update_resp.json()["data_start_date"] == "2026-03-02"

        job_name = f"test-job-{uuid4().hex[:8]}"
        create_resp = client.post(
            "/api/jobs/",
            headers=_headers(),
            json={
                "name": job_name,
                "description": "Integration test job description",
                "agent_name": "sandbox",
                "cron_expression": "30 7 mon-fri",
                "timezone": "Africa/Casablanca",
                "target_channel": "sandbox",
                "prompt_template": "Remind me to stretch.",
                "source": "integration_test",
                "created_by": "pytest",
            },
        )
        assert create_resp.status_code == 200
        job = create_resp.json()
        assert job["name"] == job_name
        assert "description" in job
        assert job["cron_expression"] == "30 7 * * mon-fri"
        assert job["agent_name"] == "sandbox"
        job_id = int(job["id"])

        list_resp = client.get("/api/jobs/?agent_name=sandbox", headers=_headers())
        assert list_resp.status_code == 200
        assert any(int(row["id"]) == job_id for row in list_resp.json())

        pause_resp = client.post(f"/api/jobs/{job_id}/pause", headers=_headers())
        assert pause_resp.status_code == 200
        assert pause_resp.json()["paused"] is True

        resume_resp = client.post(f"/api/jobs/{job_id}/resume", headers=_headers())
        assert resume_resp.status_code == 200
        assert resume_resp.json()["paused"] is False

        runs_resp = client.get(f"/api/jobs/{job_id}/runs", headers=_headers())
        assert runs_resp.status_code == 200
        assert isinstance(runs_resp.json(), list)

        delete_resp = client.delete(f"/api/jobs/{job_id}", headers=_headers())
        assert delete_resp.status_code == 200

        missing_resp = client.get(f"/api/jobs/{job_id}", headers=_headers())
        assert missing_resp.status_code == 404


def test_data_start_date_filters_goal_progress_checkins():
    with TestClient(app) as client:
        item_resp = client.post(
            "/api/life/items",
            headers=_headers(),
            json={"domain": "planning", "title": f"Filter test {uuid4().hex[:6]}", "kind": "goal"},
        )
        assert item_resp.status_code == 200
        item_id = int(item_resp.json()["id"])

        checkin_resp = client.post(
            f"/api/life/items/{item_id}/checkin",
            headers=_headers(),
            json={"result": "done", "note": "integration checkin"},
        )
        assert checkin_resp.status_code == 200

        settings_resp = client.put(
            "/api/settings/",
            headers=_headers(),
            json={"data_start_date": "2099-01-01"},
        )
        assert settings_resp.status_code == 200

        progress_resp = client.get(f"/api/life/items/{item_id}/progress", headers=_headers())
        assert progress_resp.status_code == 200
        payload = progress_resp.json()
        assert payload["checkin_count"] == 0

        restore_resp = client.put(
            "/api/settings/",
            headers=_headers(),
            json={"data_start_date": "2026-03-02"},
        )
        assert restore_resp.status_code == 200
