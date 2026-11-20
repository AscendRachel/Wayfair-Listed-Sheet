// Inventory Data: the Wayfair All Inventory Export (one row per warehouse), checked like the sheet's INVENTORY DATA tab.
// Every warehouse of a product must show the same Retail Price, and the stock must agree: 0 everywhere, or stock everywhere.
// Like the catalog, every row is in one scrolling list (only the rows on screen are drawn, so 16,000 rows stay fast).
import { $, ago, api, debounce, download, esc, fmt, qs, toast } from "./util.js";

const NUM = new Set(["in_stock", "available", "bis_qty", "orders90", "price"]);
const WIDTH = { part: 140, mplid: 105, warehouse: 245, wh_type: 105, in_stock: 80, available: 85, bis_qty: 105, bis_date: 125,
  orders90: 95, stock_update: 195, price: 95, priority: 80 };
const ROW_H = 34;
const n = (v) => { const x = parseFloat(String(v ?? "").replace(/[$,]/g, "")); return Number.isFinite(x) ? x : 0; };
const priceKey = (v) => { const s = String(v ?? "").replace(/[$,]/g, "").trim(); const x = parseFloat(s); return Number.isFinite(x) ? x.toFixed(2) : s; };

// Which cells of a mismatched product are the odd ones out: prices that differ from the most common one,
// and the warehouses with 0 stock while another has some.
function oddCells(g) {
  const odd = new Set();
  if (g.chk !== "MISMATCH") return odd;
  const tally = {};
  g.rows.forEach((r) => (tally[priceKey(r.price)] = (tally[priceKey(r.price)] || 0) + 1));
  const keys = Object.keys(tally);
  if (keys.length > 1) {
    const common = keys.sort((a, b) => tally[b] - tally[a])[0];
    g.rows.forEach((r, i) => { if (priceKey(r.price) !== common || tally[common] === tally[keys[1]]) odd.add(`${i}:price`); });
  }
  const zero = g.rows.map((r) => n(r.in_stock) === 0);
  if (zero.some(Boolean) && !zero.every(Boolean)) g.rows.forEach((r, i) => { if (zero[i]) odd.add(`${i}:in_stock`); });
  return odd;
}

