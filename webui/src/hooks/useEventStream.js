import { useEffect, useRef, useState } from "react";
import { ensureEventsSession } from "../api";

const FLUSH_INTERVAL_MS = 150;
const MAX_BUFFER = 400;

const LATEST_WINS_TYPES = new Set([
  "system.health.updated",
  "system.readiness.updated",
  "jobs.updated",
  "jobs.run.updated",
  "approvals.pending.updated",
  "approvals.decided",
  "agents.sessions.updated",
  "agents.messages.appended",
  "prayer.schedule.updated",
  "prayer.weekly_summary.updated",
  "settings.updated",
]);

export function useEventStream({ enabled = true, onEvents }) {
  const [status, setStatus] = useState("disconnected");
  const sourceRef = useRef(null);
  const reconnectTimerRef = useRef(null);
  const bufferRef = useRef([]);
  const flushTimerRef = useRef(null);
  const retryRef = useRef(0);

  useEffect(() => {
    if (!enabled) return () => {};

    let closed = false;

    const flush = () => {
      flushTimerRef.current = null;
      const queued = bufferRef.current;
      if (!queued.length) return;
      bufferRef.current = [];

      const latestByType = new Map();
      const logByRunId = new Map();
      const passthrough = [];

      for (const event of queued) {
        if (!event?.type) continue;

        if (event.type === "jobs.run.log.appended") {
          const runId = event.entity?.id || "unknown";
          const existing = logByRunId.get(runId);
          if (existing) {
            existing.payload.lines = [...(existing.payload.lines || []), ...(event.payload?.lines || [])];
          } else {
            logByRunId.set(runId, {
              ...event,
              payload: { ...(event.payload || {}), lines: [...(event.payload?.lines || [])] },
            });
          }
          continue;
        }

        if (LATEST_WINS_TYPES.has(event.type)) {
          latestByType.set(event.type, event);
        } else {
          passthrough.push(event);
        }
      }

      const coalesced = [...latestByType.values(), ...logByRunId.values(), ...passthrough];
      if (coalesced.length && onEvents) onEvents(coalesced);
    };

    const scheduleFlush = () => {
      if (!flushTimerRef.current) {
        flushTimerRef.current = setTimeout(flush, FLUSH_INTERVAL_MS);
      }
    };

    const cleanupSource = () => {
      if (sourceRef.current) {
        sourceRef.current.close();
        sourceRef.current = null;
      }
    };

    const connect = async () => {
      try {
        await ensureEventsSession();
      } catch {
        if (!closed) {
          setStatus("reconnecting");
          const delayMs = Math.min(10000, 1000 * (retryRef.current + 1));
          reconnectTimerRef.current = setTimeout(connect, delayMs);
          retryRef.current += 1;
        }
        return;
      }

      if (closed) return;
      cleanupSource();

      setStatus("reconnecting");
      const source = new EventSource("/api/events");
      sourceRef.current = source;

      source.onopen = () => {
        retryRef.current = 0;
        setStatus("connected");
      };

      source.onmessage = (event) => {
        try {
          const parsed = JSON.parse(event.data);
          if (bufferRef.current.length >= MAX_BUFFER) {
            bufferRef.current.shift();
            // Keep silent in production; visible for local debugging.
            // eslint-disable-next-line no-console
            console.debug("[sse] buffer overflow, dropping oldest event");
          }
          bufferRef.current.push(parsed);
          scheduleFlush();
        } catch {
          // ignore malformed event payloads
        }
      };

      source.onerror = () => {
        cleanupSource();
        if (closed) return;
        setStatus("reconnecting");
        const delayMs = Math.min(10000, 1000 * (retryRef.current + 1));
        reconnectTimerRef.current = setTimeout(connect, delayMs);
        retryRef.current += 1;
      };
    };

    connect();

    return () => {
      closed = true;
      setStatus("disconnected");
      cleanupSource();
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current);
      if (flushTimerRef.current) clearTimeout(flushTimerRef.current);
      reconnectTimerRef.current = null;
      flushTimerRef.current = null;
      bufferRef.current = [];
    };
  }, [enabled, onEvents]);

  return { status };
}
