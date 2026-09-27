/* Nudge settings UI logic. textContent everywhere — never innerHTML. */
"use strict";

const $ = (id) => document.getElementById(id);
const DAYS = ["mon","tue","wed","thu","fri","sat","sun"];
const DAY_LABEL = { mon:"Mon", tue:"Tue", wed:"Wed", thu:"Thu", fri:"Fri", sat:"Sat", sun:"Sun" };

async function api(path, opts) {
  const resp = await fetch(path, opts);
  let body = null;
  try { body = await resp.json(); } catch { /* empty body */ }
  if (!resp.ok) throw new Error((body && body.error) || `HTTP ${resp.status}`);
  return body;
}

/* ---------- tabs ---------- */
const tabInk = $("tab-ink");

function moveInk() {
  const active = document.querySelector(".tab.is-active");
  if (!active || !tabInk) return;
  tabInk.style.left = active.offsetLeft + "px";
  tabInk.style.width = active.offsetWidth + "px";
  tabInk.classList.add("ready");
}

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab, .tabpane").forEach((el) => el.classList.remove("is-active"));
    tab.classList.add("is-active");
    $(`tab-${tab.dataset.tab}`).classList.add("is-active");
    moveInk();
    if (tab.dataset.tab === "status") { refreshStatus(); loadLog(); }
    if (tab.dataset.tab === "quiet") buildQuietGrid();
  });
});
window.addEventListener("resize", moveInk);

/* ---------- reminders list ---------- */
let reminderCache = [];

async function refreshReminders() {
  const data = await api("/api/reminders");
  reminderCache = data.reminders;
  const list = $("reminder-list");
  list.textContent = "";
  $("rem-count").textContent = String(reminderCache.length);
  if (!reminderCache.length) {
    const box = document.createElement("div");
    box.className = "empty";
    const g = document.createElement("span");
    g.className = "empty-glyph"; g.textContent = "🕯️";
    const t = document.createElement("p");
    t.className = "empty-text"; t.textContent = "Nothing waiting on you.";
    const h = document.createElement("p");
    h.className = "empty-hint"; h.textContent = "Add one here, or just tell your agent and it will write it down.";
    box.append(g, t, h);
    list.appendChild(box);
  }
  reminderCache.forEach((r, i) => list.appendChild(remCard(r, i)));
  const sel = $("tf-id");
  const keep = sel.value;
  sel.textContent = "";
  for (const r of reminderCache) {
    const o = document.createElement("option");
    o.value = r.id; o.textContent = `${r.id} (${r.type})`;
    sel.appendChild(o);
  }
  if (keep && reminderCache.some((r) => r.id === keep)) sel.value = keep;
}

function describe(r) {
  if (r.type === "appointment") return `appointment · ${(r.when || "").replace("T", " ")}`;
  if (r.type === "chore") return `chore · ${r.schedule || "?"}`;
  return `nudge · every ${r.every || "?"}${r.active_only ? ", while active" : ""}`;
}

function remCard(r, i) {
  const card = document.createElement("div");
  card.className = `rem-card ${r.type}`;
  card.style.setProperty("--i", String(i || 0));

  const main = document.createElement("div");
  main.className = "rem-main";
  const t = document.createElement("div");
  t.className = "rem-title";
  t.textContent = r.text;
  const sub = document.createElement("div");
  sub.className = "rem-sub";
  sub.textContent = describe(r) + (r.next_fire
    ? ` · next ${r.next_fire.replace("T", " ").slice(0, 16)}` : " · past");
  const idline = document.createElement("div");
  idline.className = "rem-id";
  idline.textContent = r.id;
  main.append(t, sub, idline);
  card.appendChild(main);

  for (const cls of ["gear2", "gear3", "deferred", "hard"]) {
    if (r[cls]) {
      const chip = document.createElement("span");
      chip.className = `chip ${cls}`;
      chip.textContent = (cls === "deferred" ? "deferred"
        : cls === "hard" ? "breaks through"
        : `gear ${cls.slice(-1)}`);
      card.appendChild(chip);
    }
  }

  const actions = document.createElement("div");
  actions.className = "rem-actions";
  const edit = document.createElement("button");
  edit.className = "icon-act";
  edit.textContent = "✎";
  edit.title = `Edit ${r.id}`;
  edit.addEventListener("click", () => startEdit(r));
  const del = document.createElement("button");
  del.className = "icon-act danger";
  del.textContent = "🗑";
  del.title = `Delete ${r.id}`;
  del.addEventListener("click", async () => {
    await api(`/api/reminders/${encodeURIComponent(r.id)}`, { method: "DELETE" });
    if ($("rf-editing").value === r.id) $("rf-cancel").click();
    refreshReminders();
  });
  actions.append(edit, del);
  card.appendChild(actions);
  return card;
}

