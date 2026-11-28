// Small helpers shared by every view.

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

export const esc = (s) =>
  String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const fmt = (n) => (n ?? 0).toLocaleString();
export const num = (v) => {
  if (v === null || v === undefined || v === "") return NaN;
  const n = Number(v);
  return Number.isFinite(n) ? n : NaN;
};
export const money = (v) => (Number.isNaN(num(v)) ? "—" : "$" + num(v).toFixed(2));
export const pct = (v) => (Number.isNaN(num(v)) ? "—" : (num(v) * 100).toFixed(0) + "%");
export const debounce = (fn, ms = 250) => {
  let t;
  return (...a) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...a), ms);
  };
};

// The server writes its times without a time zone, in ITS OWN local time (a Philippine browser must not read them as its
// own, or every "ago" is wrong by the difference between the two). The server says how far its clock is from UTC.
let serverOffsetMin = null;
export const setServerOffset = (min) => { serverOffsetMin = Number.isFinite(min) ? min : null; };

export function ago(ts) {
  if (!ts) return "—";
  const iso = String(ts).replace(" ", "T");
  const d = serverOffsetMin === null ? new Date(iso) : new Date(Date.parse(iso + "Z") - serverOffsetMin * 60000);
  if (Number.isNaN(d.getTime())) return ts;
  const s = Math.max(0, (Date.now() - d) / 1000);
  if (s < 90) return "just now";
  if (s < 5400) return Math.round(s / 60) + " min ago";
  if (s < 129600) return Math.round(s / 3600) + " h ago";
  return Math.round(s / 86400) + " days ago";
}

// ---- storage that never throws (private windows, blocked storage)
export const store = {
  get(k, fallback = "") {
    try {
      return localStorage.getItem(k) ?? fallback;
    } catch {
      return fallback;
    }
  },
  set(k, v) {
    try {
      localStorage.setItem(k, v);
    } catch {}
  },
};

// ---- API
export class ApiError extends Error {}
export async function api(path, body, opts = {}) {
  const init = { headers: {} };
  if (body !== undefined) {
    init.method = "POST";
    if (body instanceof ArrayBuffer || body instanceof Blob) {
      init.body = body;
      init.headers = { ...opts.headers };
    } else {
      init.body = JSON.stringify(body);
      init.headers["Content-Type"] = "application/json";
    }
  }
  const r = await fetch(path, init);
  if (r.status === 401) {
    location.href = "/login";
    throw new ApiError("Please sign in.");
  }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new ApiError(j.error || `Error ${r.status}${r.status === 404 ? " (" + String(path).split("?")[0] + " was not found on the server. If you just updated, restart the server)" : ""}`);
  return j;
}
export const qs = (o) =>
  new URLSearchParams(Object.entries(o).filter(([, v]) => v !== "" && v !== undefined && v !== null)).toString();

// ---- toast
let toastTimer;
export function toast(msg, kind = "") {
  const root = $("#toasts");
  root.innerHTML = `<div class="toast ${kind}" role="status">${esc(msg)}</div>`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (root.innerHTML = ""), kind === "bad" ? 6000 : 3000);
}

// ---- modal dialog: returns a promise resolved with the button value
export function dialog({ title, body, actions = [["Close", "close"]], wide = false }) {
  return new Promise((resolve) => {
    const dlg = document.createElement("dialog");
    dlg.className = "modal" + (wide ? " wide" : "");
    dlg.innerHTML = `<form method="dialog"><h3>${esc(title)}</h3><div class="modal-body">${body}</div>
      <div class="btnrow end">${actions
        .map(([label, value, cls]) => `<button class="btn ${cls || ""}" value="${esc(value)}" ${value === "close" ? "formnovalidate" : ""}>${esc(label)}</button>`)
        .join("")}</div></form>`;
    dlg.addEventListener("close", () => {
      const result = { value: dlg.returnValue, el: dlg };
      resolve(result);
      setTimeout(() => dlg.remove(), 0);
    });
    document.body.append(dlg);
    dlg.showModal();
    dlg.querySelector("input,select,textarea")?.focus();
  });
}
export async function confirmBox(title, text, yes = "Yes") {
  const r = await dialog({ title, body: `<p>${esc(text)}</p>`, actions: [["Cancel", "close"], [yes, "yes", "primary"]] });
  return r.value === "yes";
}

