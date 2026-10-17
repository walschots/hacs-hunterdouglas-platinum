/*
 * Hunter Douglas Platinum card — modelled on the Platinum App.
 * Vertical sliders side by side: Bottom rail, Middle rail and Vanes (whichever
 * the blind has). The slider moves the way the rail moves, and the labels at
 * each end are quick buttons.
 *
 * One blind:
 *   type: custom:hunterdouglas-platinum-card
 *   entity: cover.mbr_bottom_rail        # any of the blind's covers
 *   name: MBR                             # optional
 *
 * A whole room (moves every listed blind together, like "Operate all shades in this room"):
 *   type: custom:hunterdouglas-platinum-card
 *   name: MBR
 *   entities:
 *     - cover.mbr_left_bottom_rail
 *     - cover.mbr_right_bottom_rail
 *
 * Optional: slider_height (px, default 170).
 * Served and loaded automatically by the hunterdouglas_platinum integration.
 */
const CARD_VERSION = "0.4.1";

// How each control is drawn. topValue = the value at the top of the slider.
const ROLES = [
  { role: "bottom", label: "Bottom Rail", top: "Open", bottom: "Close", topValue: 100 },
  { role: "middle", label: "Middle Rail", top: "Close", bottom: "Open", topValue: 0 },
  { role: "vanes", label: "Vanes", top: "Open", bottom: "Close", topValue: 100 },
];

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
        { name: "slider_height", selector: { number: { min: 100, max: 400, step: 10, unit_of_measurement: "px" } } },
      ],
      computeLabel: (s) =>
        ({
          entity: "Blind",
          entities: "…or several blinds (whole room)",
          name: "Name (optional)",
          slider_height: "Slider height",
        })[s.name],
    };
  }

  setConfig(config) {
    const list = [].concat(config.entities || [], config.entity ? [config.entity] : []);
    if (!list.length) throw new Error("Pick a blind (entity) or a list of blinds (entities)");
    this._config = { slider_height: 170, ...config };
    this._anchors = [...new Set(list.map((e) => (typeof e === "string" ? e : e.entity)))];
    this._built = false;
    if (this._hass) this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() {
    return Math.ceil((this._config ? this._config.slider_height : 170) / 50) + 2;
  }

  getGridOptions() {
    return { columns: 6, min_columns: 4, rows: this.getCardSize() };
  }

  /* ---------- data ---------- */

  _deviceOf(id) {
    const e = this._hass.entities && this._hass.entities[id];
    return e && e.device_id;
  }

  // All covers belonging to the same blind as `anchorId`, keyed by role.
  _blind(anchorId) {
    const states = this._hass.states;
    const anchor = states[anchorId];
    if (!anchor) return null;
    const a = anchor.attributes;
    if (a.shade_id === undefined || !a.platinum_role) return { bottom: anchor }; // not one of ours
    const device = this._deviceOf(anchorId);
    const parts = {};
    for (const s of Object.values(states)) {
      if (!s.entity_id.startsWith("cover.") || s.attributes.shade_id !== a.shade_id) continue;
      const d = this._deviceOf(s.entity_id);
      if (device && d && d !== device) continue;
      const role = s.attributes.platinum_role;
      if (ROLES.some((r) => r.role === role)) parts[role] = s;
    }
    if (!parts.vanes && parts.bottom && typeof parts.bottom.attributes.current_tilt_position === "number") {
      parts.vanes = { ...parts.bottom, _tilt: true };
    }
    return parts;
  }

  _collect() {
    const groups = {}; // role -> [state]
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
    const vals = states
      .map((s) => (s._tilt ? s.attributes.current_tilt_position : s.attributes.current_position))
      .filter((v) => typeof v === "number");
    if (!vals.length) return null;
    return Math.round(vals.reduce((a, b) => a + b, 0) / vals.length);
  }

  _title() {
    if (this._config.name) return this._config.name;
    if (this._anchors.length > 1) return "All shades";
    const dev = this._deviceOf(this._anchors[0]);
    const d = dev && this._hass.devices && this._hass.devices[dev];
    if (d) return d.name_by_user || d.name;
    const s = this._hass.states[this._anchors[0]];
    return ((s && s.attributes.friendly_name) || "").replace(/\s*(Bottom rail|Middle rail|Vanes)$/i, "");
  }

  _send(role, value) {
    const states = (this._groups && this._groups[role]) || [];
    const tilt = states.filter((s) => s._tilt).map((s) => s.entity_id);
    const pos = states.filter((s) => !s._tilt).map((s) => s.entity_id);
    if (pos.length) this._hass.callService("cover", "set_cover_position", { entity_id: pos, position: value });
    if (tilt.length)
      this._hass.callService("cover", "set_cover_tilt_position", { entity_id: tilt, tilt_position: value });
  }

  /* ---------- rendering ---------- */

  _build() {
    this.innerHTML = "";
    const card = document.createElement("ha-card");
    const h = this._config.slider_height;
    card.innerHTML = `
      <style>
        .hd { padding: 12px 12px 14px; }
        .hd-head { display: flex; align-items: center; gap: 8px; padding: 2px 4px 10px; }
        .hd-title { flex: 1; min-width: 0; font-size: 16px; font-weight: 500; color: var(--primary-text-color);
                    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; }
        .hd-all { display: flex; gap: 6px; }
        .hd-all button, .hd-end {
          font: inherit; font-size: 13px; color: var(--primary-text-color); background: transparent; cursor: pointer;
          border: 1px solid var(--divider-color, rgba(127,127,127,.3)); border-radius: 16px; padding: 5px 12px;
        }
        .hd-all button:hover, .hd-end:hover { background: var(--secondary-background-color, rgba(127,127,127,.1)); }
        .hd-cols { display: flex; justify-content: space-evenly; gap: 4px; }
        .hd-col { display: flex; flex-direction: column; align-items: center; gap: 6px; flex: 1 1 0; min-width: 0; max-width: 140px; }
        .hd-col[hidden] { display: none; }
        .hd-end { width: 100%; max-width: 92px; padding: 5px 4px; }
        .hd-slider { position: relative; width: 56px; height: ${h + 28}px; touch-action: none; cursor: pointer; outline: none; }
        .hd-rail { position: absolute; left: 0; right: 0; top: 14px; bottom: 14px; }
        .hd-track { position: absolute; left: 50%; top: 0; bottom: 0; width: 4px; margin-left: -2px; border-radius: 2px;
                    background: var(--divider-color, rgba(127,127,127,.35)); }
        .hd-fill { position: absolute; left: 50%; width: 4px; margin-left: -2px; border-radius: 2px; background: var(--primary-color); }
        .hd-ticks { position: absolute; left: 0; top: 0; bottom: 0; width: 18px; }
        .hd-ticks i { position: absolute; left: 0; height: 1.5px; background: var(--secondary-text-color); opacity: .55; }
        .hd-thumb { position: absolute; left: 50%; width: 28px; height: 28px; margin: -14px 0 0 -14px; border-radius: 50%;
                    background: #fff; box-shadow: 0 1px 4px rgba(0,0,0,.35); transition: top .15s ease; }
        .hd-slider.dragging .hd-thumb { transition: none; }
        .hd-slider:focus-visible .hd-thumb { box-shadow: 0 0 0 3px var(--primary-color); }
        .hd-label { font-size: 13px; color: var(--primary-text-color); text-align: center; line-height: 1.2; }
        .hd-val { font-size: 12px; color: var(--secondary-text-color); font-variant-numeric: tabular-nums; }
        .hd-missing { color: var(--error-color, #db4437); font-size: 13px; padding: 8px 4px; }
      </style>
      <div class="hd">
        <div class="hd-head">
          <div class="hd-title"></div>
          <div class="hd-all"><button data-all="open">Open</button><button data-all="close">Close</button></div>
        </div>
        <div class="hd-cols">
          ${ROLES.map(
            (r) => `
            <div class="hd-col" data-role="${r.role}">
              <button class="hd-end" data-end="top">${r.top}</button>
              <div class="hd-slider" role="slider" tabindex="0" aria-label="${r.label}" aria-valuemin="0" aria-valuemax="100"><div class="hd-rail">
                <div class="hd-ticks">${[0, 25, 50, 75, 100]
                  .map((t) => `<i style="top:${t}%;width:${t % 50 ? 10 : 18}px"></i>`)
                  .join("")}</div>
                <div class="hd-track"></div><div class="hd-fill"></div><div class="hd-thumb"></div>
              </div></div>
              <button class="hd-end" data-end="bottom">${r.bottom}</button>
              <div class="hd-label">${r.label}</div>
              <div class="hd-val"></div>
            </div>`
          ).join("")}
        </div>
      </div>`;
    this.appendChild(card);
    this._els = { title: card.querySelector(".hd-title"), cols: {} };
    for (const r of ROLES) {
      const col = card.querySelector(`.hd-col[data-role=${r.role}]`);
      const el = {
        col,
        slider: col.querySelector(".hd-slider"),
        rail: col.querySelector(".hd-rail"),
        fill: col.querySelector(".hd-fill"),
        thumb: col.querySelector(".hd-thumb"),
        val: col.querySelector(".hd-val"),
      };
      this._els.cols[r.role] = el;
      this._wireSlider(r, el);
      col.querySelector('[data-end="top"]').addEventListener("click", () => this._commit(r, r.topValue));
      col.querySelector('[data-end="bottom"]').addEventListener("click", () => this._commit(r, 100 - r.topValue));
    }
    card.querySelector('[data-all="open"]').addEventListener("click", () => {
      this._commit(ROLES[0], 100);
      if (this._groups.middle) this._commit(ROLES[1], 0);
    });
    card.querySelector('[data-all="close"]').addEventListener("click", () => {
      this._commit(ROLES[0], 0);
      if (this._groups.middle) this._commit(ROLES[1], 0);
    });
    this._els.title.addEventListener("click", () => {
      const ev = new Event("hass-more-info", { bubbles: true, composed: true });
      ev.detail = { entityId: this._anchors[0] };
      this.dispatchEvent(ev);
    });
    this._dragging = null;
    this._shown = {};
    this._built = true;
  }

  _wireSlider(r, el) {
    const fromEvent = (ev) => {
      const rect = el.rail.getBoundingClientRect();
      const frac = Math.min(1, Math.max(0, (ev.clientY - rect.top) / rect.height)); // 0 = top
      return Math.round(r.topValue === 100 ? 100 - frac * 100 : frac * 100);
    };
    el.slider.addEventListener("pointerdown", (ev) => {
      ev.preventDefault();
      el.slider.setPointerCapture(ev.pointerId);
      this._dragging = r.role;
      el.slider.classList.add("dragging");
      this._paint(r, fromEvent(ev));
    });
    el.slider.addEventListener("pointermove", (ev) => {
      if (this._dragging === r.role) this._paint(r, fromEvent(ev));
    });
    const end = (ev) => {
      if (this._dragging !== r.role) return;
      this._dragging = null;
      el.slider.classList.remove("dragging");
      this._commit(r, fromEvent(ev));
    };
    el.slider.addEventListener("pointerup", end);
    el.slider.addEventListener("pointercancel", () => {
      this._dragging = null;
      el.slider.classList.remove("dragging");
      this._sig = null;
      this._render();
    });
    el.slider.addEventListener("keydown", (ev) => {
      const cur = this._shown[r.role] ?? 0;
      const up = r.topValue === 100 ? 1 : -1; // "up" key moves the thumb up
      const step = { ArrowUp: 5 * up, ArrowRight: 5 * up, ArrowDown: -5 * up, ArrowLeft: -5 * up, PageUp: 25 * up, PageDown: -25 * up }[ev.key];
      let v = step !== undefined ? cur + step : { Home: r.topValue, End: 100 - r.topValue }[ev.key];
      if (v === undefined) return;
      ev.preventDefault();
      this._commit(r, Math.max(0, Math.min(100, v)));
    });
  }

  _commit(r, value) {
    this._paint(r, value);
    this._send(r.role, value);
  }

  _paint(r, value) {
    this._shown = { ...this._shown, [r.role]: value };
    const el = this._els.cols[r.role];
    const v = value === null || value === undefined ? 0 : value;
    const topFrac = r.topValue === 100 ? 1 - v / 100 : v / 100; // thumb position from the top
    el.thumb.style.top = `${topFrac * 100}%`;
    // Blue runs from the "Close" end of the slider to the thumb (like the Platinum App).
    if (r.topValue === 100) {
      el.fill.style.top = `${topFrac * 100}%`;
      el.fill.style.bottom = "0";
    } else {
      el.fill.style.top = "0";
      el.fill.style.bottom = `${(1 - topFrac) * 100}%`;
    }
    el.slider.setAttribute("aria-valuenow", String(v));
    el.val.textContent = value === null || value === undefined ? "–" : `${v}%`;
  }

  _render() {
    if (!this._config || !this._hass) return;
    if (!this._built) this._build();
    const groups = this._collect();
    if (!groups) {
      this._els.title.innerHTML = `<span class="hd-missing">Not found: ${this._anchors.join(", ")}</span>`;
      return;
    }
    const sig = JSON.stringify(
      ROLES.map((r) => [r.role, (groups[r.role] || []).map((s) => s.entity_id), this._value(groups[r.role] || [])])
    );
    if (sig === this._sig) return;
    this._sig = sig;
    this._groups = groups;
    this._els.title.textContent = this._title();
    for (const r of ROLES) {
      const has = !!groups[r.role];
      this._els.cols[r.role].col.hidden = !has;
      if (has && this._dragging !== r.role) this._paint(r, this._value(groups[r.role]));
    }
  }
}

customElements.define("hunterdouglas-platinum-card", HunterDouglasPlatinumCard);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "hunterdouglas-platinum-card",
  name: "Hunter Douglas Platinum blind",
  description: "Platinum App-style sliders for the bottom rail, middle rail and vanes of a blind or a whole room.",
  preview: true,
});
console.info(`%c HUNTERDOUGLAS-PLATINUM-CARD %c ${CARD_VERSION} `, "background:#0b6;color:#fff", "");
