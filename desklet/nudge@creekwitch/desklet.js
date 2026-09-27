/* Nudge desklet — shows what Nudge is waiting on, and takes verdicts.

   Talks to the daemon's localhost API (settings.server). Everything the
   desklet draws comes from the server; it re-derives nothing (AGENTS.md:
   one definition of "due"/"quiet"/"next").
*/

/* Cinnamon 6.x ships BOTH libsoup 2.4 and 3.0 typelibs, and cjs warns
   "Requiring Soup but it has 2 versions available" without an explicit pick —
   which can silently hand back the libsoup 3 API where Message.new() and
   queue_message() no longer exist. Pin 2.4 (present on Mint 20 through 22),
   falling back to 3.0 only if 2.4 is genuinely absent so the desklet still
   loads instead of throwing at import time. */
if (imports.gi.versions) {
    imports.gi.versions.Soup = "2.4";
}

const Desklet = imports.ui.desklet;
const St = imports.gi.St;
const Mainloop = imports.mainloop;
const GLib = imports.gi.GLib;
const Settings = imports.ui.settings;
const Cinnamon = imports.gi.Cinnamon;
const Soup = imports.gi.Soup;
const Gettext = imports.gettext;

const UUID = "nudge@creekwitch";

/* ---- tiny HTTP helper (soup2 API: Mint 20/21/22 all ship libsoup 2.4) ---- */
let _session = null;

function _httpSession() {
    if (!_session) {
        _session = new Soup.Session();
        _session.timeout = 5;
    }
    return _session;
}

/* libsoup 3 dropped Message.new() and queue_message() for async/await
   send_and_read_async(). Detect the API we actually got rather than assuming,
   so a libsoup3-only Mint reports something readable instead of a crash. */
function _soupIsV2() {
    return typeof Soup.Message !== "undefined" && typeof Soup.Message.new === "function";
}

function _get(url, callback) {
    if (!_soupIsV2()) {
        _get3(url, callback);
        return;
    }
    let msg = Soup.Message.new("GET", url);
    if (!msg) { callback(null); return; }
    // libsoup 2.x on Mint takes queue_message(msg, callback) — TWO args, the
    // callback receiving (session, message). Passing a third argument (the
    // newer shape) makes cjs warn and never invoke the callback, so the
    // desklet would sit silently blank.
    _httpSession().queue_message(msg, (ses, m) => {
        try {
            const ok = m.status_code === 200;
            const text = m.response_body ? m.response_body.data : null;
            callback(ok && text ? JSON.parse(text) : null);
        } catch (e) {
            callback(null);
        }
    });
}

/* libsoup 3 path: async/await on the session, no Message object. */
async function _get3(url, callback) {
    try {
        const ses = new Soup.Session();
        const res = await ses.send_and_read_async(
            Soup.Message.new("GET", url), 0, null);
        const bytes = ses.send_and_read_finish(res);
        const text = new TextDecoder().decode(bytes.get_data());
        callback(JSON.parse(text));
    } catch (e) {
        callback(null);
    }
}

function _post(url, payload, callback) {
    if (!_soupIsV2()) {
        _post3(url, payload, callback);
        return;
    }
    let msg = Soup.Message.new("POST", url);
    if (!msg) { callback(false); return; }
    const body = JSON.stringify(payload);
    msg.set_request("application/json", Soup.MemoryUse.COPY, body);
    // two-arg form, same as _get above — see the note there.
    _httpSession().queue_message(msg, (ses, m) => {
        callback(m.status_code >= 200 && m.status_code < 300);
    });
}

/* libsoup 3 POST: build the message, set the body on the request body
   stream, then send async. Same callback contract as the v2 path. */
async function _post3(url, payload, callback) {
    try {
        const ses = new Soup.Session();
        const msg = Soup.Message.new("POST", url);
        const body = JSON.stringify(payload);
        msg.set_request_body_from_bytes(
            "application/json",
            new GLib.Bytes(new TextEncoder().encode(body)));
        const res = await ses.send_and_read_async(msg, 0, null);
        ses.send_and_read_finish(res);
        callback(msg.get_status() >= 200 && msg.get_status() < 300);
    } catch (e) {
        callback(false);
    }
}

/* ---- the desklet ---- */

function NudgeDesklet(metadata, desklet_id) {
    this._init(metadata, desklet_id);
}

