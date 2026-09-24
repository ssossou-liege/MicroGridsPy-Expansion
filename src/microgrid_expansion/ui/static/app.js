/* The page. No framework: the surface is small enough that one would cost more than it saves,
   and a build step would put a toolchain between a developer and a tool meant to be run. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { groups: [], overrides: {}, defaults: {}, job: null, timer: null,
                result: null, projects: [], projectName: "",
                sites: [], site: null, arch: null, classes: [], lang: "en",
                page: "project", reached: 1 };

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

/* Amounts arrive in dollars and are shown in the currency of the country. The conversion
   happens here and nowhere else, so nothing stored or exported depends on today's rate. */
let currency = { code: "USD", per_usd: 1 };
const toLocal = v => v === null || v === undefined ? null : v * currency.per_usd;
const amount = (v, d = 0) => v === null || v === undefined ? "—"
  : nf(toLocal(v), currency.per_usd > 50 ? 0 : d);
const perKwh = v => v === null || v === undefined ? "—"
  : nf(toLocal(v), currency.per_usd > 50 ? 0 : 4);
const unit = suffix => `${currency.code}${suffix}`;
// "per year" is a word, not punctuation. Each language abbreviates it its own way, and
// hard-coding one of them printed it on the other language's page.
const perYear = () => unit(T("unit.per_year"));

/* Text on its way into markup. A village called Kpali"ba, or an activity note with a
   quotation mark in it, would otherwise close the attribute it sits in and drop the rest of
   the element on the floor. */
const esc = v => String(v ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;")
                                .replace(/>/g, "&gt;").replace(/"/g, "&quot;");

/* The note that used to sit under every box, folded behind a marker beside its label. A
   form whose every question carries a paragraph reads as an essay with boxes in it; the
   reasons are worth keeping, but worth keeping out of the way. Focus opens it as hover
   does, so a form filled from the keyboard is not one with half its content unreachable.
   Near the right edge the panel is hung from the right, or it would run off the page. */
const info = key => `<button class="info" type="button"
   aria-label="${esc(T("wiz.info"))}" data-tip="${esc(T(key))}">i</button>`;

function figure(k, v, u, note) {
  return `<div class="figure"><div class="k">${k}</div>
    <div class="v">${v}${u ? `<span class="u">${u}</span>` : ""}</div>
    ${note ? `<div class="n">${note}</div>` : ""}</div>`;
}


/* ------------------------------------------------------------------ charts
   Drawn by hand in SVG. A charting library would be one more thing to ship and to keep
   current for two figures whose shape is fixed; these are stacked areas and a line. */

const COLOURS = { pv_load: "#f0a02a", discharge: "#2f9e5e", generator: "#c0392b",
                   curtailed: "#b9bcc4", unserved: "#8e44ad" };

function area(series, x, y) {
  // Cumulative stack: each band sits on the one below, so the top edge is total supply.
  let bottom = new Array(series[0].values.length).fill(0);
  return series.map(s => {
    const top = s.values.map((v, i) => bottom[i] + v);
    const front = top.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    const back = bottom.map((v, i) => `${x(i)},${y(v)}`).reverse().join(" ");
    bottom = top;
    return `<polygon points="${front} ${back}" fill="${s.color}" fill-opacity=".85"/>`;
  }).join("");
}

function chartWeek(d) {
  // The right-hand margin carries a second scale for the state of charge, which is energy
  // and not power. Drawn on the same axis without saying so, a dashed line at two thirds of
  // the height reads as two thirds of the peak kilowatts, which it is not.
  const W = 900, H = 240, L = 46, R = 56, TOP = 12, B = 26;
  const n = d.demand.length;
  const series = [
    { values: d.pv_load,   color: COLOURS.pv_load },
    { values: d.discharge, color: COLOURS.discharge },
    { values: d.generator, color: COLOURS.generator },
  ];
  const supply = d.demand.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const ymax = Math.max(...supply, ...d.demand) * 1.12 || 1;
  const x = i => L + (i / Math.max(n - 1, 1)) * (W - L - R);
  const y = v => H - B - (v / ymax) * (H - TOP - B);
  const socMax = d.soc_max_kwh || 1;
  const ysoc = v => H - B - (v / socMax) * (H - TOP - B);

  const days = [];
  for (let i = 0; i < n; i += 24)
    days.push(`<line class="axis" x1="${x(i)}" y1="${TOP}" x2="${x(i)}" y2="${H - B}"/>
      <text x="${x(i) + 4}" y="${H - 9}">${T("chart.day")}${Math.floor(i / 24) + 1}</text>`);

  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="${T("chart.week.alt")}">
    ${days.join("")}
    <line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>
    ${area(series, x, y)}
    <polyline class="soc" points="${d.soc.map((v, i) => `${x(i)},${ysoc(v)}`).join(" ")}"/>
    <polyline class="demand" points="${d.demand.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"/>
    <text x="4" y="${TOP + 9}">${nf(ymax, 0)} kW</text>
    <text x="4" y="${H - B}">0</text>
    <text x="${W - R + 8}" y="${TOP + 9}" fill="var(--ink-soft)">${nf(socMax, 0)} kWh</text>
    <text x="${W - R + 8}" y="${H - B}" fill="var(--ink-soft)">0</text>
  </svg>
  <div class="legend">
    <span><i style="background:${COLOURS.pv_load}"></i>${T("chart.pv_load")}</span>
    <span><i style="background:${COLOURS.discharge}"></i>${T("chart.discharge")}</span>
    <span><i style="background:${COLOURS.generator}"></i>${T("chart.generator")}</span>
    <span><i class="line" style="background:var(--ink)"></i>${T("chart.demand")}</span>
    <span><i class="line" style="background:var(--ink-soft)"></i>${T("chart.soc")}</span>
  </div>`;
}

function chartMonths(m) {
  const W = 900, H = 210, L = 46, R = 12, TOP = 12, B = 26;
  const months = ["J","F","M","A","M","J","J","A","S","O","N","D"];
  const series = [
    { values: m.pv_load,   color: COLOURS.pv_load },
    { values: m.discharge, color: COLOURS.discharge },
    { values: m.generator, color: COLOURS.generator },
  ];
  const totals = months.map((_, i) => series.reduce((a, s) => a + s.values[i], 0));
  const ymax = Math.max(...totals) * 1.12 || 1;
  const bw = (W - L - R) / 12 * .62;
  let out = "";
  months.forEach((name, i) => {
    const cx = L + (i + .5) * (W - L - R) / 12;
    let bottom = H - B;
    series.forEach(s => {
      const h = (s.values[i] / ymax) * (H - TOP - B);
      bottom -= h;
      out += `<rect x="${cx - bw / 2}" y="${bottom}" width="${bw}" height="${Math.max(h, 0)}"
                fill="${s.color}" fill-opacity=".85"/>`;
    });
    out += `<text x="${cx}" y="${H - 9}" text-anchor="middle">${name}</text>`;
  });
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
     aria-label="${T("chart.months.alt")}">
    <line class="axis" x1="${L}" y1="${H - B}" x2="${W - R}" y2="${H - B}"/>
    ${out}
    <text x="4" y="${TOP + 9}">${nf(ymax / 1000, 1)} MWh</text>
    <text x="4" y="${H - B}">0</text>
  </svg>`;
}

/* ------------------------------------------------------------------ the tree
   A plan over a scenario tree is forty-six plants, and a table of forty-six rows is not a
   plan: what a developer needs to see is which branch leads where, and at which milestone
   the plant has to grow. So it is drawn. Stages run left to right at their milestone years,
   futures run top to bottom, every node carries the plant it holds, and a node that is
   larger than the one it grew from is marked -- those marks are the expansion plan, and
   everything unmarked is capacity already bought at year zero.

   The line into a node is as thick as that future is likely, so the eye follows the branch
   the money should follow. */
function chartTree(tree) {
  const nodes = tree.per_node || [];
  const root = nodes.find(n => n.parent === null || n.parent === undefined);
  if (!nodes.length || !root) return "";

  const by = new Map(nodes.map(n => [n.node, n]));
  const kids = new Map();
  for (const n of nodes) {
    if (n.parent === null || n.parent === undefined) continue;
    if (!kids.has(n.parent)) kids.set(n.parent, []);
    kids.get(n.parent).push(n.node);
  }

  // Leaves take consecutive rows in depth-first order; a branch sits at the mean of the
  // futures below it, so it is drawn beside what it leads to rather than above it.
  const row = new Map();
  let nextRow = 0;
  const place = id => {
    const children = kids.get(id) || [];
    if (!children.length) { row.set(id, nextRow++); return nextRow - 1; }
    const ys = children.map(place);
    const y = (Math.min(...ys) + Math.max(...ys)) / 2;
    row.set(id, y);
    return y;
  };
  place(root.node);

  const stages = [...new Set(nodes.map(n => n.stage))].sort((a, b) => a - b);
  const years = Object.keys(tree.reduction_error || {}).map(Number).sort((a, b) => a - b);
  const BOX = 132, RH = 26, L = 8, R = 8, TOP = 34, BOT = 10;
  const W = 1000, H = TOP + nextRow * RH + BOT;
  const span = stages.length > 1 ? (W - L - R - BOX) / (stages.length - 1) : 0;
  const x = stage => L + stages.indexOf(stage) * span;
  const y = id => TOP + (row.get(id) + 0.5) * RH;

  const total = n => n.pv_kw + (n.pv_ac_kw || 0);
  const grows = n => {
    const up = by.get(n.parent);
    return up && (total(n) > total(up) + 1e-6 || n.battery_kwh > up.battery_kwh + 1e-6);
  };

  // Probability sets the weight of a line. A branch carrying half the mass and one
  // carrying a twentieth are not the same advice, and drawn alike they read as though
  // they were.
  const pmax = Math.max(...nodes.map(n => n.probability));
  const edges = nodes.filter(n => by.has(n.parent)).map(n => {
    const up = by.get(n.parent);
    const x0 = x(up.stage) + BOX, x1 = x(n.stage), mid = (x0 + x1) / 2;
    const w = 0.7 + 2.3 * Math.sqrt(n.probability / pmax);
    return `<path d="M${x0} ${y(up.node)} C${mid} ${y(up.node)}, ${mid} ${y(n.node)},
             ${x1} ${y(n.node)}" class="branch" stroke-width="${w.toFixed(2)}"/>`;
  }).join("");

  const boxes = nodes.map(n => {
    const top = y(n.node) - RH / 2 + 2, klass = grows(n) ? "grow" : "hold";
    const detail = [
      `${T("tree.node")} ${n.node}`,
      `${T("plan.probability")}: ${pct(n.probability * 100, 1)}`,
      `${T("res.pv")}: ${nf(total(n), 1)} kW`,
      `${T("res.storage")}: ${nf(n.battery_kwh)} kWh`,
      `${T("res.conversion")}: ${nf(n.inverter_kw, 1)} kW`,
      `${T("res.generator")}: ${nf(n.generator_kw)} kW`,
      `${T("plan.energy")}: ${nf(n.energy_served_kwh / 1000, 1)} MWh`,
      n.grid_connected ? T("plan.grid_here") : "",
    ].filter(Boolean).join("\n");
    return `<g class="tnode ${klass}">
      <title>${esc(detail)}</title>
      <rect x="${x(n.stage)}" y="${top}" width="${BOX}" height="${RH - 4}" rx="5"/>
      <text x="${x(n.stage) + 8}" y="${top + 15}">${nf(total(n), 1)} kW · ${
        nf(n.battery_kwh)} kWh</text>
      ${n.grid_connected ? `<circle cx="${x(n.stage) + BOX - 9}" cy="${top + 11}" r="3.2"
        class="gridmark"/>` : ""}
    </g>`;
  }).join("");

  const heads = stages.map(s => {
    const label = years[stages.indexOf(s)];
    return `<text x="${x(s)}" y="18" class="thead">${label === undefined
      ? `${T("tree.stage")} ${s}` : `${T("tree.year")} ${label}`}</text>`;
  }).join("");

  return `<svg class="tree" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(T("tree.alt"))}" style="min-width:760px">
      ${heads}${edges}${boxes}
    </svg>
    <div class="legend" style="margin-top:14px">
      <span><i class="swatch grow"></i>${T("tree.grows")}</span>
      <span><i class="swatch hold"></i>${T("tree.holds")}</span>
      <span><i class="swatch gridmark"></i>${T("plan.grid_here")}</span>
    </div>`;
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
      if (path.startsWith("currency.")) { refreshCurrency(); return; }
      const loc = $("#" + el.id + "-loc");
      if (loc && Number.isFinite(raw))
        loc.textContent = `≈ ${nf(raw * currency.per_usd, currency.per_usd > 50 ? 0 : 2)} `
          + `${(state.groups.flatMap(g => g.fields).find(x => x.path === path)?.unit ?? "")
               .replace("$", currency.code)}`;
      el.closest(".field").classList.toggle(
        "changed", String(raw) !== String(state.defaults[path]));
    });
  });
}