/* ---------- reminder form (adapts to type) ---------- */
function syncFormType() {
  const type = $("rf-type").value;
  $("rf-when-row").hidden = type !== "appointment";
  $("rf-schedule-row").hidden = type !== "chore";
  $("rf-every-row").hidden = type !== "nudge";
  $("rf-hard-row").hidden = type !== "appointment";
  $("rf-active-only-row").hidden = type !== "nudge";
}
$("rf-type").addEventListener("change", syncFormType);

function startEdit(r) {
  $("rf-title").textContent = `Editing ${r.id}`;
  $("rf-sub").textContent = "Change what you like. The daemon picks it up on its next tick.";
  $("rf-editing").value = r.id;
  $("rf-id").value = r.id; $("rf-id").disabled = true;
  $("rf-type").value = r.type;
  $("rf-text").value = r.text;
  $("rf-when").value = r.when ? r.when.slice(0, 16) : "";
  $("rf-schedule").value = r.schedule || "";
  $("rf-every").value = r.every || "";
  $("rf-active-only").checked = !!r.active_only;
  $("rf-hard").checked = !!r.hard;
  $("rf-note").value = r.note || "";
  $("rf-cancel").hidden = false;
  $("rf-save").textContent = "Save changes";
  $("rf-error").hidden = true;
  syncFormType();
  markEditingCard(r.id);
  $("rf-text").focus();
}

/* Show which card the form is currently editing. The form sits in its own
   column, so without this a person editing "laundry" among five cards gets no
   signal which row the Save button belongs to. */
function markEditingCard(id) {
  document.querySelectorAll(".rem-card.is-editing").forEach((c) => c.classList.remove("is-editing"));
  if (!id) return;
  const card = [...document.querySelectorAll(".rem-card")]
    .find((c) => c.querySelector(".rem-id") && c.querySelector(".rem-id").textContent === id);
  if (card) card.classList.add("is-editing");
}

function resetForm() {
  $("reminder-form").reset();
  $("rf-editing").value = ""; $("rf-id").disabled = false;
  $("rf-title").textContent = "Add a reminder";
  $("rf-sub").textContent = "Chat is for capture. This is for shaping.";
  $("rf-cancel").hidden = true; $("rf-error").hidden = true;
  $("rf-save").textContent = "Save reminder";
  markEditingCard(null);
  // a sensible default so the datetime field is never blank on an appointment
  if (!$("rf-when").value) {
    const t = new Date(Date.now() + 60 * 60 * 1000);
    t.setMinutes(0, 0, 0);
    const pad = (n) => String(n).padStart(2, "0");
    $("rf-when").value =
      `${t.getFullYear()}-${pad(t.getMonth() + 1)}-${pad(t.getDate())}T${pad(t.getHours())}:${pad(t.getMinutes())}`;
  }
  syncFormType();
}

$("rf-cancel").addEventListener("click", resetForm);