export function download(href) {
  const a = document.createElement("a");
  a.href = href;
  a.click();
}

// ---- status vocabulary (colors come from CSS classes)
export const STATUS = {
  "Out of Stock": { cls: "crit", desc: "Inventory is on but Amazon shows currently unavailable or temporarily out of stock." },
  "OOS Different Item": { cls: "crit", desc: "The Amazon listing changed to a different item (pack count or size no longer matches). Set it out of stock." },
  "OOS Variation": { cls: "crit", desc: "The variation Amazon shows isn't the one in the catalog's VARIATION column." },
  "High Price": { cls: "crit", desc: "Amazon price is now above your source price. Margin is shrinking." },
  "Low Inventory": { cls: "warn", desc: "Amazon shows “Only X left in stock”." },
  TimeFrame: { cls: "warn", desc: "Earliest delivery is further out than the allowed days." },
  "Low Price": { cls: "info", desc: "Amazon price dropped below your source price." },
  "Manual Check": { cls: "neutral", desc: "The scraper couldn't read availability or open the page, or the Amazon title doesn't look like the product." },
  "Check Inventory": { cls: "violet", desc: "Listed, inventory off, and Amazon looks available. Ticking Inventory would be clean: no Time Frame, OOS Variation or OOS Different Item." },
  Normal: { cls: "ok", desc: "No issues from the last check." },
  "Not checked": { cls: "neutral", desc: "No Amazon check yet." },
};
export const QUEUE_UI = {
  "listing-changed": { cls: "crit", desc: "The Amazon title now states a different pack count or size than the catalog. The listing really changed." },
  "title-mismatch": { cls: "warn", desc: "Too few of the product's key words are in Amazon's title (rewording is ignored). Worth a look." },
  "mz-missing": { cls: "warn", desc: "Listed in the catalog but missing from the latest Wayfair download." },
  "mz-stock-off": { cls: "crit", desc: "Wayfair quantity above 0 while your inventory flag is off." },
  "mz-zero-on": { cls: "warn", desc: "Wayfair quantity is 0 while your inventory flag is on." },
  "mz-price": { cls: "info", desc: "Inventory is on, but the imported Wayfair price isn't the promo price (or the selling price when there is no promo)." },
  "dq-markup": { cls: "neutral", desc: "No Mark Up Percentage means no Selling Price and no Promo Price." },
  "dq-spn": { cls: "neutral", desc: "SPN is blank, so the Wayfair inventory and price can't be matched." },
  "dq-listing": { cls: "neutral", desc: "Status (Live, Not Live, Not Listed ...) is blank." },
  "dq-link": { cls: "neutral", desc: "Can't be scraped until a source link is added." },
};
export const pill = (status) =>
  `<span class="pill s-${(STATUS[status] || STATUS["Not checked"]).cls}">${esc(status || "Not checked")}</span>`;

// ---- same pricing formula as the server (used for live previews while typing): the MAXAYA LLC sheet's K, L, N, P
// 48%, 48 and 0.48 all mean 0.48 (above 5 is read as whole percent); null when blank or not a number
export function pctValue(raw) {
  const t = String(raw ?? "").trim();
  if (t === "") return null;
  const n = Number(t.replace(/[%,\s]/g, ""));
  if (Number.isNaN(n)) return null;
  return t.includes("%") || Math.abs(n) > 5 ? n / 100 : n;
}
export function priceFor(link, source, markup, promoPct, pr) {
  const fee = String(link ?? "").trim() ? num(pr.fee) : null;
  const s = num(source);
  const cost = fee === null || source === "" || source == null || Number.isNaN(s) ? null : s + fee;
  const mk = markup === "" || markup == null ? null : num(markup);
  const selling = cost === null || mk === null || Number.isNaN(mk) ? null : cost * (1 + mk);
  const pp = promoPct === "" || promoPct == null ? null : num(promoPct);
  const promo = selling === null || pp === null || Number.isNaN(pp) || pp === 1 ? null : selling / (1 - pp);
  const auto = promo ?? selling;
  return { fee, cost, selling, promo, auto: auto === null ? null : Math.round(auto * 100) / 100 };
}