function fieldRow(f) {
  const id = "f-" + f.path.replace(/\./g, "-");
  const control = f.kind === "choice"
    // The values are the model's own -- "slow", "mixed", "yes" -- and stay as they are:
    // they name settings, results files and cache keys. Only what the reader sees is
    // translated, and a value with no entry shows itself, which is right for a currency
    // code or a solver name.
    ? `<select id="${id}" data-path="${f.path}">${f.choices.map(
         c => `<option value="${c}"${c === f.value ? " selected" : ""}>${
                 STR[`choice.${c}`] ?? c}</option>`
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
  const local = f.unit.includes("$") && currency.per_usd !== 1 && Number.isFinite(f.value)
    ? `<div class="hint" id="${id}-loc">≈ ${nf(f.value * currency.per_usd,
        currency.per_usd > 50 ? 0 : 2)} ${f.unit.replace("$", currency.code)}</div>` : "";
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

/* ------------------------------------------------------------------ the sizing
   One answer, and everything that stands behind it, on one page. The plant to buy comes
   first and alone, because that is the whole purpose of the exercise and a reader who
   stops after the first card has still got what they came for. Under it: what it costs,
   what the futures it was sized for will ask of it, what the certified reference year says
   about it, how it runs, and what it earns. */
function renderSizing(r) {
  if (r && r.currency) currency = r.currency;
  const host = $("#sizing");
  if (!r) {
    host.innerHTML = `<div class="card empty"><h4>${T("sizing.none.title")}</h4>
      <p>${T("sizing.none.body")}</p></div>`;
    return;
  }

  const d = r.plant, ref = r.reference || {}, e = r.expected || {}, tree = r.tree || {};
  const total = d.pv_kw + (d.pv_ac_kw || 0);
  const proven = r.proven || {};

  const sub = ref.subsidy_fraction;
  const rows = [["res.pv", "pv_kw", 1, "kW"], ["res.storage", "battery_kwh", 0, "kWh"],
                ["res.conversion", "inverter_kw", 1, "kW"],
                ["res.generator", "generator_kw", 0, "kW"]];

  host.innerHTML = `
    <div class="verdict">
      <div class="verdict-head">
        <h3>${T("sizing.build")}</h3>
        <span class="where">${esc(r.site)}${tree.leaves
          ? ` · ${T("sizing.over_tree", { leaves: nf(tree.leaves), nodes: nf(tree.nodes) })}`
          : ""}</span>
      </div>
      <div class="figures">
        ${figure(T("res.pv"), nf(total, 1), "kW", d.pv_ac_kw
            ? `${nf(d.pv_kw, 1)} ${T("res.battery_bus")} · ${nf(d.pv_ac_kw, 1)} ${T("res.load_bus")}`
            : null)}
        ${figure(T("res.storage"), nf(d.battery_kwh), "kWh", ref.battery_life_years
            ? T("res.battery_life", { n: nf(ref.battery_life_years, 1) }) : null)}
        ${figure(T("res.conversion"), nf(d.inverter_kw, 1), "kW")}
        ${figure(T("res.generator"), nf(d.generator_kw), "kW")}
      </div>
      <p style="margin:16px 0 0">
        <span class="badge ${proven.first_stage ? "ok" : "warn"}">${
          proven.first_stage ? T("sizing.proven.yes") : T("sizing.proven.no")}</span>
        ${info("sizing.proven.hint")}
      </p>
    </div>

    <div class="card">
      <h3>${T("plan.cost")}</h3>
      <div class="figures">
        ${figure(T("plan.expected_lcoe"), perKwh(e.expected_lcoe_usd_kwh), unit("/kWh"),
                 `${T("res.target")} ${perKwh(ref.tariff_target_usd_kwh)}`)}
        ${figure(T("plan.expected_cost"), amount(e.expected_rule_cost_usd), currency.code)}
        ${figure(T("res.subsidy"), sub ? pct(sub * 100) : T("res.subsidy.none"), "",
                 sub ? T("res.subsidy", { n: `${amount(ref.subsidy_usd)} ${currency.code}` })
                     : T("res.subsidy.met"))}
        ${figure(T("plan.gap"), pct(e.price_of_heuristic_pct), "")}
      </div>
      <p class="hint" style="margin-top:12px">${T("plan.upper")}</p>
    </div>

    ${(tree.per_node || []).length ? `
    <div class="card">
      <h3>${T("tree.title")}</h3>
      <p class="hint" style="margin-bottom:16px">${T("tree.lead")}</p>
      <div class="tree-scroll">${chartTree(tree)}</div>
      <p class="hint" style="margin-top:14px">${
        T("plan.tree", { nodes: nf(tree.nodes), leaves: nf(tree.leaves) })}</p>
      ${Object.keys(tree.reduction_error || {}).length ? `<p class="hint"
        style="margin-top:6px">${T("tree.error", { list: Object.entries(tree.reduction_error)
          .sort((a, b) => a[0] - b[0])
          .map(([year, e]) => `${year} — ${pct(e * 100, 1)}`).join(" · ") })}</p>` : ""}
    </div>` : ""}

    ${r.agreement ? `
    <div class="card">
      <h3>${T("sizing.reference")}</h3>
      <table class="compare">
        <tr><th>${T("res.quantity")}</th><th>${T("sizing.build")}</th>
            <th>${T("sizing.reference")}</th><th>${T("sizing.difference")}</th></tr>
        ${rows.map(([key, k, dp, u]) => {
          const a = r.agreement[k];
          if (!a) return "";
          const same = Math.abs(a.difference) < 1e-6;
          return `<tr><td>${T(key)}</td>
            <td>${nf(a.first_stage, dp)} ${u}</td>
            <td>${nf(a.reference_year, dp)} ${u}</td>
            <td class="${same ? "same" : "gap"}">${same ? "—"
              : `${a.difference > 0 ? "+" : ""}${nf(a.difference, dp)} ${u}`}</td></tr>`;
        }).join("")}
      </table>
      <p style="margin:14px 0 0">
        <span class="badge ${proven.reference_year ? "ok" : "warn"}">${
          proven.reference_year ? T("res.proven") : T("res.unproven")}</span>
      </p>
      <p class="hint" style="margin-top:10px">${T("sizing.reference.hint")}</p>
      ${(ref.binding_ceilings || []).length ? `<p class="hint" style="margin-top:8px">${
        T("res.ceiling_binds", {
          which: ref.binding_ceilings.map(c => T(`res.ceiling.${c}`)).join(", ") })}</p>` : ""}
    </div>` : ""}

    ${ref.dispatch ? `
    <div class="card">
      <h3>${T("res.week")}</h3>
      ${chartWeek(ref.dispatch)}
      <p class="hint" style="margin-top:14px">${T("res.week.hint")}</p>
    </div>
    <div class="card">
      <h3>${T("res.year")}</h3>
      ${chartMonths(ref.dispatch.monthly)}
    </div>` : ""}

    ${ref.finance ? `
    <div class="card">
      <h3>${T("fin.title")}</h3>
      <div class="figures">
        ${figure(T("fin.irr"), ref.finance.irr === null ? T("fin.irr.none")
                 : pct(ref.finance.irr * 100), "",
                 ref.finance.irr === null ? T("fin.irr.never")
                 : (ref.finance.irr_without_salvage === null
                    || ref.finance.irr_without_salvage === undefined
                    ? T("fin.at_tariff", {
                        tariff: `${perKwh(ref.tariff_target_usd_kwh)} ${unit("/kWh")}` })
                    : T("fin.bare_irr", { rate: pct(ref.finance.irr_without_salvage * 100) })))}
        ${figure(T("fin.payback"),
                 ref.finance.payback_years === null ? T("fin.payback.never")
                 : nf(ref.finance.payback_years, 1),
                 ref.finance.payback_years === null ? "" : T("fin.years"),
                 ref.finance.discounted_payback_years === null ? T("fin.disc_never")
                 : T("fin.disc", { n: nf(ref.finance.discounted_payback_years, 1) }))}
        ${figure(T("fin.npv"), amount(ref.finance.net_present_value_usd), currency.code)}
        ${figure(T("fin.capital"), amount(ref.finance.initial_capital_usd), currency.code,
                 ref.finance.subsidy_usd
                   ? T("fin.of_which", { n: amount(ref.finance.subsidy_usd) }) : null)}
      </div>
      <table style="margin-top:18px">
        <tr><th>${T("fin.year")}</th><th>${T("fin.investment")}</th><th>${T("fin.operating")}</th>
            <th>${T("fin.revenue")}</th><th>${T("fin.salvage")}</th><th>${T("fin.net")}</th></tr>
        ${ref.finance.cash_flows.filter(c => c.year <= 3 || c.capital > 0 ||
            c.year === ref.finance.cash_flows.length - 1).slice(0, 9).map(c => `<tr>
          <td>${c.year}</td><td>${c.capital ? amount(c.capital) : "—"}</td>
          <td>${c.operating ? amount(c.operating) : "—"}</td>
          <td>${c.revenue ? amount(c.revenue) : "—"}</td>
          <td>${c.salvage ? amount(c.salvage) : "—"}</td>
          <td><b>${amount(c.net)}</b></td></tr>`).join("")}
      </table>
      ${ref.infrastructure_usd ? `<p class="hint" style="margin-top:10px">${
          T("fin.beyond_plant", { n: `${amount(ref.infrastructure_usd)} ${currency.code}` })}</p>`
        : `<p class="hint warn" style="margin-top:10px">${T("fin.plant_only")}</p>`}
      <p class="hint" style="margin-top:12px">${T("fin.hint")}
         ${ref.finance_unsubsidised && ref.finance.subsidy_usd
           ? T("fin.unsubsidised", { rate: ref.finance_unsubsidised.irr === null
               ? T("fin.irr.none") : pct(ref.finance_unsubsidised.irr * 100) }) : ""}
         ${T("fin.replacements")}</p>
    </div>` : ""}

    <div class="card">
      <h3>${T("res.how")}</h3>
      <table>
        <tr><th>${T("res.quantity")}</th><th>${T("res.value")}</th></tr>
        <tr><td>${T("res.lattice")}</td><td>${nf(ref.lattice_size)}</td></tr>
        <tr><td>${T("res.pruned")}</td><td>${nf(ref.pruned_points)}</td></tr>
        <tr><td>${T("res.simulated")}</td><td>${nf(ref.enumerated_points)}</td></tr>
        <tr><td>${T("res.relaxations")}</td><td>${nf(ref.relaxations)}</td></tr>
        <tr><td>${T("plan.evaluations")}</td><td>${nf(e.search_evaluations)}</td></tr>
        <tr><td>${T("res.seconds")}</td><td>${nf(ref.seconds, 1)} s</td></tr>
      </table>
      <p class="hint" style="margin-top:12px">${T("res.coverage")}</p>
      <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn quiet" onclick="exportResult('csv')">${T("action.export_csv")}</button>
        <button class="btn quiet" onclick="exportResult('json')">${T("action.export_json")}</button>
        <button class="btn quiet" onclick="printReport()">${T("action.print")}</button>
      </div>
    </div>`;
}


/* ------------------------------------------------------------------ the new project page
   Everything asked for here comes off a field survey: a name, a point on a map, a count of
   households by type and a roster of the enterprises the village runs. Nothing on this page
   has to be guessed at a desk, and nothing that can be derived is asked for -- the time zone
   follows from the longitude, and the interface reads it there rather than inviting an hour
   of error into the one place a storage sizing is least able to absorb it. */
let map = null, pin = null;

function renderCommunity() {
  const s = state.site || {};
  const tpl = s.origin === "template";
  const roster = s.productive_mix || {};
  const lock = tpl ? " disabled" : "";

  $("#lieu").innerHTML = `
    <div class="card">
      <div class="field">
        <div><label for="project-name">${T("proj.name")}</label>${info("proj.name.hint")}</div>
        <div class="control"><input id="project-name" type="text"
             placeholder="${esc(T("proj.placeholder"))}" value="${esc(state.projectName)}"></div>
      </div>
      <div class="field">
        <div><label for="site-name">${T("site.name")}</label>${info("site.name.hint")}</div>
        <div class="control"><input id="site-name" type="text"
             value="${esc(s.name ?? "")}"${lock}></div>
      </div>
    </div>

    <div class="card">
      <h3>${T("site.where")}</h3>
      <div id="map"></div>
      <div class="coords">
        <div><label for="lat">${T("site.latitude")}</label>
          <input id="lat" type="number" step="0.0001" value="${s.latitude ?? ""}"></div>
        <div><label for="lon">${T("site.longitude")}</label>
          <input id="lon" type="number" step="0.0001" value="${s.longitude ?? ""}"></div>
      </div>
      <p class="hint" style="margin-top:12px">${T("site.map.hint")}</p>
      <p class="hint" id="utc-derived" style="margin-top:6px"></p>
      <div class="hidden" id="utc-fix" style="margin-top:8px;display:flex;gap:8px;
           align-items:center;max-width:280px">
        <label for="utc" style="font-size:12.5px;color:var(--ink-soft)">${T("site.utc")}</label>
        <input id="utc" type="number" min="-12" max="14" step="1" style="width:84px">
      </div>
      <div style="margin-top:16px;display:flex;gap:10px;align-items:center">
        <button class="btn quiet" id="get-resource"
          ${s.latitude == null ? "disabled" : ""}>${T("action.fetch_resource")}</button>
        ${s.has_resource ? `<span class="badge ok">${T("site.series.have")}</span>`
                         : `<span class="badge warn">${T("site.series.none")}</span>`}
        ${tpl || !state.sites.some(x => x.name === s.name) ? "" : `
          <div class="spacer" style="flex:1"></div>
          <button class="btn link" id="site-drop">${T("action.delete")}</button>`}
      </div>
      ${s.has_resource ? "" : `<p class="hint" style="margin-top:10px">${T("site.series.hint")}</p>`}
    </div>

    <div class="card">
      <div class="field wide">
        <div><label for="hh1">${T("site.households")}</label>${info("site.households.hint")}</div>
        <div class="control" style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
          ${["HH1", "HH2", "HH3"].map(k => `<div>
             <label for="${k.toLowerCase()}"
               style="font-size:11.5px;color:var(--ink-faint)">${k}</label>
             <input id="${k.toLowerCase()}" type="number" min="0" step="1"
               value="${(s.census || {})[k] ?? 0}"${lock}></div>`).join("")}
        </div>
      </div>
      <div class="field wide">
        <div><label>${T("site.productive")}</label>${info("site.productive.hint")}</div>
        <div class="control">
          <div class="roster">
            ${state.classes.map(c => {
              const n = roster[c.key] || 0;
              return `<label class="pue${n ? " on" : ""}" data-class="${esc(c.key)}">
                <input type="checkbox" data-pue="${esc(c.key)}"${n ? " checked" : ""}${lock}>
                <span class="lbl">${esc(c.label)}${info(`pue.${c.key}.hint`)}</span>
                <input type="number" min="0" step="1" data-count="${esc(c.key)}"
                  aria-label="${esc(c.label)} — ${esc(T("pue.count"))}"
                  value="${n || ""}" placeholder="0"${n ? "" : " disabled"}${lock}>
              </label>`;
            }).join("")}
          </div>
          <div class="roster-foot" id="pue-total"></div>
        </div>
      </div>
    </div>`;

  $("#project-name").oninput = e => state.projectName = e.target.value;

  const drop = $("#site-drop");
  if (drop) drop.onclick = async () => {
    await fetch(`/api/sites/${encodeURIComponent(state.site.name)}`, { method: "DELETE" });
    state.site = null;
    await refreshSites();
    openHome();
  };
  $("#get-resource").onclick = async () => {
    if (!state.site.has_resource && state.site.origin === "user" && !(await saveSite())) return;
    const r = await fetch(`/api/sites/${encodeURIComponent(state.site.name)}/resource`,
                          { method: "POST" });
    state.job = await r.json();
    buttons(false); $("#cancel").classList.remove("hidden"); poll();
  };

  ["lat", "lon"].forEach(id => $("#" + id).addEventListener("change", () => {
    const lat = parseFloat($("#lat").value), lon = parseFloat($("#lon").value);
    if (Number.isFinite(lat) && Number.isFinite(lon)) place(lat, lon, true);
    showTimezone();
  }));

  $$("#lieu input[data-pue]").forEach(box => box.onchange = e => {
    const key = e.target.dataset.pue;
    const count = $(`#lieu input[data-count="${key}"]`);
    count.disabled = !e.target.checked;
    if (e.target.checked && !count.value) count.value = 1;
    if (!e.target.checked) count.value = "";
    e.target.closest(".pue").classList.toggle("on", e.target.checked);
    readRoster();
  });
  $$("#lieu input[data-count]").forEach(box => box.oninput = readRoster);

  readRoster();
  showTimezone();
  mountMap(s.latitude, s.longitude);
}

