"""Minimal OpenViking HTTP client for LifeOS."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

_AGENT_SLUG_RE = re.compile(r"[^A-Za-z0-9_-]+")
_MAX_SESSION_ARCHIVE_SCAN = 512


def _agent_slug(agent_name: str | None) -> str:
    value = (agent_name or "default").strip() or "default"
    return _AGENT_SLUG_RE.sub("-", value)


def build_session_key(agent_name: str, session_id: int | str) -> str:
    return f"lifeos:{_agent_slug(agent_name)}:{session_id}"


def build_session_root_uri(agent_name: str, session_id: int | str) -> str:
    return f"viking://session/{settings.openviking_user}/{build_session_key(agent_name, session_id)}"


def build_session_messages_uri(agent_name: str, session_id: int | str) -> str:
    return f"{build_session_root_uri(agent_name, session_id)}/messages.jsonl"


def build_session_summary_uri(agent_name: str, session_id: int | str) -> str:
    return f"{build_session_root_uri(agent_name, session_id)}/.lifeos-session-summary.md"


def build_session_archive_messages_uri(agent_name: str, session_id: int | str, archive_index: int) -> str:
    return f"{build_session_root_uri(agent_name, session_id)}/history/archive_{archive_index:03d}/messages.jsonl"


def build_session_archive_root_uri(agent_name: str, session_id: int | str, archive_index: int) -> str:
    return f"{build_session_root_uri(agent_name, session_id)}/history/archive_{archive_index:03d}"


def _is_not_found_error(exc: OpenVikingApiError) -> bool:
    return exc.status_code == 404 or (exc.code or "").upper() == "NOT_FOUND"


def _parse_session_message_lines(content: str, agent_name: str, session_id: int | str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for line in str(content).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Skipping malformed OpenViking session line for %s/%s", agent_name, session_id)
            continue
        if isinstance(payload, dict):
            messages.append(payload)
    return messages


def _message_sort_key(payload: dict[str, Any], ordinal: int) -> tuple[datetime, int]:
    raw_timestamp = str(payload.get("created_at") or "").strip()
    if raw_timestamp:
        normalized = raw_timestamp.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed, ordinal
        except Exception:
            pass
    return datetime.min.replace(tzinfo=timezone.utc), ordinal


@dataclass(slots=True)
class OpenVikingSearchResult:
    memories: list[dict[str, Any]]
    resources: list[dict[str, Any]]
    skills: list[dict[str, Any]]


class OpenVikingApiError(RuntimeError):
    """Raised when the OpenViking HTTP API returns an error."""

    def __init__(self, message: str, *, code: str | None = None, status_code: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class OpenVikingUnavailableError(RuntimeError):
    """Raised when LifeOS cannot rely on OpenViking for required operations."""


class OpenVikingClient:
    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=settings.openviking_base_url.rstrip("/"),
                timeout=httpx.Timeout(30.0, connect=5.0),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _headers(self, agent_name: str | None = None) -> dict[str, str]:
        headers = {
            "X-OpenViking-Account": settings.openviking_account,
            "X-OpenViking-User": settings.openviking_user,
        }
        if settings.effective_openviking_api_key:
            headers["X-API-Key"] = settings.effective_openviking_api_key
        if agent_name:
            headers["X-OpenViking-Agent"] = _agent_slug(agent_name)
        return headers

    async def _request(
        self,
        method: str,
        path: str,
        *,
        agent_name: str | None = None,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        client = await self._get_client()
        try:
            response = await client.request(
                method,
                path,
                headers=self._headers(agent_name),
                params=params,
                json=json_body,
            )
        except httpx.HTTPError as exc:
            raise OpenVikingUnavailableError(f"OpenViking request failed for {method} {path}: {exc}") from exc

        try:
            payload = response.json()
        except ValueError:
            payload = None

        if response.is_error:
            error = payload.get("error") if isinstance(payload, dict) else None
            raise OpenVikingApiError(
                (error or {}).get("message") or response.text or f"HTTP {response.status_code}",
                code=(error or {}).get("code"),
                status_code=response.status_code,
            )
        if isinstance(payload, dict) and payload.get("status") == "error":
            error = payload.get("error") or {}
            raise OpenVikingApiError(
                error.get("message") or "OpenViking API error",
                code=error.get("code"),
                status_code=response.status_code,
            )
        if isinstance(payload, dict) and "result" in payload:
            return payload.get("result")
        return payload

    async def health(self) -> dict[str, Any]:
        client = await self._get_client()
        try:
            response = await client.get("/health", headers=self._headers())
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise OpenVikingUnavailableError(f"OpenViking health check failed: {exc}") from exc

    async def validate_ready(self) -> dict[str, Any]:
        if not settings.effective_openviking_api_key:
            raise OpenVikingUnavailableError(
                "OpenViking requires OPENVIKING_API_KEY or a non-default API_SECRET_KEY."
            )
        health = await self.health()
        if not health.get("healthy", False):
            raise OpenVikingUnavailableError(f"OpenViking reported unhealthy status: {health}")
        try:
            # OpenViking can report healthy before its background processing
            # queue is fully ready. Treat a wait timeout as transient so the
            # backend can finish booting and retry later during normal usage.
            await self.wait_processed(timeout=0)
        except OpenVikingUnavailableError as exc:
            logger.warning("OpenViking wait_processed timed out during startup; continuing: %s", exc)
        return health

    async def add_message(self, agent_name: str, session_id: int | str, role: str, content: str) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/sessions/{build_session_key(agent_name, session_id)}/messages",
            agent_name=agent_name,
            json_body={"role": role, "content": content},
        )

    async def commit_session(
        self,
        agent_name: str,
        session_id: int | str,
        *,
        wait: bool = False,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"/api/v1/sessions/{build_session_key(agent_name, session_id)}/commit",
            agent_name=agent_name,
            params={"wait": str(wait).lower()},
            json_body={"telemetry": False},
        )

    async def search(
        self,
        agent_name: str,
        query: str,
        *,
        session_id: int | str | None = None,
        target_uri: str = "",
        limit: int = 6,
    ) -> OpenVikingSearchResult:
        result = await self._request(
            "POST",
            "/api/v1/search/search",
            agent_name=agent_name,
            json_body={
                "query": query,
                "target_uri": target_uri,
                "session_id": build_session_key(agent_name, session_id) if session_id is not None else None,
                "limit": limit,
            },
        )
        return OpenVikingSearchResult(
            memories=list((result or {}).get("memories") or []),
            resources=list((result or {}).get("resources") or []),
            skills=list((result or {}).get("skills") or []),
        )

    async def read_content(
        self,
        uri: str,
        *,
        agent_name: str | None = None,
        offset: int = 0,
        limit: int = -1,
    ) -> str:
        content = await self._request(
            "GET",
            "/api/v1/content/read",
            agent_name=agent_name,
            params={"uri": uri, "offset": offset, "limit": limit},
        )
        return str(content or "")

    async def write_content(
        self,
        uri: str,
        content: str,
        *,
        agent_name: str | None = None,
        mode: str = "replace",
        wait: bool = False,
        timeout: float | None = None,
    ) -> Any:
        return await self._request(
            "POST",
            "/api/v1/content/write",
            agent_name=agent_name,
            json_body={
                "uri": uri,
                "content": content,
                "mode": mode,
                "wait": wait,
                "timeout": timeout,
                "telemetry": False,
            },
        )

    async def repair_failed_session_archives(
        self,
        agent_name: str,
        session_id: int | str,
        *,
        max_archives: int = _MAX_SESSION_ARCHIVE_SCAN,
    ) -> list[dict[str, Any]]:
        repaired: list[dict[str, Any]] = []
        for archive_index in range(1, max_archives + 1):
            archive_uri = build_session_archive_root_uri(agent_name, session_id, archive_index)
            try:
                messages_content = await self.read_content(
                    f"{archive_uri}/messages.jsonl",
                    agent_name=agent_name,
                )
            except OpenVikingApiError as exc:
                if _is_not_found_error(exc):
                    break
                raise

            try:
                await self.read_content(f"{archive_uri}/.done", agent_name=agent_name)
                continue
            except OpenVikingApiError as exc:
                if not _is_not_found_error(exc):
                    raise

            try:
                failed_content = await self.read_content(
                    f"{archive_uri}/.failed.json",
                    agent_name=agent_name,
                )
            except OpenVikingApiError as exc:
                if _is_not_found_error(exc):
                    continue
                raise

            messages = _parse_session_message_lines(messages_content, agent_name, session_id)
            first_id = str((messages[0] if messages else {}).get("id") or "")
            last_id = str((messages[-1] if messages else {}).get("id") or "")
            done_payload = json.dumps(
                {
                    "starting_message_id": first_id,
                    "ending_message_id": last_id,
                    "recovered_by": "lifeos",
                    "recovered_at": datetime.now(timezone.utc).isoformat(),
                },
                ensure_ascii=False,
            )
            await self.write_content(
                f"{archive_uri}/.done",
                done_payload,
                agent_name=agent_name,
                wait=False,
            )
            try:
                await self.rm(f"{archive_uri}/.failed.json", recursive=False)
            except OpenVikingApiError as exc:
                if not _is_not_found_error(exc):
                    raise
            repaired.append(
                {
                    "archive_id": f"archive_{archive_index:03d}",
                    "archive_uri": archive_uri,
                    "failed": failed_content,
                }
            )
        return repaired

    async def read_session_messages(
        self,
        agent_name: str,
        session_id: int | str,
    ) -> list[dict[str, Any]]:
        payloads_with_order: list[tuple[dict[str, Any], int]] = []
        seen_ids: set[str] = set()
        ordinal = 0

        for archive_index in range(1, _MAX_SESSION_ARCHIVE_SCAN + 1):
            try:
                content = await self.read_content(
                    build_session_archive_messages_uri(agent_name, session_id, archive_index),
                    agent_name=agent_name,
                )
            except OpenVikingApiError as exc:
                if _is_not_found_error(exc):
                    break
                raise
            for payload in _parse_session_message_lines(content, agent_name, session_id):
                message_id = str(payload.get("id") or "").strip()
                if message_id and message_id in seen_ids:
                    continue
                if message_id:
                    seen_ids.add(message_id)
                payloads_with_order.append((payload, ordinal))
                ordinal += 1

        try:
            active_content = await self.read_content(
                build_session_messages_uri(agent_name, session_id),
                agent_name=agent_name,
            )
        except OpenVikingApiError as exc:
            if not _is_not_found_error(exc):
                raise
            active_content = ""

        for payload in _parse_session_message_lines(active_content, agent_name, session_id):
            message_id = str(payload.get("id") or "").strip()
            if message_id and message_id in seen_ids:
                continue
            if message_id:
                seen_ids.add(message_id)
            payloads_with_order.append((payload, ordinal))
            ordinal += 1

        payloads_with_order.sort(key=lambda item: _message_sort_key(item[0], item[1]))
        return [payload for payload, _ in payloads_with_order]

    async def read_session_summary(self, agent_name: str, session_id: int | str) -> str:
        try:
            return await self.read_content(
                build_session_summary_uri(agent_name, session_id),
                agent_name=agent_name,
            )
        except OpenVikingApiError as exc:
            if _is_not_found_error(exc):
                return ""
            raise

    async def _upload_temp_file(self, content: bytes, filename: str) -> str:
        client = await self._get_client()
        try:
            response = await client.post(
                "/api/v1/resources/temp_upload",
                headers=self._headers("system"),
                files={"file": (filename, content, "text/markdown")},
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPError as exc:
            raise OpenVikingUnavailableError(f"Failed uploading temporary OpenViking content: {exc}") from exc
        if isinstance(payload, dict) and payload.get("status") == "error":
            error = payload.get("error") or {}
            raise OpenVikingApiError(
                error.get("message") or "OpenViking temp upload failed",
                code=error.get("code"),
                status_code=response.status_code,
            )
        result = payload.get("result") if isinstance(payload, dict) else None
        temp_path = (result or {}).get("temp_path")
        if not temp_path:
            raise OpenVikingApiError(
                "OpenViking temp upload did not return a temp path",
                status_code=response.status_code,
            )
        return str(temp_path)

    async def write_text_resource(
        self,
        *,
        uri: str,
        content: str,
        filename: str,
        reason: str = "",
        instruction: str = "",
        wait: bool = True,
    ) -> dict[str, Any]:
        try:
            await self.rm(uri, recursive=True)
        except OpenVikingApiError as exc:
            if exc.status_code != 404 and (exc.code or "").upper() != "NOT_FOUND":
                raise
        temp_path = await self._upload_temp_file(content.encode("utf-8"), filename)
        return await self._request(
            "POST",
            "/api/v1/resources",
            agent_name="system",
            json_body={
                "temp_path": temp_path,
                "to": uri,
                "reason": reason,
                "instruction": instruction,
                "wait": wait,
                "preserve_structure": False,
                "watch_interval": 0,
            },
        )

    async def write_session_summary(
        self,
        agent_name: str,
        session_id: int | str,
        content: str,
    ) -> dict[str, Any]:
        return await self.write_text_resource(
            uri=build_session_summary_uri(agent_name, session_id),
            content=content,
            filename="lifeos-session-summary.md",
            reason="LifeOS session summary",
            instruction="Store the latest compact session summary for prompt assembly.",
            wait=True,
        )

    async def add_resource(
        self,
        *,
        path: str,
        to: str,
        reason: str = "",
        instruction: str = "",
        wait: bool = False,
        ignore_dirs: str | None = None,
        include: str | None = None,
        exclude: str | None = None,
        preserve_structure: bool = True,
        watch_interval: float = 5.0,
    ) -> dict[str, Any]:
        body = {
            "path": path,
            "to": to,
            "reason": reason,
            "instruction": instruction,
            "wait": wait,
            "preserve_structure": preserve_structure,
            "watch_interval": watch_interval,
        }
        if ignore_dirs:
            body["ignore_dirs"] = ignore_dirs
        if include:
            body["include"] = include
        if exclude:
            body["exclude"] = exclude
        return await self._request(
            "POST",
            "/api/v1/resources",
            agent_name="system",
            json_body=body,
        )

    async def stat(self, uri: str) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/api/v1/fs/stat",
            agent_name="system",
            params={"uri": uri},
        )

    async def rm(self, uri: str, *, recursive: bool = True) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            "/api/v1/fs",
            agent_name="system",
            params={"uri": uri, "recursive": str(recursive).lower()},
        )

    async def wait_processed(self, timeout: float | None = None) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/api/v1/system/wait",
            agent_name="system",
            json_body={"timeout": timeout},
        )


openviking_client = OpenVikingClient()


async def close_openviking_client() -> None:
    await openviking_client.close()
