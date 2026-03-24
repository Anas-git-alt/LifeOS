import { QUERY_KEYS } from "../queryKeys";

export function routeRealtimeEvents(queryClient, events) {
  for (const event of events) {
    if (!event?.type) continue;

    switch (event.type) {
      case "system.health.updated":
        queryClient.setQueryData(QUERY_KEYS.health, event.payload);
        break;
      case "system.readiness.updated":
        queryClient.setQueryData(QUERY_KEYS.readiness, event.payload);
        break;
      case "jobs.updated":
      case "jobs.run.updated":
      case "jobs.run.log.appended":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.jobsSummary, exact: true });
        break;
      case "approvals.pending.updated":
      case "approvals.decided":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.approvalsPending, exact: true });
        break;
      case "agents.sessions.updated":
      case "agents.messages.appended":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.agentSessions, exact: true });
        break;
      case "workspace.archives.updated":
      case "workspace.sync.updated":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.workspaceArchives, exact: true });
        break;
      case "prayer.schedule.updated":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.prayerScheduleToday, exact: true });
        break;
      case "prayer.weekly_summary.updated":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.prayerWeeklySummary, exact: true });
        break;
      case "settings.updated":
        queryClient.invalidateQueries({ queryKey: QUERY_KEYS.settings, exact: true });
        break;
      default:
        break;
    }
  }
}
