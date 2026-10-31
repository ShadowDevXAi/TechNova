/**
 * Load the signed-in member and the first data snapshot used by portal pages.
 * This hook centralizes startup/manual refresh behavior and clears invalid sessions.
 */
import { useEffect } from "react";
import { api } from "../api/client.js";

export default function useWorkspaceData({
  token, selected, setError, setToken, setUser, setDashboard, setDatabaseStats,
  setAutoTaskSettings, setMembers, setTasks, setTeams, setCommonTasks,
  setDailySchedules, setLeaderboard, setCreditLedger, setNotifications,
  setReviewQueue, setSelectedReviewIds, setSelected,
}) {
  const load = async (t = token) => {
    if (!t) return;
    setError("");
    try {
      const me = await api("/auth/me", t);
      setUser(me);
      const [
        dashboard, members, tasks, teams, commonTasks, leaderboard, ledger,
        schedules, inbox, reviews, dbStats, autoStats,
      ] = await Promise.all([
        api("/dashboard", t),
        api("/members", t),
        api("/tasks", t),
        api("/teams", t),
        api("/common-tasks", t),
        api("/leaderboard", t),
        api("/credits/ledger", t),
        ["Founder", "Core Management"].includes(me.role)
          ? api("/task-schedules", t)
          : Promise.resolve([]),
        api("/notifications", t),
        ["Founder", "Core Management"].includes(me.role)
          ? api("/tasks/review-queue", t)
          : Promise.resolve([]),
        ["Founder", "Core Management"].includes(me.role)
          ? api("/admin/database-stats", t).catch(() => null)
          : Promise.resolve(null),
        ["Founder", "Core Management"].includes(me.role)
          ? api("/auto-tasks/settings", t).catch(() => null)
          : Promise.resolve(null),
      ]);

      setDashboard(dashboard);
      setDatabaseStats(dbStats);
      if (autoStats) setAutoTaskSettings(autoStats);
      setMembers(members);
      setTasks(tasks);
      setTeams(teams);
      setCommonTasks(commonTasks);
      setDailySchedules(schedules);
      setLeaderboard(leaderboard);
      setCreditLedger(ledger);
      setNotifications(inbox);
      setReviewQueue(reviews);
      setSelectedReviewIds((current) =>
        current.filter((id) => reviews.some((task) => task.id === id))
      );
      if (me.role === "Member") setSelected(me);
      else if (!selected && members.length) setSelected(members[0]);
    } catch (error) {
      localStorage.removeItem("tn_token");
      setToken("");
      setUser(null);
      setError(error.message);
    }
  };

  // Load the complete workspace whenever a session token becomes available.
  useEffect(() => {
    if (token) load(token);
  }, [token]);

  return load;
}