$("reminder-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const editing = $("rf-editing").value;
  const type = $("rf-type").value;
  const payload = { id: $("rf-id").value.trim(), type, text: $("rf-text").value.trim() };
  if (type === "appointment") payload.when = $("rf-when").value.replace("T", " ");
  if (type === "chore") payload.schedule = $("rf-schedule").value.trim();
  if (type === "nudge") {
    payload.every = $("rf-every").value.trim();
    payload.active_only = $("rf-active-only").checked;
  }
  if (type === "appointment") payload.hard = $("rf-hard").checked;
  if ($("rf-note").value.trim()) payload.note = $("rf-note").value.trim();
  try {
    if (editing) {
      await api(`/api/reminders/${encodeURIComponent(editing)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/reminders", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
    }
    resetForm();
    refreshReminders();
  } catch (e) {
    const err = $("rf-error");
    err.textContent = e.message; err.hidden = false;
  }
});

/* ---------- quiet hours ---------- */
function todayKey() { return DAYS[(new Date().getDay() + 6) % 7]; }

function buildQuietGrid() {
  api("/api/config").then((cfg) => {
    const grid = $("quiet-grid");
    grid.textContent = "";
    const today = todayKey();
    for (const day of DAYS) {
      const range = cfg.quiet_hours[day] || ["23:30", "09:00"];
      const row = document.createElement("div");
      row.className = "qday" + (day === today ? " today" : "");
      row.dataset.day = day;

      const name = document.createElement("span");
      name.className = "qname";
      name.textContent = DAY_LABEL[day] + (day === today ? " · today" : "");

      const on = document.createElement("input");
      on.type = "checkbox";
      on.checked = !!cfg.quiet_hours[day];
      on.title = "quiet hours on this day";

      const start = document.createElement("input");
      start.type = "time"; start.value = range[0];
      const dash = document.createElement("span");
      dash.className = "dash"; dash.textContent = "→";
      const end = document.createElement("input");
      end.type = "time"; end.value = range[1];

      const off = document.createElement("button");
      off.className = "icon-act";
      off.textContent = "✕";
      off.title = "no quiet hours this day";
      off.addEventListener("click", () => {
        on.checked = false;
        row.classList.remove("on");
      });

      row.append(name, on, start, dash, end, off);
      if (on.checked) row.classList.add("on");
      on.addEventListener("change", () => row.classList.toggle("on", on.checked));
      // a fresh day starts with the default range; make it clear it is off
      if (!cfg.quiet_hours[day]) start.value = start.value || "23:30";
      grid.appendChild(row);
    }
    const note = $("quiet-spill");
    const text = quietSpillNote(cfg);
    note.textContent = text;
    note.hidden = !text;
  });
}

/* Sync a quiet row's visual state with its checkbox. Bulk actions (copy,
   none) used to flip checkboxes without touching the class, so the grid kept
   showing days as armed after they had been switched off. */
function syncQuietRow(row) {
  row.classList.toggle("on", row.querySelector("input[type=checkbox]").checked);
}

/* A range that crosses midnight runs into the NEXT day. "Mon 23:30 -> 09:00"
   therefore quiets Monday night *and* Tuesday morning. The daemon has always
   done this correctly, but the grid never said so, so a person setting Monday
   would see Tuesday go quiet and have no idea why. Say it out loud instead. */
function quietSpillNote(cfg) {
  const spans = DAYS.filter((d) => {
    const r = cfg.quiet_hours[d];
    return r && r[0] > r[1];
  });
  if (!spans.length) return "";
  const names = spans.map((d) => DAY_LABEL[d]).join(", ");
  return `Ranges that cross midnight also quiet the following morning (${names} → the next day).`;
}

$("quiet-none").addEventListener("click", () => {
  document.querySelectorAll(".qday").forEach((row) => {
    row.querySelector("input[type=checkbox]").checked = false;
    syncQuietRow(row);
  });
});
$("quiet-copy").addEventListener("click", () => {
  const today = document.querySelector(`.qday[data-day="${todayKey()}"]`);
  document.querySelectorAll(".qday").forEach((row) => {
    row.querySelector("input[type=checkbox]").checked = today.querySelector("input[type=checkbox]").checked;
    row.querySelectorAll("input[type=time]").forEach((inp, i) => {
      inp.value = today.querySelectorAll("input[type=time]")[i].value;
    });
    syncQuietRow(row);
  });
});
$("quiet-save").addEventListener("click", async () => {
  const cfg = await api("/api/config");
  cfg.quiet_hours = {};
  document.querySelectorAll(".qday").forEach((row) => {
    if (row.querySelector("input[type=checkbox]").checked) {
      const [start, end] = row.querySelectorAll("input[type=time]");
      cfg.quiet_hours[row.dataset.day] = [start.value, end.value];
    }
  });
  await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cfg) });
  const m = $("quiet-msg");
  m.textContent = Object.keys(cfg.quiet_hours).length
    ? "Saved. Chores and nudges will wait through those hours — queued, not dropped."
    : "Saved. No quiet hours — everything arrives when it fires.";
  m.hidden = false;
  refreshStatus();
});

/* ---------- behavior ---------- */
async function fillBehavior() {
  const cfg = await api("/api/config");
  $("bf-gear2").value = cfg.gear2_delay_min;
  $("bf-gear3").value = cfg.gear3_delay_min;
  $("bf-snooze").value = cfg.snooze_options.join(", ");
  $("bf-chime").checked = cfg.chime;
  $("bf-chimerep").value = cfg.chime_repeat_s;
  $("bf-corner").value = cfg.popup_corner;
}
$("behavior-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const msg = $("bf-msg");
  const payload = {
    gear2_delay_min: Number($("bf-gear2").value),
    gear3_delay_min: Number($("bf-gear3").value),
    snooze_options: $("bf-snooze").value.split(",").map((s) => Number(s.trim())).filter(Boolean),
    chime: $("bf-chime").checked,
    chime_repeat_s: Number($("bf-chimerep").value),
    popup_corner: $("bf-corner").value,
    quiet_hours: (await api("/api/config")).quiet_hours,
  };
  try {
    await api("/api/config", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
    msg.textContent = "Saved. The daemon picks it up on its next tick.";
    msg.className = "muted"; msg.hidden = false;
    refreshConfig();   // the calendar's snooze menu reads the same options
  } catch (e) {
    msg.textContent = e.message; msg.className = "error"; msg.hidden = false;
  }
});

/* ---------- status + test-fire + log ---------- */
async function refreshStatus() {
  const s = await api("/api/status");
  const when = new Date(s.now);
  $("status-line").textContent =
    `${when.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })} — ` +
    (s.quiet ? "quiet hours" : "awake");

  const cards = $("status-cards");
  cards.textContent = "";
  const mk = (n, l, cls) => {
    const d = document.createElement("div");
    d.className = "stat" + (cls ? " " + cls : "");
    const num = document.createElement("div"); num.className = "n"; num.textContent = n;
    const lab = document.createElement("div"); lab.className = "l"; lab.textContent = l;
    d.append(num, lab);
    return d;
  };
  cards.appendChild(mk(String(s.pending.length), "escalating now", s.pending.length ? "warn" : ""));

  const deferredBox = mk(String(s.deferred.length),
    s.quiet ? "waiting for quiet hours to end" : "already waited through quiet hours",
    s.deferred.length ? "quiet" : "");
  cards.appendChild(deferredBox);

  const nextBox = document.createElement("div");
  nextBox.className = "stat next";
  const nv = document.createElement("div"); nv.className = "n";
  nv.textContent = s.next ? s.next.at.slice(11, 16) : "—";
  nv.style.fontSize = "22px";
  const nl = document.createElement("div"); nl.className = "l";
  nl.textContent = s.next ? `next: ${s.next.id}` : "nothing scheduled";
  nextBox.append(nv, nl);
  cards.appendChild(nextBox);
}

$("tf-go").addEventListener("click", async () => {
  const id = $("tf-id").value;
  if (!id) return;
  $("tf-result").hidden = false;
  $("tf-result").textContent = "Firing — watch gears 1 → 2 → 3 over the next ~40s…";
  try {
    await api("/api/test-fire", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    $("tf-result").textContent = `Fired "${id}". It climbs on the daemon's ticks (gear delays apply).`;
    refreshStatus();
  } catch (e) {
    $("tf-result").textContent = `Failed: ${e.message}`;
  }
});

