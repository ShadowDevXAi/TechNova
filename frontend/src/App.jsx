import React, { useEffect, useState } from "react";
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
} from "lucide-react";
import { QRCodeSVG } from "qrcode.react";
import { Html5QrcodeScanner } from "html5-qrcode";


const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  "https://technova-5h0g.onrender.com"
).replace(/\/$/, "");


const API_BASE = (
  import.meta.env.VITE_API_BASE_URL ||
  "https://technova-5h0g.onrender.com"
).replace(/\/$/, "");

const api = async (path, token, opts = {}) => {
  const isForm = opts.body instanceof FormData;

  const r = await fetch(`${API_BASE}/api${path}`, {
    ...opts,
    headers: {
      ...(!isForm ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: "Bearer " + token } : {}),
      ...(opts.headers || {}),
    },
  });

  let data = {};

  try {
    data = await r.json();
  } catch {
    // Handle empty or non-JSON responses.
  }

  if (!r.ok) {
    throw new Error(
      data.detail || data.message || "Request failed: " + r.status
    );
  }

  return data;
};


const links = [
  ["Overview", LayoutDashboard],
  ["Members", Users],
  ["Tasks & Projects", ClipboardList],
  ["Digital ID Cards", CreditCard],
  ["Verification", ShieldCheck],
  ["Teams", FolderKanban],
  ["Settings", Settings],
];

