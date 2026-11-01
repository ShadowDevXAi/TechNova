import React, { useEffect, useState } from "react";
import TechNovaHub from "./TechNovaHub";
import PushNotificationSettings from "./components/PushNotificationSettings.jsx";
import TwoFactorSettings from "./components/TwoFactorSettings.jsx";
import StorageSettings from "./components/StorageSettings.jsx";
import ContactNotificationSettings from "./components/ContactNotificationSettings.jsx";
import { listenForForegroundMessages } from "./firebase.js";
import { api, API_BASE } from "./api/client.js";
import TechNovaLogo from "./components/TechNovaLogo.jsx";
import { links } from "./config/navigation.js";
import { formatBytes, initials } from "./utils/formatters.js";
import useWorkspaceData from "./hooks/useWorkspaceData.js";
import useWorkspacePolling from "./hooks/useWorkspacePolling.js";
import createPortalActions from "./services/portalActions.js";
import { createPortal } from "react-dom";
import {
  LayoutDashboard,
  Users,
  ClipboardList,
  CreditCard,
  ShieldCheck,
  FolderKanban,
  Settings,
  Bell,
  Search,
  Plus,
  ArrowUpRight,
  Code2,
  Check,
  Menu,
  X,
  Download,
  LogOut,
  RefreshCw,
  UserCheck,
  LockKeyhole,
  AlertTriangle,
  Trophy,
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { Html5QrcodeScanner } from "html5-qrcode";


// Shared API, branding, navigation and formatting utilities are imported above.

/**
 * Main portal coordinator: owns the authenticated session, shared workspace state,
 * screen selection and event callbacks passed to the portal UI.
 */
function App() {
  const [token, setToken] = useState(localStorage.getItem("tn_token") || "");
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("Overview");
  const [members, setMembers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [commonTasks, setCommonTasks] = useState([]);
  const [dailySchedules, setDailySchedules] = useState([]);
  const [leaderboard, setLeaderboard] = useState({ top_10: [], top_three: [], my_entry: null });
  const [creditLedger, setCreditLedger] = useState({ balance: 0, earned_total: 0, penalized_total: 0, entries: [] });
  const [notifications, setNotifications] = useState([]);
  const [reviewQueue, setReviewQueue] = useState([]);
  const [selectedReviewIds, setSelectedReviewIds] = useState([]);
  const [reviewSearch, setReviewSearch] = useState("");
  const [assigneeSearch, setAssigneeSearch] = useState("");
  const [taskStatusFilter, setTaskStatusFilter] = useState("All");
  const [selectedTaskDetail, setSelectedTaskDetail] = useState(null);
  const [announcementForm, setAnnouncementForm] = useState({ title: "", message: "" });
  const [submissionForm, setSubmissionForm] = useState({
    taskId: "",
    title: "",
    submission_evidence_url: "",
    project_url: "",
    submission_note: "",
    submission_attested: false,
  });
  const [teams, setTeams] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [databaseStats, setDatabaseStats] = useState(null);
  const [autoTaskSettings, setAutoTaskSettings] = useState({ mode: "custom", daily_target: 5, unlimited_daily_cap: 20, generated_today: 0, open_today: 0, total_generated: 0, remaining_today: 5, auto_archive_enabled: true, auto_archive_after_days: 30 });
  const [autoTaskBusy, setAutoTaskBusy] = useState(false);
  const [emailStatus, setEmailStatus] = useState(null);
  const [emailTestBusy, setEmailTestBusy] = useState(false);
  const [twoFactorFlow, setTwoFactorFlow] = useState(null);
  const [twoFactorSetup, setTwoFactorSetup] = useState(null);
  const [twoFactorCode, setTwoFactorCode] = useState("");
  const [twoFactorRecoveryCodes, setTwoFactorRecoveryCodes] = useState([]);
  const [twoFactorPendingSession, setTwoFactorPendingSession] = useState(null);
  const [trustDevice, setTrustDevice] = useState(true);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [modal, setModal] = useState("");
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const [authNotice, setAuthNotice] = useState("");
  const [verificationResendBusy, setVerificationResendBusy] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [authMode, setAuthMode] = useState("login");
  const [resetToken, setResetToken] = useState("");
  const [resetEmail, setResetEmail] = useState("");
  const [resetPassword, setResetPassword] = useState("");
  const [auth, setAuth] = useState({
    name: "",
    email: "",
    password: "",
    team: "Unassigned",
  });
  const [memberForm, setMemberForm] = useState({
    name: "",
    email: "",
    password: "",
    role: "Member",
    team: "Unassigned",
    status: "Active",
  });
  const [taskForm, setTaskForm] = useState({
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
  const [verifyToken, setVerifyToken] = useState("");
  const [verifyResult, setVerifyResult] = useState(null);
  const [pendingReviewTasks, setPendingReviewTasks] = useState([]);
  const [reviewQueueMemberId, setReviewQueueMemberId] = useState("");
  const [autoVerifyRoute, setAutoVerifyRoute] = useState(false);
  const [issuedCard, setIssuedCard] = useState(null);
  const [ownCard, setOwnCard] = useState(null);
  const [selectedProgress, setSelectedProgress] = useState(null);
  const [progressLoading, setProgressLoading] = useState(false);
  const [progressError, setProgressError] = useState("");
  const [scanEnabled, setScanEnabled] = useState(false);
  const [cardRoleFilter, setCardRoleFilter] = useState("Founder");
  const [settingsForm, setSettingsForm] = useState({
    current_password: "",
    new_password: "",
  });
  const [profileForm, setProfileForm] = useState({ name: "" });
  const [audit, setAudit] = useState([]);

  // Show a short success toast after a member or management action completes.
  const notify = (s) => {
    setToast(s);
    setTimeout(() => setToast(""), 3000);
  };

  // Include the server request ID when available so a Render log entry can be located.
  const fail = (e) => {
    const message = e.message || "Something went wrong";
    setError(e.requestId ? message + " (Error ID: " + e.requestId + ")" : message);
  };

  // Purpose: Ask for a new email verification link without exposing account existence.
  async function resendEmailVerification() {
    if (!auth.email.trim()) {
      setError("Enter your email address first.");
      return;
    }
    setVerificationResendBusy(true);
    setError("");
    setAuthNotice("");
    try {
      const result = await api("/auth/email-verification/resend", "", {
        method: "POST",
        body: JSON.stringify({ email: auth.email.trim() }),
      });
      setAuthNotice(result.message);
    } catch (err) {
      setError(err.message || "Could not request a verification email.");
    } finally {
      setVerificationResendBusy(false);
    }
  }

  // Initial workspace loading and background refresh are managed by dedicated hooks.
  const load = useWorkspaceData({
    token, selected,
    setError, setToken, setUser, setDashboard, setDatabaseStats,
    setAutoTaskSettings, setMembers, setTasks, setTeams, setCommonTasks,
    setDailySchedules, setLeaderboard, setCreditLedger, setNotifications,
    setReviewQueue, setSelectedReviewIds, setSelected,
  });
  useWorkspacePolling({
    token, user, page,
    setTasks, setNotifications, setDashboard, setDatabaseStats,
    setCommonTasks, setAutoTaskSettings, setReviewQueue, setSelectedReviewIds, setAudit,
  });

  // Keep navigation usable on short screens and on mobile devices.
  useEffect(() => {
    if (!mobile) return undefined;
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    const onKeyDown = (event) => {
      if (event.key === "Escape") setMobile(false);
    };
    const onResize = () => {
      if (window.innerWidth > 760) setMobile(false);
    };
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("resize", onResize);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("resize", onResize);
    };
  }, [mobile]);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "auto" });
    setSearch("");
  }, [page]);

  useEffect(() => {
    const p = window.location.pathname.match(/^\/verify\/([^/]+)$/);
    if (p) {
      setPage("Verification");
      setVerifyToken(decodeURIComponent(p[1]));
      setVerifyResult(null);
      setAutoVerifyRoute(true);
    }
    const params = new URLSearchParams(window.location.search);
    const emailToken = params.get("verify_email");
    if (emailToken) {
      api("/auth/email-verification/confirm", "", {
        method: "POST",
        body: JSON.stringify({ token: emailToken }),
      }).then((result) => {
        setAuthNotice(result.message || "Email verified. You can sign in after administrator approval.");
        setAuthMode("login");
        setAuth((current) => ({ ...current, password: "" }));
      }).catch((err) => {
        setError(err.message || "Email verification failed. Request a new link.");
      }).finally(() => {
        params.delete("verify_email");
        const query = params.toString();
        window.history.replaceState({}, "", window.location.pathname + (query ? "?" + query : "") + window.location.hash);
      });
    }
  }, []);

  useEffect(() => {
    if (!autoVerifyRoute || !token || !user || page !== "Verification" || !verifyToken) return;
    let cancelled = false;
    const candidate = extractCardToken(verifyToken);
    api("/verify/" + encodeURIComponent(candidate), token)
      .then(async (result) => {
        if (cancelled) return;
        setVerifyResult(result);
        setAutoVerifyRoute(false);
        try {
          await loadPendingReviewTasksFor(result);
        } catch (err) {
          if (!cancelled) fail(err);
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setVerifyResult({ valid: false, status: err.message });
          setPendingReviewTasks([]);
          setReviewQueueMemberId("");
          setAutoVerifyRoute(false);
        }
      });
    return () => { cancelled = true; };
  }, [autoVerifyRoute, token, user?.id, page, verifyToken]);

  // Load progression for the selected cardholder, not only the signed-in administrator.
  // Refresh occasionally so newly approved tasks appear while the ID card stays open.
  useEffect(() => {
    if (page !== "Digital ID Cards" || !token || !selected?.id) {
      setSelectedProgress(null);
      setProgressLoading(false);
      setProgressError("");
      return undefined;
    }

    let cancelled = false;
    const loadProgress = async () => {
      setProgressLoading(true);
      try {
        const snapshot = await api(
          "/members/" + encodeURIComponent(selected.id) + "/progress",
          token
        );
        if (!cancelled) {
          setSelectedProgress(snapshot);
          setProgressError("");
        }
      } catch (err) {
        if (!cancelled) {
          setProgressError(err.message || "Member progress could not be loaded.");
        }
      } finally {
        if (!cancelled) setProgressLoading(false);
      }
    };

    setSelectedProgress(null);
    loadProgress();
    const timer = window.setInterval(loadProgress, 60000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [page, token, selected?.id]);

  useEffect(() => {
    if (page !== "Digital ID Cards" || !token || !user ||
        selected?.id !== user.id || ownCard?.member_id === user.member_id) return;
    let cancelled = false;
    api("/cards/me/issue", token, { method: "POST" })
      .then((card) => { if (!cancelled) setOwnCard(card); })
      .catch((err) => { if (!cancelled) fail(err); });
    return () => { cancelled = true; };
  }, [page, token, user?.id, user?.member_id, selected?.id, ownCard?.member_id]);

  useEffect(() => {
    if (!scanEnabled || page !== "Verification" || !isAdmin) return;
    let scanner;
    try {
      scanner = new Html5QrcodeScanner(
        "technova-qr-reader",
        {
          fps: 10,
          qrbox: { width: 230, height: 230 },
          rememberLastUsedCamera: true,
        },
        false
      );
      scanner.render(
        async (decodedText) => {
          setVerifyToken(decodedText);
          setScanEnabled(false);
          let candidate = decodedText.trim();
          try {
            if (
              candidate.startsWith("http://") ||
              candidate.startsWith("https://")
            ) {
              const u = new URL(candidate);
              candidate = u.pathname.split("/").filter(Boolean).pop() || "";
            }
            setPendingReviewTasks([]);
            setReviewQueueMemberId("");
            const result = await api(
              "/verify/" + encodeURIComponent(candidate),
              token
            );
            setVerifyResult(result);
            await loadPendingReviewTasksFor(result);
          } catch (err) {
            setVerifyResult({ valid: false, status: err.message });
            setPendingReviewTasks([]);
            setReviewQueueMemberId("");
          }
          try {
            await scanner.clear();
          } catch {}
        },
        () => {}
      );
    } catch (err) {
      setError(
        "Camera scanner could not start. Allow camera access or paste the QR URL instead."
      );
      setScanEnabled(false);
    }
    return () => {
      if (scanner) {
        scanner.clear().catch(() => {});
      }
    };
  }, [scanEnabled, page]);

  // Shared role flags control management-only controls throughout the portal.
  const isAdmin = user && ["Founder", "Core Management"].includes(user.role);
  const isFounder = user?.role === "Founder";

  // Build the action layer once per render from the state needed by portal operations.
  const {
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
    checkEmailStatus,
    sendTestEmail,
    completeTwoFactorSetup,
    completeTwoFactorLogin,
    finishTwoFactorSetup,
    cancelTwoFactorFlow,
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
  } = createPortalActions({
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
    setAuthNotice,
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
    emailStatus,
    setEmailStatus,
    emailTestBusy,
    setEmailTestBusy,
    twoFactorFlow,
    setTwoFactorFlow,
    twoFactorSetup,
    setTwoFactorSetup,
    twoFactorCode,
    setTwoFactorCode,
    twoFactorRecoveryCodes,
    setTwoFactorRecoveryCodes,
    twoFactorPendingSession,
    setTwoFactorPendingSession,
    trustDevice,
    setTrustDevice,
    api,
    API_BASE,
    notify,
    fail,
    load,
    isAdmin,
    isFounder
  });



  // Derived view data: keep search and status filtering out of the JSX markup.
  const filteredMembers = members.filter((m) =>
    (m.name + " " + m.member_id + " " + m.team + " " + m.email)
      .toLowerCase()
      .includes(search.toLowerCase())
  );
  const eligibleAssignees = members.filter(
    (m) =>
      m.status === "Active" &&
      (isFounder
        ? ["Core Management", "Member"].includes(m.role)
        : m.role === "Member")
  );
  const filteredAssignees = eligibleAssignees.filter((m) =>
    (m.name + " " + m.member_id + " " + m.team)
      .toLowerCase()
      .includes(assigneeSearch.toLowerCase())
  );
  const filteredReviewQueue = reviewQueue.filter((task) =>
    (task.title + " " + task.assignee_name + " " + task.assignee_member_id + " " + task.assignee_team + " " + task.submission_note)
      .toLowerCase()
      .includes(reviewSearch.toLowerCase())
  );
  const filteredTaskRows = tasks.filter((task) => {
    const matchesSearch = (task.title + " " + task.assignee_name + " " + task.project)
      .toLowerCase()
      .includes(search.toLowerCase());
    return matchesSearch && (taskStatusFilter === "All" || task.status === taskStatusFilter);
  });
  const taskStatusCounts = {
    All: tasks.length,
    Todo: tasks.filter((task) => task.status === "Todo").length,
    "In progress": tasks.filter((task) => task.status === "In progress").length,
    Review: tasks.filter((task) => task.status === "Review").length,
    Done: tasks.filter((task) => task.status === "Done").length,
  };
  const unreadNotifications = notifications.filter((item) => !item.read).length;

  // Surface push messages immediately while the portal tab is open.
  useEffect(() => {
    if (!token || !user) return undefined;
    let active = true;
    let unsubscribe = () => {};
    listenForForegroundMessages((payload) => {
      const title = payload?.notification?.title || payload?.data?.title || "TechNova update";
      const body = payload?.notification?.body || payload?.data?.body || "You have a new club notification.";
      if ("Notification" in window && Notification.permission === "granted") {
        try { new Notification(title, { body }); } catch {}
      }
    }).then((stop) => {
      if (active) unsubscribe = stop;
      else stop();
    }).catch(() => {});
    return () => {
      active = false;
      unsubscribe();
    };
  }, [token, user?.id]);

  if (twoFactorFlow) {
    return (
      <div className="authscreen">
        <div className="authbrand">
          <div className="logo"><TechNovaLogo /></div>
          <div><b>Tech<span>Nova</span></b><small>TECHNOLOGY DEVELOPMENT CLUB</small></div>
        </div>
        <div className="authcard two-factor-auth-card">
          <div className="eyebrow"><LockKeyhole size={14} /> MANAGEMENT ACCOUNT SECURITY</div>
          {twoFactorFlow.mode === "setup" && (
            <>
              <h1>Secure your account.</h1>
              <p>Founder and Core Management accounts must use an authenticator app. Scan this QR code with Google Authenticator, Microsoft Authenticator, 1Password or another TOTP app.</p>
              {twoFactorSetup?.provisioning_uri ? (
                <div className="two-factor-qr">
                  <QRCodeSVG value={twoFactorSetup.provisioning_uri} size={190} level="M" />
                  <small>Can't scan? Add this setup key manually:</small>
                  <code>{twoFactorSetup.secret}</code>
                  <small>Account: {twoFactorSetup.account} · Issuer: {twoFactorSetup.issuer}</small>
                </div>
              ) : <p>Preparing your secure authenticator setup…</p>}
              <form onSubmit={completeTwoFactorSetup}>
                <label>6-digit authenticator code
                  <input required inputMode="numeric" autoComplete="one-time-code" pattern="[0-9 ]{6,8}" maxLength="8" value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} placeholder="123456" />
                </label>
                <label className="two-factor-trust-option">
                  <input type="checkbox" checked={trustDevice} onChange={(e) => setTrustDevice(e.target.checked)} />
                  <span>Trust this browser for 30 days</span>
                </label>
                <button className="primary full" disabled={busy || !twoFactorSetup?.secret}>{busy ? "Verifying…" : "Enable two-factor authentication"}</button>
              </form>
            </>
          )}
          {twoFactorFlow.mode === "verify" && (
            <>
              <h1>Verify it's you.</h1>
              <p>Enter the current 6-digit code from your authenticator app. You can also enter one unused recovery code.</p>
              <form onSubmit={completeTwoFactorLogin}>
                <label>Authenticator or recovery code
                  <input required autoFocus autoComplete="one-time-code" value={twoFactorCode} onChange={(e) => setTwoFactorCode(e.target.value)} placeholder="6-digit code or recovery code" />
                </label>
                <label className="two-factor-trust-option">
                  <input type="checkbox" checked={trustDevice} onChange={(e) => setTrustDevice(e.target.checked)} />
                  <span>Trust this browser for 30 days</span>
                </label>
                <button className="primary full" disabled={busy || !twoFactorCode.trim()}>{busy ? "Verifying…" : "Verify and sign in"}</button>
              </form>
            </>
          )}
          {twoFactorFlow.mode === "recovery" && (
            <>
              <h1>Save your recovery codes.</h1>
              <p>Authenticator protection is enabled. These codes can each be used once if you lose access to your authenticator. They will not be shown again.</p>
              <div className="two-factor-recovery-grid">
                {twoFactorRecoveryCodes.map((code) => <code key={code}>{code}</code>)}
              </div>
              <button className="primary full" onClick={finishTwoFactorSetup} disabled={!twoFactorPendingSession}>I've saved my recovery codes — continue</button>
            </>
          )}
          {error && <div className="errorbox"><AlertTriangle size={16} />{error}</div>}
          {twoFactorFlow.mode !== "recovery" && (
            <div className="authswitch">
              <button type="button" onClick={cancelTwoFactorFlow}>Cancel and return to sign in</button>
            </div>
          )}
          <div className="authhint">Do not share authenticator codes or recovery codes with anyone, including club staff.</div>
        </div>
        <div className="authfooter">TECHNOVA · CREATE • CODE • INNOVATE</div>
      </div>
    );
  }

  if (!token || !user) {
    return (
      <div className="authscreen">
        <div className="authbrand">
          <div className="logo"><TechNovaLogo /></div>
          <div>
            <b>
              Tech<span>Nova</span>
            </b>
            <small>TECHNOLOGY DEVELOPMENT CLUB</small>
          </div>
        </div>
        <div className="authcard">
          <div className="eyebrow">
            <LockKeyhole size={14} /> SECURE CLUB WORKSPACE
          </div>
          <h1>
            {authMode === "login"
              ? "Welcome back."
              : authMode === "register"
              ? "Join TechNova."
              : "Reset your password."}
          </h1>
          <p>
            {authMode === "login"
              ? "Sign in to manage projects, tasks, and your digital club ID."
              : authMode === "register"
              ? "Create your student account. A club administrator must approve it."
              : "Request a reset token, then set a new password."}
          </p>
          {authNotice && <div className="auth-success-notice" role="status">{authNotice}</div>}
          {error && (
            <div className="errorbox">
              <AlertTriangle size={16} />
              {error}
            </div>
          )}
          <form
            onSubmit={
              authMode === "reset"
                ? resetToken
                  ? confirmReset
                  : requestReset
                : login
            }
          >
            {authMode === "reset" ? (
              <>
                {!resetToken && (
                  <label>
                    Email address
                    <input
                      type="email"
                      required
                      value={resetEmail}
                      onChange={(e) => setResetEmail(e.target.value)}
                      placeholder="you@example.com"
                    />
                  </label>
                )}
                {resetToken && (
                  <>
                    <label>
                      Reset token
                      <input
                        required
                        value={resetToken}
                        onChange={(e) => setResetToken(e.target.value)}
                      />
                    </label>
                    <label>
                      New password
                      <input
                        type="password"
                        required
                        minLength="12"
                        value={resetPassword}
                        onChange={(e) => setResetPassword(e.target.value)}
                      />
                    </label>
                  </>
                )}
              </>
            ) : (
              <>
                {authMode === "register" && (
                  <label>
                    Full name
                    <input
                      required
                      minLength="2"
                      value={auth.name}
                      onChange={(e) =>
                        setAuth({ ...auth, name: e.target.value })
                      }
                      placeholder="Your full name"
                    />
                  </label>
                )}
                <label>
                  Email address
                  <input
                    type="email"
                    required
                    value={auth.email}
                    onChange={(e) =>
                      setAuth({ ...auth, email: e.target.value })
                    }
                    placeholder="you@example.com"
                  />
                </label>
                <label>
                  Password
                  <input
                    type="password"
                    required
                    minLength={authMode === "register" ? 12 : 1}
                    value={auth.password}
                    onChange={(e) =>
                      setAuth({ ...auth, password: e.target.value })
                    }
                    placeholder={
                      authMode === "register"
                        ? "At least 12 characters"
                        : "Your password"
                    }
                  />
                </label>
                {authMode === "register" && (
                  <label>
                    Preferred team
                    <input
                      value={auth.team}
                      onChange={(e) =>
                        setAuth({ ...auth, team: e.target.value })
                      }
                      placeholder="e.g. Web Development"
                    />
                  </label>
                )}
              </>
            )}
            <button className="primary full" disabled={busy}>
              {busy
                ? "Please wait…"
                : authMode === "login"
                ? "Sign in"
                : authMode === "register"
                ? "Submit registration"
                : resetToken
                ? "Set new password"
                : "Request reset token"}
            </button>
          </form>
          <div className="authswitch">
            {authMode === "login"
              ? "New to TechNova?"
              : authMode === "register"
              ? "Already registered?"
              : "Back to sign in?"}{" "}
            <button
              onClick={() => {
                setAuthMode(authMode === "login" ? "register" : "login");
                setError("");
                setAuthNotice("");
              }}
            >
              {authMode === "login" ? "Create an account" : "Sign in"}
            </button>{" "}
            {authMode === "login" && (
              <>
                <button type="button" onClick={resendEmailVerification} disabled={verificationResendBusy}>
                  {verificationResendBusy ? "Sending…" : "Resend verification email"}
                </button>
                <button
                  type="button"
                  onClick={() => {
                    setAuthMode("reset");
                    setResetToken("");
                    setError("");
                    setAuthNotice("");
                  }}
                >
                  Forgot password?
                </button>
              </>
            )}
          </div>
          <div className="authhint">
            Public registration creates a pending Member account. Founder/Core
            roles can only be granted by authorized club management.
          </div>
        </div>
        <div className="authfooter">TECHNOVA · CREATE • CODE • INNOVATE</div>
      </div>
    );
  }

  return (
    <div className="shell">
      {mobile && (
        <button
          className="sidebar-backdrop"
          aria-label="Close navigation menu"
          onClick={() => setMobile(false)}
        />
      )}
      <aside
        id="technova-main-navigation"
        className={mobile ? "sidebar open" : "sidebar"}
        aria-label="Main navigation"
        aria-hidden={window.innerWidth <= 760 && !mobile}
      >
        <div className="brand">
          <div className="logo"><TechNovaLogo /></div>
          <div>
            <b>
              Tech<span>Nova</span>
            </b>
            <small>TECHNOLOGY DEVELOPMENT CLUB</small>
          </div>
          <button className="close" aria-label="Close navigation menu" onClick={() => setMobile(false)}>
            <X />
          </button>
        </div>
        <div className="workspace">
          <span className="workspace-logo"><TechNovaLogo /></span>
          <div>
            <b>TechNova Club</b>
            <small>{user.role} workspace</small>
          </div>
        </div>
        <label className="navlabel">WORKSPACE</label>
        {links.slice(0, 5).map(([n, I]) => (
          <button
            className={"nav " + (page === n ? "chosen" : "")}
            key={n}
            onClick={() => {
              setPage(n);
              setMobile(false);
            }}
          >
            <I size={17} />
            {n}
          </button>
        ))}
        <label className="navlabel">MANAGE</label>
        {links.slice(5).filter(([n]) => n !== "Verification" || isAdmin).map(([n, I]) => (
          <button
            className={"nav " + (page === n ? "chosen" : "")}
            key={n}
            onClick={() => {
              setPage(n);
              setMobile(false);
            }}
          >
            <I size={17} />
            {n}
          </button>
        ))}
        {isFounder && (
          <button
            className={"nav " + (page === "Audit Log" ? "chosen" : "")}
            onClick={() => {
              setPage("Audit Log");
              setMobile(false);
            }}
          >
            <ShieldCheck size={17} />
            Audit Log
          </button>
        )}
        <div className="sidebottom">
          <div className="quote">
            <ShieldCheck size={18} />
            <b>Secure by design.</b>
            <p>Learn together. Ship together.</p>
          </div>
          <div className="who">
            <div className="avatar">{initials(user.name)}</div>
            <div className="whotext">
              <b>{user.name}</b>
              <small>
                {user.role} · {user.member_id}
              </small>
            </div>
            <button className="logout" title="Sign out" onClick={logout}>
              <LogOut size={16} />
            </button>
          </div>
        </div>
      </aside>

      <main>
        <header>
          <button
            className="hamb"
            aria-label={mobile ? "Close navigation menu" : "Open navigation menu"}
            aria-expanded={mobile}
            aria-controls="technova-main-navigation"
            onClick={() => setMobile(!mobile)}
          >
            {mobile ? <X /> : <Menu />}
          </button>
          <div className="crumb">
            TechNova <span>/</span> <b>{page}</b>
          </div>
          <div className="topright">
            <div className="system-status" title="Your TechNova workspace is connected">
              <span className="system-status-dot" />
              Workspace live
            </div>
            <div className="search">
              <Search size={15} />
              <input
                placeholder="Search members or tasks…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button
              className="bell notification-bell"
              title="Open notifications"
              aria-label={unreadNotifications ? unreadNotifications + " unread notifications" : "Open notifications"}
              onClick={() => setPage("Notifications")}
            >
              <Bell size={17} />
              {unreadNotifications > 0 && <span className="notification-count">{unreadNotifications > 9 ? "9+" : unreadNotifications}</span>}
            </button>
            <div className="avatar">{initials(user.name)}</div>
          </div>
        </header>

        <section className="content">
          {error && (
            <div className="errorbanner">
              <AlertTriangle size={16} />
              {error}
              <button onClick={() => setError("")}>Dismiss</button>
            </div>
          )}

          {page === "Club Hub" && <TechNovaHub token={token} user={user} />}

          {page === "Overview" && (
            <>
              <div className="hero">
                <div className="eyebrow">✦ YOUR CLUB, ONE WORKSPACE</div>
                <h1>
                  Build the future,
                  <br />
                  <em>together.</em>
                </h1>
                <p>
                  Welcome back, {user.name.split(" ")[0]}. Here’s the latest
                  from TechNova.
                </p>
                {isAdmin && (
                  <button
                    className="primary"
                    onClick={() => {
                      setTaskForm({
                        ...taskForm,
                        assignment_mode: "individual",
                        assignee_ids: [],
                        assignee_id:
                          members.find(
                            (m) => m.status === "Active" && m.role === "Member"
                          )?.id ||
                          members[0]?.id ||
                          "",
                      });
                      setModal("task");
                    }}
                  >
                    <Plus size={15} /> Create a task
                  </button>
                )}
                <div className="planet">
                  <div className="planet-logo-frame"><TechNovaLogo /></div>
                  <b>TECHNOVA</b>
                  <small>CREATE · CODE · INNOVATE</small>
                </div>
              </div>
              <div className="stats">
                {[
                  [Users, "Total members", dashboard?.members_total ?? "—", "cyan"],
                  [UserCheck, "Active members", dashboard?.members_active ?? "—", "green"],
                  [ClipboardList, "Open tasks", dashboard?.tasks_open ?? "—", "purple"],
                  [Check, "Tasks completed", dashboard?.tasks_done ?? "—", "gold"],
                ].map(([I, l, v, c]) => (
                  <div className="stat" key={l}>
                    <span className={c}>
                      <I size={18} />
                    </span>
                    <small>{l}</small>
                    <strong>{v}</strong>
                  </div>
                ))}
              </div>
              {isAdmin && (
                <section className="panel database-monitor-panel">
                  <div className="panelhead">
                    <div>
                      <b>Database monitoring · MongoDB live</b>
                      <small>Live collection counts and storage statistics · refreshes every 30 seconds</small>
                    </div>
                    <span className="database-live-indicator"><i /> LIVE</span>
                  </div>
                  <div className="database-metrics">
                    <div className="database-metric"><small>Collections</small><strong>{databaseStats?.collections_count ?? "—"}</strong></div>
                    <div className="database-metric"><small>Total documents</small><strong>{databaseStats?.documents_count?.toLocaleString() ?? "—"}</strong></div>
                    <div className="database-metric"><small>Storage used</small><strong>{formatBytes(databaseStats?.storage_bytes)}</strong><small>Data {formatBytes(databaseStats?.data_bytes)} · Index {formatBytes(databaseStats?.index_bytes)}</small></div>
                    <div className="database-metric"><small>Storage remaining</small><strong>{databaseStats?.storage_limit_configured ? formatBytes(databaseStats.remaining_bytes) : "Set limit"}</strong><small>{databaseStats?.storage_limit_configured ? "Against configured MongoDB storage cap" : "Set MONGODB_STORAGE_LIMIT_GB on Render to calculate remaining capacity"}</small></div>
                  </div>
                  <div className="database-collection-wrap">
                    <div className="database-collection-heading"><b>Collection activity</b><small>{databaseStats?.database || "Database"} · {databaseStats?.measured_at ? new Date(databaseStats.measured_at).toLocaleTimeString() : "Waiting for data"}</small></div>
                    <div className="database-collection-list">
                      {(databaseStats?.collections || []).map((item) => (
                        <div className="database-collection-row" key={item.name}>
                          <span>{item.name}</span><b>{item.documents.toLocaleString()}</b>
                        </div>
                      ))}
                      {!databaseStats?.collections?.length && <small className="database-empty">Collection statistics are loading.</small>}
                    </div>
                  </div>
                </section>
              )}
              <div className="panel">
                <div className="panelhead">
                  <div>
                    <b>Recent tasks</b>
                    <small>Live data from MongoDB</small>
                  </div>
                  <button
                    className="textbtn"
                    onClick={() => setPage("Tasks & Projects")}
                  >
                    View all <ArrowUpRight size={14} />
                  </button>
                </div>
                {(dashboard?.recent_tasks || []).map((t) => (
                  <div className="taskrow" key={t.id}>
                    <span className="taskicon">
                      <Code2 size={17} />
                    </span>
                    <div className="taskname">
                      <b>{t.title}</b>
                      <small>
                        {t.id.slice(-6)} · {t.assignee_name}
                      </small>
                    </div>
                    <span
                      className={
                        "pill " + t.status.toLowerCase().replace(" ", "-")
                      }
                    >
                      {t.status}
                    </span>
                  </div>
                ))}
                {!dashboard?.recent_tasks?.length && (
                  <div className="empty">
                    No tasks yet.{" "}
                    {isAdmin
                      ? "Create the first task to get started."
                      : "Tasks assigned to you will appear here."}
                  </div>
                )}
              </div>
            </>
          )}

          {page === "Leaderboard" && (
            <>
              <div className="title">
                <div>
                  <label>TECHNOVA MEMBER PROGRESSION</label>
                  <h1>Leaderboard</h1>
                  <p>Credits come from tasks that Founder or Core Management has approved. Rankings refresh with the workspace.</p>
                </div>
              </div>
              <div className="leaderboard-summary-grid">
                <div className="panel leaderboard-my-card">
                  <small>YOUR CURRENT POSITION</small>
                  <strong>{leaderboard.my_entry?.position ? "#" + leaderboard.my_entry.position : "—"}</strong>
                  <span>{leaderboard.my_entry ? leaderboard.my_entry.rank + " rank · " + leaderboard.my_entry.credits + " credits" : user.role === "Member" ? "No approved task credits yet" : "Leaderboard ranks active Members"}</span>
                </div>
                <div className="panel leaderboard-my-card">
                  <small>APPROVED TASKS</small>
                  <strong>{leaderboard.my_entry?.completed_tasks ?? 0}</strong>
                  <span>Only approved completions count</span>
                </div>
                <div className="panel leaderboard-my-card leaderboard-perk-card">
                  <small>TOP 3 RECOGNITION</small>
                  <strong>{leaderboard.my_entry?.top_three_eligible ? "Eligible" : "Top 3"}</strong>
                  <span>{leaderboard.my_entry?.top_three_eligible ? "You are currently in the Top 3 shortlist." : "Top 3 active Members with earned credits are shortlisted."}</span>
                </div>
              </div>
              <div className="leaderboard-summary-grid credit-ledger-summary">
                <div className="panel leaderboard-my-card">
                  <small>AVAILABLE CREDITS</small>
                  <strong>{creditLedger.balance.toLocaleString()} CR</strong>
                  <span>Earned {creditLedger.earned_total.toLocaleString()} · Deductions {creditLedger.penalized_total.toLocaleString()}</span>
                </div>
              </div>
              <div className="panel tablepanel credit-ledger-panel">
                <div className="panelhead">
                  <b>My credit history</b>
                  <small>Recent task awards and rule/deadline deductions</small>
                </div>
                <div className="overflow">
                  <table>
                    <thead><tr><th>ACTIVITY</th><th>REASON</th><th>DATE</th><th>CHANGE</th></tr></thead>
                    <tbody>
                      {(creditLedger.entries || []).map((entry) => (
                        <tr key={entry.id}>
                          <td><b>{entry.title}</b><small className="sub">{entry.type === "earned" ? "Approved task" : (entry.category || "Disciplinary penalty").replaceAll("_", " ")}</small></td>
                          <td>{entry.reason}</td>
                          <td>{entry.created_at ? new Date(entry.created_at).toLocaleString() : "—"}</td>
                          <td><b className={entry.points >= 0 ? "credit-positive" : "credit-negative"}>{entry.points > 0 ? "+" : ""}{entry.points} CR</b></td>
                        </tr>
                      ))}
                      {!creditLedger.entries?.length && <tr><td colSpan="4" className="empty">No credit activity yet. Approved task rewards will appear here.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
              <div className="panel leaderboard-perks">
                <div className="panelhead">
                  <b>Top 3 opportunities</b>
                  <span className="common-task-count">Founder-reviewed</span>
                </div>
                <p>The current Top 3 credit holders become eligible to join selected Core Management-led club projects and be considered to accompany the Founder at coding competitions. This is a recognition shortlist, not an automatic role promotion or guaranteed competition seat; the Founder confirms each opportunity.</p>
                <div className="leaderboard-top-three">
                  {(leaderboard.top_three || []).map((entry) => (
                    <div className="leaderboard-top-card" key={entry.member_id}>
                      <span className="leader-position">#{entry.position}</span>
                      <div><b>{entry.name}</b><small>{entry.member_id} · {entry.rank} rank</small></div>
                      <strong>{entry.credits} CR</strong>
                      {entry.top_three_eligible ? <span className="leader-eligible">Project / competition eligible</span> : <span className="leader-pending">Complete an approved task to qualify</span>}
                    </div>
                  ))}
                  {!leaderboard.top_three?.length && <div className="empty">No active Members on the board yet.</div>}
                </div>
              </div>
              <div className="panel tablepanel leaderboard-table-panel">
                <div className="panelhead">
                  <b>Top 10 Members</b>
                  <small>{leaderboard.active_member_count || 0} active Members · ranked by credits, then approved tasks</small>
                </div>
                <div className="overflow">
                  <table>
                    <thead><tr><th>POSITION</th><th>MEMBER</th><th>MEMBER RANK</th><th>CREDITS</th><th>APPROVED TASKS</th><th>RECOGNITION</th></tr></thead>
                    <tbody>
                      {(leaderboard.top_10 || []).map((entry) => (
                        <tr key={entry.member_id}>
                          <td><span className="leader-position">#{entry.position}</span></td>
                          <td><b>{entry.name}</b><small className="sub">{entry.member_id} · {entry.team || "Unassigned"}</small></td>
                          <td><span className={"member-rank-pill rank-" + entry.rank.toLowerCase()}>{entry.rank}</span></td>
                          <td><b className="leader-credit-value">{entry.credits.toLocaleString()} CR</b></td>
                          <td>{entry.completed_tasks}</td>
                          <td>{entry.top_three_eligible ? <span className="leader-eligible">Top 3 shortlist</span> : "—"}</td>
                        </tr>
                      ))}
                      {!leaderboard.top_10?.length && <tr><td colSpan="6" className="empty">No approved task credits recorded yet.</td></tr>}
                    </tbody>
                  </table>
                </div>
              </div>
              <p className="leaderboard-footnote">Task difficulty rewards: F 5 · E 10 · D 20 · C 35 · B 55 · A 85 · S 125 · SS 175 · SSS 250 credits. Member ranks rise with lifetime approved credits; old completed tasks are not backdated.</p>
            </>
          )}

          {page === "Notifications" && (
            <>
              <div className="title">
                <div>
                  <label>YOUR WORKSPACE INBOX</label>
                  <h1>Notifications</h1>
                  <p>Task updates, club announcements, and important messages from management.</p>
                </div>
                <div className="titleactions">
                  <button className="secondary" onClick={refresh}>
                    <RefreshCw size={14} /> Refresh inbox
                  </button>
                  {isAdmin && (
                    <button className="primary" onClick={() => setModal("announcement")}>
                      <Plus size={14} /> Broadcast to Members + Faculty
                    </button>
                  )}
                </div>
              </div>
              <div className="panel notification-list">
                {notifications.map((item) => (
                  <div className={"notification-row " + (item.read ? "" : "unread")} key={item.id}>
                    <span className="notification-symbol"><Bell size={17} /></span>
                    <div className="notification-copy">
                      <b>{item.title}</b>
                      <p>{item.message}</p>
                      <small>{item.created_at ? new Date(item.created_at).toLocaleString() : "Just now"}</small>
                    </div>
                    <button className="secondary notification-open" onClick={() => markNotificationRead(item)}>
                      {["task_assigned", "common_task", "common_task_response", "task_review", "task_approved"].includes(item.type) ? "Open tasks" : item.read ? "Viewed" : "Mark read"}
                    </button>
                  </div>
                ))}
                {!notifications.length && (
                  <div className="empty">You are all caught up. New task assignments will appear here.</div>
                )}
              </div>
            </>
          )}

          {page === "Members" && (
            <>
              <div className="title">
                <div>
                  <label>PEOPLE & PERMISSIONS</label>
                  <h1>Members</h1>
                  <p>Persistent member records and server-enforced roles.</p>
                </div>
                <div className="titleactions">
                  <button
                    className="secondary"
                    onClick={() => {
                      let csv = [
                        "Member ID,Name,Email,Role,Team,Status",
                        ...members.map((m) =>
                          [m.member_id, m.name, m.email, m.role, m.team, m.status]
                            .map((x) => `"${String(x || "").replaceAll('"', '""')}"`)
                            .join(",")
                        ),
                      ].join("\n");
                      let a = document.createElement("a");
                      a.href = URL.createObjectURL(
                        new Blob([csv], { type: "text/csv" })
                      );
                      a.download = "technova-members.csv";
                      a.click();
                    }}
                  >
                    <Download size={14} /> Export CSV
                  </button>
                  {isFounder && (
                    <button
                      className="primary"
                      onClick={() => setModal("member")}
                    >
                      <Plus size={14} /> Add member
                    </button>
                  )}
                </div>
              </div>
              <div className="stats compact">
                {[
                  ["Total members", members.length],
                  [
                    "Core management",
                    members.filter((m) => m.role === "Core Management").length,
                  ],
                  ["Faculty", members.filter((m) => m.role === "Faculty").length],
                  [
                    "Awaiting approval",
                    members.filter((m) => m.status === "Pending").length,
                  ],
                ].map((x) => (
                  <div className="stat" key={x[0]}>
                    <small>{x[0]}</small>
                    <strong>{x[1]}</strong>
                  </div>
                ))}
              </div>
              <div className="panel tablepanel">
                <div className="panelhead">
                  <b>
                    Member directory{" "}
                    <small>{filteredMembers.length} records</small>
                  </b>
                </div>
                <div className="overflow">
                  <table>
                    <thead>
                      <tr>
                        <th>MEMBER</th>
                        <th>ID</th>
                        <th>ROLE</th>
                        <th>TEAM</th>
                        <th>STATUS</th>
                        <th>ACTIONS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {filteredMembers.map((m) => (
                        <tr key={m.id}>
                          <td>
                            <div className="member">
                              <div className="avatar">{initials(m.name)}</div>
                              <div>
                                <b>{m.name}</b>
                                <small>{m.email}</small>
                                {m.suspension_reason && m.status === "Suspended" && <small className="sub">{m.suspension_reason}</small>}
                              </div>
                            </div>
                          </td>
                          <td>{m.member_id}</td>
                          <td>
                            <span
                              className={
                                "pill " +
                                (m.role === "Founder"
                                  ? "founder"
                                  : m.role === "Core Management"
                                  ? "core"
                                  : "memberpill")
                              }
                            >
                              {m.role}
                            </span>
                          </td>
                          <td>
                            {isFounder && m.role !== "Founder" ? (
                              <select
                                aria-label={`Assign team to ${m.name}`}
                                value={m.team || "Unassigned"}
                                onChange={(e) => updateMember(m, { team: e.target.value })}
                              >
                                <option value="Unassigned">Unassigned</option>
                                {teams.map((team) => (
                                  <option key={team.id} value={team.name}>{team.name}</option>
                                ))}
                              </select>
                            ) : m.team}
                          </td>
                          <td>
                            <span className={"pill " + m.status.toLowerCase()} title={m.suspension_reason || ""}>
                              {m.status}
                            </span>
                            {m.status === "Suspended" && m.suspension_until && <small className="sub">Until {new Date(m.suspension_until).toLocaleString()}</small>}
                          </td>
                          <td>
                            <div className="rowactions">
                              <button
                                className="textbtn"
                                onClick={() => {
                                  setSelected(m);
                                  setPage("Digital ID Cards");
                                }}
                              >
                                ID card
                              </button>
                              {isAdmin && m.status === "Pending" && (
                                <button
                                  className="textbtn"
                                  onClick={() => approveMember(m)}
                                >
                                  Approve
                                </button>
                              )}
                              {isFounder && m.role !== "Founder" && (
                                <select
                                  value={m.role}
                                  onChange={(e) =>
                                    updateMember(m, { role: e.target.value })
                                  }
                                >
                                  <option>Member</option>
                                  <option>Faculty</option>
                                  <option>Core Management</option>
                                </select>
                              )}
                              {isAdmin && m.role === "Member" && m.status === "Active" && (
                                <button className="textbtn danger" onClick={() => disciplineMember(m)}>
                                  Temporary suspend
                                </button>
                              )}
                              {isAdmin && m.role === "Member" && m.status === "Suspended" && (
                                <button className="textbtn" onClick={() => reinstateMember(m)}>
                                  Reinstate
                                </button>
                              )}
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>
            </>
          )}

          {page === "Tasks & Projects" && (
            <>
              <div className="task-page-compact">
              <div className="title">
                <div>
                  <label>WORK MANAGEMENT</label>
                  <h1>Tasks & projects</h1>
                  <p>
                    Assign work, track progress, and keep project delivery visible.
                  </p>
                </div>
                {isAdmin && (
                  <button
                    className="primary"
                    onClick={() => {
                      setTaskForm({
                        ...taskForm,
                        assignment_mode: "individual",
                        assignee_ids: [],
                        assignee_id:
                          members.find((m) => m.status === "Active" && m.role === "Member")?.id ||
                          members[0]?.id ||
                          "",
                      });
                      setModal("task");
                    }}
                  >
                    <Plus size={14} /> Create task
                  </button>
                )}
              </div>

                            <div className="task-status-toolbar">
                <div className="task-status-heading">
                  <b>{isAdmin ? "Club-wide task status" : "My task status"}</b>
                  <small>{isAdmin ? "Includes tasks assigned to every member and team." : "Live refresh every 15 seconds"}</small>
                </div>
                <div className="task-status-tabs" role="group" aria-label="Filter tasks by status">
                  {[
                    ["All", "All tasks"],
                    ["Todo", "To do"],
                    ["In progress", "In progress"],
                    ["Review", "In review"],
                    ["Done", "Completed"],
                  ].map(([value, label]) => (
                    <button
                      type="button"
                      key={value}
                      className={"task-filter-chip " + (taskStatusFilter === value ? "active" : "")}
                      aria-pressed={taskStatusFilter === value}
                      onClick={() => setTaskStatusFilter(value)}
                    >
                      {label}<span>{taskStatusCounts[value]}</span>
                    </button>
                  ))}
                </div>
              </div>

                            <div className="stats compact four">
                {[
                  ["All tasks", tasks.length],
                  [
                    "In progress",
                    tasks.filter((t) => t.status === "In progress").length,
                  ],
                  [
                    "In review",
                    tasks.filter((t) => t.status === "Review").length,
                  ],
                  [
                    "Completed",
                    tasks.filter((t) => t.status === "Done").length,
                  ],
                ].map((x) => (
                  <div className="stat" key={x[0]}>
                    <small>{x[0]}</small>
                    <strong>{x[1]}</strong>
                  </div>
                ))}
              </div>

                            <div className="panel kanban-task-board">
                <div className="panelhead kanban-board-heading">
                  <div>
                    <b>{isAdmin ? "All club tasks" : "My task board"}</b>
                    <small>{isAdmin ? "Club-wide task overview · Founder and Core Management" : "Your assigned tasks"} · {filteredTaskRows.length} visible / {tasks.length} total</small>
                  </div>
                  <span className="common-task-count">{filteredTaskRows.length} tasks</span>
                </div>
                <div className="kanban-mobile-nav">
                  <span>Swipe to view all stages</span>
                  <div>
                    <button type="button" aria-label="Previous task column" onClick={(e) => e.currentTarget.closest(".kanban-task-board")?.querySelector(".kanban-lanes")?.scrollBy({ left: -260, behavior: "smooth" })}>‹</button>
                    <button type="button" aria-label="Next task column" onClick={(e) => e.currentTarget.closest(".kanban-task-board")?.querySelector(".kanban-lanes")?.scrollBy({ left: 260, behavior: "smooth" })}>›</button>
                  </div>
                </div>
                <div className="kanban-lanes">
                  {[
                    { key: "Todo", title: "To do", tone: "todo" },
                    { key: "In progress", title: "Doing", tone: "doing" },
                    { key: "Review", title: "In review", tone: "review" },
                    { key: "Done", title: "Done", tone: "done" },
                  ].map((lane) => {
                    const laneTasks = filteredTaskRows.filter((task) => task.status === lane.key);
                    return (
                      <section className={"kanban-lane lane-" + lane.tone} key={lane.key}>
                        <header className="kanban-lane-heading">
                          <span className="kanban-lane-dot" />
                          <b>{lane.title}</b>
                          <span className="kanban-lane-count">{laneTasks.length}</span>
                        </header>
                        <div className="kanban-lane-cards">
                          {laneTasks.map((t) => (
                            <article className="kanban-task-card" key={t.id} role="button" tabIndex={0} aria-label={`View details for ${t.title}`} onClick={() => setSelectedTaskDetail(t)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedTaskDetail(t); } }}>
                              <div className="kanban-task-top">
                                <small>{t.id.slice(-6)} · {t.project || "Club project"}</small>
                                <span className={"pill " + (t.priority || "Medium").toLowerCase()}>{t.priority || "Medium"}</span>
                              </div>
                              <h3>{t.title}</h3>
                              {t.description && <p>{t.description}</p>}
                              <div className="kanban-task-tags">
                                <span className={"difficulty-badge rank-" + (t.difficulty_rank || "F").toLowerCase()}>{t.difficulty_rank || "F"} rank</span>
                                <span>{t.programming_language || "General"}</span>
                                {t.recurrence === "daily" && <span className="schedule-state active">Daily</span>}
                                {t.auto_generated && <span className="schedule-state active">Auto-generated</span>}
                                {t.task_state === "Suspended" && <span className="schedule-state paused">Paused</span>}
                              </div>
                              <div className="kanban-task-details">
                                <span><b>Assigned to</b>{t.assignee_name || "Unassigned"}</span>
                                <span><b>Due date</b>{t.due_date || "Not set"}</span>
                                <span><b>Reward</b>{t.status === "Done" ? (t.credits_awarded || 0) : (t.credits_reward || 5)} credits</span>
                              </div>
                              {t.review_feedback && <div className="kanban-feedback">Feedback: {t.review_feedback}</div>}
                              {t.status === "Done" && t.completion_confirmed_by_name && <small className="kanban-confirmed">Confirmed by {t.completion_confirmed_by_name}</small>}
                              {t.task_state === "Suspended" && <div className="kanban-paused-note">Paused by management</div>}
                              {user.role === "Member" && t.assignee_id === user.id && t.status !== "Done" && t.task_state !== "Suspended" && (
                                <label className="kanban-status-control">Update progress
                                  <select
                                    value={t.status}
                                    onChange={(e) => {
                                      const nextStatus = e.target.value;
                                      if (nextStatus === "Review") openTaskSubmission(t);
                                      else updateTask(t, { status: nextStatus });
                                    }}
                                  >
                                    {t.status === "Todo" && <option value="Todo">To do</option>}
                                    {t.status === "Todo" && <option value="In progress">In progress</option>}
                                    {t.status === "In progress" && <option value="In progress">In progress</option>}
                                    {t.status === "In progress" && <option value="Review">Submit for review</option>}
                                    {t.status === "Review" && <option value="Review">In review</option>}
                                    {t.status === "Review" && <option value="In progress">Return to work</option>}
                                  </select>
                                </label>
                              )}
                              <div className="kanban-card-actions">
                                <button className="textbtn" onClick={async () => {
                                  const comment = prompt("Add a task comment");
                                  if (comment) {
                                    try {
                                      await api(`/tasks/${t.id}/comments`, token, { method: "POST", body: JSON.stringify({ text: comment }) });
                                      notify("Comment added");
                                    } catch (e) { fail(e); }
                                  }
                                }}>Comment</button>
                                <label className="filebtn">Attach
                                  <input type="file" hidden onChange={(e) => e.target.files?.[0] && uploadAttachment(t.id, e.target.files[0])} />
                                </label>
                                {isAdmin && (
                                  <>
                                    <button className="textbtn" onClick={() => toggleTaskPause(t)}>{t.task_state === "Suspended" ? "Resume" : "Pause"}</button>
                                    <button className="textbtn danger" onClick={() => archiveTask(t)}>Archive</button>
                                  </>
                                )}
                              </div>
                            </article>
                          ))}
                          {!laneTasks.length && <div className="kanban-lane-empty">No tasks in this stage</div>}
                        </div>
                      </section>
                    );
                  })}
                </div>
                {!tasks.length && <div className="empty">No tasks created yet.</div>}
              </div>
              {selectedTaskDetail && createPortal((
                <div className="task-detail-backdrop" onClick={() => setSelectedTaskDetail(null)}>
                  <section className="task-detail-modal" role="dialog" aria-modal="true" aria-labelledby="task-detail-title" onClick={(e) => e.stopPropagation()}>
                    <header className="task-detail-header">
                      <div><small>TECHNOVA TASK DETAILS</small><h2 id="task-detail-title">{selectedTaskDetail.title}</h2></div>
                      <button type="button" className="textbtn" onClick={() => setSelectedTaskDetail(null)} aria-label="Close task details">✕</button>
                    </header>
                    <div className="task-detail-content">
                      <p>{selectedTaskDetail.description || "No additional description provided."}</p>
                      {selectedTaskDetail.submission_note && <div className="task-detail-submission"><b>Submission note</b><p>{selectedTaskDetail.submission_note}</p></div>}
                      {selectedTaskDetail.submission_evidence_url && <a className="task-detail-evidence" href={selectedTaskDetail.submission_evidence_url} target="_blank" rel="noreferrer">Open submitted screenshot evidence ↗</a>}
                      {selectedTaskDetail.project_url && <a className="task-detail-evidence" href={selectedTaskDetail.project_url} target="_blank" rel="noreferrer">Open project / demo ↗</a>}
                      {!!selectedTaskDetail.attachments?.length && <div className="task-detail-submission"><b>Attached files</b>{selectedTaskDetail.attachments.map(file => <p key={file.id}>{file.filename}</p>)}</div>}
                      <div className="task-detail-grid">
                        <span className="task-detail-status-field"><b>Status</b>
                          {isAdmin && selectedTaskDetail.status !== "Done" ? (
                            <select value={selectedTaskDetail.status || "Todo"} onChange={async (e) => {
                              const nextStatus = e.target.value;
                              await updateTask(selectedTaskDetail, { status: nextStatus });
                              setSelectedTaskDetail(current => current ? { ...current, status: nextStatus } : current);
                            }}>
                              <option value="Todo">To do</option>
                              <option value="In progress">In progress</option>
                              <option value="Review">In review / submission</option>
                            </select>
                          ) : (selectedTaskDetail.status || "Todo")}
                        </span>
                        <span><b>Priority</b>{selectedTaskDetail.priority || "Medium"}</span>
                        <span><b>Assigned to</b>{selectedTaskDetail.assignee_name || "Unassigned"}</span>
                        <span><b>Due date</b>{selectedTaskDetail.due_date || "Not set"}</span>
                        <span><b>Difficulty rank</b>{selectedTaskDetail.difficulty_rank || "F"}</span>
                        <span><b>Reward</b>{selectedTaskDetail.status === "Done" ? (selectedTaskDetail.credits_awarded || 0) : (selectedTaskDetail.credits_reward || 5)} credits</span>
                        <span><b>Project</b>{selectedTaskDetail.project || "Club project"}</span>
                        <span><b>Language</b>{selectedTaskDetail.programming_language || "General"}</span>
                        {selectedTaskDetail.submitted_at && <span><b>Submitted</b>{new Date(selectedTaskDetail.submitted_at).toLocaleString()}</span>}
                        {selectedTaskDetail.submission_attested !== undefined && <span><b>Member attestation</b>{selectedTaskDetail.submission_attested ? "Confirmed" : "Missing"}</span>}
                        {selectedTaskDetail.accepted_count !== undefined && <span><b>Accepted</b>{selectedTaskDetail.accepted_count ?? selectedTaskDetail.accepted_members?.length ?? 0} members</span>}
                        {selectedTaskDetail.completed_count !== undefined && <span><b>Completed</b>{selectedTaskDetail.completed_count ?? selectedTaskDetail.completed_members?.length ?? 0} members</span>}
                      </div>
                      {user?.role === "Member" && !selectedTaskDetail.response_status && selectedTaskDetail.task_state !== "Suspended" && (
                        <div className="task-detail-response-actions" onClick={(event) => event.stopPropagation()}>
                          <p>You have not responded to this open mission yet.</p>
                          <button type="button" className="primary" disabled={busy} onClick={() => respondToCommonTask(selectedTaskDetail, "accepted")}>
                            <Check size={15}/> {busy ? "Please wait..." : "Accept task"}
                          </button>
                          <button type="button" className="secondary" disabled={busy} onClick={() => respondToCommonTask(selectedTaskDetail, "declined")}>Reject mission</button>
                        </div>
                      )}
                      {selectedTaskDetail.response_status && (
                        <div className={"common-task-response " + selectedTaskDetail.response_status}>
                          {selectedTaskDetail.response_status === "accepted" ? "✓ You accepted this task — it is in your task list." : "You rejected this mission."}
                        </div>
                      )}
                      {(selectedTaskDetail.accepted_members?.length > 0 || selectedTaskDetail.completed_members?.length > 0) && (
                        <div className="task-detail-member-lists">
                          {selectedTaskDetail.accepted_members?.length > 0 && <p><b>Accepted by:</b> {selectedTaskDetail.accepted_members.join(", ")}</p>}
                          {selectedTaskDetail.completed_members?.length > 0 && <p><b>Completed by:</b> {selectedTaskDetail.completed_members.join(", ")}</p>}
                        </div>
                      )}
                      {selectedTaskDetail.review_feedback && <div className="kanban-feedback">Review feedback: {selectedTaskDetail.review_feedback}</div>}
                      {selectedTaskDetail.task_state === "Suspended" && <div className="kanban-paused-note">This task is paused by management.</div>}
                      {selectedTaskDetail.status === "Done" && selectedTaskDetail.completion_confirmed_by_name && <p className="kanban-confirmed">Confirmed by {selectedTaskDetail.completion_confirmed_by_name}</p>}
                    </div>
                    <footer className="task-detail-footer"><button type="button" onClick={() => setSelectedTaskDetail(null)}>Close details</button></footer>
                  </section>
                </div>
              ), document.body)}
                            <div className="panel common-task-board">
                <div className="panelhead">
                  <div>
                    <b>Daily Task Board · Open volunteer missions</b>
                    <small>Daily AI missions are randomly generated here. Members may accept or decline; no one is assigned automatically.</small>
                  </div>
                  <span className="common-task-count">{commonTasks.length} open</span>
                </div>
                <div className="common-task-grid">
                  {commonTasks.map((item) => (
                    <article className="common-task-card" key={item.id} role="button" tabIndex={0} aria-label={`View details for ${item.title}`} onClick={() => setSelectedTaskDetail(item)} onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelectedTaskDetail(item); } }}>
                      <div className="common-task-meta">
                        <div className="common-task-badges">
                          <span className="pill">{item.priority}</span>
                          <span className={"difficulty-badge rank-" + (item.difficulty_rank || "F").toLowerCase()}>{item.difficulty_rank || "F"} · {item.credits_reward || 5} CR</span>
                          {item.task_state === "Suspended" && <span className="schedule-state paused">Paused</span>}
                          {item.recurrence === "daily" && <span className="schedule-state active">Daily mission</span>}
                          {item.auto_generated && <span className="schedule-state active">{(item.generation_source || "").toLowerCase().includes("gemini") ? "Gemini AI" : "Auto-generated"}</span>}
                        </div>
                        <small className="common-task-category">{item.project || "Club projects"} <span>·</span> {item.programming_language || "General"}</small>
                      </div>
                      <h3>{item.title}</h3>
                      <p>{item.description || "No additional description provided."}</p>
                      <small className="common-task-due">Due: {item.due_date || "No due date"}</small>
                      <div className="common-task-progress">
                        <div>
                          <b>Accepted · {item.accepted_count ?? item.accepted_members?.length ?? 0}</b>
                          <div className="common-task-member-list" aria-label="Members who accepted this task">
                            {item.accepted_members?.length
                              ? item.accepted_members.map((name, index) => (
                                  <span className="member-name-chip accepted" key={name + "-" + index}>{name}</span>
                                ))
                              : <small>No one has accepted yet.</small>}
                          </div>
                        </div>
                        <div>
                          <b>Completed · {item.completed_count ?? item.completed_members?.length ?? 0}</b>
                          <div className="common-task-member-list" aria-label="Members who completed this task">
                            {item.completed_members?.length
                              ? item.completed_members.map((name, index) => (
                                  <span className="member-name-chip completed" key={name + "-" + index}>{name}</span>
                                ))
                              : <small>No one has completed this task yet.</small>}
                          </div>
                        </div>
                      </div>
                      {user.role === "Member" && item.task_state !== "Suspended" && !item.response_status && (
                        <div className="common-task-actions" onClick={(e) => e.stopPropagation()}>
                          <button className="primary" onClick={() => respondToCommonTask(item, "accepted")}>
                            <Check size={14} /> Accept task
                          </button>
                          <button className="secondary" onClick={() => respondToCommonTask(item, "declined")}>
                            Reject mission
                          </button>
                        </div>
                      )}
                      {item.response_status && (
                        <div className={"common-task-response " + item.response_status}>
                          {item.response_status === "accepted" ? "✓ You accepted this task — it is in your task list." : "You rejected this mission."}
                        </div>
                      )}
                      {isAdmin && (
                        <>
                          <small className="common-task-creator">Posted by {item.created_by_name}</small>
                          <div className="common-task-actions" onClick={(e) => e.stopPropagation()}>
                            <button className="secondary" onClick={() => manageCommonTask(item, item.task_state === "Suspended" ? "resume" : "pause")}>{item.task_state === "Suspended" ? "Resume mission" : "Pause mission"}</button>
                            <button className="textbtn danger" onClick={() => manageCommonTask(item, "delete")}>Archive</button>
                          </div>
                        </>
                      )}
                    </article>
                  ))}
                  {!commonTasks.length && (
                    <div className="empty common-empty">No daily missions are available right now. The next random mission will appear automatically.</div>
                  )}
                </div>
              </div>

              <details className="task-operations-disclosure" open={reviewQueue.length > 0}>
                <summary>
                  <span><b>Management & automation</b><small>Completion approvals, recurring missions and AI generation settings</small></span>
                  <span className="operations-summary-count">{reviewQueue.length} pending approvals</span>
                </summary>
                <div className="task-operations-content">
                  {isAdmin && (
                <div className="panel review-queue-panel">
                  <div className="panelhead">
                    <div>
                      <b>Quick completion approvals</b>
                      <small>{reviewQueue.length} submission(s) waiting · batch approval available for large queues</small>
                    </div>
                    <span className="common-task-count">{reviewQueue.length} pending</span>
                  </div>
                  <div className="review-queue-controls">
                    <input
                      type="search"
                      value={reviewSearch}
                      onChange={(e) => setReviewSearch(e.target.value)}
                      placeholder="Search task or member name..."
                    />
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setSelectedReviewIds(filteredReviewQueue.map((task) => task.id))}
                      disabled={!filteredReviewQueue.length}
                    >
                      Select visible
                    </button>
                    <button
                      type="button"
                      className="secondary"
                      onClick={() => setSelectedReviewIds([])}
                      disabled={!selectedReviewIds.length}
                    >
                      Clear
                    </button>
                    <button
                      type="button"
                      className="primary"
                      onClick={approveSelectedTasks}
                      disabled={busy || !selectedReviewIds.length}
                    >
                      <Check size={14} /> Approve selected ({selectedReviewIds.length})
                    </button>
                    <button
                      type="button"
                      className="primary review-approve-all"
                      onClick={() => approveSelectedTasks(filteredReviewQueue.map((task) => task.id), "matching submissions")}
                      disabled={busy || !filteredReviewQueue.length}
                      title="Approve every task currently shown by this search"
                    >
                      <Check size={14} /> Approve all matching ({filteredReviewQueue.length})
                    </button>
                  </div>
                  <div className="review-queue-list">
                    {filteredReviewQueue.map((task) => (
                      <label className="review-queue-item" key={task.id}>
                        <input
                          type="checkbox"
                          checked={selectedReviewIds.includes(task.id)}
                          onChange={(e) => setSelectedReviewIds((current) =>
                            e.target.checked
                              ? [...current, task.id]
                              : current.filter((id) => id !== task.id)
                          )}
                        />
                        <span className="review-queue-copy">
                          <b>{task.title}</b>
                          <small>{task.assignee_name} · {task.assignee_member_id || "Member"} · {task.assignee_team || "Unassigned"}</small>
                          <span>{task.submission_note || "No completion note submitted."}</span>
                          <span className="review-readiness">
                            {task.submission_evidence_url && task.submission_attested
                              ? "✓ Ready for approval — screenshot and attestation received"
                              : "Needs resubmission: " + [!task.submission_evidence_url ? "screenshot evidence" : "", !task.submission_attested ? "member attestation" : ""].filter(Boolean).join(" and ")}
                          </span>
                          <button type="button" className="primary review-single-approve" disabled={busy || !task.submission_evidence_url || !task.submission_attested} onClick={(event) => { event.preventDefault(); event.stopPropagation(); approveSelectedTasks([task.id], "submission"); }}>
                            <Check size={13}/> Approve submission
                          </button>
                          {task.submission_evidence_url ? (
                            <span className="submission-evidence">
                              <a href={task.submission_evidence_url} target="_blank" rel="noreferrer">Open screenshot evidence ↗</a>
                              <a href={task.submission_evidence_url} target="_blank" rel="noreferrer" className="evidence-preview-link">
                                <img
                                  src={task.submission_evidence_url}
                                  alt={task.title + " submission screenshot"}
                                  loading="lazy"
                                  onError={(event) => { event.currentTarget.style.display = "none"; }}
                                />
                              </a>
                            </span>
                          ) : (
                            <small className="evidence-missing">No screenshot evidence attached — request a new submission.</small>
                          )}
                          {task.project_url && (
                            <a href={task.project_url} target="_blank" rel="noreferrer">Open project / demo link ↗</a>
                          )}
                          <small>{task.attachments_count || 0} file attachment(s) · Submitted {task.submitted_at ? new Date(task.submitted_at).toLocaleString() : "recently"}</small>
                          {!!task.attachments?.length && (
                            <span className="review-attachments">
                              {task.attachments.map((file) => (
                                <button
                                  type="button"
                                  className="textbtn"
                                  key={file.id}
                                  onClick={() => downloadReviewAttachment(file)}
                                >
                                  <Download size={12} /> {file.filename}
                                </button>
                              ))}
                            </span>
                          )}
                          <button
                            type="button"
                            className="textbtn review-return-button"
                            disabled={busy}
                            onClick={(event) => { event.preventDefault(); event.stopPropagation(); requestTaskChanges(task); }}
                          >
                            Request changes
                          </button>
                        </span>
                      </label>
                    ))}
                    {!filteredReviewQueue.length && (
                      <div className="empty">
                        {reviewQueue.length ? "No submissions match your search." : "No submissions are waiting for approval."}
                      </div>
                    )}
                  </div>
                  <p className="review-queue-note">Only Founder and Core Management can approve. Search or filter the queue, inspect submitted notes and attachments, then approve selected items or all matching items in one confirmation. Large queues are processed in batches; QR scanning remains optional for identity checks when needed.</p>
                </div>
              )}

              {isAdmin && (
                <div className="panel daily-schedule-panel">
                  <div className="panelhead">
                    <div><b>Daily mission automation</b><small>Shared daily mission templates publish to the volunteer board. Members choose whether to accept or reject.</small></div>
                    <span className="common-task-count">{dailySchedules.filter((schedule) => schedule.active && schedule.assignment_mode === "open_to_all").length} active</span>
                  </div>
                  <div className="daily-schedule-list">
                    {dailySchedules.filter((schedule) => schedule.assignment_mode === "open_to_all").map((schedule) => (
                      <div className="daily-schedule-row" key={schedule.id}>
                        <div><b>{schedule.title}</b><small>{schedule.assignment_mode === "open_to_all" ? "Common mission" : "Assigned task"} · Starts {schedule.start_date} · Last created {schedule.last_generated_date || "pending"}</small></div>
                        <span className={"schedule-state " + (schedule.active ? "active" : "paused")}>{schedule.active ? "Repeating" : "Paused"}</span>
                        <button className="textbtn" onClick={() => toggleDailySchedule(schedule)}>{schedule.active ? "Pause" : "Resume"}</button>
                        <button className="textbtn danger" onClick={() => deleteDailySchedule(schedule)}>Stop</button>
                      </div>
                    ))}
                    {!dailySchedules.length && <div className="empty">No recurring shared missions configured. The random AI daily mission is generated separately.</div>}
                  </div>
                  <div className="auto-task-controls">
                    <div className="panelhead">
                      <div><b>Random mission generator</b><small>Set a daily target or enable unlimited mode with a safety cap.</small></div>
                      <span className="common-task-count">{autoTaskSettings.generated_today || 0} generated today</span>
                    </div>
                    <div className="auto-task-metrics">
                      <span><b>{autoTaskSettings.open_today || 0}</b><small>Open today</small></span>
                      <span><b>{autoTaskSettings.total_generated || 0}</b><small>Total generated</small></span>
                      <span><b>{autoTaskSettings.remaining_today || 0}</b><small>Remaining today</small></span>
                    </div>
                    {isFounder ? (
                      <>
                        <div className="auto-task-setting-row">
                          <label>Generation mode
                            <select value={autoTaskSettings.mode} onChange={(e) => setAutoTaskSettings((current) => ({ ...current, mode: e.target.value }))}>
                              <option value="custom">Custom daily target</option>
                              <option value="unlimited">Unlimited mode (safe cap)</option>
                            </select>
                          </label>
                          {autoTaskSettings.mode === "custom" && (
                            <label>Daily missions (1–50)
                              <input type="number" min="1" max="50" value={autoTaskSettings.daily_target} onChange={(e) => setAutoTaskSettings((current) => ({ ...current, daily_target: e.target.value }))} />
                            </label>
                          )}
                        </div>
                        <small className="auto-task-safety-note">{autoTaskSettings.mode === "unlimited" ? "Unlimited mode publishes up to 20 missions per day to protect Gemini API usage and the 512 MB database." : "Custom mode publishes up to your selected number per day (maximum 50)."}</small>
                        <div className="auto-task-setting-row">
                          <label>Automatic task archiving
                            <select
                              value={autoTaskSettings.auto_archive_enabled ? "enabled" : "disabled"}
                              onChange={(e) => setAutoTaskSettings((current) => ({ ...current, auto_archive_enabled: e.target.value === "enabled" }))}
                            >
                              <option value="enabled">Enabled</option>
                              <option value="disabled">Disabled</option>
                            </select>
                          </label>
                          <label>Keep completed tasks for (days)
                            <input
                              type="number"
                              min="1"
                              max="3650"
                              value={autoTaskSettings.auto_archive_after_days}
                              onChange={(e) => setAutoTaskSettings((current) => ({ ...current, auto_archive_after_days: e.target.value }))}
                            />
                          </label>
                        </div>
                        <small className="auto-task-safety-note">
                          When enabled, completed assigned tasks and closed shared missions are automatically archived after the selected number of days. Active, paused and review tasks are never archived. Archived records stay in the database for history, audit and XP.
                        </small>
                        <div className="auto-task-actions">
                          <button className="primary" onClick={saveAutoTaskSettings} disabled={autoTaskBusy}>Save automation settings</button>
                          <button className="secondary" onClick={generateAutoTasksNow} disabled={autoTaskBusy}>Generate now</button>
                          <button className="secondary" onClick={runAutoArchiveNow} disabled={autoTaskBusy || !autoTaskSettings.auto_archive_enabled}>Archive eligible now</button>
                        </div>
                      </>
                    ) : (
                      <small className="auto-task-safety-note">Founder controls generation mode and limits. Current mode: {autoTaskSettings.mode === "unlimited" ? "Unlimited (20/day safety cap)" : "Custom · " + autoTaskSettings.daily_target + "/day"}.</small>
                    )}
                  </div>
                </div>
              )}
                </div>
              </details>
            
              </div>
            </>
          )}

          {page === "Digital ID Cards" && (
            <div className="id-studio-page">
              <div className="title">
                <div>
                  <label>IDENTITY STUDIO</label>
                  <h1>Digital ID cards</h1>
                  <p>Issue secure, server-verifiable QR cards for active members.</p>
                </div>
                <button className="secondary" onClick={() => window.print()}>
                  <Download size={14} /> Print / Save card as PDF
                </button>
              </div>
              {isAdmin && <div className="card-role-tabs">
                {["Founder", "Core Management", "Faculty", "Member"].map((role) => (
                  <button
                    key={role}
                    className={cardRoleFilter === role ? "active" : ""}
                    onClick={() => {
                      setCardRoleFilter(role);
                      const next = members.find((m) => m.role === role);
                      if (next) {
                        setSelected(next);
                        setIssuedCard(null);
                      }
                    }}
                  >
                    {role} IDs{" "}
                    <span>
                      {members.filter((m) => m.role === role).length}
                    </span>
                  </button>
                ))}
              </div>}
              <div className={isAdmin ? "idlayout" : "idlayout member-idlayout"}>
                <div
                  className={
                    "idcard " +
                    (selected?.id === user.id && ownCard?.verification_url ? "hasOwnQr " : "") +
                    (selected?.role === "Founder"
                      ? "founderCard"
                      : selected?.role === "Core Management"
                      ? "coreCard"
                      : "memberCard")
                  }
                >
                  {selected?.id === user.id && ownCard?.verification_url && (
                    <div className="id-qr-corner" title="Your secure TechNova verification QR">
                      <QRCodeSVG value={ownCard.verification_url} size={76} level="M" />
                      <small>SCAN ID</small>
                    </div>
                  )}
                  <div className="cardbrand">
                    <div className="miniTN"><TechNovaLogo /></div>
                    <div>
                      <b>
                        Tech<span>Nova</span>
                      </b>
                      <small>COLLEGE TECHNICAL CLUB</small>
                    </div>
                  </div>
                  {selected ? (
                    <>
                      <div className="cardperson">
                        <div className="photo">{initials(selected.name)}</div>
                        <div>
                          <label>
                            {selected.role === "Core Management"
                              ? "CORE MANAGEMENT TEAM"
                              : selected.role.toUpperCase()}
                          </label>
                          <h2>{selected.name}</h2>
                          <span>{selected.member_id}</span>
                        </div>
                      </div>
                      <section className="card-progression" aria-label="TechNova progression and leadership rank">
                        <div className="card-progression-heading">
                          <span>{selectedProgress?.progression_type === "founder" ? "TECHNOVA LEADERSHIP" : "TECHNOVA PROGRESSION"}</span>
                          {selectedProgress && selectedProgress.progression_type !== "founder" && <b>LEVEL {selectedProgress.level}</b>}
                        </div>
                        {progressLoading && !selectedProgress ? (
                          <div className="card-progression-loading">Calculating member progress…</div>
                        ) : selectedProgress?.progression_type === "founder" ? (
                          <div className="founder-origin-panel">
                            <div className="card-progression-title">{selectedProgress.level_title}</div>
                            <p>Permanent leadership status — not earned through XP, tasks, or credits.</p>
                            <span>Founder authority is role-based, never level-based.</span>
                          </div>
                        ) : selectedProgress ? (
                          <>
                            <div className="card-progression-title">{selectedProgress.level_title}</div>
                            <div className="card-progression-xp">
                              <strong>{Number(selectedProgress.xp).toLocaleString("en-IN")} XP</strong>
                              <span>{Number(selectedProgress.xp_to_next_level).toLocaleString("en-IN")} XP to next level</span>
                            </div>
                            <div
                              className="card-progression-track"
                              role="progressbar"
                              aria-label="Progress to next level"
                              aria-valuemin={0}
                              aria-valuemax={100}
                              aria-valuenow={selectedProgress.level_progress}
                            >
                              <span style={{ width: selectedProgress.level_progress + "%" }} />
                            </div>
                            <div className="card-progression-foot">
                              <span>{selectedProgress.completed_tasks} approved · {selectedProgress.pending_reviews} in review</span>
                              <span>{selectedProgress.credits} credits · Rank {selectedProgress.credit_rank}</span>
                            </div>
                          </>
                        ) : (
                          <div className="card-progression-loading">
                            {progressError || "Member progress is not available yet."}
                          </div>
                        )}
                      </section>
                      <div className="carddata">
                        <p>
                          <small>TEAM</small>
                          <b>{selected.team}</b>
                        </p>
                        <p>
                          <small>STATUS</small>
                          <b>{selected.status}</b>
                        </p>
                        <p>
                          <small>EMAIL</small>
                          <b>{selected.email || "—"}</b>
                        </p>
                        <p>
                          <small>COLLEGE</small>
                          <b>Mangaldeep College of Engineering</b>
                        </p>
                      </div>
                      <div className="cardtag">
                        CREATE · CODE · INNOVATE{" "}
                        <span>TECHNOVA / 2026</span>
                      </div>
                    </>
                  ) : (
                    <div className="empty">Choose a member.</div>
                  )}
                </div>
                {isAdmin && <div className="panel qrpanel">
                  <h3>Choose a cardholder</h3>
                  <p>Only active members can receive cards.</p>
                  <div className="picker">
                    {members
                      .filter((m) => m.role === cardRoleFilter)
                      .map((m) => (
                        <button
                          className={selected?.id === m.id ? "picked" : ""}
                          key={m.id}
                          onClick={() => {
                            setSelected(m);
                            setIssuedCard(null);
                          }}
                        >
                          <div className="avatar">{initials(m.name)}</div>
                          <div>
                            <b>{m.name}</b>
                            <small>
                              {m.member_id} · {m.role} · {m.status}
                            </small>
                          </div>
                        </button>
                      ))}
                  </div>
                  {selected && (
                    <div className="cardcontrols">
                      {isFounder && selected.status === "Active" && (
                        <button
                          className="primary"
                          onClick={() => issueCard(selected)}
                        >
                          <ShieldCheck size={14} /> Issue / replace secure card
                        </button>
                      )}
                      {isFounder && (
                        <button
                          className="secondary"
                          onClick={() => revokeCard(selected)}
                        >
                          Revoke active card
                        </button>
                      )}
                    </div>
                  )}
                  {issuedCard && (
                    <div className="qrwrap">
                      <QRCodeSVG
                        value={issuedCard.verification_url}
                        size={105}
                      />
                      <div>
                        <b>Issued verification QR</b>
                        <p>
                          Keep this token private. The QR opens the public
                          verification page.
                        </p>
                        <code>{issuedCard.verification_url}</code>
                        <button
                          className="secondary"
                          onClick={() => {
                            navigator.clipboard?.writeText(
                              issuedCard.verification_url
                            );
                            notify(
                              "Verification URL copied if clipboard permission is available."
                            );
                          }}
                        >
                          Copy verification URL
                        </button>
                      </div>
                    </div>
                  )}
                </div>}
              </div>
            </div>
          )}

          {page === "Verification" && (
            <>
              <div className="title">
                <div>
                  <label>TRUST & SAFETY</label>
                  <h1>ID verification</h1>
                  <p>Verify an issued QR token using the backend.</p>
                </div>
              </div>
              <div className="verify panel">
                <div className="verifyicon">
                  <ShieldCheck size={26} />
                </div>
                <h2>Verify a member card</h2>
                <p>
                  Paste the secure token from the card URL, or open a QR
                  verification link directly.
                </p>
                <form onSubmit={verify}>
                  <input
                    value={verifyToken}
                    onChange={(e) => setVerifyToken(e.target.value)}
                    placeholder="Paste verification token or URL"
                    required
                  />
                  <button className="primary">Verify ID</button>
                </form>
                {isAdmin && (
                  <>
                    <div className="scan-actions">
                      <button
                        className="secondary"
                        type="button"
                        onClick={() => setScanEnabled((v) => !v)}
                      >
                        {scanEnabled
                          ? "Stop camera scanner"
                          : "Scan QR with camera"}
                      </button>
                      <small>
                        Allow camera permission when prompted. HTTPS or
                        localhost is required by most browsers.
                      </small>
                    </div>
                    {scanEnabled && (
                      <div id="technova-qr-reader" className="qr-reader" />
                    )}
                  </>
                )}
                {verifyResult && (
                  <div
                    className={
                      "verifyresult " + (verifyResult.valid ? "good" : "bad")
                    }
                  >
                    <b>
                      {verifyResult.valid
                        ? "✓ Valid active member"
                        : "✕ " + (verifyResult.status || "Card invalid")}
                    </b>
                    {verifyResult.valid && (
                      <>
                        <p>
                          {verifyResult.name} · {verifyResult.member_id}
                        </p>
                        <small>
                          {verifyResult.role} · {verifyResult.club}
                        </small>
                        {verifyResult.progression_type === "founder" ? (
                          <div className="verify-member-progress founder-origin-verify">
                            <b>{verifyResult.level_title || "Founder · Origin Rank"}</b>
                            <span>Permanent leadership status · Not XP-based</span>
                          </div>
                        ) : verifyResult.level_title && (
                          <div className="verify-member-progress">
                            <b>Level {verifyResult.level} · {verifyResult.level_title}</b>
                            <span>{Number(verifyResult.xp || 0).toLocaleString("en-IN")} XP</span>
                          </div>
                        )}
                        {user &&
                          ["Founder", "Core Management"].includes(user.role) &&
                          (!isAdmin ||
                            user.role === "Founder" ||
                            verifyResult.role === "Member") && (
                            <div className="confirm-row">
                              <button
                                className="primary"
                                onClick={confirmVerification}
                                disabled={verifyResult.confirmed}
                              >
                                {verifyResult.confirmed
                                  ? "Identity confirmed ✓"
                                  : "Confirm identity"}
                              </button>
                              <small>
                                Confirm only after matching the photo/name to
                                the person.
                              </small>
                            </div>
                          )}
                      </>
                    )}
                  </div>
                )}
                {verifyResult?.valid && reviewQueueMemberId === verifyResult.member_id && (
                  <div className="panel tablepanel task-review-queue">
                    <div className="panelhead">
                      <b>Completion confirmations</b>
                      <small>
                        {verifyResult.name} · {verifyResult.member_id} · {verifyResult.team || "Unassigned"}
                      </small>
                    </div>
                    {pendingReviewTasks.length ? (
                      <div className="overflow">
                        <table>
                          <thead>
                            <tr>
                              <th>TASK</th>
                              <th>PROJECT / TEAM</th>
                              <th>SUBMISSION NOTE</th>
                              <th>CONFIRM</th>
                            </tr>
                          </thead>
                          <tbody>
                            {pendingReviewTasks.map((task) => (
                              <tr key={task.id}>
                                <td>
                                  <b>{task.title}</b>
                                  <small className="sub">{task.id.slice(-6)} · {task.assignee_name}</small>
                                </td>
                                <td>{task.project}<small className="sub">{task.assignee_team || verifyResult.team || "Unassigned"}</small></td>
                                <td>{task.submission_note || "No note provided"}</td>
                                <td>
                                  <button className="primary" onClick={() => confirmTaskCompletion(task)}>
                                    <Check size={14} /> Confirm completion
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    ) : (
                      <div className="empty">No tasks are awaiting completion confirmation for this member.</div>
                    )}
                    <small className="sub queue-help">
                      Confirm only after scanning this assignee's QR and checking the submitted work.
                    </small>
                  </div>
                )}
                <div className="privacy">
                  <ShieldCheck size={18} /> Verification checks a random token
                  hash and member status on the server. Public responses omit
                  private email data.
                </div>
              </div>
            </>
          )}

          {page === "Teams" && (
            <>
              <div className="title">
                <div>
                  <label>COLLABORATION</label>
                  <h1>Teams</h1>
                  <p>Manage club focus areas and team descriptions.</p>
                </div>
                {isAdmin && (
                  <button className="primary" onClick={() => setModal("team")}>
                    <Plus size={14} /> New team
                  </button>
                )}
              </div>
              <div className="teams">
                {teams.map((t) => (
                  <div className="panel team" key={t.id}>
                    <FolderKanban />
                    <h3>{t.name}</h3>
                    <p>{t.description}</p>
                    <small>
                      {members.filter((m) => m.team === t.name).length} members
                      assigned
                    </small>
                    {isAdmin && (
                      <div className="team-roster">
                        {members.filter((m) => m.team === t.name).map((member) => (
                          <div className="team-member" key={member.id}>
                            <span>
                              <b>{member.name}</b>
                              <small>{member.member_id}</small>
                            </span>
                            <em>{member.role}</em>
                          </div>
                        ))}
                        {!members.some((m) => m.team === t.name) && (
                          <p className="team-empty">No members assigned yet.</p>
                        )}
                      </div>
                    )}
                  </div>
                ))}
                {isAdmin && (
                  <div className="panel team unassigned-team">
                    <FolderKanban />
                    <h3>Unassigned</h3>
                    <p>Members who have not been placed in a team.</p>
                    <small>{members.filter((m) => !m.team || m.team === "Unassigned").length} members</small>
                    <div className="team-roster">
                      {members.filter((m) => !m.team || m.team === "Unassigned").map((member) => (
                        <div className="team-member" key={member.id}>
                          <span>
                            <b>{member.name}</b>
                            <small>{member.member_id}</small>
                          </span>
                          <em>{member.role}</em>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </>
          )}

          {page === "Settings" && (
            <>
              <div className="title">
                <div>
                  <label>ACCOUNT SECURITY</label>
                  <h1>Settings</h1>
                  <p>Change your password and review secure portal practices.</p>
                </div>
              </div>
              <div className="panel settings">
                {isAdmin && <TwoFactorSettings token={token} />}
                {isFounder && <StorageSettings token={token} />}
                <ContactNotificationSettings token={token} />
                <PushNotificationSettings token={token} />
                {isFounder && (
                  <div className="email-delivery-panel">
                    <h3>Email notifications</h3>
                    <p>Check the backend email provider and send a real test email to your Founder address.</p>
                    {emailStatus && (
                      <div className="email-delivery-status">
                        <p><b>Email delivery:</b> {emailStatus.configured ? "Configured" : "Not configured"}</p>
                        <p><b>Provider:</b> {emailStatus.provider || "SMTP"}</p>
                        <p><b>Endpoint:</b> {emailStatus.host || "Not set"} · Port {emailStatus.port || "—"}</p>
                        <p><b>Sender:</b> {emailStatus.from_email || "Not set"}</p>
                        <p><b>Transport:</b> {emailStatus.transport || (emailStatus.use_ssl ? "SSL" : emailStatus.use_tls ? "STARTTLS" : "Unencrypted (not recommended)")}</p>
                        {emailStatus.missing?.length > 0 && (
                          <p className="email-delivery-warning"><b>Missing:</b> {emailStatus.missing.join(", ")}</p>
                        )}
                        {emailStatus.last_24_hours && (
                          <p><b>Last 24 hours:</b> {emailStatus.last_24_hours.sent} sent · {emailStatus.last_24_hours.failed} failed · {emailStatus.last_24_hours.not_configured} skipped (SMTP not set)</p>
                        )}
                      </div>
                    )}
                    <div className="email-delivery-actions">
                      <button type="button" className="secondary" onClick={checkEmailStatus} disabled={emailTestBusy}>Check email configuration</button>
                      <button type="button" className="primary" onClick={sendTestEmail} disabled={emailTestBusy}>{emailTestBusy ? "Sending..." : "Send test email to " + user.email}</button>
                    </div>
                  </div>
                )}
                <h3>Profile</h3>
                <form onSubmit={saveProfile}>
                  <label>
                    Display name
                    <input
                      required
                      minLength="2"
                      maxLength="100"
                      value={profileForm.name || user.name}
                      onChange={(e) =>
                        setProfileForm({ ...profileForm, name: e.target.value })
                      }
                    />
                  </label>
                  <div className="profile-team">
                    <small>Assigned team</small>
                    <b>{user.team || "Unassigned"}</b>
                    <span>Team assignments are managed by the Founder.</span>
                  </div>
                  <button className="secondary">Save profile</button>
                </form>

                <h3>Change password</h3>
                <form onSubmit={changePassword}>
                  <label>
                    Current password
                    <input
                      type="password"
                      required
                      value={settingsForm.current_password}
                      onChange={(e) =>
                        setSettingsForm({
                          ...settingsForm,
                          current_password: e.target.value,
                        })
                      }
                    />
                  </label>
                  <label>
                    New password (12+ characters)
                    <input
                      type="password"
                      minLength="12"
                      required
                      value={settingsForm.new_password}
                      onChange={(e) =>
                        setSettingsForm({
                          ...settingsForm,
                          new_password: e.target.value,
                        })
                      }
                    />
                  </label>
                  <button className="primary">Update password</button>
                </form>

                <h3>Security notes</h3>
                {[
                  "Role permissions are enforced by FastAPI.",
                  "Passwords are hashed using Argon2.",
                  "Card tokens are random; only token hashes are stored.",
                  "Use HTTPS and rotate environment secrets before deployment.",
                ].map((x) => (
                  <p className="checkline" key={x}>
                    <ShieldCheck size={15} />
                    {x}
                  </p>
                ))}
              </div>
            </>
          )}

          {page === "Audit Log" && (
            <>
              <div className="title">
                <div>
                  <label>FOUNDER CONTROLS</label>
                  <h1>Audit log</h1>
                  <p>Recent security-sensitive actions recorded by the API.</p>
                </div>
                <button className="secondary" onClick={loadAudit}>
                  <RefreshCw size={14} /> Refresh
                </button>
              </div>
              <div className="panel tablepanel">
                <div className="overflow">
                  <table>
                    <thead>
                      <tr>
                        <th>TIME</th>
                        <th>ACTION</th>
                        <th>ROLE</th>
                        <th>TARGET</th>
                      </tr>
                    </thead>
                    <tbody>
                      {audit.map((a) => (
                        <tr key={a.id}>
                          <td>
                            {a.created_at
                              ? new Date(a.created_at).toLocaleString()
                              : "—"}
                          </td>
                          <td>{a.action}</td>
                          <td>{a.actor_role || "Public"}</td>
                          <td>{a.target}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {!audit.length && (
                  <div className="empty">Click Refresh to load audit events.</div>
                )}
              </div>
            </>
          )}
        </section>

        <footer>
          © 2026 TechNova · Create • Code • Innovate{" "}
          <span>
            <i /> Connected to API
          </span>
        </footer>
      </main>

      {modal && (
        <div className="backdrop" onClick={() => setModal("")}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button className="modalx" onClick={() => setModal("")}>
              ×
            </button>
            <label className="eyebrow">
              {modal === "member"
                ? "MEMBER MANAGEMENT"
                : modal === "task"
                ? "PROJECT WORKSPACE"
                : modal === "taskSubmission"
                ? "TASK COMPLETION EVIDENCE"
                : modal === "announcement"
                ? "CLUB-WIDE COMMUNICATION"
                : "TEAM SETTINGS"}
            </label>
            <h2>
              {modal === "member"
                ? "Create an account"
                : modal === "task"
                ? "Create a task"
                : modal === "taskSubmission"
                ? "Submit task for review"
                : modal === "announcement"
                ? "Broadcast an announcement"
                : "Create a team"}
            </h2>
            <p>
              {modal === "announcement"
                ? "This message will appear in the inbox of every active Member and Faculty account."
                : modal === "taskSubmission"
                ? "Attach a screenshot link and explain what you completed. Founder/Core Management will inspect the evidence before marking the task Done."
                : "Data is validated and saved by the API."}
            </p>

            {modal === "member" && (
              <form onSubmit={createMember}>
                <label>
                  Full name
                  <input
                    required
                    minLength="2"
                    value={memberForm.name}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, name: e.target.value })
                    }
                  />
                </label>
                <label>
                  Email
                  <input
                    required
                    type="email"
                    value={memberForm.email}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, email: e.target.value })
                    }
                  />
                </label>
                <label>
                  Temporary password (12+ chars)
                  <input
                    required
                    minLength="12"
                    type="password"
                    value={memberForm.password}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, password: e.target.value })
                    }
                  />
                </label>
                <label>
                  Role
                  <select
                    value={memberForm.role}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, role: e.target.value })
                    }
                  >
                    <option>Member</option>
                    <option>Faculty</option>
                    <option>Core Management</option>
                  </select>
                  {memberForm.role === "Faculty" && (
                    <small className="field-help">Faculty can receive announcements and view club updates, but cannot be assigned student tasks or approve submissions.</small>
                  )}
                </label>
                <label>
                  Team
                  <input
                    value={memberForm.team}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, team: e.target.value })
                    }
                  />
                </label>
                <label>
                  Status
                  <select
                    value={memberForm.status}
                    onChange={(e) =>
                      setMemberForm({ ...memberForm, status: e.target.value })
                    }
                  >
                    <option>Active</option>
                    <option>Pending</option>
                  </select>
                </label>
                <div className="modalactions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setModal("")}
                  >
                    Cancel
                  </button>
                  <button className="primary" disabled={busy}>
                    Create member
                  </button>
                </div>
              </form>
            )}

            {modal === "task" && (
              <form onSubmit={createTask}>
                <label>
                  Task title
                  <input
                    required
                    minLength="3"
                    value={taskForm.title}
                    onChange={(e) =>
                      setTaskForm({ ...taskForm, title: e.target.value })
                    }
                  />
                </label>
                <label>
                  Description
                  <textarea
                    value={taskForm.description}
                    onChange={(e) =>
                      setTaskForm({ ...taskForm, description: e.target.value })
                    }
                  />
                </label>
                <label>
                  Assignment type
                  <select
                    value={taskForm.assignment_mode}
                    onChange={(e) => setTaskForm({
                      ...taskForm,
                      assignment_mode: e.target.value,
                      assignee_id: "",
                      assignee_ids: [],
                    })}
                  >
                    <option value="individual">One member</option>
                    <option value="selected_members">Multiple selected members</option>
                    <option value="open_to_all">Common task — all Members can choose</option>
                  </select>
                </label>
                {taskForm.assignment_mode === "individual" && (
                  <label>
                    Assignee
                    <select
                      required
                      value={taskForm.assignee_id}
                      onChange={(e) => setTaskForm({ ...taskForm, assignee_id: e.target.value })}
                    >
                      <option value="">Choose active member</option>
                      {eligibleAssignees.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} · {m.role} · {m.member_id}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                {taskForm.assignment_mode === "selected_members" && (
                  <div className="member-picker">
                    <b>Select members for this task ({taskForm.assignee_ids.length} selected)</b>
                    <small>Each selected member receives a separate task card and can track progress independently.</small>
                    <input
                      type="search"
                      value={assigneeSearch}
                      onChange={(e) => setAssigneeSearch(e.target.value)}
                      placeholder="Search member name, ID or team..."
                    />
                    <div className="member-picker-list">
                      {filteredAssignees.map((m) => (
                        <label className="member-picker-option" key={m.id}>
                          <input
                            type="checkbox"
                            checked={taskForm.assignee_ids.includes(m.id)}
                            onChange={(e) => setTaskForm({
                              ...taskForm,
                              assignee_ids: e.target.checked
                                ? [...taskForm.assignee_ids, m.id]
                                : taskForm.assignee_ids.filter((id) => id !== m.id),
                            })}
                          />
                          <span><b>{m.name}</b><small>{m.role} · {m.member_id} · {m.team || "Unassigned"}</small></span>
                        </label>
                      ))}
                      {!filteredAssignees.length && <small>No active members match this search.</small>}
                    </div>
                  </div>
                )}
                {taskForm.assignment_mode === "open_to_all" && (
                  <div className="assignment-hint">
                    <b>Open volunteer task</b>
                    <p>This appears in every active Member’s Common Tasks board. Each person can accept or decline; accepted tasks are tracked separately.</p>
                  </div>
                )}
                <label>
                  Project
                  <input
                    value={taskForm.project}
                    onChange={(e) =>
                      setTaskForm({ ...taskForm, project: e.target.value })
                    }
                  />
                </label>
                <div className="twocol">
                  <label>
                    Task difficulty · credit reward
                    <select
                      value={taskForm.difficulty_rank}
                      onChange={(e) => setTaskForm({ ...taskForm, difficulty_rank: e.target.value })}
                    >
                      <option value="F">F · Starter · 5 credits</option>
                      <option value="E">E · Easy · 10 credits</option>
                      <option value="D">D · Basic · 20 credits</option>
                      <option value="C">C · Intermediate · 35 credits</option>
                      <option value="B">B · Skilled · 55 credits</option>
                      <option value="A">A · Advanced · 85 credits</option>
                      <option value="S">S · Expert · 125 credits</option>
                      <option value="SS">SS · Elite · 175 credits</option>
                      <option value="SSS">SSS · Legendary · 250 credits</option>
                    </select>
                  </label>
                  <label>
                    Coding language / technology
                    <select
                      value={taskForm.programming_language}
                      onChange={(e) => setTaskForm({ ...taskForm, programming_language: e.target.value })}
                    >
                      {["General", "C", "C++", "C#", "Java", "Python", "JavaScript", "TypeScript", "HTML/CSS", "React", "FastAPI", "SQL / MongoDB", "Godot / GDScript", "Other"].map((language) => (
                        <option key={language} value={language}>{language}</option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="twocol">
                  <label>
                    Task schedule
                    <select value={taskForm.recurrence} onChange={(e) => setTaskForm({ ...taskForm, recurrence: e.target.value })}>
                      <option value="once">One-time task</option>
                      <option value="daily">Repeat automatically every day</option>
                    </select>
                  </label>
                  <label>
                    Priority
                    <select
                      value={taskForm.priority}
                      onChange={(e) =>
                        setTaskForm({ ...taskForm, priority: e.target.value })
                      }
                    >
                      <option>Low</option>
                      <option>Medium</option>
                      <option>High</option>
                    </select>
                  </label>
                  <label>
                    Due date
                    <input
                      type="date"
                      value={taskForm.due_date}
                      onChange={(e) =>
                        setTaskForm({ ...taskForm, due_date: e.target.value })
                      }
                    />
                  </label>
                </div>
                <div className="modalactions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setModal("")}
                  >
                    Cancel
                  </button>
                  <button className="primary" disabled={busy}>
                    Create task
                  </button>
                </div>
              </form>
            )}

            {modal === "taskSubmission" && (
              <form onSubmit={submitTaskForReview} className="submission-form">
                <div className="submission-task-heading">
                  <small>SUBMITTING</small>
                  <b>{submissionForm.title}</b>
                </div>
                <div className="submission-help">
                  <b>Step 1 · Capture your work</b>
                  <small>Take a screenshot of the completed result. Upload it to ImagePaste, then paste the share link below. For a permanent link, sign in to ImagePaste before uploading.</small>
                  <a href="https://imagepaste.org/" target="_blank" rel="noreferrer">Open ImagePaste uploader ↗</a>
                </div>
                <label>
                  Screenshot evidence link
                  <input
                    required
                    type="url"
                    value={submissionForm.submission_evidence_url}
                    onChange={(event) => setSubmissionForm({ ...submissionForm, submission_evidence_url: event.target.value })}
                    placeholder="https://imagepaste.org/..."
                  />
                </label>
                {submissionForm.submission_evidence_url.startsWith("https://") && (
                  <div className="submission-preview">
                    <small>Screenshot preview</small>
                    <img
                      src={submissionForm.submission_evidence_url}
                      alt="Submission evidence preview"
                      onError={(event) => { event.currentTarget.style.display = "none"; }}
                    />
                  </div>
                )}
                <label>
                  Project / demo / repository link <span className="optional-label">(optional)</span>
                  <input
                    type="url"
                    value={submissionForm.project_url}
                    onChange={(event) => setSubmissionForm({ ...submissionForm, project_url: event.target.value })}
                    placeholder="https://github.com/... or https://your-demo..."
                  />
                </label>
                <label>
                  What did you complete?
                  <textarea
                    required
                    minLength={10}
                    maxLength={2000}
                    rows={4}
                    value={submissionForm.submission_note}
                    onChange={(event) => setSubmissionForm({ ...submissionForm, submission_note: event.target.value })}
                    placeholder="Describe the result, what you tested, and which task requirements are complete..."
                  />
                </label>
                <label className="submission-attestation">
                  <input
                    type="checkbox"
                    checked={submissionForm.submission_attested}
                    onChange={(event) => setSubmissionForm({ ...submissionForm, submission_attested: event.target.checked })}
                    required
                  />
                  <span>I confirm this screenshot and the links show my current work for this task.</span>
                </label>
                <div className="modalactions">
                  <button type="button" className="secondary" onClick={() => setModal("")}>Cancel</button>
                  <button className="primary" disabled={busy || !submissionForm.submission_attested}>Submit evidence for review</button>
                </div>
              </form>
            )}

            {modal === "announcement" && (
              <form onSubmit={createAnnouncement}>
                <label>
                  Announcement title
                  <input
                    required
                    minLength="3"
                    maxLength="120"
                    value={announcementForm.title}
                    onChange={(e) => setAnnouncementForm({ ...announcementForm, title: e.target.value })}
                    placeholder="e.g. TechNova weekly meeting"
                  />
                </label>
                <label>
                  Message
                  <textarea
                    required
                    minLength="3"
                    maxLength="3000"
                    rows={5}
                    value={announcementForm.message}
                    onChange={(e) => setAnnouncementForm({ ...announcementForm, message: e.target.value })}
                    placeholder="Write the announcement, meeting details, deadline or instructions..."
                  />
                </label>
                <div className="announcement-audience">
                  <b>Audience: all active Members + Faculty</b>
                  <small>In-app notifications are immediate. Email delivery is also enabled when SMTP is configured on the backend.</small>
                </div>
                <div className="modalactions">
                  <button type="button" className="secondary" onClick={() => setModal("")}>Cancel</button>
                  <button className="primary" disabled={busy}>Send announcement</button>
                </div>
              </form>
            )}

            {modal === "team" && (
              <form onSubmit={createTeam}>
                <label>
                  Team name
                  <input name="name" required minLength="2" />
                </label>
                <label>
                  Description
                  <textarea name="description" />
                </label>
                <div className="modalactions">
                  <button
                    type="button"
                    className="secondary"
                    onClick={() => setModal("")}
                  >
                    Cancel
                  </button>
                  <button className="primary">Create team</button>
                </div>
              </form>
            )}
          </div>
        </div>
      )}

      {toast && <div className="toast">✓ {toast}</div>}
    </div>
  );
}

export default App;


/* Management MFA enrollment and trusted-device controls */