export async function mount(el, params, ctx) {
  const admin = ctx.isAdmin();
  const f = { show: params.get("show") || "all", q: params.get("q") || "" };
  let data = null, flat = [], drawn = "";
  let hits = [], hitSet = new Set(), cur = -1;          // Ctrl+F: [row, column] of each match, and the one shown

  const head = () => {
    const i = data?.info, c = data?.counts || {};
    return `<div class="section-head"><div><h2>Inventory Data</h2><p>The Wayfair <b>All Inventory Export</b>, one row per product per warehouse. Like column M of the INVENTORY DATA sheet, each product's warehouses must have the same <b>Retail Price</b>
        and agreeing <b>In Stock</b> (0 must be 0 everywhere; above 0 can differ as long as every warehouse has stock). A <b>⚠️ MISMATCH</b> is what to correct on the marketplace.
        Uploading also fills the catalog's IMPORTED INVENTORY and IMPORTED PRICE from each product's first warehouse row.${i ? ` <span class="hint">Current file: ${esc(i.filename)}, uploaded by ${esc(i.user)} ${esc(ago(i.at))}.</span>` : ""}</p></div>
      <div class="btnrow">${admin ? `<label class="btn primary" style="cursor:pointer">⬆ Upload inventory export<input type="file" id="ifile" accept=".csv,.tsv,.txt,.xlsx,.xlsm" hidden></label>` : ""}
        <button class="btn" id="exp" ${c.mismatch ? "" : "disabled"}>Export ${fmt(c.mismatch || 0)} mismatches (CSV)</button></div></div>
      <div id="ibusy"></div>
      ${i ? `<div class="qgrid" style="margin-bottom:12px">
        <button class="qcard ${f.show === "all" ? "" : "zero"}" data-show="all"><span class="qn">${fmt(c.products)}</span><span class="ql">Products (${fmt(i.rows)} warehouse rows)</span></button>
        <button class="qcard ${c.mismatch ? "warn" : "zero"}" data-show="mismatch"><span class="qn">${fmt(c.mismatch)}</span><span class="ql">⚠️ Mismatch</span></button>
        <button class="qcard ok" data-show="ok"><span class="qn">${fmt(c.ok)}</span><span class="ql">✅ OK</span></button>
        ${c.not_in_catalog ? `<div class="qcard zero"><span class="qn">${fmt(c.not_in_catalog)}</span><span class="ql">MPLID not in the catalog</span></div>` : ""}</div>` : ""}`;
  };

  // One table row. Like the sheet, the check sits on the product's first warehouse row only.
  const rowHtml = (k) => {
    const { g, i, odd } = flat[k], r = g.rows[i], bad = g.chk === "MISMATCH";
    const mark = (ck) => (hitSet.has(`${k}:${ck}`) ? ` inv-hit${hits[cur]?.[0] === k && hits[cur]?.[1] === ck ? " inv-cur" : ""}` : "");
    const cells = data.columns.map((c) => {
      let v = esc(r[c.k] ?? "");
      if (c.k === "mplid" && i === 0 && g.cat_sku) v = `<a href="#catalog?q=${encodeURIComponent(g.cat_sku)}" title="Open in the catalog">${v}</a>`;
      return `<td class="${NUM.has(c.k) ? "num" : ""} ${c.k === "part" || c.k === "mplid" ? "mono" : ""} ${odd.has(`${i}:${c.k}`) ? "inv-odd" : ""}${mark(c.k)}" title="${esc(r[c.k] ?? "")}">${v}</td>`;
    }).join("");
    const chk = i > 0 ? "" : g.chk === "MISMATCH" ? `<span class="pill s-crit">⚠️ MISMATCH</span> <span class="inv-why">${esc(g.why)}</span>` : g.chk === "OK" ? `<span class="pill s-ok">✅ OK</span>` : `<span class="muted">${esc(g.why)}</span>`;
    const name = i > 0 ? "" : g.cat_sku ? esc(g.name || g.cat_sku) : `<span class="muted">Not in the catalog</span>`;
    return `<tr class="${i === 0 ? "inv-first" : ""} ${bad ? "inv-bad" : ""}">${cells}<td class="${mark("chk")}" title="${esc(i === 0 ? g.why || "" : "")}">${chk}</td><td class="${mark("name")}" title="${esc(i === 0 ? g.name || "" : "")}">${name}</td></tr>`;
  };

  // Only the rows in view (plus a margin) are in the page; spacer rows keep the scrollbar the full length.
  const paint = (force) => {
    const wrap = $("#iwrap"), body = $("#ibody");
    if (!wrap || !body) return;
    const ncol = data.columns.length + 2;
    if (!flat.length) { body.innerHTML = `<tr><td colspan="${ncol}" class="empty">${data.info ? "Nothing matches." : "No inventory export uploaded yet."}</td></tr>`; return; }
    const from = Math.max(0, Math.floor(wrap.scrollTop / ROW_H) - 20);
    const to = Math.min(flat.length, Math.ceil((wrap.scrollTop + wrap.clientHeight) / ROW_H) + 20);
    const key = `${from}:${to}`;
    if (!force && key === drawn) return;
    drawn = key;
    let html = `<tr class="spacer" style="height:${from * ROW_H}px"><td colspan="${ncol}"></td></tr>`;
    for (let k = from; k < to; k++) html += rowHtml(k);
    html += `<tr class="spacer" style="height:${(flat.length - to) * ROW_H}px"><td colspan="${ncol}"></td></tr>`;
    body.innerHTML = html;
  };

  const fit = () => {
    const wrap = $("#iwrap");
    if (wrap) wrap.style.height = Math.max(360, innerHeight - wrap.getBoundingClientRect().top - 16) + "px";
  };

  const load = async () => {
    data = await api("/api/inventory?" + qs({ ...f, page: 0 }));
    flat = [];
    for (const g of data.groups) {
      const odd = oddCells(g);
      g.rows.forEach((_, i) => flat.push({ g, i, odd }));
    }
    $("#ihead").innerHTML = head();
    $("#icount").textContent = `${fmt(data.total)} products · ${fmt(flat.length)} rows`;
    $("#ihrow").innerHTML = data.columns.map((c) => `<th class="${NUM.has(c.k) ? "num" : ""}">${esc(c.l)}</th>`).join("") + "<th>Check</th><th>Catalog product</th>";
    $("#icols").innerHTML = data.columns.map((c) => `<col style="width:${WIDTH[c.k] || 110}px">`).join("") + `<col style="width:330px"><col style="width:380px">`;
    $("#iwrap").scrollTop = 0;
    hits = []; hitSet = new Set(); cur = -1;
    if (!$("#ifind").classList.contains("hidden") && $("#ifindq").value.trim()) findRun(0);
    fit();
    paint(true);
  };

  // Ctrl+F, like the sheet: marks every cell holding the text and jumps to them one by one (the search box still filters).
  const findText = (k, ck) => {
    const { g, i } = flat[k];
    if (ck === "chk") return i ? "" : g.chk === "MISMATCH" ? `⚠️ MISMATCH ${g.why || ""}` : g.chk === "OK" ? "✅ OK" : g.why || "";
    if (ck === "name") return i ? "" : g.cat_sku ? g.name || g.cat_sku : "Not in the catalog";
    return String(g.rows[i][ck] ?? "");
  };
  const findRun = (step) => {
    const q = $("#ifindq").value.trim().toLowerCase(), keys = [...data.columns.map((c) => c.k), "chk", "name"];
    hits = [];
    if (q) for (let k = 0; k < flat.length; k++) keys.forEach((ck) => { if (findText(k, ck).toLowerCase().includes(q)) hits.push([k, ck]); });
    hitSet = new Set(hits.map(([k, ck]) => `${k}:${ck}`));
    if (!hits.length) { cur = -1; $("#ifindn").textContent = q ? "No results" : ""; return paint(true); }
    const prev = cur >= 0 && cur < hits.length ? cur : -1;
    cur = step === 0 ? Math.max(0, prev) : ((prev < 0 ? (step > 0 ? -1 : 0) : prev) + step + hits.length) % hits.length;
    $("#ifindn").textContent = `${fmt(cur + 1)} of ${fmt(hits.length)}`;
    const wrap = $("#iwrap"), k = hits[cur][0], top = k * ROW_H, head = wrap.querySelector("thead").offsetHeight;
    if (top < wrap.scrollTop || top + ROW_H > wrap.scrollTop + wrap.clientHeight - head) wrap.scrollTop = Math.max(0, top - (wrap.clientHeight - head) / 2);
    paint(true);
    const cell = wrap.querySelector("td.inv-cur");                // bring the column into view too
    if (cell) { const l = cell.offsetLeft, w = cell.offsetWidth; if (l < wrap.scrollLeft || l + w > wrap.scrollLeft + wrap.clientWidth) wrap.scrollLeft = Math.max(0, l - 40); }
  };
  const findOpen = () => {
    const bar = $("#ifind"), inp = $("#ifindq");
    bar.style.top = (document.querySelector("header.top")?.getBoundingClientRect().bottom ?? 0) + 10 + "px";   // under the top bar, at the right, like a browser find box
    bar.style.right = "24px";
    bar.classList.remove("hidden");
    inp.focus();
    inp.select();
  };
  const findClose = () => { $("#ifind").classList.add("hidden"); hits = []; hitSet = new Set(); cur = -1; paint(true); };
  const onKey = (e) => {
    if (!el.isConnected || !$("#iwrap")) return removeEventListener("keydown", onKey, true);
    if ((e.ctrlKey || e.metaKey) && !e.altKey && e.key.toLowerCase() === "f" && !document.querySelector("dialog[open]")) { e.preventDefault(); findOpen(); }
  };
  addEventListener("keydown", onKey, true);

  el.innerHTML = `<div class="invpage"><div id="ihead"></div>
    <div class="findbar hidden" id="ifind" role="search"><span class="fbin"><input id="ifindq" type="text" placeholder="Find in all rows" aria-label="Find in all rows" autocomplete="off" spellcheck="false"><span class="fbn" id="ifindn"></span></span>
      <button class="fbb" id="ifprev" title="Previous (Shift+Enter)" aria-label="Previous match">↑</button><button class="fbb" id="ifnext" title="Next (Enter)" aria-label="Next match">↓</button><button class="fbb" id="ifclose" title="Close (Esc)" aria-label="Close find">✕</button></div>
    <div class="panel"><div class="toolbar"><input class="grow" id="iq" type="search" placeholder="Search Part Number, MPLID, warehouse or product name" value="${esc(f.q)}">
      <select id="ishow" aria-label="Show"><option value="all">All products</option><option value="mismatch">⚠️ Mismatch only</option><option value="ok">✅ OK only</option></select>
      <span class="muted" id="icount"></span></div>
      <div class="tablewrap inv-wrap" id="iwrap"><table class="inv"><colgroup id="icols"></colgroup><thead><tr id="ihrow"></tr></thead><tbody id="ibody"><tr><td class="empty">Loading…</td></tr></tbody></table></div></div></div>`;
  $("#ishow").value = f.show;
  $("#iwrap").addEventListener("scroll", () => paint(), { passive: true });
  const onResize = () => { if (!el.isConnected || !$("#iwrap")) return removeEventListener("resize", onResize); fit(); paint(); };
  addEventListener("resize", onResize);

  el.oninput = debounce((e) => { if (e.target.id === "iq") { f.q = e.target.value; load(); } if (e.target.id === "ifindq") { cur = -1; findRun(0); } }, 250);
  $("#ifindq").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); findRun(e.shiftKey ? -1 : 1); }
    if (e.key === "Escape") { e.preventDefault(); findClose(); }
  });
  el.onchange = async (e) => {
    if (e.target.id === "ishow") { f.show = e.target.value; load(); }
    if (e.target.id === "ifile" && e.target.files[0]) {
      const file = e.target.files[0];
      $("#ibusy").innerHTML = `<div class="banner" style="margin-bottom:12px"><b>Reading ${esc(file.name)}…</b></div>`;
      try {
        const r = await api("/api/inventory/import", await file.arrayBuffer(), { headers: { "X-Filename": encodeURIComponent(file.name) } });
        toast(`Imported ${fmt(r.products)} products (${fmt(r.rows)} warehouse rows): ${fmt(r.mismatch)} mismatched. ${fmt(r.catalog_filled)} catalog products got their imported inventory and price.`);
        ctx.refreshCounts?.();
        await load();
      } catch (err) {
        toast(err.message, "bad");
        $("#ibusy").innerHTML = "";
      }
    }
  };
  el.onclick = (e) => {
    if (e.target.closest("#ifnext")) return findRun(1);
    if (e.target.closest("#ifprev")) return findRun(-1);
    if (e.target.closest("#ifclose")) return findClose();
    const s = e.target.closest("[data-show]");
    if (s) { f.show = s.dataset.show; $("#ishow").value = f.show; return load(); }
    if (e.target.closest("#exp")) download("/api/export/inventory.csv?" + qs({ show: "mismatch", q: f.q }));
  };
  await load();
}
