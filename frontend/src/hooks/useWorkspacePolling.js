/**
 * Keep the active workspace snapshot fresh without reloading every screen's data.
 * Polling pauses while the browser tab is hidden and avoids overlapping requests.
 */
import { useEffect } from "react";
import { api } from "../api/client.js";

export default function useWorkspacePolling({
  token, user, page, setTasks, setNotifications, setDashboard,
  setDatabaseStats, setCommonTasks, setAutoTaskSettings, setReviewQueue,
  setSelectedReviewIds, setAudit,
}) {
  useEffect(() => {
    if (!token || !user) return undefined;
    let cancelled = false;
    let inFlight = false;

    const syncWorkspace = async () => {
      if (document.visibilityState !== "visible" || inFlight) return;
      inFlight = true;
      try {
        const requests = [
          api("/tasks", token),
          api("/notifications", token),
          api("/dashboard", token),
        ];
        if (["Founder", "Core Management"].includes(user.role)) {
          requests.push(api("/tasks/review-queue", token));
          requests.push(api("/admin/database-stats", token).catch(() => null));
          requests.push(api("/common-tasks", token));
          requests.push(api("/auto-tasks/settings", token).catch(() => null));
        }
        const [
          nextTasks, nextNotifications, nextDashboard, nextReviews,
          nextDbStats, nextCommonTasks, nextAutoStats,
        ] = await Promise.all(requests);
        if (cancelled) return;

        setTasks(nextTasks);
        setNotifications(nextNotifications);
        setDashboard(nextDashboard);
        if (nextDbStats) setDatabaseStats(nextDbStats);
        if (nextCommonTasks) setCommonTasks(nextCommonTasks);
        if (nextAutoStats) setAutoTaskSettings(nextAutoStats);
        if (nextReviews) {
          setReviewQueue(nextReviews);
          setSelectedReviewIds((current) =>
            current.filter((id) => nextReviews.some((task) => task.id === id))
          );
        }
        if (page === "Audit Log") {
          const nextAudit = await api("/audit?limit=100", token);
          if (!cancelled) setAudit(nextAudit);
        }
      } catch {
        // Keep the last successful snapshot during short network interruptions.
      } finally {
        inFlight = false;
      }
    };

    const timer = window.setInterval(syncWorkspace, 30000);
    const onVisible = () => {
      if (document.visibilityState === "visible") syncWorkspace();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [token, user?.role, page]);
}
