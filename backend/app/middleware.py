"""HTTP middleware for request IDs and structured request logs."""

import json
import logging
import time
import uuid

from fastapi import Request

logger = logging.getLogger("lifeos.http")


async def request_context_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()

    response = await call_next(request)
    elapsed_ms = int((time.perf_counter() - start) * 1000)
    response.headers["X-Request-ID"] = request_id

    payload = {
        "request_id": request_id,
        "method": request.method,
        "path": request.url.path,
        "status_code": response.status_code,
        "latency_ms": elapsed_ms,
    }
    logger.info(json.dumps(payload, separators=(",", ":")))
    return response