NudgeDesklet.prototype = {
    __proto__: Desklet.Desklet.prototype,

    _init: function (metadata, desklet_id) {
        Desklet.Desklet.prototype._init.call(this, metadata, desklet_id);
        this._timeout = null;

        this.settings = new Settings.DeskletSettings(this, UUID, desklet_id);
        this.settings.bindProperty(Settings.BindingDirection.IN, "port", "port",
            this._onSettingsChanged, null);
        this.settings.bindProperty(Settings.BindingDirection.IN, "refresh_seconds",
            "refresh_seconds", this._onSettingsChanged, null);
        this.settings.bindProperty(Settings.BindingDirection.IN, "show_deferred",
            "show_deferred", this._onSettingsChanged, null);

        this._buildUI();
        this._refresh();
    },

    _buildUI: function () {
        this._main = new St.BoxLayout({ vertical: true, style_class: "nudge-desklet" });

        // header
        let head = new St.BoxLayout({ style_class: "nudge-head" });
        this._title = new St.Label({ text: "🕯️ Nudge", style_class: "nudge-title" });
        this._dot = new St.Label({ text: "·", style_class: "nudge-dot" });
        head.add(this._title, { y_align: St.Align.MIDDLE });
        head.add(this._dot, { y_align: St.Align.MIDDLE });

        // the thing itself
        this._body = new St.Label({ text: "…", style_class: "nudge-body" });
        this._body.clutter_text.line_wrap = true;

        // meta line: gear / deferred / next
        this._metaLine = new St.Label({ text: "", style_class: "nudge-meta" });

        // buttons
        let row = new St.BoxLayout({ style_class: "nudge-row" });
        this._doneBtn = new St.Button({ label: "Done", style_class: "nudge-btn ok" });
        this._didntBtn = new St.Button({ label: "Didn't do it", style_class: "nudge-btn meh" });
        this._snoozeBtn = new St.Button({ label: "Snooze 10", style_class: "nudge-btn" });
        this._doneBtn.connect("clicked", () => this._verdict("done"));
        this._didntBtn.connect("clicked", () => this._verdict("didnt"));
        this._snoozeBtn.connect("clicked", () => this._verdict("snooze", 10));
        row.add(this._doneBtn, { expand: true });
        row.add(this._didntBtn, { expand: true });
        row.add(this._snoozeBtn, { expand: true });

        this._main.add(head);
        this._main.add(this._body);
        this._main.add(this._metaLine);
        this._main.add(row);
        this.setContent(this._main);
    },

    _onSettingsChanged: function () {
        this._refresh();
    },

    _base: function () {
        return "http://127.0.0.1:" + (this.port || 8130);
    },

    /* the focused reminder: the highest gear still escalating */
    _pick: function (status, reminders) {
        let pending = status.pending || [];
        if (pending.length) {
            let best = pending[0];
            for (let p of pending) { if (p.gear > best.gear) { best = p; } }
            let r = reminders.find((x) => x.id === best.id);
            return r ? { id: r.id, text: r.text, gear: best.gear } : null;
        }
        return null;
    },

    _refresh: function () {
        if (this._timeout) { Mainloop.source_remove(this._timeout); this._timeout = null; }

        _get(this._base() + "/api/status", (status) => {
            if (!status) {
                this._title.set_text("🕯️ Nudge");
                this._body.set_text("Not running — start the daemon");
                this._metaLine.set_text("");
                this._setButtons(false);
                this._schedule();
                return;
            }
            _get(this._base() + "/api/reminders", (data) => {
                const reminders = (data && data.reminders) || [];
                const focused = this._pick(status, reminders);
                if (focused) {
                    this._title.set_text("🕯️ " + focused.text);
                    this._dot.set_text(focused.gear >= 3 ? "●●●" : (focused.gear >= 2 ? "●●" : "●"));
                    this._dot.style_class = "nudge-dot g" + focused.gear;
                    this._body.set_text("waiting on you");
                    let bits = [];
                    if (status.deferred.length && this.show_deferred) {
                        bits.push(status.deferred.length + " deferred (quiet hours)");
                    }
                    if (status.next) {
                        bits.push("next: " + status.next.id + " at " +
                                  status.next.at.slice(11, 16));
                    }
                    if (status.quiet) { bits.push("quiet hours"); }
                    this._metaLine.set_text(bits.join(" · "));
                    this._setButtons(true);
                } else {
                    this._title.set_text("🕯️ Nudge");
                    this._dot.set_text("·");
                    this._dot.style_class = "nudge-dot";
                    this._body.set_text("all quiet");
                    let bits = [];
                    if (status.next) {
                        bits.push("next: " + status.next.id + " at " +
                                  status.next.at.slice(11, 16));
                    }
                    if (status.deferred.length && this.show_deferred) {
                        bits.push(status.deferred.length + " waiting for morning");
                    }
                    if (status.quiet) { bits.push("quiet hours"); }
                    this._metaLine.set_text(bits.join(" · "));
                    this._setButtons(false);
                }
                this._schedule();
            });
        });
    },

    _setButtons: function (enabled) {
        this._doneBtn.reactive = enabled;
        this._didntBtn.reactive = enabled;
        this._snoozeBtn.reactive = enabled;
        this._doneBtn.opacity = enabled ? 255 : 120;
        this._didntBtn.opacity = enabled ? 255 : 120;
        this._snoozeBtn.opacity = enabled ? 255 : 120;
    },

    _verdict: function (kind, snooze_min) {
        // Which reminder does this verdict belong to? The daemon resolves it
        // the same way we do: ask for status, then take the highest gear.
        //
        // `pending` is only populated for reminders that have ALREADY
        // escalated to gear 1+. Most of the time nothing is pending (a
        // reminder that has not fired yet, or one sitting in quiet hours), so
        // bailing out on an empty list made Done / Didn't / Snooze silently do
        // nothing — the button looked live and just wasn't. Fall back to `next`
        // (the soonest reminder) so a verdict is always actionable.
        _get(this._base() + "/api/status", (status) => {
            if (!status) { return; }
            let target = null;
            const pend = status.pending || [];
            if (pend.length) {
                target = pend[0];
                for (let p of pend) { if (p.gear > target.gear) { target = p; } }
            } else if (status.next && status.next.id) {
                target = { id: status.next.id, gear: 0 };
            }
            if (!target) { return; }
            let payload = { id: target.id, verdict: kind };
            if (snooze_min) { payload.snooze_min = snooze_min; }
            _post(this._base() + "/api/popup-verdict", payload, (ok) => {
                this._refresh();
            });
        });
    },

    _schedule: function () {
        this._timeout = Mainloop.timeout_add_seconds(
            Math.max(5, this.refresh_seconds || 20), () => {
                this._refresh();
                return false;   // _refresh re-arms the timer
            });
    },

    on_desklet_removed: function () {
        if (this._timeout) { Mainloop.source_remove(this._timeout); this._timeout = null; }
    },
};

function main(metadata, desklet_id) {
    return new NudgeDesklet(metadata, desklet_id);
}