async function loadLog() {
  const view = $("log-view");
  try {
    const data = await api("/api/log?lines=60");
    view.textContent = (data.lines && data.lines.length)
      ? data.lines.join("\n") : "Nothing logged yet.";
  } catch (e) {
    view.textContent = `No log available: ${e.message}`;
  }
}

/* ---------- calendar modal logic ---------- */
let calYear = null, calMonth = null, calSelected = null;

function openCalendar() {
  $("cal-modal").hidden = false;
  if (calYear === null) {
    const now = new Date();
    calYear = now.getFullYear(); calMonth = now.getMonth() + 1;
  }
  loadCalendar();
  $("cal-close").focus();
}
function closeCalendar() {
  $("cal-modal").hidden = true;
  $("cal-open").focus();
}
$("cal-open").addEventListener("click", openCalendar);
$("cal-close").addEventListener("click", closeCalendar);
$("cal-modal").addEventListener("click", (ev) => {
  if (ev.target === $("cal-modal")) closeCalendar();  // backdrop click closes
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape" && !$("cal-modal").hidden) closeCalendar();
  else if ((ev.key === "c" || ev.key === "C") && ev.target === document.body) openCalendar();
});
$("cal-today").addEventListener("click", () => {
  const now = new Date();
  calYear = now.getFullYear(); calMonth = now.getMonth() + 1;
  calSelected = null;
  loadCalendar();
});
$("cal-prev").addEventListener("click", () => {
  calMonth--; if (calMonth < 1) { calMonth = 12; calYear--; }
  calSelected = null;
  loadCalendar();
});
$("cal-next").addEventListener("click", () => {
  calMonth++; if (calMonth > 12) { calMonth = 1; calYear++; }
  calSelected = null;
  loadCalendar();
});

