/* The page. No framework: the surface is small enough that one would cost more than it saves,
   and a build step would put a toolchain between a developer and a tool meant to be run. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { groups: [], overrides: {}, defaults: {}, job: null, timer: null,
                results: { size: null, plan: null }, projects: [], projectName: "",
                sites: [], site: null, arch: null, lang: "en" };

/* ------------------------------------------------------------------ language
   Every sentence on this page comes from the catalogue the server hands over at boot. The
   page holds no English and no French of its own, so adding a language is a matter of
   translating one file rather than of finding the strings scattered through this one.

   A key that is missing renders as itself. That is deliberate: a visible "f.tariff.hint"
   is a bug report, where a blank space would be a bug nobody notices. */
let STR = {};

const T = (key, vars) => {
  let out = STR[key] ?? key;
  if (vars) for (const [k, v] of Object.entries(vars)) out = out.replaceAll(`{${k}}`, v);
  return out;
};

/* The markup carries data-t on anything static; this fills them in. Everything else is
   rendered from the catalogue as it is built. */
function paintStatic() {
  $$("[data-t]").forEach(el => { el.textContent = T(el.dataset.t); });
}

/* ------------------------------------------------------------------ formatting */
const nf = (v, d = 0) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : v.toLocaleString(state.lang === "fr" ? "fr-FR" : "en-GB",
                           { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1) => v === null || v === undefined ? "—" : nf(v, d) + " %";
const money = v => v === null || v === undefined ? "—" : nf(Math.round(v));

/* Amounts arrive in dollars and are shown in the currency of the country. The conversion
   happens here and nowhere else, so nothing stored or exported depends on today's rate. */
let devise = { code: "USD", per_usd: 1 };
const enLocal = v => v === null || v === undefined ? null : v * devise.per_usd;
const somme = (v, d = 0) => v === null || v === undefined ? "—"
  : nf(enLocal(v), devise.per_usd > 50 ? 0 : d);
const parKwh = v => v === null || v === undefined ? "—"
  : nf(enLocal(v), devise.per_usd > 50 ? 0 : 4);
const unite = suffixe => `${devise.code}${suffixe}`;

function figure(k, v, u, note) {
  return `<div class="figure"><div class="k">${k}</div>
    <div class="v">${v}${u ? `<span class="u">${u}</span>` : ""}</div>
    ${note ? `<div class="n">${note}</div>` : ""}</div>`;
}


/* ------------------------------------------------------------------ charts
   Drawn by hand in SVG. A charting library would be one more thing to ship and to keep
   current for two figures whose shape is fixed; these are stacked areas and a line. */

const COULEURS = { pv_load: "#f0a02a", discharge: "#2f9e5e", generator: "#c0392b",
                   curtailed: "#b9bcc4", unserved: "#8e44ad" };

function aire(series, x, y) {
  // Cumulative stack: each band sits on the one below, so the top edge is total supply.
  let bas = new Array(series[0].values.length).fill(0);
  return series.map(s => {
    const haut = s.values.map((v, i) => bas[i] + v);
    const avant = haut.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    const arriere = bas.map((v, i) => `${x(i)},${y(v)}`).reverse().join(" ");
    bas = haut;
    return `<polygon points="${avant} ${arriere}" fill="${s.color}" fill-opacity=".85"/>`;
  }).join("");
}

function chartWeek(d) {
  // The right-hand margin carries a second scale for the state of charge, which is energy
  // and not power. Drawn on the same axis without saying so, a dashed line at two thirds of
  // the height reads as two thirds of the peak kilowatts, which it is not.
  const W = 900, H = 240, L = 46, R = 56, TOP = 12, B = 26;
  const n = d.demand.length;
  const series = [
    { values: d.pv_load,   color: COULEURS.pv_load },
    { values: d.discharge, color: COULEURS.discharge },
    { values: d.generator, color: COULEURS.generator },
  ];
  const somme = d.demand.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const ymax = Math.max(...somme, ...d.demand) * 1.12 || 1;
  const x = i => L + (i / Math.max(n - 1, 1)) * (W - L - R);
  const y = v => H - B - (v / ymax) * (H - TOP - B);
  const socMax = d.soc_max_kwh || 1;
  const ysoc = v => H - B - (v / socMax) * (H - TOP - B);

  const jours = [];
  for (let i = 0; i < n; i += 24)
    jours.push(`<line class="axis" x1="${x(i)}" y1="${TOP}" x2="${x(i)}" y2="${H - B}"/>
      <text x="${x(i) + 4}" y="${H - 9}">J${Math.floor(i / 24) + 1}</text>`);

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="${T("chart.week.alt")}">
    ${jours.join("")}
    <line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>
    ${aire(series, x, y)}
    <polyline class="soc" points="${d.soc.map((v, i) => `${x(i)},${ysoc(v)}`).join(" ")}"/>
    <polyline class="demand" points="${d.demand.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>
    <text x="4" y="${TOP + 9}">${nf(ymax, 0)} kW</text>
    <text x="4" y="${H - B}">0</text>
    <text x="${W - R + 8}" y="${TOP + 9}" fill="var(--ink-soft)">${nf(socMax, 0)} kWh</text>
    <text x="${W - R + 8}" y="${H - B}" fill="var(--ink-soft)">0</text>
  </svg>
  <div class="legend">
    <span><i style="background:${COULEURS.pv_load}"></i>${T("chart.pv_load")}</span>
    <span><i style="background:${COULEURS.discharge}"></i>${T("chart.discharge")}</span>
    <span><i style="background:${COULEURS.generator}"></i>${T("chart.generator")}</span>
    <span><i class="line" style="background:var(--ink)"></i>${T("chart.demand")}</span>
    <span><i class="line" style="background:var(--ink-soft)"></i>${T("chart.soc")}</span>
  </div>`;
}

function chartMonths(m) {
  const W = 900, H = 210, L = 46, R = 12, TOP = 12, B = 26;
  const mois = ["J","F","M","A","M","J","J","A","S","O","N","D"];
  const series = [
    { values: m.pv_load,   color: COULEURS.pv_load },
    { values: m.discharge, color: COULEURS.discharge },
    { values: m.generator, color: COULEURS.generator },
  ];
  const totaux = mois.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const ymax = Math.max(...totaux) * 1.12 || 1;
  const bw = (W - L - R) / 12 * .62;
  let out = "";
  mois.forEach((nom, i) => {
    const cx = L + (i + .5) * (W - L - R) / 12;
    let bas = H - B;
    series.forEach(s => {
      const h = (s.values[i] / ymax) * (H - TOP - B);
      bas -= h;
      out += `<rect x="${cx - bw / 2}" y="${bas}" width="${bw}" height="${Math.max(h, 0)}"
                fill="${s.color}" fill-opacity=".85"/>`;
    });
    out += `<text x="${cx}" y="${H - 9}" text-anchor="middle">${nom}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="${T("chart.months.alt")}">
    <line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>
    ${out}
    <text x="4" y="${TOP + 9}">${nf(ymax / 1000, 1)} MWh</text>
    <text x="4" y="${H - B}">0</text>
  </svg>`;
}

/* ------------------------------------------------------------------ the form */
function renderForm() {
  // The form is rebuilt from the overrides, never from the values the server first sent.
  // It is redrawn on any currency keystroke and on a language change, and a rebuild that
  // read the original values would quietly put them back into the boxes while the study
  // went on using what the reader typed.
  for (const g of state.groups) for (const f of g.fields)
    if (f.path in state.overrides) f.value = state.overrides[f.path];

  $("#form").innerHTML = state.groups.map(g => `
    <div class="card">
      <h3>${g.title}</h3>
      ${g.fields.map(f => fieldRow(f)).join("")}
    </div>`).join("");

  $$("#form input, #form select").forEach(el => {
    el.addEventListener("input", () => {
      const path = el.dataset.path;
      const raw = el.type === "number" ? parseFloat(el.value) : el.value;
      state.overrides[path] = raw;
      if (path.startsWith("currency.")) { majDevise(); return; }
      const loc = $("#" + el.id + "-loc");
      if (loc && Number.isFinite(raw))
        loc.textContent = `≈ ${nf(raw * devise.per_usd, devise.per_usd > 50 ? 0 : 2)} `
          + `${(state.groups.flatMap(g => g.fields).find(x => x.path === path)?.unit ?? "")
               .replace("$", devise.code)}`;
      el.closest(".field").classList.toggle(
        "changed", String(raw) !== String(state.defaults[path]));
    });
  });
}

function fieldRow(f) {
  const id = "f-" + f.path.replace(/\./g, "-");
  const control = f.kind === "choice"
    ? `<select id="${id}" data-path="${f.path}">${f.choices.map(
         c => `<option value="${c}"${c === f.value ? " selected" : ""}>${c}</option>`
       ).join("")}</select>`
    // A setting that is deliberately absent -- no required service level, for one -- renders
    // as an empty box and not as the string "null", which a number input rejects and the
    // console complains about.
    : `<input id="${id}" data-path="${f.path}" type="number"
         step="${f.step ?? (f.kind === "integer" ? 1 : "any")}"
         value="${f.value ?? ""}" placeholder="${f.value === null ? "—" : ""}">`;
  // A price typed in dollars and read back in francs, with a factor of six hundred between
  // them and nothing on the form to say so, is a mistake waiting to be made. The equivalent
  // is shown beside the box rather than converting the box, which would round the sourced
  // figure on every round trip.
  const local = f.unit.includes("$") && devise.per_usd !== 1 && Number.isFinite(f.value)
    ? `<div class="hint" id="${id}-loc">≈ ${nf(f.value * devise.per_usd,
        devise.per_usd > 50 ? 0 : 2)} ${f.unit.replace("$", devise.code)}</div>` : "";
  // A field the reader has moved away from its sourced value is marked, and stays marked
  // through any re-render -- a language change among them. Reading the mark off the state
  // rather than setting it once on the keystroke is what makes it survive.
  const change = String(f.value) !== String(state.defaults[f.path]) ? " changed" : "";
  return `<div class="field${change}">
      <div>
        <label for="${id}">${f.label}</label>
        ${f.hint ? `<div class="hint">${f.hint}</div>` : ""}
        ${f.source ? `<div class="source"><b>${T("source.label")}</b><span>${f.source}</span></div>` : ""}
      </div>
      <div class="control" style="flex-direction:column;align-items:stretch">
        <div style="display:flex;align-items:center;gap:8px">
          ${control}${f.unit ? `<span class="unit">${f.unit}</span>` : ""}
        </div>${local}
      </div>
    </div>`;
}

/* ------------------------------------------------------------------ results */
function renderSize(r) {
  if (r && r.currency) devise = r.currency;
  if (!r) {
    $("#result").innerHTML = `<div class="card empty"><h4>${T("res.none.title")}</h4>
      <p>${T("res.none.body")}</p></div>`;
    return;
  }
  const d = r.design, total = d.pv_kw + (d.pv_ac_kw || 0);
  const sub = r.subsidy_fraction;
  const badge = r.proven
    ? `<span class="badge ok">${T("res.proven")}</span>`
    : `<span class="badge warn">${T("res.unproven")}</span>`;
  $("#result").innerHTML = `
    <div class="card">
      <h3>${T("res.plant")} — ${r.site}, ${T("res.growth")} ${r.trajectory}</h3>
      <div class="figures">
        ${figure(T("res.pv"), nf(total, 1), "kW",
                 d.pv_ac_kw ? `${nf(d.pv_kw,1)} ${T("res.battery_bus")} · ${nf(d.pv_ac_kw,1)} ${T("res.load_bus")}` : null)}
        ${figure(T("res.storage"), nf(d.battery_kwh), "kWh")}
        ${figure(T("res.conversion"), nf(d.inverter_kw, 1), "kW")}
        ${figure(T("res.generator"), nf(d.generator_kw), "kW")}
      </div>
      <p style="margin:16px 0 0">${badge}</p>
    </div>

    <div class="card">
      <h3>${T("res.cost_title")}</h3>
      <div class="figures">
        ${figure(T("res.lcoe"), parKwh(r.lcoe_usd_kwh), unite("/kWh"),
                 `${T("res.target")} ${parKwh(r.tariff_target_usd_kwh)}`)}
        ${figure(T("res.annual"), somme(r.z_rule_usd_yr), unite("/an"))}
        ${figure(T("res.subsidy"), sub ? pct(sub * 100) : T("res.subsidy.none"), "",
                 sub ? T("res.subsidy", { n: `${somme(r.subsidy_usd)} ${devise.code}` })
                     : T("res.subsidy.met"))}
        ${figure(T("res.gap"), pct(r.price_rel_pct), "",
                 `${somme(r.price_abs_usd_yr)} ${unite("/an")}`)}
      </div>
    </div>

    ${r.dispatch ? `
    <div class="card">
      <h3>${T("res.week")}</h3>
      ${chartWeek(r.dispatch)}
      <p class="hint" style="margin-top:14px">${T("res.week.hint")}</p>
    </div>
    <div class="card">
      <h3>${T("res.year")}</h3>
      ${chartMonths(r.dispatch.monthly)}
    </div>` : ""}

    ${r.finance ? `
    <div class="card">
      <h3>${T("fin.title")}</h3>
      <div class="figures">
        ${figure(T("fin.irr"), r.finance.irr === null ? T("fin.irr.none")
                 : pct(r.finance.irr * 100), "",
                 r.finance.irr === null ? T("fin.irr.never")
                 : T("fin.at_tariff", { tariff: `${parKwh(r.tariff_target_usd_kwh)} ${unite("/kWh")}` }))}
        ${figure(T("fin.payback"),
                 r.finance.payback_years === null ? T("fin.payback.never")
                 : nf(r.finance.payback_years, 1), r.finance.payback_years === null ? "" : T("fin.years"),
                 r.finance.discounted_payback_years === null ? T("fin.disc_never")
                 : T("fin.disc", { n: nf(r.finance.discounted_payback_years, 1) }))}
        ${figure(T("fin.npv"), somme(r.finance.net_present_value_usd), devise.code)}
        ${figure(T("fin.capital"), somme(r.finance.initial_capital_usd), devise.code,
                 r.finance.subsidy_usd ? T("fin.of_which", { n: somme(r.finance.subsidy_usd) }) : null)}
      </div>
      <table style="margin-top:18px">
        <tr><th>${T("fin.year")}</th><th>${T("fin.investment")}</th><th>${T("fin.operating")}</th><th>${T("fin.revenue")}</th><th>${T("fin.net")}</th></tr>
        ${r.finance.cash_flows.filter(c => c.year <= 3 || c.capital > 0 ||
            c.year === r.finance.cash_flows.length - 1).slice(0, 9).map(c => `<tr>
          <td>${c.year}</td><td>${c.capital ? somme(c.capital) : "—"}</td>
          <td>${c.operating ? somme(c.operating) : "—"}</td>
          <td>${c.revenue ? somme(c.revenue) : "—"}</td>
          <td><b>${somme(c.net)}</b></td></tr>`).join("")}
      </table>
      <p class="hint" style="margin-top:12px">${T("fin.hint")}
         ${r.finance_unsubsidised && r.finance.subsidy_usd
           ? T("fin.unsubsidised", { rate: r.finance_unsubsidised.irr === null
               ? T("fin.irr.none") : pct(r.finance_unsubsidised.irr * 100) }) : ""}
         ${T("fin.replacements")}</p>
    </div>` : ""}

    <div class="card">
      <h3>${T("res.how")}</h3>
      <table>
        <tr><th>${T("res.quantity")}</th><th>${T("res.value")}</th></tr>
        <tr><td>${T("res.lattice")}</td><td>${nf(r.lattice_size)}</td></tr>
        <tr><td>${T("res.pruned")}</td><td>${nf(r.pruned_points)}</td></tr>
        <tr><td>${T("res.simulated")}</td><td>${nf(r.enumerated_points)}</td></tr>
        <tr><td>${T("res.relaxations")}</td><td>${nf(r.relaxations)}</td></tr>
        <tr><td>${T("res.seconds")}</td><td>${nf(r.seconds, 1)} s</td></tr>
      </table>
      <p class="hint" style="margin-top:12px">${T("res.coverage")}</p>
      <div style="margin-top:16px;display:flex;gap:10px">
        <button class="btn quiet" onclick="exporter('size','csv')">${T("action.export_csv")}</button>
        <button class="btn quiet" onclick="exporter('size','json')">${T("action.export_json")}</button>
        <button class="btn quiet" onclick="imprimer()">${T("action.print")}</button>
      </div>
    </div>`;
}

function renderPlan(r) {
  if (r && r.currency) devise = r.currency;
  if (!r) {
    $("#plan").innerHTML = `<div class="card empty"><h4>${T("plan.none.title")}</h4>
      <p>${T("plan.none.body")}</p></div>`;
    return;
  }
  const p = r.root_plan, e = r.expected, total = p.pv_kw + (p.pv_ac_kw || 0);
  // Milestone years live in the reduction record, keyed by year; r.stages holds indices,
  // and reading a year out of it labelled the first branch "année 1" instead of "année 5".
  const jalons = Object.keys(r.reduction_error || {}).map(Number).sort((a, b) => a - b);
  const anneeBranche = jalons[1] ?? "suivante";
  const stage1 = (r.per_node || []).filter(n => n.stage === 1)
    .sort((a, b) => b.probability - a.probability);
  $("#plan").innerHTML = `
    <div class="card">
      <h3>${T("plan.commit")} — ${r.site}</h3>
      <div class="figures">
        ${figure(T("res.pv"), nf(total, 1), "kW",
                 p.pv_ac_kw ? `${nf(p.pv_kw,1)} ${T("res.battery_bus")} · ${nf(p.pv_ac_kw,1)} ${T("res.load_bus")}` : null)}
        ${figure("Stockage", nf(p.battery_kwh), "kWh")}
        ${figure("Conversion", nf(p.inverter_kw, 1), "kW")}
        ${figure("Groupe", nf(p.generator_kw), "kW")}
      </div>
    </div>

    <div class="card">
      <h3>${T("plan.future")}</h3>
      <table>
        <tr><th>${T("plan.branch")} ${anneeBranche}</th><th>${T("plan.probability")}</th>
            <th>${T("plan.energy")}</th><th>${T("res.pv")}</th><th>${T("res.storage")}</th></tr>
        ${stage1.map((n, i) => {
          const champ = n.pv_kw + (n.pv_ac_kw || 0);
          const suite = champ > total + 1e-6 || n.battery_kwh > p.battery_kwh + 1e-6;
          return `<tr>
            <td>${i + 1}<span style="color:var(--ink-soft)"> — ${suite ? T("plan.enlarge") : T("plan.hold")}${
              n.grid_connected ? `, ${T("plan.grid_here")}` : ""}</span></td>
            <td>${pct(n.probability * 100, 0)}</td>
            <td>${nf(n.energy_served_kwh / 1000, 1)} MWh</td>
            <td>${nf(champ, 1)} kW</td>
            <td>${nf(n.battery_kwh)} kWh</td></tr>`;
        }).join("")}
      </table>
      <p class="hint" style="margin-top:12px">${T("plan.tree", { nodes: nf(r.nodes), leaves: nf(r.leaves) })}</p>
    </div>

    <div class="card">
      <h3>${T("plan.cost")}</h3>
      <div class="figures">
        ${figure(T("plan.expected_lcoe"), parKwh(e.expected_lcoe_usd_kwh), unite("/kWh"))}
        ${figure(T("plan.expected_cost"), somme(e.expected_rule_cost_usd), devise.code)}
        ${figure(T("plan.gap"), pct(e.price_of_heuristic_pct), "")}
        ${figure(T("plan.evaluations"), nf(e.search_evaluations), "")}
      </div>
      <p class="hint" style="margin-top:12px">${T("plan.upper")}</p>
      <div style="margin-top:16px;display:flex;gap:10px">
        <button class="btn quiet" onclick="exporter('plan','csv')">${T("action.export_csv")}</button>
        <button class="btn quiet" onclick="exporter('plan','json')">${T("action.export_json")}</button>
        <button class="btn quiet" onclick="imprimer()">${T("action.print")}</button>
      </div>
    </div>`;
}


/* ------------------------------------------------------------------ community */
let carte = null, marqueur = null;

function renderLieu() {
  const s = state.site || {};
  const tpl = s.origin === "template";
  $("#lieu").innerHTML = `
    <div class="card">
      <h3>${T("site.card")}</h3>
      <div class="field">
        <div><label for="site-pick">${T("site.picker")}</label>
          <div class="hint">${T("site.picker.hint")}</div></div>
        <div class="control">
          <select id="site-pick">${state.sites.map(x =>
            `<option value="${x.name}"${x.name === s.name ? " selected" : ""}>${x.name}${
              x.origin === "template" ? T("site.example") : ""}</option>`).join("")}
            <option value="__new__">${T("site.new")}</option>
          </select>
        </div>
      </div>
      <div class="field">
        <div><label for="site-name">${T("site.name")}</label></div>
        <div class="control"><input id="site-name" type="text" value="${s.name ?? ""}"
             ${tpl ? "disabled" : ""}></div>
      </div>
      <div class="field">
        <div><label for="hh1">${T("site.households")}</label>
          <div class="hint">${T("site.households.hint")}</div></div>
        <div class="control" style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px">
          ${["HH1", "HH2", "HH3"].map(t => `<div>
             <label for="${t.toLowerCase()}" style="font-size:11.5px;color:var(--ink-faint)">${t}</label>
             <input id="${t.toLowerCase()}" type="number" min="0" step="1"
               value="${(s.census || {})[t] ?? 0}" ${tpl ? "disabled" : ""}></div>`).join("")}
        </div>
      </div>
      <div class="field">
        <div><label for="pue">${T("site.productive")}</label>
          <div class="hint">${T("site.productive.hint")}</div></div>
        <div class="control"><input id="pue" type="number" min="0" step="1"
             placeholder="${T("site.estimated")}" value="${s.productive_units ?? ""}"
             ${tpl ? "disabled" : ""}></div>
      </div>
      <div class="field">
        <div><label for="utc">${T("site.utc")}</label>
          <div class="hint">${T("site.utc.hint")}</div></div>
        <div class="control"><input id="utc" type="number" min="-12" max="14" step="1"
             value="${s.utc_offset_hours ?? 1}" ${tpl ? "disabled" : ""}>
          <span class="unit" id="utc-hint"></span></div>
      </div>
    </div>

    <div class="card">
      <h3>${T("site.where")}</h3>
      <div id="carte"></div>
      <div class="coords">
        <div><label for="lat">${T("site.latitude")}</label>
          <input id="lat" type="number" step="0.0001" value="${s.latitude ?? ""}"></div>
        <div><label for="lon">${T("site.longitude")}</label>
          <input id="lon" type="number" step="0.0001" value="${s.longitude ?? ""}"></div>
      </div>
      <p class="hint" style="margin-top:12px">${T("site.map.hint")}</p>
      <div style="margin-top:16px;display:flex;gap:10px;align-items:center">
        ${tpl ? "" : `<button class="btn primary" id="site-save">${T("action.save_site")}</button>`}
        <button class="btn quiet" id="get-resource"
          ${s.latitude == null ? "disabled" : ""}>${T("action.fetch_resource")}</button>
        ${s.has_resource ? `<span class="badge ok">${T("site.series.have")}</span>`
                         : `<span class="badge warn">${T("site.series.none")}</span>`}
        ${tpl ? "" : `<div class="spacer" style="flex:1"></div>
          <button class="btn link" id="site-drop">${T("action.delete")}</button>`}
      </div>
      ${s.has_resource ? "" : `<p class="hint" style="margin-top:10px">${T("site.series.hint")}</p>`}
    </div>`;

  $("#site-pick").onchange = e => {
    if (e.target.value === "__new__") {
      state.site = { name: T("site.new.name"), origin: "user",
                     census: { HH1: 120, HH2: 0, HH3: 0 }, n_households: 120,
                     productive_units: null, latitude: null, longitude: null,
                     utc_offset_hours: 1 };
    } else {
      state.site = state.sites.find(x => x.name === e.target.value);
      state.overrides["site"] = state.site.name;
      const champ = $("#f-site");
      if (champ) champ.value = state.site.name;
    }
    renderLieu(); loadArchetypes();
  };
  const save = $("#site-save");
  if (save) save.onclick = saveSite;
  const drop = $("#site-drop");
  if (drop) drop.onclick = async () => {
    await fetch(`/api/sites/${encodeURIComponent(state.site.name)}`, { method: "DELETE" });
    await refreshSites();
  };
  $("#get-resource").onclick = async () => {
    if (!state.site.has_resource && state.site.origin === "user") await saveSite();
    const r = await fetch(`/api/sites/${encodeURIComponent(state.site.name)}/resource`,
                          { method: "POST" });
    state.job = await r.json();
    buttons(false); $("#cancel").classList.remove("hidden"); poll();
  };
  ["lat", "lon"].forEach(id => $("#" + id).addEventListener("change", () => {
    const la = parseFloat($("#lat").value), lo = parseFloat($("#lon").value);
    if (Number.isFinite(la) && Number.isFinite(lo)) placer(la, lo, true);
  }));
  proposerFuseau();
  $("#lon").addEventListener("change", proposerFuseau);

  monterCarte(s.latitude, s.longitude);
}

function monterCarte(lat, lon) {
  const hote = $("#carte");
  if (!hote || typeof L === "undefined") return;
  carte = L.map(hote, { attributionControl: true })
           .setView([lat ?? 9.5, lon ?? 2.3], lat == null ? 5 : 13);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
              { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(carte);
  // A field office may have no network. The map then shows nothing, which must not stop the
  // work: the coordinate boxes remain the authority and the map only ever mirrors them.
  carte.on("click", e => placer(e.latlng.lat, e.latlng.lng, false));
  if (lat != null && lon != null) placer(lat, lon, false);
}

function placer(lat, lon, recentrer) {
  if (!state.site) return;
  state.site.latitude = Math.round(lat * 1e6) / 1e6;
  state.site.longitude = Math.round(lon * 1e6) / 1e6;
  $("#lat").value = state.site.latitude;
  $("#lon").value = state.site.longitude;
  $("#get-resource").disabled = false;
  if (!carte) return;
  if (marqueur) marqueur.setLatLng([lat, lon]);
  else marqueur = L.marker([lat, lon], { draggable: true }).addTo(carte)
                   .on("dragend", ev => {
                     const p = ev.target.getLatLng(); placer(p.lat, p.lng, false);
                   });
  if (recentrer) carte.setView([lat, lon], Math.max(carte.getZoom(), 13));
}

function proposerFuseau() {
  // The sun, not the state: solar noon follows longitude, and the zone a country keeps is
  // often an hour or more away from it. The suggestion is a starting point the developer
  // corrects, not an answer -- which is why it is shown beside the box and not written into it.
  const lo = parseFloat($("#lon")?.value);
  const champ = $("#utc-hint");
  if (!champ) return;
  if (!Number.isFinite(lo)) { champ.textContent = ""; return; }
  const solaire = Math.round(lo / 15);
  const saisi = parseInt($("#utc")?.value ?? "1", 10);
  champ.textContent = saisi === solaire ? `h` : `h · ${T("site.solar_noon")}${solaire >= 0 ? "+" : ""}${solaire}`;
}

async function saveSite() {
  const s = state.site;
  const pue = $("#pue").value.trim();
  const body = {
    name: ($("#site-name")?.value || s.name).trim(),
    latitude: parseFloat($("#lat").value), longitude: parseFloat($("#lon").value),
    census: Object.fromEntries(["HH1", "HH2", "HH3"].map(
      t => [t, parseInt($("#" + t.toLowerCase()).value || 0, 10)])),
    productive_units: pue === "" ? null : parseInt(pue, 10),
    utc_offset_hours: parseInt($("#utc").value || 1, 10),
  };
  const r = await fetch("/api/sites", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!r.ok) { setState(T("state.site_failed"), null); return; }
  state.overrides["site"] = body.name;
  await refreshSites(body.name);
  setState(T("state.site_saved", { name: body.name }), null);
}

async function refreshSites(select) {
  state.sites = await (await fetch("/api/sites")).json();
  const nom = select || state.overrides["site"];
  state.site = state.sites.find(x => x.name === nom) || state.sites[0];
  const champ = $("#f-site");
  if (champ) {
    champ.innerHTML = state.sites.map(
      x => `<option value="${x.name}"${x.name === state.site.name ? " selected" : ""}>${x.name}</option>`).join("");
  }
  state.overrides["site"] = state.site.name;
  renderLieu(); await loadArchetypes();
}

/* ------------------------------------------------------------------ archetypes */
async function loadArchetypes() {
  if (!state.site) return;
  state.arch = await (await fetch(
    `/api/archetypes/${encodeURIComponent(state.site.name)}?lang=${state.lang || ""}`)).json();
  renderArchetypes();
}

function renderArchetypes() {
  const a = state.arch;
  if (!a) return;
  $("#usages").innerHTML = `
    <div class="notice">
      <b>${T("arch.origin")}.</b> ${a.note}
      ${a.adjusted ? ` <b>${T("arch.adjusted")}</b>` : ""}
    </div>
    <div class="card">
      <h3>${T("arch.title")}</h3>
      <div class="arch">
        <div class="who"><b>${T("arch.behaviour")}</b></div>
        <div class="head">${T("arch.energy")}</div>
        <div class="head">${T("arch.peak")}</div>
        <div class="head">${T("arch.load_factor")}</div>
      </div>
      ${a.archetypes.map(x => `
        <div class="arch">
          <div class="who"><b>${x.label}</b>
            <span>${x.share_pct} % ${T("arch.share")} · ${x.n_observations} ${T("arch.records")}
              ${x.well_supported ? "" : ` · <b>${T("arch.weak")}</b>`}</span></div>
          <div><input type="number" step="0.001" data-c="${x.cluster}" data-k="mean_daily_kwh"
               value="${x.mean_daily_kwh}"></div>
          <div><input type="number" step="1" data-c="${x.cluster}" data-k="mean_peak_w"
               value="${x.mean_peak_w}"></div>
          <div><input type="number" step="0.01" data-c="${x.cluster}" data-k="mean_load_factor"
               value="${x.mean_load_factor}" disabled></div>
        </div>`).join("")}
      <p class="hint" style="margin-top:14px">${T("arch.hint")}</p>
      <div style="margin-top:16px;display:flex;gap:10px">
        <button class="btn primary" id="arch-save">${T("action.apply")}</button>
        <button class="btn quiet" id="arch-reset">${T("action.reset")}</button>
      </div>
    </div>`;

  $("#arch-save").onclick = async () => {
    const payload = {};
    $$("#usages input[data-c]").forEach(el => {
      if (el.disabled) return;
      (payload[el.dataset.c] ||= {})[el.dataset.k] = parseFloat(el.value);
    });
    state.arch = await (await fetch("/api/archetypes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ site: state.site.name, archetypes: payload })
    })).json();
    renderArchetypes();
    setState(T("state.applied"), null);
  };
  $("#arch-reset").onclick = async () => {
    state.arch = await (await fetch(
      `/api/archetypes/${encodeURIComponent(state.site.name)}`, { method: "DELETE" })).json();
    renderArchetypes();
  };
}

/* ------------------------------------------------------------------ projects */
function imprimer() {
  // Print, rather than a PDF written by hand: the browser already lays this page out and
  // already knows how to make a file of it, and a second renderer would be a second thing
  // to keep in step with the first. The print stylesheet decides what reaches the sheet.
  const tete = document.createElement("div");
  tete.className = "print-only";
  tete.innerHTML = `<div style="margin-bottom:18px">
      <h1 style="font-size:22px;margin:0">${T("print.title")} — ${state.site?.name ?? ""}</h1>
      <p style="color:#444;margin:6px 0 0;font-size:11px">
        ${state.projectName ? state.projectName + " · " : ""}
        ${T("print.issued", { date: new Date().toLocaleDateString(
            state.lang === "fr" ? "fr-FR" : "en-GB", { dateStyle: "long" }) })} ·
        ${T("print.amounts", { code: devise.code })}${devise.per_usd !== 1
          ? ` (1 USD = ${nf(devise.per_usd, 2)} ${devise.code})` : ""}</p>
      <p style="color:#444;margin:8px 0 0;font-size:10.5px">
        ${T("print.behaviour")} ${state.arch?.adjusted
          ? T("print.arch.adjusted") : T("print.arch.shipped")}
        ${state.arch?.note ?? ""}</p>
    </div>`;
  const main = $(".main");
  main.prepend(tete);
  window.print();
  setTimeout(() => tete.remove(), 500);
}

async function exporter(kind, format) {
  const result = state.results[kind];
  if (!result) return;
  const r = await fetch(`/api/export.${format}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, result, lang: state.lang })
  });
  const blob = await r.blob();
  const nom = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = nom ? nom[1] : `export.${format}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function renderProjects() {
  const options = state.projects.map(
    p => `<option value="${p.slug}">${p.name}${p.site ? ` — ${p.site}` : ""}</option>`).join("");
  $("#projects").innerHTML = `
    <span class="name">${T("proj.label")}</span>
    <input id="project-name" placeholder="${T("proj.placeholder")}" value="${state.projectName}">
    <button class="btn quiet" id="save">${T("action.save")}</button>
    <div class="spacer"></div>
    ${state.projects.length ? `<select id="open"><option value="">${T("action.open")}</option>${options}</select>
       <button class="btn link" id="drop">${T("action.delete")}</button>` : ""}`;

  $("#project-name").oninput = e => state.projectName = e.target.value;
  $("#save").onclick = async () => {
    const r = await fetch("/api/projects", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: state.projectName || "Sans nom",
                             overrides: state.overrides, results: state.results })
    });
    if (r.ok) { await refreshProjects(); setState(T("state.saved"), null); }
  };
  const open = $("#open");
  if (open) open.onchange = async e => {
    if (!e.target.value) return;
    const p = await (await fetch(`/api/projects/${e.target.value}`)).json();
    state.overrides = { ...state.overrides, ...p.overrides };
    state.projectName = p.name;
    state.results = p.results || { size: null, plan: null };
    for (const g of state.groups) for (const f of g.fields)
      if (p.overrides[f.path] !== undefined) f.value = p.overrides[f.path];
    renderForm(); renderProjects();
    renderSize(state.results.size); renderPlan(state.results.plan);
    setState(T("proj.opened", { name: p.name }), null);
  };
  const drop = $("#drop");
  if (drop) drop.onclick = async () => {
    const slug = $("#open").value;
    if (!slug) return;
    await fetch(`/api/projects/${slug}`, { method: "DELETE" });
    await refreshProjects();
  };
}

async function refreshProjects() {
  state.projects = await (await fetch("/api/projects")).json();
  renderProjects();
}

/* ------------------------------------------------------------------ running */
async function launch(kind) {
  const r = await fetch(`/api/${kind}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides: state.overrides })
  });
  const job = await r.json();
  if (!r.ok) { setState(`<b>${T("state.failed")}</b> ${job.detail ?? ""}`, null); return; }
  state.job = job;
  $("#cancel").classList.remove("hidden");
  buttons(false);
  poll();
}