/* The roster the reader has ticked, kept on the site as it is typed so that a page rebuilt
   in another language, or returned to from the next step, still holds it. */
function readRoster() {
  const mix = {};
  $$("#lieu input[data-count]").forEach(box => {
    const n = parseInt(box.value || "0", 10);
    if (Number.isFinite(n) && n > 0) mix[box.dataset.count] = n;
  });
  if (state.site) state.site.productive_mix = mix;
  const total = Object.values(mix).reduce((a, b) => a + b, 0);
  const foot = $("#pue-total");
  if (foot) foot.textContent = total ? T("pue.total", { n: nf(total) }) : T("pue.none");
}

function mountMap(lat, lon) {
  const host = $("#map");
  if (!host) return;
  // The page is rebuilt on every language change and on every move between communities,
  // and each rebuild is a new container. The old map and the old marker have to go with the
  // old container: keeping the marker meant a point placed afterwards was moved on a map
  // that had already been thrown away, and the new one showed nothing.
  if (map) { try { map.remove(); } catch { /* already detached with its container */ } }
  map = null; pin = null;
  // Leaflet is vendored, but its tiles are not: with no network the map is a grey box, and
  // a grey box with nothing written in it reads as a broken page rather than as a missing
  // connection. The coordinates below remain the authority either way.
  if (typeof L === "undefined") {
    host.outerHTML = `<div class="offline" id="map">${T("site.map.hint")}</div>`;
    return;
  }
  map = L.map(host, { attributionControl: true })
           .setView([lat ?? 9.5, lon ?? 2.3], lat == null ? 5 : 13);
  L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png",
              { maxZoom: 19, attribution: "© OpenStreetMap" }).addTo(map);
  // A field office may have no network. The map then shows nothing, which must not stop the
  // work: the coordinate boxes remain the authority and the map only ever mirrors them.
  map.on("click", e => place(e.latlng.lat, e.latlng.lng, false));
  if (lat != null && lon != null) place(lat, lon, false);
}