async function loadCalendar() {
  $("cal-title").textContent = "…";
  const data = await api(`/api/calendar?year=${calYear}&month=${calMonth}`);
  $("cal-title").textContent = `${data.month_name} ${data.year}`;

  const byDay = {};
  for (const ev of data.events) {
    const day = Number(ev.at.slice(8, 10));
    (byDay[day] = byDay[day] || []).push(ev);
  }

  const grid = $("cal-grid");
  grid.textContent = "";
  for (let i = 0; i < data.first_weekday; i++) {
    const b = document.createElement("div");
    b.className = "cal-cell blank";
    grid.appendChild(b);
  }
  for (let day = 1; day <= data.days_in_month; day++) {
    const iso = `${data.year}-${String(data.month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
    const cell = document.createElement("button");
    cell.type = "button";
    cell.className = "cal-cell";
    cell.dataset.iso = iso;
    if (iso === data.today) cell.classList.add("today");
    if (iso === calSelected) cell.classList.add("selected");
    const dnum = document.createElement("span");
    dnum.className = "dnum"; dnum.textContent = day;
    cell.appendChild(dnum);
    const dayEvents = byDay[day] || [];
    for (const ev of dayEvents.slice(0, 3)) {
      const s = document.createElement("span");
      s.className = `ev ${ev.type}${ev.past ? " past" : ""}`;
      s.textContent = `${ev.at.slice(11, 16)} ${ev.text}`;
      s.title = `${ev.text} — ${ev.type}, ${ev.at.replace("T", " ")}` +
        (ev.repeats ? `, repeating every ${ev.repeats}` : "") +
        (movable(ev) ? " · drag to another day to move it" : "");
      // Only what the daemon can actually move is draggable. A nudge repeats on
      // an interval and has no date to land on; offering the drag would be a lie.
      if (movable(ev)) {
        s.classList.add("draggable");
        s.draggable = true;
        s.addEventListener("dragstart", (e) => onDragStart(e, ev, s));
        s.addEventListener("dragend", () => onDragEnd());
      }
      cell.appendChild(s);
    }
    if (dayEvents.length > 3) {
      const more = document.createElement("span");
      more.className = "more";
      more.textContent = `+${dayEvents.length - 3} more`;
      cell.appendChild(more);
    }
    cell.addEventListener("click", () => selectDay(iso, dayEvents));
    cell.addEventListener("dragover", onDragOver);
    cell.addEventListener("dragleave", () => {
      cell.classList.remove("drop-hot", "drop-bad");
    });
    cell.addEventListener("drop", (e) => onDrop(e, iso));
    grid.appendChild(cell);
  }
  document.querySelectorAll(".cal-cell.selected").forEach((c) => c.classList.remove("selected"));
  $("cal-day").hidden = true;
  hideToast();
}

/* ---------- what can be dragged ---------- */
function movable(ev) {
  // appointments have a real date; chores have weekdays to move between.
  return ev.type === "appointment" || ev.type === "chore";
}

let dragEv = null;

function onDragStart(e, ev, node) {
  dragEv = ev;
  node.classList.add("dragging");
  e.dataTransfer.effectAllowed = "move";
  // Firefox needs data set for a drag to start at all.
  e.dataTransfer.setData("text/plain", ev.id);
}

function onDragEnd() {
  dragEv = null;
  document.querySelectorAll(".ev.dragging").forEach((n) => n.classList.remove("dragging"));
  document.querySelectorAll(".cal-cell").forEach((c) => c.classList.remove("drop-hot", "drop-bad"));
}

function onDragOver(e) {
  if (!dragEv) return;
  e.preventDefault();
  const cell = e.currentTarget;
  const target = cell.dataset.iso;
  if (!target) return;
  // A chore only moves between the weekdays it already runs on? No — the whole
  // point is moving it to a new day. But moving onto the day it already fires
  // is a no-op, and dragging a *past* appointment forward is a real edit, so
  // only reject the same-day drop.
  const sameDay = dragEv.at.slice(0, 10) === target;
  e.dataTransfer.dropEffect = sameDay ? "none" : "move";
  cell.classList.toggle("drop-hot", !sameDay);
  cell.classList.toggle("drop-bad", sameDay);
}

const WD = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];

async function onDrop(e, iso) {
  e.preventDefault();
  const ev = dragEv;
  onDragEnd();
  if (!ev || ev.at.slice(0, 10) === iso) return;

  try {
    if (ev.type === "appointment") {
      // keep the clock time, move the date
      const time = ev.at.slice(11, 16);
      await api(`/api/reminders/${encodeURIComponent(ev.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ when: `${iso} ${time}` }),
      });
      toast(`Moved "${ev.text}" to ${niceDate(iso)} at ${time}.`);
    } else {
      // A chore carries weekdays, not a date. Dropping it on a day adds that
      // weekday. The current schedule must be known: if the cache has no entry
      // for this id we refuse rather than invent one, because the fallback below
      // (empty days + a made-up time) would replace a real schedule with
      // "sat 09:00" and look like a successful drag.
      const r = reminderCache.find((x) => x.id === ev.id);
      if (!r || !r.schedule) {
        toast(`Couldn't move "${ev.text}" — its schedule isn't loaded. Reopen the calendar.`, true);
        return;
      }
      const parts = r.schedule.trim().split(/\s+/);
      const current = (parts[0] || "").split(",").map((d) => d.trim()).filter(Boolean);
      const time = parts.slice(1).join(" ");
      if (!current.length || !time) {
        toast(`Couldn't read the schedule for "${r.text}".`, true);
        return;
      }
      const dow = WD[new Date(iso + "T00:00").getDay()];
      if (current.includes(dow)) {
        toast(`"${r.text}" already runs on ${dow}.`, true);
        return;
      }
      const next = [...current, dow].sort((a, b) => WD.indexOf(a) - WD.indexOf(b));
      await api(`/api/reminders/${encodeURIComponent(ev.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ schedule: `${next.join(",")} ${time}` }),
      });
      toast(`"${r.text}" now also runs on ${dow}.`);
    }
    await refreshReminders();
    await loadCalendar();
  } catch (err) {
    toast(`Couldn't move it: ${err.message}`, true);
  }
}

