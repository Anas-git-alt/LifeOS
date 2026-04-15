import { useCallback, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  getAgentSessionsSummary,
  getHealth,
  getJobRuns,
  getJobs,
  getPendingActions,
  getPrayerScheduleToday,
  getPrayerWeeklySummary,
  getReadiness,
  getTodayAgenda,
} from "../api";
import { useEventStream } from "../hooks/useEventStream";
import { getJobRunDetail } from "../jobRuns";
import { QUERY_KEYS } from "../queryKeys";
import { routeRealtimeEvents } from "../realtime/eventRouter";
import WidgetCard, { WidgetEmpty, WidgetError, WidgetSkeleton } from "./WidgetCard";

function formatUpdatedAt(updatedAt) {
  if (!updatedAt) return "Not synced yet";
  return `Updated ${new Date(updatedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function listLimit(expanded, compact = 5, expandedLimit = 20) {
  return expanded ? expandedLimit : compact;
}

function healthBadge(status) {
  const normalized = String(status || "unknown").toLowerCase();
  if (["healthy", "ok", "ready", "success", "connected", "active", "enabled", "on"].includes(normalized)) {
    return "badge-approved";
  }
  if (["pending", "running", "queued"].includes(normalized)) return "badge-pending";
  return "badge-rejected";
}

function jobStatusBadge(job) {
  if (job.paused) return "badge-pending";
  if (job.enabled) return "badge-active";
  return "badge-rejected";
}

async function fetchJobsSummary() {
  const jobs = await getJobs();
  const topJobs = jobs.slice(0, 8);
  const runs = await Promise.all(
    topJobs.map(async (job) => {
      try {
        return [job.id, await getJobRuns(job.id, 3)];
      } catch {
        return [job.id, []];
      }
    }),
  );
  return { jobs, runsByJob: Object.fromEntries(runs) };
}

export default function MissionControl({ hasToken = false, onNavigate, onChangeToken }) {
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState({
    approvals: false,
    jobs: false,
    today: false,
    agents: false,
  });

  const onEvents = useCallback(
    (events) => {
      routeRealtimeEvents(queryClient, events);
    },
    [queryClient],
  );

  const { status: realtimeStatus } = useEventStream({ enabled: hasToken, onEvents });

  const healthQuery = useQuery({ queryKey: QUERY_KEYS.health, queryFn: getHealth, refetchInterval: 60000 });
  const readinessQuery = useQuery({ queryKey: QUERY_KEYS.readiness, queryFn: getReadiness, refetchInterval: 60000 });
  const approvalsQuery = useQuery({
    queryKey: QUERY_KEYS.approvalsPending,
    queryFn: getPendingActions,
    enabled: hasToken,
    refetchInterval: 45000,
  });
  const jobsQuery = useQuery({ queryKey: QUERY_KEYS.jobsSummary, queryFn: fetchJobsSummary, enabled: hasToken, refetchInterval: 45000 });
  const todayQuery = useQuery({ queryKey: QUERY_KEYS.todayAgenda, queryFn: getTodayAgenda, enabled: hasToken, refetchInterval: 45000 });
  const prayerScheduleQuery = useQuery({
    queryKey: QUERY_KEYS.prayerScheduleToday,
    queryFn: getPrayerScheduleToday,
    enabled: hasToken,
    refetchInterval: 60000,
  });
  const prayerWeeklyQuery = useQuery({
    queryKey: QUERY_KEYS.prayerWeeklySummary,
    queryFn: getPrayerWeeklySummary,
    enabled: hasToken,
    refetchInterval: 60000,
  });
  const agentsQuery = useQuery({
    queryKey: QUERY_KEYS.agentSessions,
    queryFn: () => getAgentSessionsSummary(6),
    enabled: hasToken,
    refetchInterval: 45000,
  });

  const systemUpdatedAt = Math.max(healthQuery.dataUpdatedAt || 0, readinessQuery.dataUpdatedAt || 0);
  const todayTopFocus = useMemo(() => todayQuery.data?.top_focus || [], [todayQuery.data]);
  const pendingApprovals = approvalsQuery.data || [];
  const jobs = jobsQuery.data?.jobs || [];
  const runsByJob = jobsQuery.data?.runsByJob || {};
  const sessions = agentsQuery.data || [];

  return (
    <div>
      <header className="page-header mission-header">
        <div className="page-header-row">
          <div>
            <h1>Mission Control</h1>
            <p>Live system pulse across approvals, jobs, today priorities, and agent activity.</p>
          </div>
          <div className="action-row">
            <button type="button" className="btn btn-ghost" onClick={onChangeToken}>
              Change Token
            </button>
          </div>
        </div>
      </header>

      <section className="mission-grid" aria-live="polite">
        <WidgetCard
          title="System"
          subtitle="Health, readiness, and realtime stream"
          status={<RealtimeBadge status={realtimeStatus} />}
          footer={formatUpdatedAt(systemUpdatedAt)}
          actions={
            <button className="btn btn-ghost" onClick={() => { healthQuery.refetch(); readinessQuery.refetch(); }}>
              Refresh
            </button>
          }
        >
          {(healthQuery.isLoading || readinessQuery.isLoading) && <WidgetSkeleton lines={3} />}
          {(healthQuery.error || readinessQuery.error) && (
            <WidgetError
              message={(healthQuery.error || readinessQuery.error)?.message}
              onRetry={() => {
                healthQuery.refetch();
                readinessQuery.refetch();
              }}
            />
          )}
          {!healthQuery.isLoading && !readinessQuery.isLoading && !healthQuery.error && !readinessQuery.error && (
            <div className="widget-list">
              <div className="widget-row">
                <span>Health</span>
                <span className={`badge ${healthBadge(healthQuery.data?.status)}`}>{healthQuery.data?.status || "unknown"}</span>
              </div>
              <div className="widget-row">
                <span>Readiness</span>
                <span className={`badge ${healthBadge(readinessQuery.data?.status)}`}>{readinessQuery.data?.status || "unknown"}</span>
              </div>
              <div className="widget-row">
                <span>Database</span>
                <span className={`badge ${readinessQuery.data?.database ? "badge-approved" : "badge-rejected"}`}>
                  {readinessQuery.data?.database ? "connected" : "degraded"}
                </span>
              </div>
            </div>
          )}
        </WidgetCard>

        <WidgetCard
          title="Approvals"
          subtitle="Pending queue requiring owner decision"
          footer={formatUpdatedAt(approvalsQuery.dataUpdatedAt)}
          actions={
            <>
              <button className="btn btn-ghost" onClick={() => setExpanded((prev) => ({ ...prev, approvals: !prev.approvals }))} disabled={!hasToken}>
                {expanded.approvals ? "Show less" : "Show more"}
              </button>
              <button className="btn btn-ghost" onClick={() => onNavigate("approvals")}>View all</button>
            </>
          }
        >
          {!hasToken && (
            <WidgetEmpty
              message="Connect API token to load approvals."
              action={<button className="btn btn-primary" onClick={onChangeToken}>Set token</button>}
            />
          )}
          {approvalsQuery.isLoading && <WidgetSkeleton lines={4} />}
          {approvalsQuery.error && <WidgetError message={approvalsQuery.error.message} onRetry={approvalsQuery.refetch} />}
          {hasToken && !approvalsQuery.isLoading && !approvalsQuery.error && pendingApprovals.length === 0 && (
            <WidgetEmpty
              message="No pending approvals right now."
              action={<button className="btn btn-primary" onClick={() => onNavigate("agent-create")}>Create Agent</button>}
            />
          )}
          {hasToken && !approvalsQuery.isLoading && !approvalsQuery.error && pendingApprovals.length > 0 && (
            <div className="widget-list">
              {pendingApprovals.slice(0, listLimit(expanded.approvals, 5)).map((action) => (
                <div key={action.id} className="widget-row stack">
                  <strong>#{action.id} · {action.agent_name}</strong>
                  <span>{action.summary}</span>
                </div>
              ))}
            </div>
          )}
        </WidgetCard>

        <WidgetCard
          title="Jobs"
          subtitle="Recent run status and schedule"
          footer={formatUpdatedAt(jobsQuery.dataUpdatedAt)}
          actions={
            <>
              <button className="btn btn-ghost" onClick={() => setExpanded((prev) => ({ ...prev, jobs: !prev.jobs }))} disabled={!hasToken}>
                {expanded.jobs ? "Show less" : "Show more"}
              </button>
              <button className="btn btn-ghost" onClick={() => onNavigate("jobs")}>View all</button>
            </>
          }
        >
          {!hasToken && (
            <WidgetEmpty
              message="Connect API token to load jobs."
              action={<button className="btn btn-primary" onClick={onChangeToken}>Set token</button>}
            />
          )}
          {jobsQuery.isLoading && <WidgetSkeleton lines={5} />}
          {jobsQuery.error && <WidgetError message={jobsQuery.error.message} onRetry={jobsQuery.refetch} />}
          {hasToken && !jobsQuery.isLoading && !jobsQuery.error && jobs.length === 0 && (
            <WidgetEmpty
              message="No scheduled jobs yet."
              action={<button className="btn btn-primary" onClick={() => onNavigate("jobs")}>Create Job</button>}
            />
          )}
          {hasToken && !jobsQuery.isLoading && !jobsQuery.error && jobs.length > 0 && (
            <div className="widget-list">
              {jobs.slice(0, listLimit(expanded.jobs, 4)).map((job) => {
                const latestRun = runsByJob[job.id]?.[0];
                const latestRunDetail = getJobRunDetail(latestRun);
                return (
                  <div key={job.id} className="widget-row stack">
                    <strong>#{job.id} {job.name}</strong>
                    <span>
                      <span className={`badge ${jobStatusBadge(job)}`}>{job.paused ? "paused" : job.enabled ? "active" : "disabled"}</span>
                      {" · "}
                      {job.next_run_at || "no next run"}
                    </span>
                    {latestRun ? (
                      <span>
                        Last run: <span className={`badge ${healthBadge(latestRun.status)}`}>{latestRun.status}</span> at{" "}
                        {new Date(latestRun.created_at).toLocaleTimeString()}
                        {latestRunDetail ? ` · ${latestRunDetail}` : ""}
                      </span>
                    ) : (
                      <span>No runs yet</span>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </WidgetCard>

        <WidgetCard
          title="Today"
          subtitle="Top focus with prayer context"
          footer={formatUpdatedAt(Math.max(todayQuery.dataUpdatedAt || 0, prayerScheduleQuery.dataUpdatedAt || 0, prayerWeeklyQuery.dataUpdatedAt || 0))}
          actions={
            <>
              <button className="btn btn-ghost" onClick={() => setExpanded((prev) => ({ ...prev, today: !prev.today }))} disabled={!hasToken}>
                {expanded.today ? "Show less" : "Show more"}
              </button>
              <button className="btn btn-ghost" onClick={() => onNavigate("today")}>View all</button>
            </>
          }
        >
          {!hasToken && (
            <WidgetEmpty
              message="Connect API token to load Today context."
              action={<button className="btn btn-primary" onClick={onChangeToken}>Set token</button>}
            />
          )}
          {(todayQuery.isLoading || prayerScheduleQuery.isLoading || prayerWeeklyQuery.isLoading) && <WidgetSkeleton lines={5} />}
          {(todayQuery.error || prayerScheduleQuery.error || prayerWeeklyQuery.error) && (
            <WidgetError
              message={(todayQuery.error || prayerScheduleQuery.error || prayerWeeklyQuery.error)?.message}
              onRetry={() => {
                todayQuery.refetch();
                prayerScheduleQuery.refetch();
                prayerWeeklyQuery.refetch();
              }}
            />
          )}
          {hasToken && !todayQuery.isLoading && !todayQuery.error && todayTopFocus.length === 0 && (
            <WidgetEmpty
              message="No focus items yet for today."
              action={<button className="btn btn-primary" onClick={() => onNavigate("life")}>Add focus item</button>}
            />
          )}
          {hasToken && !todayQuery.isLoading && !todayQuery.error && todayTopFocus.length > 0 && (
            <div className="widget-list">
              {todayTopFocus.slice(0, listLimit(expanded.today, 5)).map((item) => (
                <div key={item.id} className="widget-row stack">
                  <strong>#{item.id} {item.title}</strong>
                  <span>{item.domain} · {item.priority}</span>
                </div>
              ))}
              <div className="widget-row"><span>Next prayer</span><strong>{prayerScheduleQuery.data?.next_prayer || "n/a"}</strong></div>
              <div className="widget-row"><span>Prayer score</span><strong>{prayerWeeklyQuery.data?.prayer_accuracy_percent ?? "n/a"}%</strong></div>
            </div>
          )}
        </WidgetCard>

        <WidgetCard
          title="Agents"
          subtitle="Recent session activity"
          footer={formatUpdatedAt(agentsQuery.dataUpdatedAt)}
          actions={
            <>
              <button className="btn btn-ghost" onClick={() => setExpanded((prev) => ({ ...prev, agents: !prev.agents }))} disabled={!hasToken}>
                {expanded.agents ? "Show less" : "Show more"}
              </button>
              <button className="btn btn-ghost" onClick={() => onNavigate("agents")}>View all</button>
            </>
          }
        >
          {!hasToken && (
            <WidgetEmpty
              message="Connect API token to load active sessions."
              action={<button className="btn btn-primary" onClick={onChangeToken}>Set token</button>}
            />
          )}
          {agentsQuery.isLoading && <WidgetSkeleton lines={4} />}
          {agentsQuery.error && <WidgetError message={agentsQuery.error.message} onRetry={agentsQuery.refetch} />}
          {hasToken && !agentsQuery.isLoading && !agentsQuery.error && sessions.length === 0 && (
            <WidgetEmpty
              message="No active agent sessions yet."
              action={<button className="btn btn-primary" onClick={() => onNavigate("agents")}>Open Agents</button>}
            />
          )}
          {hasToken && !agentsQuery.isLoading && !agentsQuery.error && sessions.length > 0 && (
            <div className="widget-list">
              {sessions.slice(0, listLimit(expanded.agents, 6)).map((session) => (
                <div key={`${session.agent_name}-${session.id}`} className="widget-row stack">
                  <strong>{session.agent_name} · {session.title || "New chat"}</strong>
                  <span>{session.last_message_at ? new Date(session.last_message_at).toLocaleString() : "No messages yet"}</span>
                </div>
              ))}
            </div>
          )}
        </WidgetCard>
      </section>
    </div>
  );
}

function RealtimeBadge({ status }) {
  if (status === "connected") {
    return <span className="badge badge-approved">Realtime connected</span>;
  }
  if (status === "reconnecting") {
    return <span className="badge badge-rejected">Realtime reconnecting</span>;
  }
  return <span className="badge badge-rejected">Realtime disconnected</span>;
}
