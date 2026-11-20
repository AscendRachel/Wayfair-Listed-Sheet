// Pricing rules: the MAXAYA LLC sheet's price columns. The only shared setting is the flat 3PL fee (column K); the mark up %
// and promo % are typed per product in the catalog. A live "what would change" preview shows the effect of a new fee.
import { $, api, confirmBox, debounce, fmt, money, pctValue, priceFor, toast } from "./util.js";

export async function mount(el, params, ctx) {
  const admin = ctx.isAdmin();
  let draft = { fee: ctx.meta.pricing.fee };
  let impact = await api("/api/pricing/impact");
  const dirty = () => Number(draft.fee) !== Number(ctx.meta.pricing.fee);

  const impactText = () => dirty()
    ? `With a $${draft.fee} fee: <b>${fmt(impact.up)}</b> prices go up, <b>${fmt(impact.down)}</b> go down, ${fmt(impact.same)} stay the same${impact.none ? `, ${fmt(impact.none)} can't be priced` : ""}${impact.avg ? ` (average ${impact.avg > 0 ? "+" : ""}${money(impact.avg)} on changed ones)` : ""}.`
    : `This is the fee in use now, applied to ${fmt(impact.products)} products${impact.none ? ` (${fmt(impact.none)} can't be priced yet: no source link, source price or mark up %)` : ""}. Change it to see how many prices would change.`;

  const calc = () => {
    const s = $("#cs")?.value, mk = pctValue($("#cm")?.value), pp = pctValue($("#cp")?.value);
    const p = priceFor("link", s, mk, pp, draft);
    if (!$("#cout")) return;
    $("#cout").innerHTML = s === "" || mk === null ? `<span class="muted">Enter a source price and a mark up %.</span>`
      : `3PL fee <b>${money(p.fee)}</b> → source + fee ${money(p.cost)} → × (1 + ${+(mk * 100).toFixed(2)}%) = selling price <b>${money(p.selling)}</b>`
        + (p.promo != null ? ` → ÷ (1 − ${+(pp * 100).toFixed(2)}%) = promo price <b>${money(p.promo)}</b>` : "");
  };

  const draw = () => {
    el.innerHTML = `<div class="section-head"><div><h2>Pricing rules</h2><p>The same formulas as the MAXAYA LLC sheet. Saving a new fee recalculates every product.</p></div>
      ${admin ? `<div class="btnrow"><button class="btn" id="reset" ${dirty() ? "" : "disabled"}>Discard changes</button><button class="btn primary" id="save" ${dirty() ? "" : "disabled"}>Save pricing rules</button></div>` : ""}</div>
      ${admin ? "" : `<div class="banner">Only admins can change pricing rules.</div>`}
      <div class="two"><div>
        <div class="card" style="margin-bottom:16px"><div class="formgrid">
          <label class="field"><span>3PL fee ($ per product with a source link)</span><input type="number" step="0.01" min="0" id="fee" value="${draft.fee}" ${admin ? "" : "disabled"}></label></div>
          <div id="impact" class="banner ${dirty() ? "" : "good"}" style="margin:12px 0 0">${impactText()}</div></div>
        <div class="card"><h3>The formulas</h3><dl class="kv" style="margin-top:10px">
          <dt>3PL Fee</dt><dd>the fee above, when the row has a Source Link</dd>
          <dt>Source Price + 3PL Fee</dt><dd>Source Price + 3PL Fee</dd>
          <dt>Selling Price</dt><dd>(Source Price + 3PL Fee) × (1 + Mark Up Percentage)</dd>
          <dt>Promo Price</dt><dd>Selling Price ÷ (1 − PROMO PERCENTAGE), blank when there's no promo % (or it is 100%)</dd>
          <dt>Wayfair price check</dt><dd>the IMPORTED PRICE is compared with the Promo Price, or the Selling Price when there's no promo</dd></dl>
          <p class="hint" style="margin-top:10px">Mark Up Percentage and PROMO PERCENTAGE are typed per product in the catalog (48%, 48 or 0.48 all mean 48%).
          Any calculated cell can be typed over there, like typing over a formula in the sheet.</p></div></div>
      <div class="card"><h3>Try a price</h3><p class="hint" style="margin:6px 0 10px">Uses the fee as edited on this page, saved or not.</p>
        <div class="formgrid"><label class="field"><span>Source price ($)</span><input type="number" step="0.01" min="0" id="cs"></label>
          <label class="field"><span>Mark up %</span><input id="cm" placeholder="48%"></label>
          <label class="field"><span>Promo % (optional)</span><input id="cp" placeholder="20%"></label></div>
        <div id="cout" style="margin-top:12px"></div></div></div>`;
    calc();
  };

  const preview = debounce(async () => {
    try {
      impact = await api("/api/pricing/preview", { pricing: draft });
      $("#impact") && ($("#impact").innerHTML = impactText());
    } catch (e) {
      $("#impact") && ($("#impact").textContent = e.message);
    }
  }, 400);

  el.oninput = (e) => {
    const t = e.target;
    if (t.id === "fee") {
      draft.fee = t.value === "" ? "" : Number(t.value);
      $("#save") && ($("#save").disabled = $("#reset").disabled = !dirty());
      $("#impact") && ($("#impact").className = "banner" + (dirty() ? "" : " good"));
      preview();
    }
    calc();
  };
  el.onclick = async (e) => {
    const t = e.target;
    if (t.closest("#reset")) { draft = { fee: ctx.meta.pricing.fee }; impact = await api("/api/pricing/impact"); draw(); }
    if (t.closest("#save")) {
      if (!(await confirmBox("Save pricing rules?", `${impactText().replace(/<[^>]+>/g, "")} Every product's price is recalculated right away.`, "Save"))) return;
      try {
        await api("/api/pricing", { pricing: draft });
        await Promise.all([ctx.refreshMeta(), ctx.refreshCounts()]);
        draft = { fee: ctx.meta.pricing.fee };
        impact = await api("/api/pricing/impact");
        draw();
        toast("Pricing rules saved.");
      } catch (err) { toast(err.message, "bad"); }
    }
  };
  draw();
}