function niceDate(iso) {
  return new Date(iso + "T00:00")
    .toLocaleDateString([], { weekday: "short", month: "short", day: "numeric" });
}

/* ---------- the day detail, with inline verdicts ---------- */
let toastTimer = null;

function toast(msg, isError) {
  let el = document.querySelector(".cal-toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "cal-toast";
    $("cal-modal").querySelector(".modal").appendChild(el);
  }
  el.textContent = msg;
  el.classList.toggle("error", !!isError);
  el.hidden = false;
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(hideToast, isError ? 6000 : 3800);
}

function hideToast() {
  const el = document.querySelector(".cal-toast");
  if (el) el.hidden = true;
}

function selectDay(iso, events) {
  calSelected = iso;
  document.querySelectorAll(".cal-cell.selected").forEach((c) => c.classList.remove("selected"));
  const cell = document.querySelector(`.cal-cell[data-iso="${iso}"]`);
  if (cell) cell.classList.add("selected");

  const box = $("cal-day");
  box.textContent = "";
  const h = document.createElement("h3");
  const d = new Date(iso + "T00:00");
  h.textContent = d.toLocaleDateString([], { weekday: "long", month: "long", day: "numeric" });
  box.appendChild(h);
  if (!events.length) {
    const p = document.createElement("div");
    p.className = "muted";
    p.textContent = "Nothing scheduled. A quiet day.";
    box.appendChild(p);
  } else {
    const ul = document.createElement("ul");
    // One row per reminder, not one per fire: a 90m nudge would otherwise be
    // fifty identical lines and the Done button would be a coin toss.
    const seen = new Set();
    for (const ev of events) {
      if (seen.has(ev.id)) continue;
      seen.add(ev.id);
      ul.appendChild(dayRow(ev));
    }
    box.appendChild(ul);
  }
  box.hidden = false;
}

