/*
 * Hunter Douglas Platinum card — compact, Mushroom-style.
 *
 *   ┌───────────────────────────────┐
 *   │ (icon)  Parlor                │
 *   │         Open · 100%           │
 *   │ [ ↑ ] [ ↓ ] [vanes] [top] [✋] │   ✋ swaps the buttons for a drag bar
 *   └───────────────────────────────┘
 *
 *   type: custom:hunterdouglas-platinum-card
 *   entity: cover.parlor                 # any of the blind's covers
 *   name: Parlor                         # optional
 *   icon: mdi:blinds                     # optional
 *   top_open: 10                         # optional: how far the "top" button opens a top-down blind (%)
 *   show_vanes: true                     # optional
 *   show_top: true                       # optional
 *
 * Whole room (everything moves together):
 *   type: custom:hunterdouglas-platinum-card
 *   name: Dining
 *   entities: [cover.dining_left, cover.dining_right]
 *
 * Served and loaded automatically by the hunterdouglas_platinum integration.
 */
const CARD_VERSION = "0.5.2";

const ICONS = {
  up: "mdi:arrow-up",
  down: "mdi:arrow-down",
  slider: "mdi:gesture-swipe-horizontal",
  buttons: "mdi:arrow-up-down",
  vanesOpen: "mdi:blinds-horizontal",
  vanesClosed: "mdi:blinds-horizontal-closed",
  topOpen: "mdi:arrow-collapse-down",
  open: "mdi:blinds-open",
  closed: "mdi:blinds",
};

class HunterDouglasPlatinumCard extends HTMLElement {
  static getStubConfig(hass) {
    const first = Object.values(hass.states).find(
      (s) => s.entity_id.startsWith("cover.") && s.attributes.platinum_role === "bottom"
    );
    return { entity: first ? first.entity_id : "" };
  }

  static getConfigForm() {
    return {
      schema: [
        { name: "entity", selector: { entity: { domain: "cover" } } },
        { name: "entities", selector: { entity: { domain: "cover", multiple: true } } },
        { name: "name", selector: { text: {} } },
        { name: "icon", selector: { icon: {} } },
        {
          type: "grid",
          name: "",
          schema: [
            { name: "top_open", selector: { number: { min: 1, max: 100, step: 1, unit_of_measurement: "%" } } },
            { name: "show_vanes", selector: { boolean: {} } },
            { name: "show_top", selector: { boolean: {} } },
          ],
        },
      ],
      computeLabel: (s) =>
        ({
          entity: "Blind",
          entities: "…or several blinds (whole room)",
          name: "Name",
          icon: "Icon",
          top_open: "Top-down opening",
          show_vanes: "Vanes button",
          show_top: "Top-down button",
        })[s.name],
    };
  }