function poll() {
  clearInterval(state.timer);
  state.timer = setInterval(async () => {
    if (!state.job) return;
    const job = await (await fetch(`/api/job/${state.job.id}`)).json();
    state.job = job;
    setState(`<b>${T(job.label, job.label_args)}</b> — ${T(job.stage, job.stage_args)}`, job.fraction);
    if (job.status === "running") return;

    clearInterval(state.timer);
    $("#cancel").classList.add("hidden");
    buttons(true);
    if (job.status === "done") {
      state.results[job.kind] = job.result;
      job.kind === "size" ? renderSize(job.result) : renderPlan(job.result);
      show(job.kind === "size" ? "result" : "plan");
      setState(`<b>${T(job.label, job.label_args)}</b> — ${T("job.done")}.`, 1);
    } else {
      setState(`<b>${T(job.label, job.label_args)}</b> — ${T("job." + job.status)}. ${job.error ?? ""}`, null);
    }
  }, 700);
}

function setState(html, fraction) {
  $("#state").innerHTML = html;
  const track = $("#track");
  track.classList.toggle("hidden", fraction === null || fraction === undefined);
  if (fraction !== null && fraction !== undefined)
    track.firstElementChild.style.width = `${Math.round(fraction * 100)}%`;
}

const buttons = on => $$("#run-size, #run-plan").forEach(b => b.disabled = !on);