function dayRow(ev) {
  const li = document.createElement("li");
  li.className = ev.type;
  const t = document.createElement("span");
  t.className = "t"; t.textContent = ev.at.slice(11, 16);
  const x = document.createElement("span");
  x.className = "x"; x.textContent = ev.text;
  if (ev.repeats) {
    const rep = document.createElement("span");
    rep.className = "id"; rep.textContent = `every ${ev.repeats}`;
    x.appendChild(document.createTextNode(" "));
    x.appendChild(rep);
  }
  const id = document.createElement("span");
  id.className = "id"; id.textContent = ev.id;
  li.append(t, x, id);

  // The three honest exits, right where the reminder is listed. The snooze
  // choices come from the config, not from a constant invented here — the
  // popup and this menu must offer the same durations.
  const acts = document.createElement("span");
  acts.className = "day-actions";
  acts.append(dayBtn("Done", "ok", () => sendVerdict(ev, "done")));
  const opts = cfgCache.snooze_options && cfgCache.snooze_options.length
    ? cfgCache.snooze_options : [10];
  if (opts.length === 1) {
    acts.append(dayBtn(`Snooze ${opts[0]}`, "snooze",
      () => sendVerdict(ev, "snooze", opts[0])));
  } else {
    const sel = document.createElement("select");
    sel.className = "day-snooze";
    sel.title = "Snooze for…";
    const first = document.createElement("option");
    first.value = ""; first.textContent = "Snooze…";
    sel.appendChild(first);
    for (const m of opts) {
      const o = document.createElement("option");
      o.value = String(m); o.textContent = `${m} min`;
      sel.appendChild(o);
    }
    sel.addEventListener("click", (e) => e.stopPropagation());
    sel.addEventListener("change", async (e) => {
      e.stopPropagation();
      const m = Number(sel.value);
      if (!m) return;
      sel.disabled = true;
      await sendVerdict(ev, "snooze", m);
      sel.value = ""; sel.disabled = false;
    });
    acts.append(sel);
  }
  // "Didn't do it" is an honest out for a chore; an appointment can only be
  // snoozed (SPEC: appointment → requires Snooze instead), so we don't offer a
  // button that the daemon would have to refuse.
  if (ev.type !== "appointment") {
    acts.append(dayBtn("Didn't do it", "meh", () => sendVerdict(ev, "didnt")));
  }
  li.appendChild(acts);
  return li;
}

function dayBtn(label, kind, onAct) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = `day-btn day-btn-${kind}`;
  b.textContent = label;
  b.title = kind === "snooze" ? "Snooze 10 minutes" : `Mark it: ${label}`;
  b.addEventListener("click", async (e) => {
    e.stopPropagation();
    b.disabled = true;
    await onAct();
    b.disabled = false;
  });
  return b;
}

async function sendVerdict(ev, verdict, snoozeMin) {
  const body = { id: ev.id, verdict };
  if (snoozeMin) body.snooze_min = snoozeMin;
  try {
    await api("/api/popup-verdict", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const said = verdict === "done" ? "Marked done."
      : verdict === "didnt" ? "It'll wait. It's not going anywhere."
      : `Snoozed ${snoozeMin} minutes.`;
    toast(`${said} — the daemon picks it up on its next tick.`);
    refreshStatus();
  } catch (err) {
    toast(`Couldn't log that: ${err.message}`, true);
  }
}

/* ---------- config cache ---------- */
// The calendar needs the snooze durations to build its action menu, and it must
// offer the same choices the popup does. One fetch, refreshed when Behavior is
// saved, rather than reading config on every cell click.
let cfgCache = {};

async function refreshConfig() {
  try {
    cfgCache = await api("/api/config");
  } catch { /* leave whatever we had */ }
}

/* ---------- boot ---------- */
resetForm();          // sets the default date AND applies type-conditional hiding
refreshConfig();
refreshReminders();
refreshStatus();
fillBehavior();
// the tab ink measures real layout, so it can only be placed after paint
requestAnimationFrame(moveInk);
// fonts can shift the label widths under it
if (document.fonts && document.fonts.ready) document.fonts.ready.then(moveInk);