function App() {
  const [token, setToken] = useState(localStorage.getItem("tn_token") || "");
  const [user, setUser] = useState(null);
  const [page, setPage] = useState("Overview");
  const [members, setMembers] = useState([]);
  const [tasks, setTasks] = useState([]);
  const [teams, setTeams] = useState([]);
  const [dashboard, setDashboard] = useState(null);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [modal, setModal] = useState("");
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
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
    assignee_id: "",
    priority: "Medium",
    due_date: "",
    project: "Club projects",
  });
  const [verifyToken, setVerifyToken] = useState("");
  const [verifyResult, setVerifyResult] = useState(null);
  const [issuedCard, setIssuedCard] = useState(null);
  const [scanEnabled, setScanEnabled] = useState(false);
  const [cardRoleFilter, setCardRoleFilter] = useState("Founder");
  const [settingsForm, setSettingsForm] = useState({
    current_password: "",
    new_password: "",
  });
  const [profileForm, setProfileForm] = useState({ name: "", team: "" });
  const [audit, setAudit] = useState([]);

  const notify = (s) => {
    setToast(s);
    setTimeout(() => setToast(""), 3000);
  };

  const fail = (e) => setError(e.message || "Something went wrong");

  const load = async (t = token) => {
    if (!t) return;
    setError("");
    try {
      const me = await api("/auth/me", t);
      setUser(me);
      const [d, ms, ts, tm] = await Promise.all([
        api("/dashboard", t),
        api("/members", t),
        api("/tasks", t),
        api("/teams", t),
      ]);
      setDashboard(d);
      setMembers(ms);
      setTasks(ts);
      setTeams(tm);
      if (!selected && ms.length) setSelected(ms[0]);
    } catch (e) {
      localStorage.removeItem("tn_token");
      setToken("");
      setUser(null);
      setError(e.message);
    }
  };

  useEffect(() => {
    if (token) load(token);
  }, [token]);

  useEffect(() => {
    const p = window.location.pathname.match(/^\/verify\/([^/]+)$/);
    if (p) {
      setPage("Verification");
      setVerifyToken(decodeURIComponent(p[1]));
      setVerifyResult(null);
    }
  }, []);

  useEffect(() => {
    if (!scanEnabled || page !== "Verification") return;
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
            const result = await api(
              "/verify/" + encodeURIComponent(candidate),
              ""
            );
            setVerifyResult(result);
          } catch (err) {
            setVerifyResult({ valid: false, status: err.message });
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

  const isAdmin = user && ["Founder", "Core Management"].includes(user.role);
  const isFounder = user?.role === "Founder";

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

  function logout() {
    localStorage.removeItem("tn_token");
    setToken("");
    setUser(null);
    setMembers([]);
    setTasks([]);
    setDashboard(null);
    setPage("Overview");
    window.history.replaceState({}, "", "/");
  }

  async function refresh() {
    try {
      await load();
    } catch (e) {
      fail(e);
    }
  }

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

  async function approveMember(m) {
    try {
      await api(`/members/${m.id}/approve`, token, { method: "POST" });
      notify("Member approved");
      await refresh();
    } catch (e) {
      fail(e);
    }
  }

  async function createTask(e) {
    e.preventDefault();
    setBusy(true);
    try {
      await api("/tasks", token, {
        method: "POST",
        body: JSON.stringify(taskForm),
      });
      setModal("");
      setTaskForm({
        title: "",
        description: "",
        assignee_id: "",
        priority: "Medium",
        due_date: "",
        project: "Club projects",
      });
      notify("Task created");
      await refresh();
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }

  async function uploadAttachment(taskId, file) {
    const fd = new FormData();
    fd.append("file", file);
    try {
      await api(`/tasks/${taskId}/attachments`, token, {
        method: "POST",
        body: fd,
      });
      notify("Attachment uploaded");
    } catch (e) {
      fail(e);
    }
  }

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

  async function revokeCard(m) {
    try {
      await api(`/cards/${m.id}/revoke`, token, { method: "POST" });
      setIssuedCard(null);
      notify("Card revoked");
    } catch (e) {
      fail(e);
    }
  }

  function extractCardToken(value) {
    let candidate = (value || "").trim();
    if (candidate.startsWith("http://") || candidate.startsWith("https://")) {
      const u = new URL(candidate);
      candidate = u.pathname.split("/").filter(Boolean).pop() || "";
    }
    return candidate;
  }

  async function verify(e) {
    e?.preventDefault();
    try {
      let candidate = extractCardToken(verifyToken);
      if (!candidate) {
        throw new Error("Scan a QR code or paste its verification URL");
      }
      let v = await api("/verify/" + encodeURIComponent(candidate), "");
      setVerifyResult(v);
    } catch (e) {
      setVerifyResult({ valid: false, status: e.message });
    }
  }

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

  async function saveProfile(e) {
    e.preventDefault();
    try {
      let updated = await api("/auth/profile", token, {
        method: "PATCH",
        body: JSON.stringify(profileForm),
      });
      setUser(updated);
      notify("Profile saved");
    } catch (e) {
      fail(e);
    }
  }

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

  async function loadAudit() {
    try {
      setAudit(await api("/audit?limit=100", token));
    } catch (e) {
      fail(e);
    }
  }

  const filteredMembers = members.filter((m) =>
    (m.name + " " + m.member_id + " " + m.team + " " + m.email)
      .toLowerCase()
      .includes(search.toLowerCase())
  );

  if (!token || !user) {
    return (
      <div className="authscreen">
        <div className="authbrand">
          <div className="logo">TN</div>
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
              }}
            >
              {authMode === "login" ? "Create an account" : "Sign in"}
            </button>{" "}
            {authMode === "login" && (
              <button
                onClick={() => {
                  setAuthMode("reset");
                  setResetToken("");
                  setError("");
                }}
              >
                Forgot password?
              </button>
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
      <aside className={mobile ? "sidebar open" : "sidebar"}>
        <div className="brand">
          <div className="logo">TN</div>
          <div>
            <b>
              Tech<span>Nova</span>
            </b>
            <small>TECHNOLOGY DEVELOPMENT CLUB</small>
          </div>
          <button className="close" onClick={() => setMobile(false)}>
            <X />
          </button>
        </div>
        <div className="workspace">
          <span>TN</span>
          <div>
            <b>TechNova Club</b>
            <small>{user.role} workspace</small>
          </div>
        </div>
        <label className="navlabel">WORKSPACE</label>
        {links.slice(0, 4).map(([n, I]) => (
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
        {links.slice(4).map(([n, I]) => (
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
            onClick={() => setPage("Audit Log")}
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
          <button className="hamb" onClick={() => setMobile(!mobile)}>
            <Menu />
          </button>
          <div className="crumb">
            TechNova <span>/</span> <b>{page}</b>
          </div>
          <div className="topright">
            <div className="search">
              <Search size={15} />
              <input
                placeholder="Search current page…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <button className="bell" title="Refresh data" onClick={refresh}>
              <RefreshCw size={17} />
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
                  <div>TN</div>
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
                          <td>{m.team}</td>
                          <td>
                            <span className={"pill " + m.status.toLowerCase()}>
                              {m.status}
                            </span>
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
                                  <option>Core Management</option>
                                </select>
                              )}
                              {isFounder && m.role !== "Founder" && (
                                <button
                                  className="textbtn danger"
                                  onClick={() => {
                                    if (
                                      confirm(
                                        "Suspend this member and revoke their active cards?"
                                      )
                                    )
                                      api(`/members/${m.id}`, token, {
                                        method: "DELETE",
                                      })
                                        .then(refresh)
                                        .catch(fail);
                                  }}
                                >
                                  Suspend
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
                    <Plus size={14} /> Create task
                  </button>
                )}
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
              <div className="panel tablepanel">
                <div className="panelhead">
                  <b>Task board</b>
                  <small>Saved in MongoDB</small>
                </div>
                <div className="overflow">
                  <table>
                    <thead>
                      <tr>
                        <th>TASK</th>
                        <th>ASSIGNEE</th>
                        <th>PRIORITY</th>
                        <th>DUE</th>
                        <th>STATUS</th>
                        <th>COMMENTS</th>
                      </tr>
                    </thead>
                    <tbody>
                      {tasks
                        .filter((t) =>
                          (t.title + " " + t.assignee_name)
                            .toLowerCase()
                            .includes(search.toLowerCase())
                        )
                        .map((t) => (
                          <tr key={t.id}>
                            <td>
                              <b>{t.title}</b>
                              <small className="sub">
                                {t.id.slice(-6)} · {t.project}
                              </small>
                              {t.description && (
                                <small className="sub">{t.description}</small>
                              )}
                            </td>
                            <td>{t.assignee_name}</td>
                            <td>
                              <span className={"pill " + t.priority.toLowerCase()}>
                                {t.priority}
                              </span>
                            </td>
                            <td>{t.due_date || "Not set"}</td>
                            <td>
                              <select
                                value={t.status}
                                onChange={(e) =>
                                  updateTask(t, { status: e.target.value })
                                }
                              >
                                <option>Todo</option>
                                <option>In progress</option>
                                <option>Review</option>
                                <option>Done</option>
                              </select>
                            </td>
                            <td>
                              <button
                                className="textbtn"
                                onClick={async () => {
                                  let text = prompt("Add a task comment");
                                  if (text) {
                                    try {
                                      await api(
                                        `/tasks/${t.id}/comments`,
                                        token,
                                        {
                                          method: "POST",
                                          body: JSON.stringify({ text }),
                                        }
                                      );
                                      notify("Comment added");
                                    } catch (e) {
                                      fail(e);
                                    }
                                  }
                                }}
                              >
                                Comment
                              </button>{" "}
                              <label className="filebtn">
                                Attach
                                <input
                                  type="file"
                                  hidden
                                  onChange={(e) =>
                                    e.target.files?.[0] &&
                                    uploadAttachment(t.id, e.target.files[0])
                                  }
                                />
                              </label>
                            </td>
                          </tr>
                        ))}
                    </tbody>
                  </table>
                </div>
                {!tasks.length && (
                  <div className="empty">No tasks created yet.</div>
                )}
              </div>
            </>
          )}

          {page === "Digital ID Cards" && (
            <>
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
              <div className="card-role-tabs">
                {["Founder", "Core Management", "Member"].map((role) => (
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
              </div>
              <div className="idlayout">
                <div
                  className={
                    "idcard " +
                    (selected?.role === "Founder"
                      ? "founderCard"
                      : selected?.role === "Core Management"
                      ? "coreCard"
                      : "memberCard")
                  }
                >
                  <div className="cardbrand">
                    <div className="miniTN">TN</div>
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
                <div className="panel qrpanel">
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
                </div>
              </div>
            </>
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
                  </div>
                ))}
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
                  <label>
                    Team
                    <input
                      maxLength="80"
                      value={profileForm.team || user.team}
                      onChange={(e) =>
                        setProfileForm({ ...profileForm, team: e.target.value })
                      }
                    />
                  </label>
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
                : "TEAM SETTINGS"}
            </label>
            <h2>
              {modal === "member"
                ? "Create a member account"
                : modal === "task"
                ? "Create a task"
                : "Create a team"}
            </h2>
            <p>Data is validated and saved by the API.</p>

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
                    <option>Core Management</option>
                  </select>
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
                  Assignee
                  <select
                    required
                    value={taskForm.assignee_id}
                    onChange={(e) =>
                      setTaskForm({ ...taskForm, assignee_id: e.target.value })
                    }
                  >
                    <option value="">Choose active member</option>
                    {members
                      .filter(
                        (m) =>
                          m.status === "Active" &&
                          (isFounder
                            ? ["Core Management", "Member"].includes(m.role)
                            : m.role === "Member")
                      )
                      .map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.name} · {m.role} · {m.member_id}
                        </option>
                      ))}
                  </select>
                </label>
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

function initials(s = "") {
  return s
    .split(" ")
    .map((x) => x[0])
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

export default App;