function place(lat, lon, recentre) {
  if (!state.site) return;
  state.site.latitude = Math.round(lat * 1e6) / 1e6;
  state.site.longitude = Math.round(lon * 1e6) / 1e6;
  $("#lat").value = state.site.latitude;
  $("#lon").value = state.site.longitude;
  $("#get-resource").disabled = false;
  showTimezone();
  if (!map) return;
  if (pin) pin.setLatLng([lat, lon]);
  else pin = L.marker([lat, lon], { draggable: true }).addTo(map)
               .on("dragend", ev => { const p = ev.target.getLatLng(); place(p.lat, p.lng, false); });
  if (recentre) map.setView([lat, lon], Math.max(map.getZoom(), 13));
}

/* Not a question any more, an observation. Solar noon follows longitude at fifteen degrees
   an hour and the zone a country keeps is usually the nearest whole hour to it; the server
   derives the same figure from the same coordinate, and this only says what it will be, and
   where to correct it for the countries that keep another. */
function showTimezone() {
  const line = $("#utc-derived");
  if (!line) return;
  const lon = parseFloat($("#lon")?.value);
  if (!Number.isFinite(lon)) { line.textContent = ""; return; }
  const derived = Math.round(lon / 15);
  const minutes = Math.round((derived - lon / 15) * 60);
  const solar = minutes >= 0 ? `12:${String(minutes).padStart(2, "0")}`
                             : `11:${String(60 + minutes).padStart(2, "0")}`;
  const box = $("#utc");
  const chosen = state.site?.utc_offset_hours;
  if (box && box.value === "") box.value = chosen ?? derived;
  line.innerHTML = `${esc(T("site.utc.derived",
      { offset: `${derived >= 0 ? "+" : ""}${derived}`, solar }))}
    <button class="btn link" type="button" id="utc-show"
      style="font-size:12.5px">${T("site.utc.adjust")}</button>${info("site.utc.adjust.hint")}`;
  $("#utc-show").onclick = () => $("#utc-fix").classList.toggle("hidden");
  if (box) box.oninput = () => {
    const v = parseInt(box.value, 10);
    if (state.site) state.site.utc_offset_hours = Number.isFinite(v) ? v : null;
  };
}

