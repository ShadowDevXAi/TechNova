/**
 * Portal action handlers, grouped in one place so screen components can focus on layout.
 * The factory receives React state/setters and shared helpers from App.jsx.
 */
export default function createPortalActions(context) {
  const {
    token,
    setToken,
    user,
    setUser,
    page,
    setPage,
    members,
    setMembers,
    tasks,
    setTasks,
    commonTasks,
    setCommonTasks,
    dailySchedules,
    setDailySchedules,
    leaderboard,
    setLeaderboard,
    creditLedger,
    setCreditLedger,
    notifications,
    setNotifications,
    reviewQueue,
    setReviewQueue,
    selectedReviewIds,
    setSelectedReviewIds,
    reviewSearch,
    setReviewSearch,
    assigneeSearch,
    setAssigneeSearch,
    taskStatusFilter,
    setTaskStatusFilter,
    selectedTaskDetail,
    setSelectedTaskDetail,
    announcementForm,
    setAnnouncementForm,
    submissionForm,
    setSubmissionForm,
    teams,
    setTeams,
    dashboard,
    setDashboard,
    databaseStats,
    setDatabaseStats,
    autoTaskSettings,
    setAutoTaskSettings,
    autoTaskBusy,
    setAutoTaskBusy,
    search,
    setSearch,
    selected,
    setSelected,
    modal,
    setModal,
    toast,
    setToast,
    error,
    setError,
    busy,
    setBusy,
    mobile,
    setMobile,
    authMode,
    setAuthMode,
    resetToken,
    setResetToken,
    resetEmail,
    setResetEmail,
    resetPassword,
    setResetPassword,
    auth,
    setAuth,
    memberForm,
    setMemberForm,
    taskForm,
    setTaskForm,
    verifyToken,
    setVerifyToken,
    verifyResult,
    setVerifyResult,
    pendingReviewTasks,
    setPendingReviewTasks,
    reviewQueueMemberId,
    setReviewQueueMemberId,
    autoVerifyRoute,
    setAutoVerifyRoute,
    issuedCard,
    setIssuedCard,
    ownCard,
    setOwnCard,
    scanEnabled,
    setScanEnabled,
    cardRoleFilter,
    setCardRoleFilter,
    settingsForm,
    setSettingsForm,
    profileForm,
    setProfileForm,
    audit,
    setAudit,
    api,
    API_BASE,
    notify,
    fail,
    load,
    isAdmin,
    isFounder
  } = context;

  // Purpose: Register a new member or authenticate an existing account, then store the returned session.
  async function login(e) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      if (authMode === "register") {
        let r = await api("/auth/register", "", {
          method: "POST",
          body: JSON.stringify(auth),
        });
        notify(r.message);
        setAuthMode("login");
      } else {
        let r = await api("/auth/login", "", {
          method: "POST",
          body: JSON.stringify({ email: auth.email, password: auth.password }),
        });
        localStorage.setItem("tn_token", r.access_token);
        setToken(r.access_token);
        setUser(r.user);
      }
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Clear the session and reset all member-specific portal state.
  async function logout() {
    // Unbind this browser's notification token before ending the session.
    const registeredPushToken = localStorage.getItem("tn_fcm_token");
    if (registeredPushToken && token) {
      try {
        await api("/push/unregister", token, {
          method: "POST",
          body: JSON.stringify({ token: registeredPushToken }),
        });
      } catch {
        // Logout must remain available even if the push API is temporarily offline.
      }
      localStorage.removeItem("tn_fcm_token");
    }
    localStorage.removeItem("tn_token");
    setToken("");
    setUser(null);
    setSelected(null);
    setOwnCard(null);
    setIssuedCard(null);
    setPendingReviewTasks([]);
    setReviewQueueMemberId("");
    setMembers([]);
    setTasks([]);
    setCommonTasks([]);
    setDailySchedules([]);
    setLeaderboard({ top_10: [], top_three: [], my_entry: null });
    setCreditLedger({ balance: 0, earned_total: 0, penalized_total: 0, entries: [] });
    setNotifications([]);
    setReviewQueue([]);
    setSelectedReviewIds([]);
    setReviewSearch("");
    setAssigneeSearch("");
    setTaskStatusFilter("All");
    setAnnouncementForm({ title: "", message: "" });
    setSubmissionForm({ taskId: "", title: "", submission_evidence_url: "", project_url: "", submission_note: "", submission_attested: false });
    setDashboard(null);
    setDatabaseStats(null);
    setPage("Overview");
    window.history.replaceState({}, "", "/");
  }

  // Purpose: Reload the workspace data from the API after a user action.
  async function refresh() {
    try {
      await load();
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Create a member account from the management form.
  async function createMember(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/members", token, {
        method: "POST",
        body: JSON.stringify(memberForm),
      });
      setModal("");
      setMemberForm({
        name: "",
        email: "",
        password: "",
        role: "Member",
        team: "Unassigned",
        status: "Active",
      });
      notify("Member created");
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Update an existing member's role, team, profile or status.
  async function updateMember(m, patch) {
    try {
      await api(`/members/${m.id}`, token, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      notify("Member updated");
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Approve a pending member so the account can access the portal.
  async function approveMember(m) {
    try {
      await api(`/members/${m.id}/approve`, token, { method: "POST" });
      notify("Member approved");
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Broadcast an announcement to the club using the management form.
  async function createAnnouncement(e) {
    e.preventDefault();
    setBusy(true);
    try {
      const result = await api("/announcements", token, {
        method: "POST",
        body: JSON.stringify(announcementForm),
      });
      setModal("");
      setAnnouncementForm({ title: "", message: "" });
      notify(
        "Announcement sent to " + result.recipient_count +
        " people (" + result.member_count + " Members, " +
        result.faculty_count + " Faculty)"
      );
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Create and assign an individual or shared club task.
  async function createTask(e) {
    e.preventDefault();
    if (taskForm.assignment_mode === "selected_members" && !taskForm.assignee_ids.length) {
      fail(new Error("Select at least one active member."));
      return;
    }
    if (taskForm.assignment_mode === "individual" && !taskForm.assignee_id) {
      fail(new Error("Choose an assignee."));
      return;
    }
    setBusy(true);
    try {
      await api("/tasks", token, {
        method: "POST",
        body: JSON.stringify(taskForm),
      });
      const mode = taskForm.assignment_mode;
      const selectedCount = taskForm.assignee_ids.length;
      setModal("");
      setTaskForm({
        title: "",
        description: "",
        assignment_mode: "individual",
        assignee_id: "",
        assignee_ids: [],
        priority: "Medium",
        recurrence: "once",
        difficulty_rank: "F",
        programming_language: "General",
        due_date: "",
        project: "Club projects",
      });
      notify(
        taskForm.recurrence === "daily"
          ? "Task created. Daily copies will start tomorrow automatically."
          : mode === "open_to_all"
          ? "Common task published to Members and Faculty"
          : mode === "selected_members"
          ? "Task assigned to " + selectedCount + " members; notifications sent"
          : "Task assigned; notification sent"
      );
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Approve selected task submissions and refresh the review queue.
  async function approveSelectedTasks(taskIds = selectedReviewIds, scopeLabel = "selected submissions") {
    const requestedIds = [...new Set(taskIds)];
    const chosen = reviewQueue.filter((task) => requestedIds.includes(task.id));
    if (!chosen.length) {
      fail(new Error("Select at least one submission waiting for review."));
      return;
    }
    const eligible = chosen.filter((task) => task.submission_evidence_url && task.submission_attested);
    const blocked = chosen.length - eligible.length;
    if (!eligible.length) {
      fail(new Error("Approval needs screenshot evidence and the member's completion attestation. Ask the member to resubmit both."));
      return;
    }
    const confirmed = window.confirm(
      "Approve " + eligible.length + " ready " + scopeLabel +
      (blocked ? "? " + blocked + " submission(s) without screenshot proof or attestation will be skipped." : "?") +
      " Approved tasks move to Completed and receive credits."
    );
    if (!confirmed) return;
    setBusy(true);
    let approvedCount = 0;
    try {
      for (let start = 0; start < eligible.length; start += 100) {
        const batch = eligible.slice(start, start + 100);
        const result = await api("/tasks/bulk-confirm", token, {
          method: "POST",
          body: JSON.stringify({ task_ids: batch.map((task) => task.id) }),
        });
        approvedCount += Number(result.approved_count || 0);
      }
      setSelectedReviewIds([]);
      notify(approvedCount + " submission(s) approved" + (blocked ? "; " + blocked + " need evidence/attestation" : ""));
      await refresh();
    } catch (e) {
      await refresh();
      fail(new Error(
        approvedCount
          ? approvedCount + " approved; remaining submissions need attention. " + (e.message || "")
          : e.message || "Approval failed. Check the submission requirements and try again."
      ));
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Pause or resume an active task using the management controls.
  async function toggleTaskPause(task) {
    const nextState = task.task_state === "Suspended" ? "Active" : "Suspended";
    const reason = nextState === "Suspended" ? prompt("Why are you pausing this task?") : "";
    if (nextState === "Suspended" && (!reason || reason.trim().length < 5)) return;
    try {
      await api("/tasks/" + task.id + "/state", token, {
        method: "POST",
        body: JSON.stringify({ state: nextState, reason: reason || "" }),
      });
      notify(nextState === "Suspended" ? "Task paused; its deadline is frozen." : "Task resumed; deadline extended by pause duration.");
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Archive a task without permanently removing its history.
  async function archiveTask(task) {
    if (!confirm('Delete "' + task.title + '" from the task list? It will be removed from active lists, while its history and audit record are retained.')) return;
    try {
      const result = await api("/tasks/" + task.id, token, { method: "DELETE" });
      notify(result.message);
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Accept, decline, complete or otherwise manage a shared task response.
  async function manageCommonTask(item, action) {
    if (action === "delete" && !confirm('Archive common mission "' + item.title + '"? Existing accepted task copies are kept.')) return;
    let reason = "";
    if (action === "pause") {
      reason = prompt("Why are you pausing this common mission?") || "";
      if (reason.trim().length < 5) return;
    }
    try {
      if (action === "delete") {
        const result = await api("/common-tasks/" + item.id, token, { method: "DELETE" });
        notify(result.message);
      } else {
        const state = action === "pause" ? "Suspended" : "Active";
        await api("/common-tasks/" + item.id + "/state", token, {
          method: "POST", body: JSON.stringify({ state, reason }),
        });
        notify(action === "pause" ? "Common mission paused." : "Common mission reopened.");
      }
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Enable or disable a recurring daily task schedule.
  async function toggleDailySchedule(schedule) {
    try {
      const result = await api("/task-schedules/" + schedule.id + "/toggle", token, { method: "POST" });
      notify(result.message);
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Remove a daily task schedule from the management list.
  async function deleteDailySchedule(schedule) {
    if (!confirm('Stop creating "' + schedule.title + '" every day? Already generated tasks will remain.')) return;
    try {
      const result = await api("/task-schedules/" + schedule.id, token, { method: "DELETE" });
      notify(result.message);
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Save the automatic daily mission generation settings.
  async function saveAutoTaskSettings() {
    setAutoTaskBusy(true);
    try {
      const result = await api("/auto-tasks/settings", token, {
        method: "PUT",
        body: JSON.stringify({
          mode: autoTaskSettings.mode,
          daily_target: Number(autoTaskSettings.daily_target),
          auto_archive_enabled: Boolean(autoTaskSettings.auto_archive_enabled),
          auto_archive_after_days: Number(autoTaskSettings.auto_archive_after_days),
        }),
      });
      setAutoTaskSettings(result);
      notify("Daily generation settings saved.");
    } catch (e) { fail(e); }
    finally { setAutoTaskBusy(false); }
  }

  // Purpose: Run the completed-task auto-archive cleanup on demand.
  async function runAutoArchiveNow() {
    if (!autoTaskSettings.auto_archive_enabled) return;
    if (!confirm("Archive all completed tasks and closed shared missions older than " + Number(autoTaskSettings.auto_archive_after_days) + " days? Active, paused and review tasks will remain untouched.")) return;
    setAutoTaskBusy(true);
    try {
      const result = await api("/auto-tasks/archive-now", token, { method: "POST" });
      await refresh();
      notify(result.message || (result.total_archived || 0) + " eligible task(s) archived.");
    } catch (e) { fail(e); }
    finally { setAutoTaskBusy(false); }
  }

  // Purpose: Ask the backend to generate the daily shared coding missions immediately.
  async function generateAutoTasksNow() {
    setAutoTaskBusy(true);
    try {
      const result = await api("/auto-tasks/generate", token, { method: "POST" });
      await refresh();
      notify(result.generated ? result.generated + " new daily missions published." : "Today's generation target is already reached.");
    } catch (e) { fail(e); }
    finally { setAutoTaskBusy(false); }
  }

  // Purpose: Apply a temporary member suspension and optional credit penalty.
  async function disciplineMember(member) {
    const reason = prompt("Rule violation / reason (at least 5 characters):");
    if (!reason || reason.trim().length < 5) return;
    const hoursValue = prompt("Temporary suspension duration in hours (1–720):", "24");
    if (hoursValue === null) return;
    const duration_hours = Number(hoursValue);
    if (!Number.isInteger(duration_hours) || duration_hours < 1 || duration_hours > 720) {
      fail(new Error("Enter a suspension duration from 1 to 720 hours."));
      return;
    }
    const penaltyValue = prompt("Credit penalty (0–500 credits):", "0");
    if (penaltyValue === null) return;
    const credit_penalty = Number(penaltyValue);
    if (!Number.isInteger(credit_penalty) || credit_penalty < 0 || credit_penalty > 500) {
      fail(new Error("Enter a whole-number credit penalty from 0 to 500."));
      return;
    }
    if (!confirm("Apply a " + duration_hours + " hour suspension and deduct " + credit_penalty + " credits from " + member.name + "?")) return;
    try {
      const result = await api("/members/" + member.id + "/suspend", token, {
        method: "POST",
        body: JSON.stringify({ reason: reason.trim(), duration_hours, credit_penalty }),
      });
      notify(result.message + " · Ends " + new Date(result.suspension_until).toLocaleString());
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Restore a suspended member's portal access.
  async function reinstateMember(member) {
    if (!confirm("Reinstate " + member.name + " now?")) return;
    try {
      await api("/members/" + member.id + "/reinstate", token, { method: "POST" });
      notify("Member reinstated. A new digital ID may be issued.");
      await refresh();
    } catch (e) { fail(e); }
  }

  // Purpose: Record a member's response to a shared task.
  async function respondToCommonTask(task, response) {
    if (busy) return;
    setBusy(true);
    try {
      const result = await api("/common-tasks/" + task.id + "/respond", token, {
        method: "POST",
        body: JSON.stringify({ response }),
      });
      setCommonTasks((rows) => rows.map((row) =>
        row.id === task.id ? { ...row, response_status: response } : row
      ));
      setSelectedTaskDetail((current) =>
        current?.id === task.id ? { ...current, response_status: response } : current
      );
      notify(result.message || (response === "accepted" ? "Task accepted and added to your task list." : "Mission declined."));
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Mark one inbox notification as read.
  async function markNotificationRead(item) {
    try {
      if (!item.read) {
        await api("/notifications/" + item.id + "/read", token, { method: "POST" });
        setNotifications((rows) => rows.map((row) =>
          row.id === item.id ? { ...row, read: true } : row
        ));
      }
      if (item.type === "task_review") await refresh();
      setPage(
        item.type === "common_task" || item.type === "task_assigned" ||
        item.type === "common_task_response" || item.type === "task_review" ||
        item.type === "task_approved"
          ? "Tasks & Projects"
          : "Notifications"
      );
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Upload a supporting file to a task.
  async function uploadAttachment(taskId, file) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api(`/tasks/${taskId}/attachments`, token, {
        method: "POST",
        body: fd,
      });
      notify("Attachment uploaded");
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Download an attachment from the task review workflow.
  async function downloadReviewAttachment(file) {
    try {
      const response = await fetch(
        API_BASE + "/api/attachments/" + file.id + "/download",
        { headers: { Authorization: "Bearer " + token } }
      );
      if (!response.ok) {
        let detail = {};
        try { detail = await response.json(); } catch {}
        throw new Error(detail.detail || "Could not download " + file.filename);
      }
      const objectUrl = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = objectUrl;
      link.download = file.filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 1000);
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Prepare the task submission editor for the selected task.
  function openTaskSubmission(task) {
    setSubmissionForm({
      taskId: task.id,
      title: task.title,
      submission_evidence_url: "",
      project_url: task.project_url || "",
      submission_note: "",
      submission_attested: false,
    });
    setModal("taskSubmission");
  }

  // Purpose: Send a completed task submission to management for review.
  async function submitTaskForReview(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api(`/tasks/${submissionForm.taskId}`, token, {
        method: "PATCH",
        body: JSON.stringify({
          status: "Review",
          submission_evidence_url: submissionForm.submission_evidence_url.trim(),
          project_url: submissionForm.project_url.trim() || null,
          submission_note: submissionForm.submission_note.trim(),
          submission_attested: submissionForm.submission_attested,
        }),
      });
      setModal("");
      setSubmissionForm({
        taskId: "",
        title: "",
        submission_evidence_url: "",
        project_url: "",
        submission_note: "",
        submission_attested: false,
      });
      notify("Evidence submitted — task is now in review");
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Return a task submission to the member with a request for changes.
  async function requestTaskChanges(task) {
    const feedback = window.prompt(
      "What must the member fix before approval?",
      task.review_feedback || ""
    );
    if (feedback === null) return;
    if (!feedback.trim()) {
      fail(new Error("Enter a short reason before returning this task"));
      return;
    }
    setBusy(true);
    try {
      await api(`/tasks/${task.id}`, token, {
        method: "PATCH",
        body: JSON.stringify({ status: "In progress", review_feedback: feedback.trim() }),
      });
      notify("Task returned to the member for changes");
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  // Purpose: Update task details or status.
  async function updateTask(t, patch) {
    try {
      await api(`/tasks/${t.id}`, token, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      await refresh();
      notify("Task updated");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Issue a digital ID card to a member.
  async function issueCard(m) {
    try {
      let r = await api(`/cards/${m.id}/issue`, token, { method: "POST" });
      setIssuedCard(r);
      setSelected(m);
      notify("Secure card token issued");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Revoke the active digital ID card for a member.
  async function revokeCard(m) {
    try {
      await api(`/cards/${m.id}/revoke`, token, { method: "POST" });
      setIssuedCard(null);
      notify("Card revoked");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Extract the verification token from a pasted QR code URL or token string.
  function extractCardToken(value) {
    let candidate = (value || "").trim();
    if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
      const u = new URL(candidate);
      candidate = u.pathname.split("/").filter(Boolean).pop() || "";
    }
    return candidate;
  }

  // Purpose: Load pending task-completion confirmations for the scanned member ID.
  async function loadPendingReviewTasksFor(result) {
    if (!result?.valid || !result.member_id) {
      setPendingReviewTasks([]);
      setReviewQueueMemberId("");
      return;
    }
    const rows = await api(
      "/tasks/pending-confirmation?member_id=" + encodeURIComponent(result.member_id),
      token
    );
    setPendingReviewTasks(rows);
    setReviewQueueMemberId(result.member_id);
  }

  // Purpose: Verify an ID card token entered or scanned by management.
  async function verify(e) {
    e?.preventDefault();
    try {
      let candidate = extractCardToken(verifyToken);
      if (!candidate) {
        throw new Error("Scan a QR code or paste its verification URL");
      }
      setPendingReviewTasks([]);
      setReviewQueueMemberId("");
      let v = await api("/verify/" + encodeURIComponent(candidate), token);
      setVerifyResult(v);
      await loadPendingReviewTasksFor(v);
    } catch (e) {
      setVerifyResult({ valid: false, status: e.message });
      setPendingReviewTasks([]);
      setReviewQueueMemberId("");
    }
  }

  // Purpose: Confirm a successful ID-card scan and record the verification action.
  async function confirmVerification() {
    try {
      const candidate = extractCardToken(verifyToken);
      const result = await api(
        "/verify/" + encodeURIComponent(candidate) + "/confirm",
        token,
        { method: "POST" }
      );
      notify(result.message);
      setVerifyResult({ ...verifyResult, confirmed: true });
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Confirm a member's task completion after checking the ID card.
  async function confirmTaskCompletion(task) {
    try {
      const cardToken = extractCardToken(verifyToken);
      if (!cardToken) throw new Error("Scan the assignee's QR code first");
      await api(`/tasks/${task.id}/confirm-completion`, token, {
        method: "POST",
        body: JSON.stringify({ card_token: cardToken }),
      });
      setPendingReviewTasks((rows) => rows.filter((row) => row.id !== task.id));
      await refresh();
      notify("Task completion confirmed");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Create a new development team.
  async function createTeam(e) {
    e.preventDefault();
    try {
      await api("/teams", token, {
        method: "POST",
        body: JSON.stringify({
          name: e.target.name.value,
          description: e.target.description.value,
        }),
      });
      setModal("");
      await refresh();
      notify("Team created");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Save the signed-in member's editable profile information.
  async function saveProfile(e) {
    e.preventDefault();
    try {
      let updated = await api("/auth/profile", token, {
        method: "PATCH",
        body: JSON.stringify({ name: profileForm.name || user.name }),
      });
      setUser(updated);
      notify("Profile saved");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Request a password-reset link for the supplied email address.
  async function requestReset(e) {
    e.preventDefault();
    try {
      let r = await api("/auth/password-reset/request", "", {
        method: "POST",
        body: JSON.stringify({ email: resetEmail }),
      });
      if (r.development_reset_token) {
        setResetToken(r.development_reset_token);
      }
      notify(r.message);
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Set a new password using a valid password-reset token.
  async function confirmReset(e) {
    e.preventDefault();
    try {
      let r = await api("/auth/password-reset/confirm", "", {
        method: "POST",
        body: JSON.stringify({
          token: resetToken,
          new_password: resetPassword,
        }),
      });
      notify(r.message);
      setResetToken("");
      setResetPassword("");
      setAuthMode("login");
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Change the signed-in member's password after checking the current password.
  async function changePassword(e) {
    e.preventDefault();
    try {
      let r = await api("/auth/change-password", token, {
        method: "POST",
        body: JSON.stringify(settingsForm),
      });
      notify(r.message);
      setSettingsForm({ current_password: "", new_password: "" });
    } catch (e) {
      fail(e);
    }
  }

  // Purpose: Load the founder-only audit history.
  async function loadAudit() {
    try {
      setAudit(await api("/audit?limit=100", token));
    } catch (e) {
      fail(e);
    }
  }

  // Expose stable handler names for the JSX screen coordinator.
  return {
    login,
    logout,
    refresh,
    createMember,
    updateMember,
    approveMember,
    createAnnouncement,
    createTask,
    approveSelectedTasks,
    toggleTaskPause,
    archiveTask,
    manageCommonTask,
    toggleDailySchedule,
    deleteDailySchedule,
    saveAutoTaskSettings,
    generateAutoTasksNow,
    runAutoArchiveNow,
    disciplineMember,
    reinstateMember,
    respondToCommonTask,
    markNotificationRead,
    uploadAttachment,
    downloadReviewAttachment,
    openTaskSubmission,
    submitTaskForReview,
    requestTaskChanges,
    updateTask,
    issueCard,
    revokeCard,
    extractCardToken,
    loadPendingReviewTasksFor,
    verify,
    confirmVerification,
    confirmTaskCompletion,
    createTeam,
    saveProfile,
    requestReset,
    confirmReset,
    changePassword,
    loadAudit
  };
}
