/* The page. No framework: the surface is small enough that one would cost more than it saves,
   and a build step would put a toolchain between a developer and a tool meant to be run. */

const $  = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

const state = { groups: [], overrides: {}, defaults: {}, job: null, timer: null,
                results: { size: null, plan: null } };

/* ------------------------------------------------------------------ formatting */
const nf = (v, d = 0) => v === null || v === undefined || Number.isNaN(v)
  ? "—" : v.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });
const pct = (v, d = 1) => v === null || v === undefined ? "—" : nf(v, d) + " %";
const money = v => v === null || v === undefined ? "—" : nf(Math.round(v));

function figure(k, v, u, note) {
  return `<div class="figure"><div class="k">${k}</div>
    <div class="v">${v}${u ? `<span class="u">${u}</span>` : ""}</div>
    ${note ? `<div class="n">${note}</div>` : ""}</div>`;
}

/* ------------------------------------------------------------------ the form */
function renderForm() {
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
    : `<input id="${id}" data-path="${f.path}" type="number"
         step="${f.step ?? (f.kind === "integer" ? 1 : "any")}" value="${f.value}">`;
  return `<div class="field">
      <div>
        <label for="${id}">${f.label}</label>
        ${f.hint ? `<div class="hint">${f.hint}</div>` : ""}
        ${f.source ? `<div class="source"><b>Source</b><span>${f.source}</span></div>` : ""}
      </div>
      <div class="control">${control}${f.unit ? `<span class="unit">${f.unit}</span>` : ""}</div>
    </div>`;
}

/* ------------------------------------------------------------------ results */
function renderSize(r) {
  if (!r) {
    $("#result").innerHTML = `<div class="card empty"><h4>Rien à montrer pour l'instant</h4>
      <p>Lancez un dimensionnement depuis la barre du bas. Il faut de vingt secondes à deux
         minutes selon la localité.</p></div>`;
    return;
  }
  const d = r.design, total = d.pv_kw + (d.pv_ac_kw || 0);
  const sub = r.subsidy_fraction;
  const badge = r.proven
    ? `<span class="badge ok">Optimalité prouvée par épuisement</span>`
    : `<span class="badge warn">Recherche incomplète</span>`;
  $("#result").innerHTML = `
    <div class="card">
      <h3>Parc certifié — ${r.site}, croissance ${r.trajectory}</h3>
      <div class="figures">
        ${figure("Photovoltaïque", nf(total, 1), "kW",
                 d.pv_ac_kw ? `${nf(d.pv_kw,1)} bus batterie · ${nf(d.pv_ac_kw,1)} bus charge` : null)}
        ${figure("Stockage", nf(d.battery_kwh), "kWh")}
        ${figure("Conversion", nf(d.inverter_kw, 1), "kW")}
        ${figure("Groupe", nf(d.generator_kw), "kW")}
      </div>
      <p style="margin:16px 0 0">${badge}</p>
    </div>

    <div class="card">
      <h3>Ce que cela coûte</h3>
      <div class="figures">
        ${figure("Coût actualisé", nf(r.lcoe_usd_kwh, 4), "$/kWh",
                 `tarif visé ${nf(r.tariff_target_usd_kwh, 3)}`)}
        ${figure("Coût annualisé", money(r.z_rule_usd_yr), "$/an")}
        ${figure("Subvention", sub ? pct(sub * 100) : "aucune", "",
                 sub ? "pour atteindre le tarif" : "le tarif est atteint")}
        ${figure("Écart de dispatch", pct(r.price_rel_pct), "",
                 `${money(r.price_abs_usd_yr)} $/an`)}
      </div>
    </div>

    <div class="card">
      <h3>Comment le certificat a été obtenu</h3>
      <table>
        <tr><th>Grandeur</th><th>Valeur</th></tr>
        <tr><td>Dimensionnements de l'ensemble admissible</td><td>${nf(r.lattice_size)}</td></tr>
        <tr><td>Écartés par une borne, sans simulation</td><td>${nf(r.pruned_points)}</td></tr>
        <tr><td>Évalués par simulation</td><td>${nf(r.enumerated_points)}</td></tr>
        <tr><td>Programmes relaxés résolus</td><td>${nf(r.relaxations)}</td></tr>
        <tr><td>Durée</td><td>${nf(r.seconds, 1)} s</td></tr>
      </table>
      <p class="hint" style="margin-top:12px">Chaque dimensionnement de l'ensemble a été soit
         évalué, soit écarté par une borne dont la validité est démontrée. Aucun n'a été
         laissé de côté.</p>
    </div>`;
}