function fail(key) {
  setState(`<b>${T("state.failed")}</b> ${T(key)}`, null);
  return false;
}

async function saveSite() {
  const s = state.site;
  if (!s || s.origin === "template") return true;
  const name = ($("#site-name")?.value || s.name || "").trim();
  const lat = parseFloat($("#lat").value), lon = parseFloat($("#lon").value);
  readRoster();
  const census = Object.fromEntries(["HH1", "HH2", "HH3"].map(
    k => [k, parseInt($("#" + k.toLowerCase()).value || 0, 10)]));
  const households = Object.values(census).reduce((a, b) => a + b, 0);
  // Said before the request rather than after it: a name, a point and somebody to connect
  // are what the rest of the study is built on, and a run that fails a minute in for want
  // of one of them is a worse way to find out.
  if (!name) return fail("state.need_name");
  if (!Number.isFinite(lat) || !Number.isFinite(lon)) return fail("state.need_point");
  if (households <= 0) return fail("state.need_households");
  const body = {
    name, latitude: lat, longitude: lon, census,
    productive_mix: state.site.productive_mix || {},
  };
  const offset = parseInt($("#utc")?.value ?? "", 10);
  if (Number.isFinite(offset) && offset !== Math.round(lon / 15)) body.utc_offset_hours = offset;
  const r = await fetch("/api/sites", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body)
  });
  if (!r.ok) { setState(T("state.site_failed"), null); return false; }
  state.overrides["site"] = body.name;
  await refreshSites(body.name);
  await saveProject();
  setState(T("state.site_saved", { name: body.name }), null);
  return true;
}

async function refreshSites(select) {
  state.sites = await (await fetch("/api/sites")).json();
  const name = select || state.overrides["site"];
  state.site = state.sites.find(x => x.name === name) || state.sites[0];
  state.overrides["site"] = state.site.name;
  renderCommunity();
  await loadArchetypes();
}

/* The study is saved as the reader moves through it rather than behind a button they have
   to remember. A project that exists only in a window is one lost to a closed window. */
