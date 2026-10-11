import { Conversation } from "/static/vendor/elevenlabs-client.js";

/* ============================================================ helpers */
const $ = (s) => document.querySelector(s);
const pad = (n) => String(n).padStart(2, "0");
const isoDate = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fmtGB = (b) => (b / 1073741824).toFixed(1);
const truncate = (s, n) => (s.length > n ? s.slice(0, n) + " … (full answer is on the dashboard)" : s);
const isBangla = (s) => /[ঀ-৿]/.test(s);
const tidy = (s) => String(s || "").replace(/([।.!?])(?=[^\s\d"')\]])/g, "$1 ").trim(); // models drop the space after "।"
const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

function el(tag, attrs = {}, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") n.className = v;
    else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) n.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null) n.append(k instanceof Node ? k : String(k));
  return n;
}

async function api(path, { method = "GET", body } = {}) {
  const r = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail || detail; } catch {}
    throw new Error(detail);
  }
  return r.json();
}

const store = {
  get: (k, d) => { try { return localStorage.getItem(k) ?? d; } catch { return d; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
};

function toast(text, kind = "") {
  const t = el("div", { class: `toast ${kind}` }, text);
  $("#toasts").append(t);
  setTimeout(() => t.remove(), 7000);
}

function notify(title, body) {
  try {
    if (document.hidden && "Notification" in window && Notification.permission === "granted")
      new Notification(title, { body, icon: "/static/jarvis.ico", silent: true });
  } catch {}
}

/* ---------- conversation log with typewriter effect */
function logMsg(role, text, { label, ms, instant } = {}) {
  const box = $("#log");
  const tag = label || { user: "You", agent: "Jarvis", sys: "" }[role];
  const body = el("span");
  const lat = instant ? `⚡ instant · ${ms ?? 0} ms` : ms ? `⚡ ${(ms / 1000).toFixed(1)}s` : "";
  const m = el("div", { class: `msg ${role}` },
    tag ? el("small", {}, tag, lat ? el("span", { class: "lat" }, lat) : null) : null, body);
  box.append(m);
  while (box.children.length > 80) box.firstChild.remove();
  if (role === "agent" && !reducedMotion && text.length < 600) {
    m.classList.add("typing");
    let i = 0;
    const step = Math.max(1, Math.round(text.length / 45));
    const iv = setInterval(() => {
      i = Math.min(text.length, i + step);
      body.textContent = text.slice(0, i);
      box.scrollTop = box.scrollHeight;
      if (i >= text.length) { clearInterval(iv); m.classList.remove("typing"); }
    }, 16);
  } else body.textContent = text;
  box.scrollTop = box.scrollHeight;
}

let captionTimer = 0;
function caption(text, who = "user", hold = 4500) {
  const c = $("#caption");
  clearTimeout(captionTimer);
  c.className = `caption ${who === "agent" ? "agent" : ""}`;
  c.textContent = text.length > 160 ? text.slice(0, 157) + "…" : text;
  if (hold) captionTimer = setTimeout(() => c.classList.add("fade"), hold);
}

/* ---------- earcons */
let fxCtx = null;
function beep(freqs, dur = 0.09, vol = 0.05, type = "sine") {
  try {
    fxCtx ??= new AudioContext();
    let t = fxCtx.currentTime;
    for (const f of [].concat(freqs)) {
      const o = fxCtx.createOscillator(), g = fxCtx.createGain();
      o.type = type; o.frequency.value = f;
      g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
      o.connect(g).connect(fxCtx.destination); o.start(t); o.stop(t + dur + 0.02);
      t += dur * 0.85;
    }
  } catch {}
}
const fx = {
  listen: () => beep([660, 990], 0.07),
  heard: () => beep([880], 0.06, 0.035),
  done: () => beep([990, 1320], 0.08, 0.04),
  error: () => beep([300, 220], 0.14, 0.05, "triangle"),
  alarm: () => { for (let i = 0; i < 4; i++) setTimeout(() => beep([1046, 1318, 1568], 0.12, 0.08, "square"), i * 650); },
};

/* ============================================================ state */
let state = { todos: [], events: [], tasks: [], notes: [], timers: [], settings: { auto_approve: false } };
const knownStatus = new Map();
let firstLoad = true;

let engine = null; // null (voice off) | "eleven" (ElevenLabs agent) | "free" (Edge speech + local brain)
let conv = null, connStatus = "disconnected", mode = "listening", micMuted = false;
let micStream = null, audioCtx = null, micAnalyser = null, micData = null;
let lastUserMsgAt = 0, elevenStartedAt = 0;
let rec = null, busy = false, ttsSpeaking = false, wakeUntil = 0, lastLoudAt = 0, loudFrames = 0;
let voiceRate = Math.min(1.6, Math.max(0.7, parseFloat(store.get("hud.rate", "1.05")) || 1.05));
const brainHist = [];

/* ============================================================ clock, greeting, reminders, timers */
const bnFmt = new Intl.DateTimeFormat("bn-BD", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
const remindedEvents = new Set();
const rungTimers = new Set();

function greetingText(h) {
  return h < 5 ? "Working late" : h < 12 ? "Good morning" : h < 17 ? "Good afternoon" : h < 21 ? "Good evening" : "Good night";
}

function tick() {
  const now = new Date(), h = now.getHours();
  $("#clockTime").textContent = `${pad(h % 12 || 12)}:${pad(now.getMinutes())}:${pad(now.getSeconds())} ${h < 12 ? "AM" : "PM"}`;
  $("#clockDate").textContent = now.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
  $("#clockBn").textContent = bnFmt.format(now);
  $("#greeting").textContent = `${greetingText(h)} · Personal AI Agent`;

  const today = isoDate(now), hm = `${pad(h)}:${pad(now.getMinutes())}`;
  for (const ev of state.events) {
    if (ev.date === today && ev.time === hm && !remindedEvents.has(ev.id)) {
      remindedEvents.add(ev.id);
      fx.alarm();
      toast(`⏰ Now: ${ev.title}`, "warn");
      notify("Jarvis reminder", ev.title);
      announce(`[Reminder] It is ${hm} — time for: ${ev.title}.`, isBangla(ev.title) ? `মনে করিয়ে দিচ্ছি: ${ev.title}` : `Reminder: ${ev.title}`);
    }
  }
  renderTimers();
}

/* Tell the user something the HUD noticed: via the ElevenLabs agent if it is
   connected, otherwise speak the short text directly. */
function announce(agentText, spokenText) {
  if (isConnected()) conv.sendUserMessage(`${agentText} Tell me about it out loud in one short sentence.`);
  else if (engine === "free" || $("#speakReplies").checked) { caption(spokenText, "agent"); speak(spokenText); }
}

function renderTimers() {
  const ul = $("#timers"), now = Date.now();
  if (!state.timers.length) { ul.replaceChildren(el("li", { class: "empty" }, "No timers. Say “5 minute timer”.")); return; }
  ul.replaceChildren(...state.timers.map((t) => {
    const end = new Date(t.ends).getTime(), left = Math.max(0, Math.round((end - now) / 1000));
    if (left === 0 && !rungTimers.has(t.id)) timerDone(t);
    const pct = 100 * (1 - left / Math.max(1, t.seconds));
    const mm = left >= 3600 ? `${Math.floor(left / 3600)}:${pad(Math.floor(left / 60) % 60)}:${pad(left % 60)}` : `${pad(Math.floor(left / 60))}:${pad(left % 60)}`;
    return el("li", { class: `item timer ${left === 0 ? "ringing" : left <= 10 ? "ending" : ""}` },
      el("div", { class: "timer-top" }, el("span", { class: "timer-left" }, mm), el("span", { class: "grow" }, t.label),
        el("button", { class: "link del", title: "Cancel", onclick: () => removeTimer(t.id) }, "✕")),
      el("div", { class: "bar" }, el("i", { style: `width:${pct.toFixed(1)}%` })));
  }));
}

function timerDone(t) {
  rungTimers.add(t.id);
  fx.alarm();
  toast(`⏱️ Timer done: ${t.label}`, "warn");
  notify("Timer done", t.label);
  announce(`[Timer] The "${t.label}" timer has finished.`, isBangla(t.label) ? `${t.label} টাইমার শেষ!` : `Your ${t.label} timer is done!`);
  setTimeout(() => removeTimer(t.id), 8000);
}

async function removeTimer(id) { await api(`/api/timers/${id}`, { method: "DELETE" }).catch(() => {}); refresh(); }

/* ============================================================ weather (open-meteo, no key) */
const WX = [
  [[0], "☀️", "Clear sky"], [[1], "🌤️", "Mainly clear"], [[2], "⛅", "Partly cloudy"], [[3], "☁️", "Overcast"],
  [[45, 48], "🌫️", "Fog"], [[51, 53, 55, 56, 57], "🌦️", "Drizzle"], [[61, 63, 65, 66, 67], "🌧️", "Rain"],
  [[71, 73, 75, 77], "❄️", "Snow"], [[80, 81, 82], "🌦️", "Rain showers"], [[95, 96, 99], "⛈️", "Thunderstorm"],
];
let weatherText = "", wxCity = "";
const cityOf = () => state.settings.city || { name: "Dhaka", lat: 23.81, lon: 90.41 };

async function loadWeather() {
  const city = cityOf();
  wxCity = city.name;
  $("#wxTitle").textContent = `Weather · ${city.name}`;
  try {
    const url = `https://api.open-meteo.com/v1/forecast?latitude=${city.lat}&longitude=${city.lon}`
      + "&current=temperature_2m,relative_humidity_2m,apparent_temperature,weather_code,wind_speed_10m"
      + "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset&timezone=auto&forecast_days=1";
    const w = await (await fetch(url)).json();
    const c = w.current, d = w.daily;
    const [, icon, desc] = WX.find(([codes]) => codes.includes(c.weather_code)) || [null, "🌡️", "—"];
    $("#wxIcon").textContent = icon;
    $("#wxTemp").textContent = `${Math.round(c.temperature_2m)}°C`;
    $("#wxDesc").textContent = `${desc} · feels ${Math.round(c.apparent_temperature)}°`;
    const t = (s) => s.slice(11, 16);
    const rows = [
      ["High / Low", `${Math.round(d.temperature_2m_max[0])}° / ${Math.round(d.temperature_2m_min[0])}°`],
      ["Humidity", `${c.relative_humidity_2m}%`], ["Wind", `${Math.round(c.wind_speed_10m)} km/h`],
      ["Rain chance", `${d.precipitation_probability_max[0] ?? 0}%`], ["Sunrise / Sunset", `${t(d.sunrise[0])} / ${t(d.sunset[0])}`],
    ];
    $("#wxMore").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
    weatherText = `Weather in ${city.name} now: ${desc}, ${Math.round(c.temperature_2m)}°C (feels ${Math.round(c.apparent_temperature)}°C), `
      + `humidity ${c.relative_humidity_2m}%, today high ${Math.round(d.temperature_2m_max[0])}°C / low ${Math.round(d.temperature_2m_min[0])}°C, `
      + `rain chance ${d.precipitation_probability_max[0] ?? 0}%.`;
  } catch {
    $("#wxDesc").textContent = "Weather unavailable (offline?)";
  }
}

/* ============================================================ system */
function setGauge(id, pct, text, cls = "") {
  const g = $(id);
  g.querySelector(".val").style.strokeDashoffset = 169.6 * (1 - Math.max(0, Math.min(100, pct)) / 100);
  g.querySelector("b").textContent = text;
  g.className = `gauge ${cls}`;
}

async function loadSystem() {
  try {
    const s = await api("/api/system");
    setGauge("#gCpu", s.cpu, `${Math.round(s.cpu)}%`, s.cpu > 85 ? "bad" : s.cpu > 60 ? "warn" : "");
    setGauge("#gRam", s.ram.load, `${s.ram.load}%`, s.ram.load > 90 ? "bad" : s.ram.load > 75 ? "warn" : "");
    if (s.battery) setGauge("#gBat", s.battery.percent, `${s.battery.percent}%${s.battery.charging ? "⚡" : ""}`,
      s.battery.percent < 15 && !s.battery.charging ? "bad" : s.battery.percent < 30 ? "warn" : "");
    else setGauge("#gBat", 100, "AC");
    $("#disks").replaceChildren(...s.disks.map((d) => {
      const used = 100 * (1 - d.free / d.total);
      return el("div", { class: "disk-row" }, el("b", {}, d.name),
        el("div", { class: `bar ${d.free < 5 * 1073741824 ? "warn" : ""}` }, el("i", { style: `width:${used.toFixed(1)}%` })),
        el("span", { class: "muted" }, `${fmtGB(d.free)} GB free`));
    }));
    const up = s.uptime_s;
    const rows = [
      ["RAM free", `${fmtGB(s.ram.free)} / ${fmtGB(s.ram.total)} GB`],
      ["Brain", s.model || "—"],
      ["Ollama", s.ollama ? "● online" : "○ offline"],
      ["Uptime", `${Math.floor(up / 86400) ? Math.floor(up / 86400) + "d " : ""}${Math.floor(up / 3600) % 24}h ${Math.floor(up / 60) % 60}m`],
    ];
    $("#sysMore").replaceChildren(...rows.flatMap(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
    $("#workerState").textContent = s.worker_ready ? "⚡ Jarvis warm" : "warming up…";
  } catch {
    $("#sysMore").replaceChildren(el("dt", {}, "HUD server"), el("dd", {}, "○ offline"));
  }
}

/* ============================================================ data polling */
async function refresh() {
  let s;
  try { s = await api("/api/state"); } catch { return; }
  state = s;
  for (const t of state.tasks) {
    const prev = knownStatus.get(t.id);
    if (!firstLoad && prev && prev !== t.status && ["done", "failed"].includes(t.status)) onTaskFinished(t);
    knownStatus.set(t.id, t.status);
  }
  firstLoad = false;
  $("#autoApprove").checked = !!state.settings.auto_approve;
  if (cityOf().name !== wxCity) loadWeather();
  renderTasks(); renderTodos(); renderCalendar(); renderNotes(); renderTimers(); updateStatus();
}

function onTaskFinished(t) {
  t.status === "done" ? fx.done() : fx.error();
  toast(`${t.status === "done" ? "✅" : "⚠️"} ${t.command}`, t.status === "done" ? "" : "err");
  notify(t.status === "done" ? "Jarvis finished" : "Jarvis task failed", t.command);
  const note = `[Jarvis result for: ${t.command}]\n${truncate(t.result, 1500)}\n\nTell me this result briefly.`;
  if (isConnected()) {
    conv.sendUserMessage(note);
    logMsg("sys", "Jarvis finished — reading the result to you.");
  } else if (engine === "free" || $("#speakReplies").checked) {
    askBrain(note, "voice", { quiet: true });
  } else {
    logMsg("agent", truncate(t.result, 600), { label: "Jarvis result" });
  }
}

/* ============================================================ tasks */
const STATUS_TEXT = { pending: "NEEDS OK", queued: "QUEUED", running: "WORKING", done: "DONE", failed: "FAILED", cancelled: "CANCELLED" };
const since = (iso) => {
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
};

function renderTasks() {
  const ul = $("#tasks");
  if (!state.tasks.length) { ul.replaceChildren(el("li", { class: "empty" }, "No tasks yet. Ask Jarvis to do something on your PC.")); return; }
  ul.replaceChildren(...state.tasks.map((t) => {
    const took = t.finished && t.started ? ` · took ${Math.max(0, Math.round((new Date(t.finished) - new Date(t.started)) / 1000))}s` : "";
    const li = el("li", { class: "task", "data-status": t.status },
      el("div", { class: "task-top" }, el("span", { class: "task-cmd" }, t.command),
        el("span", { class: "badge" }, t.status === "running" ? el("span", { class: "spinner" }) : null, STATUS_TEXT[t.status] || t.status)),
      el("div", { class: "task-meta" }, `${t.source === "voice" ? "🎙️ voice" : "⌨️ typed"} · ${t.created.slice(11, 16)}`
        + (t.status === "running" && t.started ? ` · running ${since(t.started)}` : took)));
    if (t.status === "pending") {
      li.append(el("div", { class: "task-actions" },
        el("button", { class: "btn ok sm", onclick: () => taskAction(t.id, "approve") }, "✔ Run it"),
        el("button", { class: "btn danger sm", onclick: () => taskAction(t.id, "cancel") }, "✖ Cancel")));
    } else if (t.status === "running" || t.status === "queued") {
      li.append(el("div", { class: "task-actions" }, el("button", { class: "btn danger sm", onclick: () => taskAction(t.id, "cancel") }, "■ Stop")));
    } else if (t.result) {
      li.append(el("div", { class: "task-result" }, t.result));
    }
    return li;
  }));
}

async function taskAction(id, action) {
  try { await api(`/api/tasks/${id}/${action}`, { method: "POST" }); } catch (e) { toast(e.message, "err"); }
  refresh();
}

/* ============================================================ to-dos & notes */
function renderTodos() {
  const today = isoDate(new Date());
  const items = [...state.todos].sort((a, b) => (a.done - b.done) || (a.due || "9999").localeCompare(b.due || "9999"));
  const open = state.todos.filter((t) => !t.done).length;
  $("#todoCount").textContent = state.todos.length ? `${open} open · ${state.todos.length - open} done` : "";
  const ul = $("#todos");
  if (!items.length) { ul.replaceChildren(el("li", { class: "empty" }, "Nothing to do. Nice!")); return; }
  ul.replaceChildren(...items.map((t) => el("li", { class: `item ${t.done ? "done" : ""}` },
    el("input", { type: "checkbox", checked: t.done, "aria-label": "Done", onchange: (e) => patchTodo(t.id, { done: e.target.checked }) }),
    el("span", { class: "grow" }, t.title),
    t.due ? el("span", { class: `due ${!t.done && t.due < today ? "over" : ""}` }, t.due === today ? "today" : t.due.slice(5)) : null,
    el("button", { class: "link del", title: "Delete", onclick: () => removeTodo(t.id) }, "✕"))));
}

async function patchTodo(id, body) { await api(`/api/todos/${id}`, { method: "PATCH", body }); refresh(); }
async function removeTodo(id) { await api(`/api/todos/${id}`, { method: "DELETE" }); refresh(); }

function renderNotes() {
  const ul = $("#notes");
  if (!state.notes.length) { ul.replaceChildren(el("li", { class: "empty" }, "No notes. Say “Note koro: …”.")); return; }
  ul.replaceChildren(...state.notes.map((n) => el("li", { class: "item" },
    el("span", { class: "grow" }, n.text),
    el("span", { class: "note-time" }, n.created.slice(5, 10) === isoDate(new Date()).slice(5) ? n.created.slice(11, 16) : n.created.slice(5, 10)),
    el("button", { class: "link del", title: "Delete", onclick: async () => { await api(`/api/notes/${n.id}`, { method: "DELETE" }); refresh(); } }, "✕"))));
}

/* ============================================================ calendar */
let view = new Date(); view.setDate(1);
let selDate = isoDate(new Date());

function renderCalendar() {
  const y = view.getFullYear(), m = view.getMonth(), today = isoDate(new Date());
  $("#calTitle").textContent = view.toLocaleDateString("en-GB", { month: "long", year: "numeric" });
  const marked = new Set([...state.events.map((e) => e.date), ...state.todos.filter((t) => t.due && !t.done).map((t) => t.due)]);
  const start = new Date(y, m, 1 - new Date(y, m, 1).getDay());
  const cells = [];
  for (let i = 0; i < 42; i++) {
    const d = new Date(start.getFullYear(), start.getMonth(), start.getDate() + i), iso = isoDate(d);
    if (i === 35 && d.getMonth() !== m) break;
    cells.push(el("button", {
      class: [d.getMonth() !== m && "other", iso === today && "today", iso === selDate && "sel", marked.has(iso) && "has"].filter(Boolean).join(" "),
      onclick: () => { selDate = iso; renderCalendar(); }, "aria-label": iso,
    }, d.getDate()));
  }
  $("#calGrid").replaceChildren(...cells);

  const sd = new Date(selDate + "T00:00");
  $("#dayTitle").textContent = (selDate === today ? "Today · " : "") + sd.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
  const evs = state.events.filter((e) => e.date === selDate);
  const due = state.todos.filter((t) => t.due === selDate && !t.done);
  const rows = [
    ...evs.map((e) => el("li", { class: "item" }, el("span", { class: "time" }, e.time || "all day"), el("span", { class: "grow" }, e.title),
      el("button", { class: "link del", title: "Delete", onclick: async () => { await api(`/api/events/${e.id}`, { method: "DELETE" }); refresh(); } }, "✕"))),
    ...due.map((t) => el("li", { class: "item" }, el("span", { class: "time" }, "to-do"), el("span", { class: "grow" }, t.title))),
  ];
  $("#dayEvents").replaceChildren(...(rows.length ? rows : [el("li", { class: "empty" }, "No events.")]));
}

/* ============================================================ ElevenLabs client tools (relayed to the HUD server) */
const TOOL_NAMES = ["get_system_info", "get_news", "get_weather", "set_weather_city", "open_website", "play_youtube", "open_app", "media_control", "lock_pc",
  "take_screenshot", "set_timer", "cancel_timer", "add_note", "delete_note", "add_todo", "complete_todo",
  "delete_todo", "add_event", "delete_event", "ask_jarvis", "cancel_task"];

const relay = (name) => async (params = {}) => {
  try {
    const { tool_call_id, ...args } = params || {};
    const r = (await api("/api/tool", { method: "POST", body: { name, args, source: "voice" } })).result;
    refresh();
    return r;
  } catch (e) { return `Error: ${e.message}`; }
};

const clientTools = {
  ...Object.fromEntries(TOOL_NAMES.map((n) => [n, relay(n)])),
  get_agenda: async () => `${(await api("/api/tool", { method: "POST", body: { name: "get_agenda", args: {} } })).result}\n${weatherText}`,
  approve_task: async ({ task_id } = {}) => {
    // The agent may only approve after the user actually replied.
    const target = state.tasks.find((t) => t.status === "pending" && (!task_id || t.id === task_id));
    if (target && new Date(target.created).getTime() + 1000 > lastUserMsgAt)
      return "Refused: the user has not answered yet. Ask them to confirm and wait for their reply.";
    try {
      const t = await api(task_id ? `/api/tasks/${task_id}/approve` : "/api/tasks/approve", { method: "POST" });
      refresh();
      return `Approved: "${t.command}". Jarvis is working on it. The result will arrive later in a message starting with [Jarvis result].`;
    } catch (e) { return `Error: ${e.message}`; }
  },
};

/* ============================================================ voice session */
// Two engines share one mic stream (which also drives the orb):
//  - "eleven": the ElevenLabs agent (real-time, interruptible; needs credits)
//  - "free":   Edge speech recognition + the HUD brain (/api/assistant) + Edge voices
// "Auto" tries ElevenLabs first and falls back to free if it can't connect.
const isConnected = () => engine === "eleven" && conv && connStatus === "connected";
const voiceOn = () => engine !== null;
const stripTags = (s) => s.replace(/\[(?:[A-Za-z]+ ?){1,3}\]\s*/g, "").trim();
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const WAKE = /\b(hey |ok |okay )?(jarvis|jervis|jarvi|travis)\b|জার্ভিস|জারভিস|জার্ভিশ/i;

async function setupMic() {
  if (micStream) return;
  micStream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  audioCtx = new AudioContext();
  micAnalyser = audioCtx.createAnalyser();
  micAnalyser.fftSize = 512; micAnalyser.smoothingTimeConstant = 0.72;
  audioCtx.createMediaStreamSource(micStream).connect(micAnalyser);
  micData = new Uint8Array(micAnalyser.frequencyBinCount);
}

function setVoiceUi(on) {
  $("#voiceBtn").textContent = on ? "⏹ Stop voice" : "🎙️ Start voice";
  $("#muteBtn").disabled = !on;
  $("#muteBtn").textContent = micMuted ? "🎙️ Unmute" : "🔇 Mute";
}

async function startVoice() {
  if (voiceOn() || connStatus === "connecting") return;
  if ("Notification" in window && Notification.permission === "default") Notification.requestPermission().catch(() => {});
  connStatus = "connecting"; updateStatus();
  try {
    await setupMic();
  } catch (e) {
    connStatus = "disconnected"; updateStatus();
    toast(`Microphone blocked: ${e.message || e}. Allow the mic for this page and try again.`, "err");
    return;
  }
  const pref = $("#engineSel").value;
  if (pref !== "free" && await startEleven()) return;
  if (pref === "eleven") { toast("ElevenLabs could not connect (out of credits?).", "err"); await stopVoice(); return; }
  if (pref === "auto") toast("ElevenLabs is unavailable (out of credits?) — using free voice.", "warn");
  startFree();
}

async function startEleven() {
  const callbacks = {
    clientTools,
    onStatusChange: ({ status }) => { connStatus = status; updateStatus(); },
    onModeChange: ({ mode: m }) => { mode = m; updateStatus(); },
    onMessage: ({ message, role, source }) => {
      const who = role || (source === "ai" ? "agent" : "user");
      if (who === "agent") { const t = stripTags(message); if (t) { logMsg("agent", t); caption(t, "agent", 6000); } }
      else { lastUserMsgAt = Date.now(); logMsg("user", message); caption(message); }
    },
    onError: (msg) => toast(`Voice error: ${msg}`, "err"),
    onDisconnect: (details) => onElevenDisconnect(details),
    onUnhandledClientToolCall: (call) => logMsg("sys", `Unknown tool requested: ${call?.tool_name}`),
  };
  try {
    const { agent_id, token } = await api("/api/voice/token");
    if (!agent_id) return false; // no ElevenLabs agent configured: use the free voice
    elevenStartedAt = Date.now();
    engine = "eleven";
    try {
      conv = await Conversation.startSession(token
        ? { ...callbacks, conversationToken: token, connectionType: "webrtc" }
        : { ...callbacks, agentId: agent_id, connectionType: "websocket" });
    } catch (e) {
      if (!token) throw e;
      conv = await Conversation.startSession({ ...callbacks, agentId: agent_id, connectionType: "websocket" });
    }
    await new Promise((r) => setTimeout(r, 1500)); // a quota error closes the session right after it opens
    if (engine !== "eleven" || !conv) return false;
    connStatus = "connected";
    conv.sendContextualUpdate(`Live HUD context — use it to answer questions about the user's day.\n${await clientTools.get_agenda()}`);
    logMsg("sys", "ElevenLabs voice connected. Speak naturally.");
    fx.listen();
    setVoiceUi(true); updateStatus();
    return true;
  } catch {
    teardownEleven();
    return false;
  }
}

function teardownEleven() {
  const c = conv; conv = null;
  if (engine === "eleven") engine = null;
  connStatus = "disconnected"; mode = "listening";
  return c;
}

function onElevenDisconnect(details) {
  if (engine !== "eleven") return;
  const early = Date.now() - elevenStartedAt < 8000;
  teardownEleven();
  if (early) return; // startEleven() notices and falls back
  logMsg("sys", `Voice disconnected${details?.reason === "error" ? " (error)" : ""}.`);
  stopVoice();
}

/* ---------- free voice: Edge speech in/out + HUD brain */
function startFree() {
  if (!SR) { toast("This browser has no speech recognition. Open the HUD in Microsoft Edge.", "err"); stopVoice(); return; }
  engine = "free"; connStatus = "connected"; mode = "listening";
  setVoiceUi(true);
  const wake = $("#wakeWord").checked;
  logMsg("sys", `Free voice on (${$("#langSel").selectedOptions[0].text})${wake ? " — say “Jarvis …” to wake me" : ""}.`);
  fx.listen();
  updateStatus();
  listen();
}

let interimEl = null;
function showInterim(text) {
  if (!text) { interimEl?.remove(); interimEl = null; return; }
  if (!interimEl) { interimEl = el("div", { class: "msg user interim" }); $("#log").append(interimEl); }
  interimEl.textContent = text;
  caption(text, "user", 0);
  $("#log").scrollTop = $("#log").scrollHeight;
}

/* Mic loudness 0..1; also stamps lastLoudAt. Used by the orb and by the
   end-of-speech timer (which keeps working when the window is in the background). */
function sampleMic(out = tmp) {
  if (!micAnalyser || micMuted) return 0;
  micAnalyser.getByteFrequencyData(micData);
  const lvl = binsToBars(micData, out);
  if (lvl > 0.1) lastLoudAt = Date.now();
  return lvl;
}
const micScratch = new Float32Array(120);

function listen() {
  if (engine !== "free" || busy || ttsSpeaking || micMuted || rec) return;
  const r = new SR();
  r.lang = $("#langSel").value; r.interimResults = true; r.continuous = false; r.maxAlternatives = 1;
  let finalText = "", heardAt = 0;
  r.onresult = (e) => {
    let interim = "";
    for (let i = e.resultIndex; i < e.results.length; i++) {
      if (e.results[i].isFinal) finalText += e.results[i][0].transcript;
      else interim += e.results[i][0].transcript;
    }
    heardAt = Date.now();
    showInterim((finalText + " " + interim).trim());
  };
  r.onerror = (e) => {
    if (e.error === "not-allowed" || e.error === "service-not-allowed") { toast("Speech recognition is blocked for this page.", "err"); stopVoice(); }
    else if (e.error === "network") toast("Speech recognition needs internet.", "err");
  };
  r.onend = async () => {
    clearInterval(r._silence);
    rec = null; showInterim("");
    let text = finalText.trim();
    if (engine !== "free") return;
    if (text) {
      const woken = WAKE.test(text);
      if ($("#wakeWord").checked && !woken && Date.now() > wakeUntil) {
        caption(`(ignored — say “Jarvis …”) ${text}`, "user", 2500);
        setTimeout(listen, 150);
        return;
      }
      if (woken) text = text.replace(WAKE, "").replace(/^[\s,.!?।]+/, "").trim();
      fx.heard();
      if (!text) { await speak($("#langSel").value.startsWith("bn") ? "জি, বলুন।" : "Yes?"); wakeUntil = Date.now() + 20000; return; }
      await askBrain(text, "voice");
      wakeUntil = Date.now() + 20000; // follow-ups don't need the wake word
    }
    setTimeout(listen, 150);
  };
  // End the turn as soon as the mic goes quiet after speech, instead of
  // waiting for the recognizer's own (longer) end-of-speech timeout.
  r._silence = setInterval(() => {
    sampleMic(micScratch);
    if (heardAt && Date.now() - lastLoudAt > 700 && Date.now() - heardAt > 350) { clearInterval(r._silence); try { r.stop(); } catch {} }
  }, 120);
  rec = r;
  try { r.start(); } catch { rec = null; clearInterval(r._silence); setTimeout(listen, 800); }
}

const voices = () => speechSynthesis.getVoices();
speechSynthesis.addEventListener?.("voiceschanged", voices);
function pickVoice(bangla) {
  const vs = voices();
  const prefs = bangla
    ? [(v) => /^bn-BD/i.test(v.lang) && /Natural/i.test(v.name), (v) => /^bn/i.test(v.lang) && /Natural/i.test(v.name), (v) => /^bn/i.test(v.lang)]
    : [(v) => /Ryan.*Natural/i.test(v.name), (v) => /^en-GB/i.test(v.lang) && /Natural/i.test(v.name),
       (v) => /^en/i.test(v.lang) && /Natural/i.test(v.name), (v) => /^en-GB/i.test(v.lang), (v) => /^en/i.test(v.lang)];
  for (const p of prefs) { const v = vs.find(p); if (v) return v; }
  return null;
}

/* Jarvis's voice: Microsoft neural voices streamed from the HUD server
   (/api/tts, edge-tts) into an <audio> element, which also feeds the orb with
   real frequency data. If that fails (offline), fall back to the browser's
   own speechSynthesis. */
const ttsAudio = new Audio();
let ttsAnalyser = null, ttsData = null;
let speakToken = 0;

async function routeTtsThroughAnalyser() {
  // Once an <audio> is routed through Web Audio it only plays while the
  // AudioContext runs, so only route it when the context is running.
  if (ttsAnalyser) return;
  try {
    fxCtx ??= new AudioContext();
    if (fxCtx.state !== "running") await fxCtx.resume();
    if (fxCtx.state !== "running") return;
    const src = fxCtx.createMediaElementSource(ttsAudio);
    ttsAnalyser = fxCtx.createAnalyser();
    ttsAnalyser.fftSize = 512; ttsAnalyser.smoothingTimeConstant = 0.7;
    src.connect(ttsAnalyser); ttsAnalyser.connect(fxCtx.destination);
    ttsData = new Uint8Array(ttsAnalyser.frequencyBinCount);
  } catch { /* plays without visualizer */ }
}

/* Long replies are cut into chunks: the first sentence starts playing almost
   at once while the next chunk downloads in the background. */
function splitSpeech(text) {
  const sentences = text.match(/[^.!?।]+[.!?।]+["')\]]*\s*|[^.!?।]+$/g) || [text];
  const chunks = [];
  let cur = "";
  for (const sn of sentences) {
    const limit = chunks.length ? 260 : 120; // keep the first chunk short
    if (cur && (cur + sn).length > limit) { chunks.push(cur.trim()); cur = ""; }
    cur += sn;
  }
  if (cur.trim()) chunks.push(cur.trim());
  return chunks.filter(Boolean);
}

let speakDone = null; // finishes the speak() call that is playing now

function speak(text) {
  const clean = tidy(text).replace(/[*_#`>|]/g, "");
  if (!clean) return Promise.resolve();
  rec?.abort();
  const token = ++speakToken;
  const prev = speakDone; speakDone = null; prev?.(); // an interrupted caller must not wait forever
  haltAudio();
  ttsSpeaking = true; updateStatus();
  return new Promise(async (resolve) => {
    const blobs = [];
    let finished = false;
    const finish = () => {
      if (finished) return;
      finished = true;
      blobs.forEach((u) => URL.revokeObjectURL(u));
      if (speakDone === finish) speakDone = null;
      if (token === speakToken) { ttsSpeaking = false; updateStatus(); setTimeout(listen, 150); }
      resolve();
    };
    speakDone = finish;
    // Never let a stuck player stall the conversation.
    setTimeout(() => { if (!finished && token === speakToken) { haltAudio(); finish(); } }, 12000 + clean.length * 140);

    let fellBack = false;
    const fallback = (rest) => {
      if (fellBack || finished || token !== speakToken) return;
      fellBack = true;
      ttsAudio.onended = ttsAudio.onerror = null;
      browserSpeak(rest, token, finish);
    };
    const chunks = splitSpeech(clean);
    const url = (t) => `/api/tts?${new URLSearchParams({ text: t, gender: $("#voiceGender").value, rate: Math.round((voiceRate - 1) * 100) })}`;
    const fetched = new Map();
    const prefetch = (i) => {
      if (i >= chunks.length || fetched.has(i)) return;
      fetched.set(i, fetch(url(chunks[i])).then((r) => (r.ok ? r.blob() : null))
        .then((b) => { if (!b || !b.size) return null; const u = URL.createObjectURL(b); blobs.push(u); return u; })
        .catch(() => null));
    };
    let next = 0;
    const playNext = async () => {
      if (finished || token !== speakToken) return;
      if (next >= chunks.length) return finish();
      const i = next++;
      const src = i === 0 ? url(chunks[0]) : await fetched.get(i); // chunk 0 streams straight in
      if (finished || token !== speakToken) return;
      const rest = chunks.slice(i).join(" ");
      if (!src) return fallback(rest);
      prefetch(i + 1);
      ttsAudio.onended = playNext;
      ttsAudio.onerror = () => fallback(rest);
      ttsAudio.src = src;
      ttsAudio.play().catch((e) => {
        if (e.name === "AbortError") return; // replaced by newer audio
        if (e.name === "NotAllowedError") toast("Click anywhere on the page once so Jarvis is allowed to speak.", "warn");
        fallback(rest);
      });
    };
    await routeTtsThroughAnalyser();
    if (fxCtx?.state === "suspended") fxCtx.resume().catch(() => {});
    if (token !== speakToken) return finish();
    prefetch(1);
    playNext();
  });
}

function browserSpeak(clean, token, finish) {
  const parts = clean.match(/[^.!?।]+[.!?।]*\s*/g) || [clean];
  const v = pickVoice(isBangla(clean));
  const go = () => {
    if (token !== speakToken) return;
    parts.forEach((p, i) => {
      const u = new SpeechSynthesisUtterance(p.trim());
      if (v) { u.voice = v; u.lang = v.lang; } else u.lang = isBangla(clean) ? "bn-BD" : "en-GB";
      u.rate = voiceRate;
      if (i === parts.length - 1) { u.onend = finish; u.onerror = finish; }
      speechSynthesis.speak(u);
    });
  };
  // Chromium drops an utterance queued in the same tick as cancel().
  if (speechSynthesis.speaking || speechSynthesis.pending) { speechSynthesis.cancel(); setTimeout(go, 120); } else go();
}

function haltAudio() {
  ttsAudio.onended = ttsAudio.onerror = null;
  if (!ttsAudio.paused) ttsAudio.pause();
  if (ttsAudio.getAttribute("src")) { ttsAudio.removeAttribute("src"); ttsAudio.load(); }
  if (speechSynthesis.speaking || speechSynthesis.pending) speechSynthesis.cancel();
}

function stopSpeaking() {
  if (!ttsSpeaking) return;
  speakToken++; haltAudio();
  const prev = speakDone; speakDone = null; prev?.();
  ttsSpeaking = false; updateStatus(); setTimeout(listen, 150);
}

async function askBrain(text, source, { quiet = false, forceSpeak = false } = {}) {
  if (!quiet) { logMsg("user", text); caption(text); }
  brainHist.push({ role: "user", content: text });
  busy = true; updateStatus();
  let reply = "", ms = 0, instant = false;
  try {
    const d = await api("/api/assistant", { method: "POST", body: { messages: brainHist.slice(-14), source, context: weatherText } });
    reply = tidy(d.reply || ""); ms = d.ms; instant = d.model === "rule";
    if (reply) brainHist.push({ role: "assistant", content: reply });
    if (d.actions?.length) refresh();
    applyClient(d.client || {});
  } catch (e) {
    fx.error();
    toast(`Jarvis brain error: ${e.message}`, "err");
  } finally {
    busy = false; updateStatus();
  }
  if (reply) {
    logMsg("agent", reply, { ms, instant });
    caption(reply, "agent", 7000);
    if (engine === "free" || forceSpeak || $("#speakReplies").checked) await speak(reply);
  }
  while (brainHist.length > 30) brainHist.shift();
}

/* Page-side effects of instant commands: stop, language, speaking speed. */
function applyClient(c) {
  if (c.stop_speaking) stopSpeaking();
  if (c.lang) { $("#langSel").value = c.lang; store.set("hud.lang", c.lang); rec?.abort(); }
  if (c.rate) {
    voiceRate = Math.min(1.6, Math.max(0.7, +(voiceRate + c.rate).toFixed(2)));
    store.set("hud.rate", String(voiceRate));
    toast(`Voice speed: ${voiceRate.toFixed(2)}×`);
  }
}

/* ---------- stop & status */
async function stopVoice() {
  const was = engine;
  const c = teardownEleven();
  if (c) { try { await c.endSession(); } catch {} }
  engine = null;
  if (rec) { clearInterval(rec._silence); rec.abort(); rec = null; }
  showInterim("");
  stopSpeaking();
  micStream?.getTracks().forEach((t) => t.stop());
  audioCtx?.close().catch(() => {});
  micStream = audioCtx = micAnalyser = micData = null;
  connStatus = "disconnected"; mode = "listening"; micMuted = false;
  setVoiceUi(false);
  if (was) logMsg("sys", "Voice off.");
  updateStatus();
}

const toggleVoice = () => (voiceOn() || connStatus === "connecting" ? stopVoice() : startVoice());
const isSpeaking = () => (engine === "eleven" && mode === "speaking") || ttsSpeaking;

function updateStatus() {
  const working = state.tasks.some((t) => t.status === "running" || t.status === "queued");
  let s = "offline", text = "STANDBY", orb = "TAP TO TALK";
  if (connStatus === "connecting") { s = "connecting"; text = "CONNECTING"; orb = "CONNECTING"; }
  else if (isSpeaking()) { s = "speaking"; text = "SPEAKING"; orb = "SPEAKING"; }
  else if (busy) { s = "working"; text = "THINKING"; orb = "THINKING"; }
  else if (voiceOn()) {
    const tag = engine === "free" ? ($("#wakeWord").checked && Date.now() > wakeUntil ? " · SAY “JARVIS”" : " · FREE") : "";
    if (working) { s = "working"; text = "WORKING" + tag; orb = micMuted ? "MUTED" : "LISTENING"; }
    else { s = "listening"; text = (micMuted ? "MIC MUTED" : "LISTENING") + tag; orb = micMuted ? "MUTED" : "LISTENING"; }
  } else if (working) { s = "working"; text = "WORKING"; }
  $("#statusPill").dataset.state = s;
  $("#statusText").textContent = text;
  $("#orbLabel").textContent = orb;
}

/* ============================================================ orb visualizer */
const canvas = $("#orb"), ctx = canvas.getContext("2d");
const N = 120;
const bars = new Float32Array(N);
const tmp = new Float32Array(N);
const COLORS = { you: [34, 211, 238], jarvis: [251, 191, 36], think: [167, 139, 250] };
let level = 0, rot = 0, ttsLevel = 0;
const rgb = [...COLORS.you];

function binsToBars(data, out) {
  // Voice energy sits in the lower part of the spectrum: spread the first
  // ~40% of bins log-style over half the ring, then mirror it.
  const half = N / 2, usable = Math.max(8, Math.floor(data.length * 0.4));
  let sum = 0;
  for (let i = 0; i < half; i++) {
    const a = Math.floor(Math.pow(i / half, 1.6) * usable), b = Math.max(a + 1, Math.floor(Math.pow((i + 1) / half, 1.6) * usable));
    let m = 0; for (let j = a; j < b; j++) m = Math.max(m, data[j]);
    const v = m / 255; out[i] = v; out[N - 1 - i] = v; sum += v;
  }
  return sum / half;
}

function frame(ts) {
  const dpr = window.devicePixelRatio || 1, W = canvas.clientWidth * dpr, H = canvas.clientHeight * dpr;
  if (canvas.width !== W || canvas.height !== H) { canvas.width = W; canvas.height = H; }
  const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.2;

  // ---- live signal: Jarvis's voice while it speaks, otherwise yours
  let target = 0, micLevel = 0;
  tmp.fill(0);
  if (micAnalyser && !micMuted) {
    micLevel = sampleMic(tmp);
    // Barge-in: sustained speech (~0.3 s) while Jarvis talks cuts it off. The
    // bar rises with Jarvis's own loudness so speaker echo doesn't trigger it.
    if (ttsSpeaking && engine === "free" && $("#bargeIn").checked) {
      const bar = 0.2 + 0.35 * ttsLevel;
      loudFrames = micLevel > bar ? loudFrames + 1 : Math.max(0, loudFrames - 2);
      if (loudFrames > 18) { loudFrames = 0; wakeUntil = Date.now() + 20000; stopSpeaking(); fx.heard(); }
    } else loudFrames = 0;
  }
  const speaking = isSpeaking();
  if (!speaking) ttsLevel = 0;
  if (speaking) {
    let out = null;
    try {
      if (engine === "eleven") out = conv.getOutputByteFrequencyData();
      else if (ttsAnalyser && !ttsAudio.paused) { ttsAnalyser.getByteFrequencyData(ttsData); out = ttsData; }
    } catch {}
    if (out && out.length && out.some((v) => v > 0)) target = ttsLevel = binsToBars(out, tmp);
    else { // browser voices expose no audio data: synthesize a speech-like pulse
      for (let i = 0; i < N; i++) tmp[i] = 0.3 + 0.32 * Math.abs(Math.sin(ts / 130 + i * 0.35)) * Math.abs(Math.sin(ts / 370 + i * 0.05));
      target = 0.4;
    }
  } else if (busy) {
    for (let i = 0; i < N; i++) tmp[i] = 0.12 + 0.22 * Math.max(0, Math.sin(i * 0.21 - ts / 160));
    target = 0.18;
  } else target = micLevel;
  if (target < 0.015) for (let i = 0; i < N; i++) tmp[i] = 0.05 + 0.035 * Math.sin(ts / 900 + i * 0.26) ** 2; // idle breathing

  for (let i = 0; i < N; i++) bars[i] += (tmp[i] - bars[i]) * (tmp[i] > bars[i] ? 0.45 : 0.12);
  level += (target - level) * 0.15;
  const want = speaking ? COLORS.jarvis : busy ? COLORS.think : COLORS.you;
  for (let k = 0; k < 3; k++) rgb[k] += (want[k] - rgb[k]) * 0.08;
  rot += 0.0025 + level * 0.03 + (busy ? 0.02 : 0);
  const col = (a) => `rgba(${rgb[0] | 0}, ${rgb[1] | 0}, ${rgb[2] | 0}, ${a})`;

  ctx.clearRect(0, 0, W, H);
  const g = ctx.createRadialGradient(cx, cy, R * 0.2, cx, cy, R * 3);
  g.addColorStop(0, col(0.18 + level * 0.35)); g.addColorStop(1, col(0));
  ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

  ctx.lineCap = "round";
  ctx.lineWidth = 2 * dpr;
  for (let k = 0; k < 3; k++) { // rotating outer arcs
    const rr = R * (2.05 + k * 0.17), dir = k % 2 ? -1 : 1;
    ctx.strokeStyle = col(0.5 - k * 0.12);
    for (let s = 0; s < 4; s++) {
      const a0 = rot * dir * (1 + k * 0.4) + (s * Math.PI) / 2;
      ctx.beginPath(); ctx.arc(cx, cy, rr, a0, a0 + Math.PI / (3 + k)); ctx.stroke();
    }
  }
  ctx.lineWidth = 1 * dpr; ctx.strokeStyle = col(0.35);
  for (let i = 0; i < 72; i++) { // tick ring
    const a = (i / 72) * Math.PI * 2 - rot * 0.5, r1 = R * 1.9, r2 = r1 + (i % 6 ? R * 0.04 : R * 0.09);
    ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2); ctx.stroke();
  }
  if (busy) { // orbiting "thinking" particles
    for (let k = 0; k < 3; k++) {
      const a = ts / 380 + (k * Math.PI * 2) / 3, r = R * 1.55;
      ctx.fillStyle = col(0.95); ctx.shadowBlur = 16 * dpr; ctx.shadowColor = col(1);
      ctx.beginPath(); ctx.arc(cx + Math.cos(a) * r, cy + Math.sin(a) * r, 4 * dpr, 0, Math.PI * 2); ctx.fill();
    }
  }
  ctx.lineWidth = Math.max(2, (2 * Math.PI * R * 1.12) / N * 0.55);
  ctx.shadowBlur = 14 * dpr; ctx.shadowColor = col(0.9);
  for (let i = 0; i < N; i++) { // frequency bars
    const a = (i / N) * Math.PI * 2 - Math.PI / 2, v = bars[i];
    const r1 = R * 1.12, r2 = r1 + R * 0.06 + v * R * 0.78;
    ctx.strokeStyle = col(0.45 + v * 0.55);
    ctx.beginPath(); ctx.moveTo(cx + Math.cos(a) * r1, cy + Math.sin(a) * r1); ctx.lineTo(cx + Math.cos(a) * r2, cy + Math.sin(a) * r2); ctx.stroke();
  }
  ctx.lineWidth = 2 * dpr; ctx.strokeStyle = col(0.8);
  ctx.beginPath();
  for (let i = 0; i <= 180; i++) { // wobbling wave ring
    const a = (i / 180) * Math.PI * 2, r = R * 1.02 + Math.sin(a * 6 + ts / 300) * R * 0.03 * (0.3 + level * 3);
    const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
  }
  ctx.stroke();
  const cr = R * (0.86 + level * 0.18); // core
  const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, cr);
  core.addColorStop(0, "rgba(255,255,255,0.95)"); core.addColorStop(0.35, col(0.9)); core.addColorStop(1, col(0.12));
  ctx.fillStyle = core; ctx.shadowBlur = 40 * dpr * (0.5 + level);
  ctx.beginPath(); ctx.arc(cx, cy, cr, 0, Math.PI * 2); ctx.fill();
  ctx.shadowBlur = 0;
  ctx.strokeStyle = "rgba(255,255,255,0.5)"; ctx.lineWidth = 1.5 * dpr;
  ctx.beginPath(); ctx.arc(cx, cy, cr * 0.62, -rot * 2, -rot * 2 + Math.PI * 1.4); ctx.stroke();

  requestAnimationFrame(frame);
}

/* ============================================================ wiring */
$("#voiceBtn").addEventListener("click", toggleVoice);
$("#orbBtn").addEventListener("click", () => (ttsSpeaking ? stopSpeaking() : toggleVoice()));
$("#muteBtn").addEventListener("click", () => {
  if (!voiceOn()) return;
  micMuted = !micMuted;
  if (engine === "eleven") conv?.setMicMuted(micMuted);
  else if (micMuted) { if (rec) { clearInterval(rec._silence); rec.abort(); } } else listen();
  setVoiceUi(true); updateStatus();
});
for (const [id, key] of [["#engineSel", "hud.engine"], ["#langSel", "hud.lang"], ["#wakeWord", "hud.wake"],
  ["#speakReplies", "hud.speak"], ["#bargeIn", "hud.barge"], ["#voiceGender", "hud.gender"]]) {
  const n = $(id), prop = n.type === "checkbox" ? "checked" : "value";
  const saved = store.get(key, null);
  if (saved !== null) n[prop] = prop === "checked" ? saved === "1" : saved;
  n.addEventListener("change", () => { store.set(key, prop === "checked" ? (n.checked ? "1" : "0") : n.value); updateStatus(); });
}
$("#testVoice").addEventListener("click", () => {
  const bn = $("#langSel").value.startsWith("bn");
  const line = bn ? "আমি জার্ভিস। আমার কথা শুনতে পাচ্ছেন?" : "I am Jarvis. Can you hear me?";
  caption(line, "agent");
  speak(line);
});
$("#autoApprove").addEventListener("change", async (e) => {
  await api("/api/settings", { method: "PUT", body: { auto_approve: e.target.checked } });
  toast(e.target.checked ? "Auto-approve ON: voice commands run without asking." : "Auto-approve OFF: you confirm each voice command.", e.target.checked ? "warn" : "");
});

async function sendTyped(text) {
  if (isConnected()) { logMsg("user", text); lastUserMsgAt = Date.now(); conv.sendUserMessage(text); return; }
  // Typed text goes to the brain: it answers, uses the instant tools, manages
  // to-dos/calendar or starts a Jarvis task (typed tasks need no approval).
  await askBrain(text, "typed");
}
$("#cmdForm").addEventListener("submit", (e) => {
  e.preventDefault();
  const text = $("#cmdInput").value.trim(); if (!text) return;
  $("#cmdInput").value = "";
  sendTyped(text).catch((err) => toast(err.message, "err"));
});
$("#chips").addEventListener("click", async (e) => {
  const b = e.target.closest("button"); if (!b) return;
  if (b.dataset.task) { // long research jobs go straight to Jarvis
    logMsg("user", b.dataset.say);
    await api("/api/tasks", { method: "POST", body: { command: b.dataset.say, source: "typed" } });
    refresh(); return;
  }
  if (isConnected()) { logMsg("user", b.dataset.say); conv.sendUserMessage(b.dataset.say); return; }
  askBrain(b.dataset.say, "typed", { forceSpeak: b.classList.contains("hot") });
});
document.querySelectorAll("[data-timer]").forEach((b) => b.addEventListener("click", async () => {
  await api("/api/timers", { method: "POST", body: { seconds: +b.dataset.timer, label: `${+b.dataset.timer / 60} min` } });
  fx.listen(); refresh();
}));
$("#clearTasks").addEventListener("click", async () => { await api("/api/tasks/finished", { method: "DELETE" }); refresh(); });
$("#todoForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/todos", { method: "POST", body: { title: $("#todoTitle").value.trim(), due: $("#todoDue").value } });
  $("#todoTitle").value = ""; $("#todoDue").value = ""; refresh();
});
$("#noteForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  await api("/api/notes", { method: "POST", body: { text: $("#noteText").value.trim() } });
  $("#noteText").value = ""; refresh();
});
$("#eventForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/api/events", { method: "POST", body: { title: $("#eventTitle").value.trim(), date: selDate, time: $("#eventTime").value } });
    $("#eventTitle").value = ""; $("#eventTime").value = ""; refresh();
  } catch (err) { toast(err.message, "err"); }
});
$("#calPrev").addEventListener("click", () => { view = new Date(view.getFullYear(), view.getMonth() - 1, 1); renderCalendar(); });
$("#calNext").addEventListener("click", () => { view = new Date(view.getFullYear(), view.getMonth() + 1, 1); renderCalendar(); });

// A mouse click must not leave focus on a button, toggle or menu: Space would
// then press that control as well as run the talk shortcut.
document.addEventListener("click", (e) => {
  const b = e.target.closest("button, label.toggle");
  if (b && e.detail > 0) setTimeout(() => document.activeElement?.blur(), 0);
});
document.querySelectorAll("select, input[type=checkbox]").forEach((n) => n.addEventListener("change", () => n.blur()));

// Keyboard: Space = talk / interrupt, Esc = stop speaking, "/" = type
document.addEventListener("keydown", (e) => {
  const typing = /INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "");
  if (e.key === "Escape") { stopSpeaking(); if (typing) document.activeElement.blur(); return; }
  if (typing) return;
  if (e.key === "/") { e.preventDefault(); $("#cmdInput").focus(); }
  else if (e.code === "Space") {
    e.preventDefault();
    if (ttsSpeaking) stopSpeaking();
    else if (!voiceOn()) startVoice();
    else if (engine === "free") { wakeUntil = Date.now() + 20000; listen(); }
  }
});

/* ============================================================ boot */
async function boot() {
  const lines = ["Initializing core systems", "Linking brain · Ollama Cloud", "Loading calendar & to-dos", "Calibrating voice array", "All systems online"];
  const ul = $("#bootLines");
  const steps = [refresh(), loadSystem(), loadWeather()];
  if (!reducedMotion) {
    for (const [i, l] of lines.entries()) {
      const li = el("li", {}, l); ul.append(li);
      await new Promise((r) => setTimeout(r, 230));
      li.classList.add("ok");
      if (i === 2) await Promise.race([Promise.all(steps), new Promise((r) => setTimeout(r, 1200))]);
    }
    await new Promise((r) => setTimeout(r, 250));
  }
  $("#boot").classList.add("done");
}

tick(); setInterval(tick, 1000);
setInterval(loadWeather, 15 * 60 * 1000);
setInterval(loadSystem, 3000);
setInterval(refresh, 2000);
requestAnimationFrame(frame);
boot();