function renderPlan(r) {
  if (!r) {
    $("#plan").innerHTML = `<div class="card empty"><h4>Aucun plan calculé</h4>
      <p>Le plan d'extension construit un arbre de scénarios et le résout. Comptez de cinq à
         neuf minutes ; vous pouvez continuer à consulter le reste pendant ce temps.</p></div>`;
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
      <h3>À engager aujourd'hui — ${r.site}</h3>
      <div class="figures">
        ${figure("Photovoltaïque", nf(total, 1), "kW",
                 p.pv_ac_kw ? `${nf(p.pv_kw,1)} bus batterie · ${nf(p.pv_ac_kw,1)} bus charge` : null)}
        ${figure("Stockage", nf(p.battery_kwh), "kWh")}
        ${figure("Conversion", nf(p.inverter_kw, 1), "kW")}
        ${figure("Groupe", nf(p.generator_kw), "kW")}
      </div>
    </div>

    <div class="card">
      <h3>Ce que l'avenir décidera</h3>
      <table>
        <tr><th>Branche à l'année ${anneeBranche}</th><th>Probabilité</th>
            <th>Énergie à servir</th><th>Photovoltaïque</th><th>Stockage</th></tr>
        ${stage1.map((n, i) => {
          const champ = n.pv_kw + (n.pv_ac_kw || 0);
          const suite = champ > total + 1e-6 || n.battery_kwh > p.battery_kwh + 1e-6;
          return `<tr>
            <td>${i + 1}<span style="color:var(--ink-soft)"> — ${suite ? "agrandir" : "ne rien ajouter"}</span></td>
            <td>${pct(n.probability * 100, 0)}</td>
            <td>${nf(n.energy_served_kwh / 1000, 1)} MWh</td>
            <td>${nf(champ, 1)} kW</td>
            <td>${nf(n.battery_kwh)} kWh</td></tr>`;
        }).join("")}
      </table>
      <p class="hint" style="margin-top:12px">L'arbre compte ${nf(r.nodes)} nœuds et
         ${nf(r.leaves)} feuilles. Seule la première ligne est engagée ; les suivantes se
         décideront quand l'incertitude se sera levée.</p>
    </div>

    <div class="card">
      <h3>Ce que le plan coûte</h3>
      <div class="figures">
        ${figure("Coût actualisé attendu", nf(e.expected_lcoe_usd_kwh, 4), "$/kWh")}
        ${figure("Coût attendu", money(e.expected_rule_cost_usd), "$")}
        ${figure("Écart de dispatch", pct(e.price_of_heuristic_pct), "")}
        ${figure("Évaluations de plans", nf(e.search_evaluations), "")}
      </div>
      <p class="hint" style="margin-top:12px">Cet écart est un majorant : sur l'arbre, le plan
         provient d'une descente et non d'une certification par épuisement.</p>
    </div>`;
}

/* ------------------------------------------------------------------ running */
async function launch(kind) {
  const r = await fetch(`/api/${kind}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ overrides: state.overrides })
  });
  const job = await r.json();
  if (!r.ok) { setState(`<b>Échec.</b> ${job.detail ?? ""}`, null); return; }
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
    setState(`<b>${job.label}</b> — ${job.stage}`, job.fraction);
    if (job.status === "en cours") return;

    clearInterval(state.timer);
    $("#cancel").classList.add("hidden");
    buttons(true);
    if (job.status === "terminé") {
      state.results[job.kind] = job.result;
      job.kind === "size" ? renderSize(job.result) : renderPlan(job.result);
      show(job.kind === "size" ? "result" : "plan");
      setState(`<b>${job.label}</b> — terminé.`, 1);
    } else {
      setState(`<b>${job.label}</b> — ${job.status}. ${job.error ?? ""}`, null);
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
(async function boot() {
  const b = await (await fetch("/api/bootstrap")).json();
  state.groups = b.groups;
  for (const g of b.groups) for (const f of g.fields) {
    state.defaults[f.path] = f.value;
    state.overrides[f.path] = f.value;
  }
  renderForm(); renderSize(null); renderPlan(null);

  $$(".nav button").forEach(b => b.onclick = () => show(b.dataset.view));
  $("#run-size").onclick = () => launch("size");
  $("#run-plan").onclick = () => launch("plan");
  $("#cancel").onclick = async () => {
    if (state.job) await fetch(`/api/job/${state.job.id}/cancel`, { method: "POST" });
  };
})();