function show(view) {
  $$(".page").forEach(p => p.classList.toggle("hidden", p.dataset.page !== view));
  $$(".nav button").forEach(b => b.setAttribute("aria-current", String(b.dataset.view === view)));
}

/* ------------------------------------------------------------------ start */
function majDevise() {
  const code = state.overrides["currency.local_code"];
  const parEuro = parseFloat(state.overrides["currency.xof_per_eur"]);
  const dollarsParEuro = parseFloat(state.overrides["currency.usd_per_eur"]);
  if (code && Number.isFinite(parEuro) && Number.isFinite(dollarsParEuro) && dollarsParEuro)
    devise = { code, per_usd: parEuro / dollarsParEuro };
  renderForm();
}

async function setLanguage(lang) {
  // The whole page is rebuilt rather than patched: the strings live inside rendered markup,
  // and re-rendering from the catalogue is both shorter and safer than hunting for the
  // fragments that changed. What the reader has entered survives the rebuild — a language
  // is a way of reading a study, not a reason to lose one. The choice is remembered per
  // browser, not per project: it belongs to the reader, not to the work.
  try { localStorage.setItem("lang", lang); } catch { /* private window: no memory, no harm */ }
  await boot(lang);
}

async function boot(lang) {
  if (!lang) {
    try { lang = localStorage.getItem("lang"); } catch { lang = null; }
  }
  const b = await (await fetch(`/api/bootstrap?lang=${lang || ""}`)).json();
  STR = b.strings || {};
  state.lang = b.lang;
  document.documentElement.lang = b.lang;
  paintStatic();
  const picker = $("#lang");
  picker.innerHTML = Object.entries(b.languages || {})
    .map(([code, name]) => `<option value="${code}"${code === b.lang ? " selected" : ""}>${name}</option>`)
    .join("");
  picker.onchange = e => setLanguage(e.target.value);
  // On the first boot the server's values are the study; on a language change they are only
  // labels arriving in another language, and the reader's own values must survive them.
  const premier = state.groups.length === 0;
  state.groups = b.groups;
  for (const g of b.groups) for (const f of g.fields) {
    state.defaults[f.path] = f.value;
    if (premier) state.overrides[f.path] = f.value;
    else f.value = state.overrides[f.path];
  }
  state.projects = b.projects || [];
  state.sites = b.sites || [];
  state.site = state.sites.find(x => x.name === state.overrides["site"]) || state.sites[0];
  majDevise();
  renderProjects();
  renderSize(state.results.size); renderPlan(state.results.plan);
  renderLieu(); await loadArchetypes();

  $$(".nav button").forEach(b => b.onclick = () => show(b.dataset.view));
  $("#run-size").onclick = () => launch("size");
  $("#run-plan").onclick = () => launch("plan");
  $("#cancel").onclick = async () => {
    if (state.job) await fetch(`/api/job/${state.job.id}/cancel`, { method: "POST" });
  };
  // A run under way keeps its own line: the poller will repaint it in the new language on
  // its next tick, and overwriting it here would look like the run had stopped.
  if (!state.job || state.job.status !== "running") setState(T("state.ready"), null);
}

boot();