  setConfig(config) {
    const list = [].concat(config.entities || [], config.entity ? [config.entity] : []);
    if (!list.length) throw new Error("Pick a blind (entity) or several blinds (entities)");
    this._config = { top_open: 10, show_vanes: true, show_top: true, ...config };
    this._anchors = [...new Set(list.map((e) => (typeof e === "string" ? e : e.entity)))];
    this._mode = "buttons";
    this._built = false;
    this._sig = null;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return 2;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: 2 };
  }

  /* ---------------- data ---------------- */

  _deviceOf(id) {
    const e = this._hass.entities && this._hass.entities[id];
    return e && e.device_id;
  }

  _blind(anchorId) {
    const states = this._hass.states;
    const anchor = states[anchorId];
    if (!anchor) return null;
    const a = anchor.attributes;
    if (a.shade_id === undefined || !a.platinum_role) return { bottom: anchor };
    const device = this._deviceOf(anchorId);
    const parts = {};
    for (const s of Object.values(states)) {
      if (!s.entity_id.startsWith("cover.") || s.attributes.shade_id !== a.shade_id) continue;
      const d = this._deviceOf(s.entity_id);
      if (device && d && d !== device) continue;
      const role = s.attributes.platinum_role;
      if (role === "bottom" || role === "middle" || role === "vanes") parts[role] = s;
    }
    if (!parts.vanes && parts.bottom && typeof parts.bottom.attributes.current_tilt_position === "number") {
      parts.vanes = { ...parts.bottom, _tilt: true };
    }
    return parts;
  }

  _collect() {
    const groups = {};
    let found = 0;
    for (const id of this._anchors) {
      const parts = this._blind(id);
      if (!parts) continue;
      found++;
      for (const [role, st] of Object.entries(parts)) (groups[role] = groups[role] || []).push(st);
    }
    return found ? groups : null;
  }

  _value(states) {
    const vals = (states || [])
      .map((s) => (s._tilt ? s.attributes.current_tilt_position : s.attributes.current_position))
      .filter((v) => typeof v === "number");
    if (!vals.length) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  }

  _send(role, value) {
    const states = (this._groups && this._groups[role]) || [];
    const tilt = states.filter((s) => s._tilt).map((s) => s.entity_id);
    const pos = states.filter((s) => !s._tilt).map((s) => s.entity_id);
    if (pos.length) this._hass.callService("cover", "set_cover_position", { entity_id: pos, position: value });
    if (tilt.length)
      this._hass.callService("cover", "set_cover_tilt_position", { entity_id: tilt, tilt_position: value });
  }

  _title() {
    if (this._config.name) return this._config.name;
    if (this._anchors.length > 1) return "Blinds";
    const dev = this._deviceOf(this._anchors[0]);
    const d = dev && this._hass.devices && this._hass.devices[dev];
    if (d) return d.name_by_user || d.name;
    const s = this._hass.states[this._anchors[0]];
    return ((s && s.attributes.friendly_name) || "").replace(/\s*(Bottom rail|Middle rail|Vanes)$/i, "");
  }

  /* ---------------- rendering ---------------- */

  _build() {
    this.innerHTML = "";
    this.style.display = "block";
    this.style.minWidth = "0";
    const card = document.createElement("ha-card");
    card.innerHTML = `
      <style>
        hunterdouglas-platinum-card { display: block; min-width: 0; }
        .hd { padding: 12px; display: flex; flex-direction: column; gap: 12px; }
        .hd-head { display: flex; align-items: center; gap: 12px; min-width: 0; }
        .hd-icon {
          flex: none; width: 40px; height: 40px; border-radius: 50%; display: grid; place-items: center;
          cursor: pointer; transition: background .2s, color .2s;
          background: rgba(var(--rgb-disabled-color, 189,189,189), .2); color: var(--disabled-text-color, #9e9e9e);
          --mdc-icon-size: 22px;
        }
        .hd-icon.on { background: rgba(var(--rgb-blue, 33,150,243), .2); color: rgb(var(--rgb-blue, 33,150,243)); }
        .hd-text { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; }
        .hd-name { font-size: 14px; font-weight: 600; line-height: 20px; color: var(--primary-text-color);
                   white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .hd-state { font-size: 12px; line-height: 16px; color: var(--secondary-text-color);
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; font-variant-numeric: tabular-nums; }
        .hd-row { display: flex; gap: 8px; height: 42px; }
        .hd-btn {
          flex: 1 1 0; min-width: 0; height: 42px; border: none; border-radius: 12px; cursor: pointer; padding: 0;
          display: grid; place-items: center; color: var(--primary-text-color);
          background: rgba(var(--rgb-primary-text-color, 33,33,33), .05); --mdc-icon-size: 22px;
          transition: background .15s, color .15s; -webkit-tap-highlight-color: transparent;
        }
        .hd-btn:active { background: rgba(var(--rgb-primary-text-color, 33,33,33), .12); }
        .hd-btn:disabled { opacity: .35; cursor: default; }
        .hd-btn:focus-visible, .hd-bar:focus-visible { outline: 2px solid rgb(var(--rgb-blue, 33,150,243)); outline-offset: 2px; }
        .hd-btn:focus:not(:focus-visible), .hd-bar:focus:not(:focus-visible) { outline: none; }
        .hd-btn.small { flex: 0 0 auto; width: 42px; }
        .hd-btn.on { background: rgba(var(--rgb-blue, 33,150,243), .2); color: rgb(var(--rgb-blue, 33,150,243)); }
        .hd-btn[hidden], .hd-row[hidden] { display: none; }
        .hd-bar {
          position: relative; flex: 1 1 auto; min-width: 0; height: 42px; border-radius: 12px; overflow: hidden;
          background: rgba(var(--rgb-blue, 33,150,243), .2); cursor: pointer; touch-action: none;
        }
        .hd-fill { position: absolute; inset: 0 auto 0 0; background: rgb(var(--rgb-blue, 33,150,243));
                   transition: width .15s ease; }
        .hd-bar.dragging .hd-fill { transition: none; }
        .hd-missing { color: var(--error-color, #db4437); font-size: 13px; }
      </style>
      <div class="hd">
        <div class="hd-head">
          <div class="hd-icon"><ha-icon></ha-icon></div>
          <div class="hd-text"><div class="hd-name"></div><div class="hd-state"></div></div>
        </div>
        <div class="hd-row" data-mode="buttons">
          <button class="hd-btn" data-act="up" title="Open"><ha-icon icon="${ICONS.up}"></ha-icon></button>
          <button class="hd-btn" data-act="down" title="Close"><ha-icon icon="${ICONS.down}"></ha-icon></button>
          <button class="hd-btn" data-act="vanes" title="Vanes"><ha-icon></ha-icon></button>
          <button class="hd-btn" data-act="top" title="Open top"><ha-icon icon="${ICONS.topOpen}"></ha-icon></button>
          <button class="hd-btn" data-act="slider" title="Set position"><ha-icon icon="${ICONS.slider}"></ha-icon></button>
        </div>
        <div class="hd-row" data-mode="slider" hidden>
          <div class="hd-bar" role="slider" tabindex="0" aria-valuemin="0" aria-valuemax="100" aria-label="Position">
            <div class="hd-fill"></div>
          </div>
          <button class="hd-btn small" data-act="buttons" title="Buttons"><ha-icon icon="${ICONS.buttons}"></ha-icon></button>
        </div>
      </div>`;
    this.appendChild(card);
    const q = (s) => card.querySelector(s);
    this._els = {
      icon: q(".hd-icon"),
      iconEl: q(".hd-icon ha-icon"),
      name: q(".hd-name"),
      state: q(".hd-state"),
      rowButtons: q('[data-mode="buttons"]'),
      rowSlider: q('[data-mode="slider"]'),
      bar: q(".hd-bar"),
      fill: q(".hd-fill"),
      btn: Object.fromEntries([...card.querySelectorAll("[data-act]")].map((b) => [b.dataset.act, b])),
    };
    const b = this._els.btn;
    b.up.addEventListener("click", () => this._move(100));
    b.down.addEventListener("click", () => this._move(0));
    b.vanes.addEventListener("click", () => this._send("vanes", (this._vals.vanes ?? 0) > 50 ? 0 : 100));
    b.top.addEventListener("click", () =>
      this._send("middle", (this._vals.middle ?? 0) > 0 ? 0 : Number(this._config.top_open) || 10)
    );
    b.slider.addEventListener("click", () => this._setMode("slider"));
    b.buttons.addEventListener("click", () => this._setMode("buttons"));
    this._els.icon.addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._anchors[0] };
      this.dispatchEvent(ev);
    });
    this._wireBar();
    this._built = true;
  }

  _wireBar() {
    const bar = this._els.bar;
    const valueAt = (ev) => {
      const r = bar.getBoundingClientRect();
      return Math.round(Math.min(1, Math.max(0, (ev.clientX - r.left) / r.width)) * 100);
    };
    bar.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      bar.setPointerCapture(ev.pointerId);
      this._dragging = true;
      bar.classList.add("dragging");
      this._preview(valueAt(ev));
    });
    bar.addEventListener("pointermove", (ev) => this._dragging && this._preview(valueAt(ev)));
    bar.addEventListener("pointerup", (ev) => {
      if (!this._dragging) return;
      this._dragging = false;
      bar.classList.remove("dragging");
      this._move(valueAt(ev));
    });
    bar.addEventListener("pointercancel", () => {
      this._dragging = false;
      bar.classList.remove("dragging");
      this._sig = null;
      this._render();
    });
    bar.addEventListener("keydown", (ev) => {
      const step = { ArrowRight: 5, ArrowUp: 5, ArrowLeft: -5, ArrowDown: -5, PageUp: 25, PageDown: -25 }[ev.key];
      const abs = { Home: 0, End: 100 }[ev.key];
      if (step === undefined && abs === undefined) return;
      ev.preventDefault();
      this._move(abs ?? Math.max(0, Math.min(100, (this._vals.bottom ?? 0) + step)));
    });
  }

  _setMode(mode) {
    this._mode = mode;
    this._els.rowButtons.hidden = mode !== "buttons";
    this._els.rowSlider.hidden = mode !== "slider";
    
  }

  _move(value) {
    this._preview(value);
    this._send("bottom", value);
  }

  _preview(value) {
    this._els.fill.style.width = `${value}%`;
    this._els.bar.setAttribute("aria-valuenow", String(value));
    this._els.state.textContent = this._stateText({ ...this._vals, bottom: value });
  }

  _stateText(v) {
    const g = this._groups || {};
    const b = v.bottom;
    let s = b === null || b === undefined ? "Unknown" : b <= 0 ? "Closed" : `Open · ${b}%`;
    if (g.middle && (v.middle ?? 0) > 0) s += ` · Top ${v.middle}%`;
    return s;
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this._built) this._build();
    const groups = this._collect();
    if (!groups) {
      this._els.name.innerHTML = `<span class="hd-missing">Not found: ${this._anchors.join(", ")}</span>`;
      return;
    }
    const vals = { bottom: this._value(groups.bottom), middle: this._value(groups.middle), vanes: this._value(groups.vanes) };
    const sig = JSON.stringify([vals, Object.keys(groups), this._config]);
    if (sig === this._sig) return;
    this._sig = sig;
    this._groups = groups;
    this._vals = vals;

    const open = (vals.bottom ?? 0) > 0 || (vals.middle ?? 0) > 0;
    this._els.name.textContent = this._title();
    this._els.icon.classList.toggle("on", open);
    this._els.iconEl.setAttribute("icon", this._config.icon || (open ? ICONS.open : ICONS.closed));

    const b = this._els.btn;
    b.up.disabled = (vals.bottom ?? 0) >= 100;
    b.down.disabled = vals.bottom !== null && vals.bottom <= 0;
    b.vanes.hidden = !(groups.vanes && this._config.show_vanes);
    const vanesOpen = (vals.vanes ?? 0) > 50;
    b.vanes.classList.toggle("on", vanesOpen);
    b.vanes.title = vanesOpen ? "Close vanes" : "Open vanes";
    b.vanes.querySelector("ha-icon").setAttribute("icon", vanesOpen ? ICONS.vanesOpen : ICONS.vanesClosed);
    b.top.hidden = !(groups.middle && this._config.show_top);
    b.top.classList.toggle("on", (vals.middle ?? 0) > 0);
    b.top.title = (vals.middle ?? 0) > 0 ? "Close top" : `Open top ${this._config.top_open}%`;

    if (!this._dragging) this._preview(vals.bottom ?? 0);
    this._els.state.textContent = this._stateText(vals);
  }
}

if (!customElements.get("hunterdouglas-platinum-card")) {
  customElements.define("hunterdouglas-platinum-card", HunterDouglasPlatinumCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hunterdouglas-platinum-card",
    name: "Hunter Douglas Platinum blind",
    description: "Compact blind card: up/down, drag-to-position, vanes toggle and top-down toggle.",
    preview: true,
    documentationURL: "https://github.com/walschots/hacs-hunterdouglas-platinum",
  });
  console.info(`%c HUNTERDOUGLAS-PLATINUM-CARD %c ${CARD_VERSION} `, "background:#0b6;color:#fff", "");
}