async function saveProject() {
  const name = (state.projectName || state.site?.name || "").trim();
  if (!name) return;
  state.projectName = name;
  const r = await fetch("/api/projects", {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, overrides: state.overrides,
                           results: { size: state.result } })
  });
  if (r.ok) state.projects = await (await fetch("/api/projects")).json();
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
            <span>${nf(x.share_pct, 1)} ${T("arch.share")} · ${nf(x.n_observations)} ${T("arch.records")}
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
function printReport() {
  // Print, rather than a PDF written by hand: the browser already lays this page out and
  // already knows how to make a file of it, and a second renderer would be a second thing
  // to keep in step with the first. The print stylesheet decides what reaches the sheet.
  const header = document.createElement("div");
  header.className = "print-only";
  header.innerHTML = `<div style="margin-bottom:18px">
      <h1 style="font-size:22px;margin:0">${T("print.title")} — ${state.site?.name ?? ""}</h1>
      <p style="color:#444;margin:6px 0 0;font-size:11px">
        ${state.projectName ? state.projectName + " · " : ""}
        ${T("print.issued", { date: new Date().toLocaleDateString(
            state.lang === "fr" ? "fr-FR" : "en-GB", { dateStyle: "long" }) })} ·
        ${T("print.amounts", { code: currency.code })}${currency.per_usd !== 1
          ? ` (1 USD = ${nf(currency.per_usd, 2)} ${currency.code})` : ""}</p>
      <p style="color:#444;margin:8px 0 0;font-size:10.5px">
        ${T("print.behaviour")} ${state.arch?.adjusted
          ? T("print.arch.adjusted") : T("print.arch.shipped")}
        ${state.arch?.note ?? ""}</p>
    </div>`;
  const main = $(".main");
  main.prepend(header);
  window.print();
  setTimeout(() => header.remove(), 500);
}

async function exportResult(format) {
  const result = state.result;
  if (!result) return;
  const r = await fetch(`/api/export.${format}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ result, lang: state.lang })
  });
  const blob = await r.blob();
  const name = (r.headers.get("Content-Disposition") || "").match(/filename="([^"]+)"/);
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name ? name[1] : `export.${format}`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ------------------------------------------------------------------ the front door
   Drawn, not photographed. A picture of a rural mini-grid would have to be licensed,
   shipped and kept, and would show one village while the tool is for any; a drawing costs
   nothing to carry and renders in a field office with no network. */

function heroArt() {
  return `<svg viewBox="0 0 640 380" role="img" aria-label="${esc(T("home.art.alt"))}">
    <defs>
      <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#8ec5e8"/><stop offset=".58" stop-color="#ffdcb0"/>
        <stop offset="1" stop-color="#ffc58a"/>
      </linearGradient>
      <linearGradient id="soil" x1="0" y1="0" x2="0" y2="1">
        <stop offset="0" stop-color="#dcb888"/><stop offset="1" stop-color="#b98d55"/>
      </linearGradient>
      <linearGradient id="glass" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stop-color="#2d5075"/><stop offset="1" stop-color="#1a3151"/>
      </linearGradient>
    </defs>

    <rect width="640" height="380" fill="url(#sky)"/>
    <circle cx="512" cy="96" r="70" fill="#ffd166" opacity=".2"/>
    <circle cx="512" cy="96" r="40" fill="#ffd166"/>

    <!-- the far bush, flat so that it reads as distance and not as detail -->
    <path d="M0 214 Q76 190 148 210 T292 204 Q372 182 448 206 T596 200 Q620 194 640 208
             L640 246 L0 246 Z" fill="#9db77c" opacity=".5"/>
    <rect y="230" width="640" height="150" fill="url(#soil)"/>

    <!-- an acacia, because a savannah with no tree in it reads as a car park -->
    <g>
      <path d="M52 272 L52 224" stroke="#6b4f2f" stroke-width="4.5" fill="none"/>
      <ellipse cx="52" cy="220" rx="34" ry="10" fill="#7ca055"/>
      <path d="M22 222 Q52 202 82 222 Q52 212 22 222 Z" fill="#6f8f4e"/>
    </g>

    <!-- the village: round earth walls, conical thatch -->
    <g>
      <ellipse cx="146" cy="292" rx="54" ry="9" fill="#000" opacity=".08"/>
      <rect x="114" y="248" width="64" height="44" rx="4" fill="#c9a279"/>
      <path d="M102 250 L146 206 L190 250 Z" fill="#a8763f"/>
      <path d="M112 248 L146 212 M128 248 L146 214 M164 248 L146 214 M180 248 L146 212"
            stroke="#8d6134" stroke-width="1.4" opacity=".55"/>
      <rect x="137" y="266" width="18" height="26" rx="2" fill="#7a5a3c"/>
      <circle cx="166" cy="242" r="3" fill="#ffd166"/>
    </g>
    <g>
      <ellipse cx="238" cy="286" rx="40" ry="7" fill="#000" opacity=".08"/>
      <rect x="214" y="254" width="48" height="32" rx="4" fill="#d0aa83"/>
      <path d="M204 256 L238 224 L272 256 Z" fill="#b5834a"/>
      <rect x="232" y="268" width="13" height="18" rx="2" fill="#7a5a3c"/>
      <circle cx="254" cy="248" r="2.6" fill="#ffd166"/>
    </g>

    <!-- the power house: the plant the tool sizes, and the room its storage sits in -->
    <g>
      <ellipse cx="338" cy="292" rx="46" ry="8" fill="#000" opacity=".07"/>
      <rect x="306" y="252" width="66" height="40" rx="3" fill="#ece8e0"/>
      <path d="M300 252 L339 232 L378 252 Z" fill="#949aa3"/>
      <rect x="332" y="272" width="15" height="20" rx="1.5" fill="#6f7681"/>
      <rect x="313" y="260" width="13" height="9" rx="1.5" fill="#9fc4de"/>
      <rect x="354" y="260" width="13" height="9" rx="1.5" fill="#9fc4de"/>
    </g>

    <!-- the array, tilted south, on its frames -->
    <g>
      <ellipse cx="500" cy="312" rx="122" ry="11" fill="#000" opacity=".07"/>
      ${[[398, 268], [472, 282], [546, 268]].map(([x, y]) => `
        <g transform="translate(${x} ${y})">
          <path d="M0 0 L86 0 L73 -34 L-13 -34 Z" fill="url(#glass)"/>
          <path d="M-13 -34 L73 -34 L86 0 L0 0 Z" fill="none" stroke="#16293f"
                stroke-width="1.6"/>
          <path d="M8 0 L-5 -34 M30 0 L17 -34 M52 0 L39 -34 M73 0 L60 -34"
                stroke="#4f7ba6" stroke-width=".9" opacity=".65"/>
          <path d="M-6 -17 L79 -17" stroke="#4f7ba6" stroke-width=".9" opacity=".65"/>
          <rect x="15" y="0" width="5" height="24" fill="#7d7f85"/>
          <rect x="58" y="0" width="5" height="17" fill="#7d7f85"/>
        </g>`).join("")}
    </g>

    <!-- the low-voltage line: what the plant is worth nothing without, and what the tool
         now prices alongside it -->
    <g stroke="#6b6f76" stroke-width="2.2" fill="none">
      <path d="M96 292 L96 196"/><path d="M204 288 L204 204"/><path d="M296 292 L296 212"/>
      <path d="M96 202 Q150 218 204 210" stroke-width="1.4"/>
      <path d="M204 210 Q252 224 296 218" stroke-width="1.4"/>
      <path d="M86 204 L106 204"/><path d="M194 212 L214 212"/>
    </g>
    <circle cx="96" cy="194" r="3.4" fill="#ffd166"/>
    <circle cx="204" cy="202" r="3.4" fill="#ffd166"/>
  </svg>`;
}


const ICONS = {
  new: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
          stroke-linecap="round" stroke-linejoin="round">
          <path d="M5 3h9l5 5v13a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/>
          <path d="M14 3v5h5"/><path d="M12 11v7"/><path d="M8.5 14.5h7"/></svg>`,
  open: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
           stroke-linecap="round" stroke-linejoin="round">
           <path d="M3 7a1 1 0 0 1 1-1h5l2 2.5h8a1 1 0 0 1 1 1V19a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>
           <path d="M3 11h18"/></svg>`,
  test: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"
           stroke-linecap="round" stroke-linejoin="round">
           <path d="M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18Z"/>
           <path d="M12 3c-3 3.4-3 14.6 0 18"/><path d="M12 3c3 3.4 3 14.6 0 18"/>
           <path d="M3.5 9.5h17"/><path d="M3.5 14.5h17"/></svg>`,
};

/* A drawn day, not a computed one: the shape of a plant running on its array by day, on
   its storage in the evening and on its generating set at the tail of a bad night. */
function sparkDay() {
  const W = 260, H = 96, n = 24;
  const pv   = [0,0,0,0,0,0,.6,3.4,7.2,10.4,12.6,13.4,13.1,12.2,10.2,7.1,3.6,.9,0,0,0,0,0,0];
  const bat  = [1.2,1,.9,.8,.8,1,1.4,.6,0,0,0,0,0,0,0,0,2.6,6.4,8.2,7.4,5.6,4,2.6,1.7];
  const gen  = [0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,1.6,2.4,1.2,0,0,0];
  const load = pv.map((v, i) => Math.min(v, 9) + bat[i] + gen[i]);
  const ymax = Math.max(...load, ...pv) * 1.12;
  const x = i => (i / (n - 1)) * W;
  const y = v => H - (v / ymax) * H;
  const band = (values, base, colour) => {
    const top = values.map((v, i) => base[i] + v);
    const pts = top.map((v, i) => `${x(i)},${y(v)}`).join(" ");
    const back = base.map((v, i) => `${x(i)},${y(v)}`).reverse().join(" ");
    return { poly: `<polygon points="${pts} ${back}" fill="${colour}" fill-opacity=".9"/>`,
             top };
  };
  const zero = new Array(n).fill(0);
  const a = band(pv.map(v => Math.min(v, 9)), zero, COLOURS.pv_load);
  const b = band(bat, a.top, COLOURS.discharge);
  const c = band(gen, b.top, COLOURS.generator);
  return `<svg class="chart" viewBox="0 0 ${W} ${H}" role="img"
      aria-label="${esc(T("home.sample.dispatch"))}" style="height:96px">
      ${a.poly}${b.poly}${c.poly}
      <polyline points="${load.map((v, i) => `${x(i)},${y(v)}`).join(" ")}"
        fill="none" stroke="var(--ink)" stroke-width="1.4"/>
    </svg>
    <div class="legend" style="margin-top:10px">
      <span><i style="background:${COLOURS.pv_load}"></i>${T("chart.pv_load")}</span>
      <span><i style="background:${COLOURS.discharge}"></i>${T("chart.discharge")}</span>
      <span><i style="background:${COLOURS.generator}"></i>${T("chart.generator")}</span>
    </div>`;
}

/* The sample is the published certificate for Samionta under mixed coupling, not invented
   numbers: a homepage that shows a plausible plant and a plausible tariff is read as a
   result whatever the caption says, so the figures shown are ones the tool has produced. */
const SAMPLE = { pv_kw: 57.5, battery_kwh: 135, inverter_kw: 25, generator_kw: 8,
                 lcoe: 0.2104, tariff: 0.263 };

function renderHome() {
  $("#hero-art").innerHTML = heroArt();
  $("#icon-new").innerHTML = ICONS.new;
  $("#icon-open").innerHTML = ICONS.open;
  $("#icon-test").innerHTML = ICONS.test;

  const row = (k, v, u) => `<div class="row"><span>${k}</span><b>${v}<small
      style="font-weight:500;color:var(--ink-soft)"> ${u}</small></b></div>`;
  $("#samples").innerHTML = `
    <div class="sample">
      <h3>${T("home.sample.plant")}</h3>
      <div class="rows">
        ${row(T("res.pv"), nf(SAMPLE.pv_kw, 1), "kW")}
        ${row(T("res.storage"), nf(SAMPLE.battery_kwh), "kWh")}
        ${row(T("res.conversion"), nf(SAMPLE.inverter_kw), "kW")}
        ${row(T("res.generator"), nf(SAMPLE.generator_kw), "kW")}
      </div>
    </div>
    <div class="sample">
      <h3>${T("home.sample.dispatch")}</h3>
      ${sparkDay()}
    </div>
    <div class="sample">
      <h3>${T("home.sample.tariff")}</h3>
      <div class="big">${nf(SAMPLE.lcoe, 3)}<small>USD/kWh</small></div>
      <p class="under">${T("res.target")} ${nf(SAMPLE.tariff, 3)} USD/kWh · ${
        T("res.subsidy.met")}</p>
    </div>`;

  // Saved studies and shipped villages, each opening straight onto the page it belongs on.
  // Listed rather than folded into a drop-down: a developer coming back to a village wants
  // to see which studies they have of it, not to search for one by name.
  const saved = $("#home-projects");
  saved.innerHTML = state.projects.length
    ? state.projects.map(p => `<div class="saved">
        <button class="btn" data-open="${esc(p.slug)}">${esc(p.name)}
          <span class="sub">${esc(p.site || "")}${p.has_result
            ? ` · ${T("home.open.answered")}` : ""}</span></button>
        <button class="drop" data-drop="${esc(p.slug)}"
          aria-label="${esc(T("action.delete"))}">×</button>
      </div>`).join("")
    : `<span class="none">${T("home.open.none")}</span>`;
  $$("#home-projects [data-open]").forEach(b => b.onclick = () => openProject(b.dataset.open));
  $$("#home-projects [data-drop]").forEach(b => b.onclick = async () => {
    await fetch(`/api/projects/${b.dataset.drop}`, { method: "DELETE" });
    state.projects = await (await fetch("/api/projects")).json();
    renderHome();
  });

  $("#home-examples").innerHTML = state.sites.filter(x => x.origin === "template")
    .map(x => `<button class="btn" data-example="${esc(x.name)}">${esc(x.name)}
        <span class="sub">${nf(x.n_households)} ${T("home.households")}</span>
      </button>`).join("");
  $$("#home-examples .btn").forEach(b => b.onclick = () => openExample(b.dataset.example));

  $("#door-new").onclick = startNewProject;
}

function openHome() {
  $("#home").classList.remove("hidden");
  $("#study").classList.add("hidden");
  window.scrollTo(0, 0);
}

function openStudy(page) {
  $("#home").classList.add("hidden");
  $("#study").classList.remove("hidden");
  show(page || "project");
}

function startNewProject() {
  state.projectName = "";
  state.result = null;
  state.reached = 1;
  state.site = { name: T("site.new.name"), origin: "user",
                 census: { HH1: 0, HH2: 0, HH3: 0 }, n_households: 0,
                 productive_units: null, productive_mix: {},
                 latitude: null, longitude: null };
  renderCommunity();
  renderSizing(null);
  openStudy("project");
  loadArchetypes();
}

async function openProject(slug) {
  const p = await (await fetch(`/api/projects/${slug}`)).json();
  state.overrides = { ...state.overrides, ...p.overrides };
  state.projectName = p.name;
  state.result = (p.results || {}).size || null;
  state.reached = state.result ? PAGES.length : PAGES.length - 1;
  for (const g of state.groups) for (const f of g.fields)
    if (p.overrides[f.path] !== undefined) f.value = p.overrides[f.path];
  await refreshSites(p.overrides.site);
  renderForm();
  renderSizing(state.result);
  openStudy(state.result ? "sizing" : "project");
  setState(T("proj.opened", { name: p.name }), null);
}

async function openExample(name) {
  state.projectName = name;
  state.result = null;
  state.reached = PAGES.length - 1;
  state.overrides["site"] = name;
  await refreshSites(name);
  renderSizing(null);
  openStudy("project");
}

/* ------------------------------------------------------------------ moving through the pages
   Four pages in the order the work is done. A page not yet reached is closed, because the
   decision at the end rests on the three before it: a study launched from a community with
   no coordinates fails a minute in, which is a worse way to learn it than a step that has
   not opened yet. */
const PAGES = [
  { id: "project",     label: "page.project.title" },
  { id: "uses",        label: "nav.uses" },
  { id: "assumptions", label: "nav.assumptions" },
  { id: "sizing",      label: "page.sizing.title" },
];

const pageIndex = id => Math.max(0, PAGES.findIndex(p => p.id === id));

function renderSteps() {
  const here = pageIndex(state.page);
  $("#steps").innerHTML = PAGES.map((p, i) => `
    <li><button data-view="${p.id}" ${i < state.reached ? "" : "disabled"}
        aria-current="${i === here}">
      <span class="n">${i + 1}</span>
      <span class="lbl">${T(p.label)}</span>
    </button></li>`).join("");
  $$("#steps button").forEach(b => b.onclick = () => show(b.dataset.view));

  // The last page is where the decision is read, so the button that reaches it is the one
  // that computes it: one button, one action, in the place the eye already is. On the
  // decision itself it recomputes, which is what a reader who has just changed an
  // assumption and come back wants it to do.
  const last = PAGES.length - 1;
  $("#next").textContent = here < last - 1 ? T("wiz.next")
    : (here === last && state.result ? T("sizing.again") : T("action.size"));
  $("#back").classList.toggle("hidden", here === 0);
}

function show(view) {
  state.page = view;
  state.reached = Math.max(state.reached, pageIndex(view) + 1);
  $$(".page").forEach(p => p.classList.toggle("hidden", p.dataset.page !== view));
  renderSteps();
  window.scrollTo({ top: 0, behavior: "smooth" });
  // The map draws itself against a container of zero height while its page is hidden, and
  // stays that way until it is told the container has grown.
  if (view === "project" && map) setTimeout(() => map.invalidateSize(), 60);
}

async function goNext() {
  if (state.page === "project") {
    // The community is saved on the way out rather than behind a button of its own: what
    // was typed is what the next page reads, and a study run against a half-saved village
    // is the kind of error that only shows up in its results.
    if (state.site && state.site.origin !== "template" && !(await saveSite())) return;
    show("uses");
    return;
  }
  if (state.page === "uses") { show("assumptions"); return; }
  if (state.page === "assumptions") show("sizing");   // the run fills it as it arrives
  launch();
}

const goBack = () => show(PAGES[Math.max(0, pageIndex(state.page) - 1)].id);


/* ------------------------------------------------------------------ running */
async function launch() {
  const r = await fetch("/api/size", {
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
    setState(`<b>${T(job.label, job.label_args)}</b> — ${T(job.stage, job.stage_args)}`,
             job.fraction);
    if (job.status === "running") return;

    clearInterval(state.timer);
    $("#cancel").classList.add("hidden");
    buttons(true);
    if (job.status !== "done") {
      setState(`<b>${T(job.label, job.label_args)}</b> — ${T("job." + job.status)}. ${
        job.error ?? ""}`, null);
      return;
    }
    setState(`<b>${T(job.label, job.label_args)}</b> — ${T("job.done")}.`, 1);
    // A weather series is fetched from the same bar as a decision, and answers with a site
    // rather than with a result. Telling them apart by what was asked for, rather than by
    // the shape of what came back, is what keeps an empty result page from appearing.
    if (job.kind === "resource") { await refreshSites(state.site?.name); return; }
    state.result = job.result;
    state.reached = PAGES.length;
    renderSizing(job.result);
    show("sizing");
    saveProject();
  }, 700);
}

function setState(html, fraction) {
  $("#state").innerHTML = html;
  const track = $("#track");
  track.classList.toggle("hidden", fraction === null || fraction === undefined);
  if (fraction !== null && fraction !== undefined)
    track.firstElementChild.style.width = `${Math.round(fraction * 100)}%`;
}

const buttons = on => $$("#next, #back").forEach(b => b.disabled = !on);


/* ------------------------------------------------------------------ start */
function refreshCurrency() {
  const code = state.overrides["currency.local_code"];
  const perEuro = parseFloat(state.overrides["currency.xof_per_eur"]);
  const dollarsPerEuro = parseFloat(state.overrides["currency.usd_per_eur"]);
  if (code && Number.isFinite(perEuro) && Number.isFinite(dollarsPerEuro) && dollarsPerEuro)
    currency = { code, per_usd: perEuro / dollarsPerEuro };
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
  for (const id of ["#lang", "#lang-home"]) {
    const picker = $(id);
    picker.innerHTML = Object.entries(b.languages || {})
      .map(([code, name]) => `<option value="${code}"${
        code === b.lang ? " selected" : ""}>${name}</option>`).join("");
    picker.onchange = e => setLanguage(e.target.value);
  }
  // On the first boot the server's values are the study; on a language change they are only
  // labels arriving in another language, and the reader's own values must survive them.
  const first = state.groups.length === 0;
  state.groups = b.groups;
  for (const g of b.groups) for (const f of g.fields) {
    state.defaults[f.path] = f.value;
    if (first) state.overrides[f.path] = f.value;
    else f.value = state.overrides[f.path];
  }
  state.projects = b.projects || [];
  state.sites = b.sites || [];
  if (first || !state.site || state.site.origin === "template")
    state.site = state.sites.find(x => x.name === state.overrides["site"]) || state.sites[0];
  state.classes = await (await fetch(`/api/productive-classes?lang=${b.lang}`)).json();

  refreshCurrency();
  renderHome();
  renderCommunity();
  renderSizing(state.result);
  await loadArchetypes();
  renderSteps();

  $("#go-home").onclick = openHome;
  $("#next").onclick = goNext;
  $("#back").onclick = goBack;
  $("#cancel").onclick = async () => {
    if (state.job) await fetch(`/api/job/${state.job.id}/cancel`, { method: "POST" });
  };
  // A run under way keeps its own line: the poller will repaint it in the new language on
  // its next tick, and overwriting it here would look like the run had stopped.
  if (!state.job || state.job.status !== "running") setState(T("state.ready"), null);
}

boot();
