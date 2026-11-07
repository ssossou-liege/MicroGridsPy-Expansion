# Progressive connection and persistent scenario trees

*Design specification, written 2026-11-06 (session 1 of the series). Nothing in it is
implemented yet. Session 2 implements sections 4 to 7 and 10; session 3 implements section 9;
section 8 spans both.*

Decisions D1 to D3 (section 2) are the author's and are not reopened here. Every other choice
is settled in this document. The few that are the author's to confirm are marked
**[decision n]**: each carries a default, which the sessions implement unless the author has
overridden it, and section 14 collects them.

## 1. Why this exists

**What the model does today.** Every household of the census is connected at year 0 and all
of them share one connection age: 231 households at Samionta and 159 at Gbowele, each twelve
months old when the year starts. That holds in the single certified year
(`instances.build_site_year` calls `demand.generator.simulate_demand_year` with
`maturity_months=12` and the whole `site.census`) and in the tree
(`scenarios.demand_paths.simulate_stage_demand` ages the same census by
`base_maturity_months + 12 * stage_year`). The formulation said the number of connections per
customer type was sampled; the code never sampled it.

**What the meters say.**

| | Samionta | Gbowele |
|---|---|---|
| Census, households | 231 | 159 |
| Customers with readings, by calendar year | 25 (2023), 37 (2024), 57 (2025) | 40 (2024), 95 (2025) |
| Customers with readings, Sept 2025 to Aug 2026 | 65 | 142 |
| Active in Aug 2026: households, productive users, churches | 43, 15, 2 | 82, 43, 2 |
| Logistic fit on monthly active households | plateau 48.1 (s.e. 3.7), r = 0.075 per month, midpoint July 2024 | still growing, plateau not identifiable |
| Connections by 2024 in the operator's tariff plan (a plan, not a measurement) | 160 | 130 |

A global sensitivity analysis of a new site's demand gives the connected share the largest
total Sobol index, 0.46.

**What the assumption does to the results.** With the whole census present from year 0, the
year-0 plant of the tree (63.5 kWp, 175 kWh) is nearly the full single-year plant (72.5 kWp,
180 kWh), and building the latter outright costs only 0.8 % more in expectation
(`results/summary_value_of_tree_samionta.json`). Nothing is left to defer. That is a property
of the assumption, not of the method.

**Three further defects found by the same audit.**

1. *Trajectories do not persist along tree paths.* `tree/build_tree.py` nests per-stage
   medoids as a fan: every node of a stage receives the same children, each taken from
   whichever Monte-Carlo path happened to be the medoid at that stage. The growth trajectory
   and the cost future are held within a Monte-Carlo path (`scenarios/mc_sampler.draw_path`),
   not along a path of the tree. A real path of `results/summary_tree_samionta.json` serves
   74.6, 129.1, 94.8, 94.9 and then 58.7 MWh/yr, and only the central trajectory survives at
   years 10 and 15.
2. *Growth stops after 24 months.* The maturity bands are 0-3, 4-6, 7-12, 13-24 and 25+
   months (`demand/maturity.MATURITY_EDGES`). With a single cohort the demand is stationary
   from year 5, and the year-0 age is fixed at 12 months, whereas the real villages are at 33
   (Samionta) and 25 (Gbowele) months in November 2026.
3. *Network loss.* The model carries 13 % of the energy injected into the network; the
   unexplained gap measured in October 2026 was 18 to 19 % at both villages.

## 2. Decisions taken by the author

- **D1, progressive connection.** Connection is a logistic diffusion of the connected share of
  the census, with an uncertain plateau and an uncertain speed, bracketed by the two villages.
  Households join in monthly cohorts; each cohort ages on its own clock, so the
  maturity-conditioned mixture law applies per cohort and not to the community as a whole.
  Productive users keep their current rule (a Poisson intensity per connected household,
  conditioned on maturity), so they follow the connected households.
- **D2, persistence.** The connection trajectory, the growth trajectory and the cost future
  are drawn once per path and held. The tree branches on them from year 5 and keeps them
  along every path; only climate and inter-annual variability stay fan-nested.
- **D3, order.** (1) this specification and the formulation; (2) progressive connection in
  the code; (3) persistent trees; (4) recomputation; then the manuscript and the presentation,
  outside the repository.

## 3. Vocabulary and invariants

- **Village age** `a`: whole months since the site's first customer connection, the origin
  `build_productive_profiles.connection_intensity` already uses (section 4.2).
- **Cohort** `u`: the households connected in village month `u`. At village age `a` a
  household of cohort `u` has **cohort age** `a - u`, and its maturity band is
  `growth.maturity_band(a - u)`.
- **Connected stock** `N_k(a)`: households of category `k` in {HH1, HH2, HH3} connected at or
  before village month `a`, whether or not they consume. A connected household that consumes
  nothing in a month is in the mixture's `inactive` state; an unconnected household is in no
  state at all and draws nothing.
- **Active household**: a connected household outside the `inactive` state in a month (for
  the meters, one that consumed more than 0.05 kWh in it).
- **Regime** `xi = (omega, g, kappa)`: a path's connection trajectory `omega` in {low,
  central, high}, growth trajectory `g` in {slow, central, fast} and cost future `kappa` in
  {low, central, high}.

Invariants the code must hold, each tested in section 11:

- **I1.** `N_k(a)` is integer, non-decreasing in `a`, and `0 <= N_k(a) <= H_k`, the census of
  category `k`.
- **I2.** Every connected household belongs to exactly one cohort; cohort sizes are
  non-negative.
- **I3.** Along every root-to-leaf path of a persistent tree, `xi` is constant from the first
  branching on, the connected stock never decreases, and the grid, once arrived, stays.
- **I4.** With the whole census connected at village month 0 (plateau one, infinite speed),
  every output is bit for bit what the code produces today.

## 4. The connection model (session 2)

### 4.1 The curve

For a trajectory `omega`, a unit logistic on the village clock,

    l(a) = 1 / (1 + exp(-r * (a - m)))

with rate `r > 0` per month and midpoint `m` in months of village age, and a plateau share
`s` in (0, 1] of the census. A new site's stock is

    N_k(a) = floor(s * l(a) * H_k + 1/2)        for each category k separately.

Rounding each category on its own keeps each one monotone (I1); the total then differs from
`s * l(a) * sum(H_k)` by at most one household per category, which is accepted. The cohort of
month `u` holds `n_k(u) = N_k(u) - N_k(u - 1)` households, with `N_k(-1) = 0`.

The instant limit `r = inf` gives `l(a) = 1` for `a >= m` and 0 before. The schedule
`(s, r, m) = (1, inf, 0)` connects every household at village month 0, which is the model as
it stands: it is kept as the degenerate case of I4 and as the shipped default until session 4
(section 4.6).

### 4.2 Estimating it from the meter records

Sources:

- `data/demand/customer_info.parquet`, the customer roster (`customer_code`, `customer_type`,
  `site_name`, `connection_date`). The origin of the village clock is the site's earliest
  connection month over all customer types, which is how
  `demand/build_productive_profiles.connection_intensity` takes it, so the connection curve
  and the productive-user intensity run on one clock. The household stock counts the rows of
  type `HH` connected in or before each month, less those that left (section 4.7).
- `data/demand/household_customers.csv`, the household register, for the category (HH1 to
  HH3) of each household, which the brownfield state needs (section 4.5).
- The meter archives, for the validation of section 12 (active households) only, not for the
  fit.

The fit is made on the **connected stock**, not on active households. The mixture law already
carries the `inactive` state of connected households (`demand/maturity.py`); a plateau fitted
on active households and then passed through that law would remove the inactive months twice.
The audit's 48.1 households is a fit on active households, so the Samionta plateau of the
stock will come out higher. What reconciles the two descriptions is the active count the model
reproduces (criterion S2-A5).

Procedure, in a new offline module `demand/build_connection_curves.py`:

1. For each reference site, the monthly stock `N(a)` for `a = 0..T`, where `T` is the last
   complete month the roster covers. Report `T`, the origin month and the village ages they
   imply in November 2026, beside the ages since energisation the audit used (33 and 25
   months). The archive was found to end on 1 June 2026; the session confirms the month.
2. Least squares of `N(a) = K * l(a)` over `(K, r, m)`, with `N(T) <= K <= H` (the site's
   census of households) and `r > 0`. Report the estimates and their standard errors from the
   Jacobian, stating that a cumulative series is serially correlated and that these errors
   are therefore optimistic.
3. Profile the plateau: for each integer `K` from `N(T)` to `H`, refit `(r, m)` and record
   `SSR(K)`. The 95 % interval is the set of `K` with
   `SSR(K) <= SSR_min * (1 + F(0.95; 1, n - 3) / (n - 3))`, `n` being the number of months.
   The plateau is **identified** when the interval's upper end lies below `H`. Otherwise it is
   reported as a lower bound, the interval's lower end.
4. Write `data/ramp_params/reference/connection_curves.csv`, one row per site and plateau
   variant (`estimate`, `profile_lower_bound`, `census`), with columns `site_name, variant,
   plateau_households, census_households, plateau_share, rate_per_month, midpoint_months,
   se_plateau, se_rate, se_midpoint, identified, n_months, origin_month, last_month`. For the
   two fixed-plateau variants, `(r, m)` is refitted at that plateau.
5. Write `data/ramp_params/reference/connection_observed.csv`: households connected per site,
   category and connection month (`site_name, customer_type, connection_month, households`),
   the brownfield state of section 4.5.

Both tables are read at generation, so `instances._demand_fingerprint` hashes them with no
extra code. They must be listed in the reference directory's README among the tables read at
generation; a test already holds that README and `instances._NOT_READ_AT_GENERATION` together.

What to expect: at Samionta a plateau near a fifth of the census, `r` near 0.075 per month and
a midpoint in mid-2024; at Gbowele, no identified plateau.

### 4.3 The bracket

As for growth, the uncertainty is carried between the two sites, not within one. Samionta's
plateau lies between 49 and 53 households, 0.017 of its census either way, while the two
villages differ by more than 0.3 of their census: the within-site errors are reported, not
drawn.

| Trajectory | Plateau share | Rate and midpoint |
|---|---|---|
| `low` | Samionta's estimate | Samionta's fit |
| `high` | Gbowele's estimate if identified, otherwise **[decision 1]** | Gbowele's fit at that plateau |
| `central` | mean of `low` and `high` | means of `low` and `high` |

**[decision 1] The high plateau when Gbowele's is not identified.** Default
`profile_lower_bound`: the smallest plateau Gbowele's record does not reject at 95 %. It
follows the rule the growth envelope follows, nothing beyond what was observed, and it reads
"at least". The alternative, `census`, has Gbowele connect every household in the end: the
conservative end for sizing, and today's assumption. Whichever is chosen, session 4 computes
the other as a sensitivity. Settings field `connection.high_plateau`.

The names order the plateaus. If two curves cross (a lower plateau reached faster), the
session reports where; nothing is reordered.

Weights: `ConnectionWeights(low, central, high)`, a third each, validated as
`TrajectoryWeights` is: non-negative, summing to one, refused rather than normalised.

**[decision 2] The connection and growth trajectories are drawn independently.** Default
`independent`: two reference villages give no basis for saying that a village which connects
many of its households also sees each of them grow fast, nor the reverse. Nine combinations,
27 regimes with the cost futures. The alternative, `paired`, joins Samionta's connection to
Samionta's growth and Gbowele's to Gbowele's (low with slow, central with central, high with
fast): three combinations and nine regimes in all (section 9.6). Settings field
`connection.pairing`.

### 4.4 A new site with only a census

The stock of section 4.1, with the trajectory's `(s, r, m)`, and a village age at year 0 equal
to `maturity_months`: zero for a site being energised, as the interface's hint already says.
Productive users, declared rosters and declared productive uses follow the connected
households through the rule of section 5.3. Community uses (places of worship, schools) and
self-consumption (the plant room, the street lighting) are present from the first month, as
today.

Not in session 2: a developer's own connection forecast on the `Site` record, believed over the
bracket as `productive_units` already is (section 15).

### 4.5 A site with a plant and a record (brownfield)

Applies when the run is brownfield (`settings.installed` not empty, or `certify --brownfield`)
and the site has rows in `connection_observed.csv`. Otherwise the stock of section 4.4 applies.

- Up to the roster's last month `T`, `N_k(a)` is the observed stock, and the cohorts are the
  households' own connection months.
- Beyond `T`, the conditional curve

      N_k(a) = N_k(T) + floor((Nbar_k - N_k(T)) * (l(a) - l(T)) / (1 - l(T)) + 1/2)
      Nbar_k = max(floor(s * H_k + 1/2), N_k(T))

  starts on the observation, never decreases, tends to the plateau, and stays flat if the
  plateau is already passed: no trajectory disconnects anyone. If `1 - l(T) < 1e-9` there is
  no further connection.
- The plan's year 0 starts in January of `installed.base_year`, and the village age at year 0
  is derived (months from the origin to that January), not declared. `maturity_months` is then
  ignored and the derived age is written to the summary JSON. A roster that ends more than
  twelve months before that January is refused rather than extrapolated in silence.

**[decision 3] Which bracket a site with its own record follows.** Default `own`: a reference
village's future is bracketed by its own fit, the estimate plus or minus two standard errors
when its plateau is identified (Samionta), and `profile_lower_bound` to `census`, with
`central` between them, when it is not (Gbowele). Two and a half years of a village's own
record say more about it than the other village does. The alternative, `between_villages`,
gives the brownfield site the three trajectories of a new site, conditioned on its observed
stock; in a third of the futures Samionta, flat for two years, would then take up Gbowele's
pace from the plan's first month. Settings field `connection.brownfield_bracket`.

### 4.6 Settings

In `settings.py`:

```python
@dataclass
class ConnectionWeights:
    low: float = 1.0 / 3
    central: float = 1.0 / 3
    high: float = 1.0 / 3

@dataclass
class ConnectionSettings:
    #: "census" connects the whole census at village month 0, the model before progressive
    #: connection; "progressive" follows the fitted curves.
    mode: str = "census"
    #: Trajectory of the single certified year.
    trajectory: str = "central"
    weights: ConnectionWeights = field(default_factory=ConnectionWeights)
    pairing: str = "independent"              # [decision 2]
    high_plateau: str = "profile_lower_bound" # [decision 1]
    brownfield_bracket: str = "own"           # [decision 3]
    provenance: Provenance = ...              # the fit, and the roster it rests on

ProjectSettings.connection: ConnectionSettings
```

`mode` stays `"census"` until session 4 changes it, so that sessions 2 and 3 move no stored
result and every existing test keeps passing; the change of default and the recomputation
belong together. `validate()` refuses unknown names and weights that do not sum to one, and
`from_dict` round-trips the block.

### 4.7 The record, the silent meters and the census (decisions A to C)

Decided by the author on 2026-11-07, after session 2 found the roster ending in May 2026
while the meters run to 1 November 2026, and households of the roster without readings.

**The record [decision A].** Two records are built, and `build_connection_curves --record`
chooses:

- `roster`: the operator's customer roster. Its customers keep their roster type and
  connection date, and `T` is the month of its latest connection, May 2026.
- `extended`: the roster and every customer of the meter archive the roster does not list,
  up to the archive's last complete month, October 2026. Such a customer is connected in the
  month of its first reading. Its type comes from the operator's field census, received on
  7 November 2026: its category column first, its type column where that is empty, read as a household
  of that category (HH1 to HH3), a productive user (SME) or a church (CHU). Where the census
  gives no type, it is read off the consumption by a documented rule
  (`build_connection_curves.classify_meter`): a meter drawing at least 35 % of its energy
  between 07:00 and 18:00, or 1.5 kWh a day or more, is a productive user; one drawing at
  least a quarter of its week on Sundays is a church; any other is a household of the site's
  commonest category. These customers are held in `data/demand/archive_customers.csv`
  (code, site, type, category, connection month, source), which `--census` rebuilds from the
  two workbooks, reading their code and type columns only; nothing the generation runs reads
  it. Roster types stay authoritative for roster customers; a fresh roster would replace the
  census and profile types and the first-reading dates, and nothing else.

Both typing sources were checked on the roster's own customers. The profile rule misplaces
28.6 % of the 203 metered ones (22.2 % counting the household categories as one), and no
rule on these descriptors does much better: a nearest-centroid classifier on the 24-hour
shape reaches 70 % in cross-validation, against 69 % for calling every customer a household.
The census differs from the roster for 67.6 % of the 204 (its category column calls HH2 most of
the roster's HH1 households and all its HH3), and for 28 % by its type column alone. Both are
above the 5 % the author set for the extended record, so **the shipped tables hold the roster
record**, and the extended one is a sensitivity, written on request.

**Silent meters [decision B].** A meter whose last reading, a zero included, falls three
months or more before the end of the archive has failed. According to the operator a failed
meter lets no energy through, so it is neither a loss nor an inactive household.

- A replaced meter keeps its customer code, and the archive is kept per code, so a household
  continuing on a new meter is one customer already (the census lists four such codes at
  Samionta). No other identifier links two codes in the repository's data.
- Otherwise, a meter starting at the same site within two months after the failure, within a
  factor of two of its daily energy over the three months either side and with a mean day
  correlated at 0.8 or more, is a candidate replacement. Candidates are listed, not merged:
  an unmerged pair is a departure and a new connection, which leaves the stock as it is and
  resets only the cohort's age. None was found.
- A household whose failed meter was not replaced leaves the connected stock from the month
  after its last reading. The departures are carried in `connection_observed.csv`
  (`departure_month`) and taken off their own cohort.
- A roster customer whose meter never recorded is listed apart and left out of the stock. A
  code absent from both the roster and the census whose readings stopped early is not a
  customer: a meter tried in the test period or for a week, and taken down.
- `meter_status.csv` lists every code with its status, for the field team to confirm.

The curves are fitted on the net stock; the mixture law does not change.

**The S2-A5 test [decision C]** is made in month `T` on the households connected before `T`
began, net of departures: on the simulated side, that stock, each cohort at its own age in
`T`, through the site's own mixture law (slow for Samionta, fast for Gbowele); on the meters,
the same households, active when the month's energy is above zero, which is the model's own
definition of the inactive state (`build_monthly_household_clusters`: `total_kWh <= 0`). Given
the stock, the active count is a sum of independent draws, which sets the standard deviation.
As a sensitivity, the households whose failed meter was not replaced are kept in the stock and
counted inactive on the meters.

## 5. Cohort ageing in the demand generator (session 2)

### 5.1 Interface

    demand.generator.simulate_demand_year(site, year, seed, maturity_months, trajectory,
                                          scaling, apply_seasonality, include_productive,
                                          connection=None)

- `connection` is a `ConnectionSchedule` (new, `demand/connection.py`) or `None`, which means
  `ConnectionSchedule.whole_census(site)`.
- `maturity_months` keeps its name and becomes the **village age at the first month of the
  year**. Under the whole census at month 0 that is exactly today's meaning, every household
  being that old.

`ConnectionSchedule` is frozen and holds the cumulative stock per category over village months
`0..A_max`. It offers:

- `connected(a) -> dict[str, int]`, categories in `site.census` order;
- `census_by_band(a) -> dict[str, dict[str, int]]`, the connected households of each category
  grouped by the maturity band of their cohort, bands in `MATURITY_LABELS` order, empty bands
  omitted;
- `digest(until: int) -> str`, a hash of the stock up to village month `until`;
- the constructors `whole_census(site)`, `greenfield(site, curve, horizon_months)` and
  `brownfield(site, observed, curve, horizon_months)`.

`ConnectionCurve(share, rate_per_month, midpoint_months, label)` takes
`rate_per_month = math.inf` for the instant limit, and `load_curves(settings)` reads the
calibration table and returns the three trajectories under the settings' choices.

### 5.2 The composition of a month

For month `m = 1..12`, at village age `a = maturity_months + m - 1`:

```python
counts = {state: 0 for state in (*ARCHETYPES, INACTIVE)}
for band, census in schedule.census_by_band(a).items():        # MATURITY_LABELS order
    part = sample_composition(law.xs(band, level="maturity"), census, m, rng,
                              by_maturity=True)
    for state, n in part.items():
        counts[state] += n
```

Independent multinomial draws under one law add up to one multinomial draw, so grouping the
cohorts by band is exact and costs one draw per band and category rather than one per cohort.
Under the whole census there is a single band each month and the call is the one made today,
with the same arguments in the same order, so the random stream and every array derived from it
are unchanged (I4). Each band's mapping keeps `site.census`'s key order for the same reason.

Nothing else in the month changes. `_simulate_month(counts, ...)` builds the active households
only, so a schedule with fewer connected households makes every simulated year cheaper.

### 5.3 Productive users [decision D]

- The expected count is the intensity times the connected count, the intensity being read at
  the band of the **village age**, `maturity_band(a)`.
  `build_productive_profiles.connection_intensity` estimates it by village age, so the
  generator reads it on the same clock. Under a single cohort the two bands coincide.
- *Revised.* Under a progressive schedule the connected count is the **connected stock**
  `sum_k N_k(a)`, the base the intensity was estimated on (rows of type `HH` by connection
  date). Under the whole census it stays the households outside the `inactive` state: the
  legacy reading, kept so that no stored result moves. `_declared_counts` and the roster
  scaling take `share = connected / n_households` on the same base.
- **A village with a plant** starts from the productive users its record holds, as section
  4.5 does for households, and the rule decides only what changes after `T`. With `P(a)` the
  productive users connected at village month `a` (roster, or roster and archive), net of any
  that left, and `lambda(a)` the intensity at `maturity_band(a)` under the growth trajectory:

      units(a) = split(P(min(a, T))) + Poisson(mu(a)),
      mu(a)    = 0                                                    if a <= T,
               = max(0, lambda(a) sum_k N_k(a) - lambda(T) sum_k N_k(T))  if a > T,

  the Poisson part split multinomially by the trajectory's class mix, as today. `split`
  divides a count among the classes by the village's own measured mix, by largest remainders;
  that mix is the share of the village's own metered enterprises in each class, so at `T` the
  split is the observed state in whole numbers (14 at Samionta, 42 at Gbowele under the roster
  record). It is the simplest form that reproduces the observed state at `T` exactly: nothing
  is drawn on the record, and beyond it the observed users stay and only the rule's
  increment is drawn, never negative. A site that declares its own enterprises
  (`productive_units` or `productive_mix`) keeps its declaration instead.

Measured against the meters (S2-A6), counting customers of type productive user with more
than 0.05 kWh in month `T`: see section 12.

### 5.4 Outputs

`DemandYear` gains `connected: dict[int, dict[str, int]]`, the stock by category in each month.
`composition` now covers connected households only; under the whole census it is unchanged.

### 5.5 Unchanged

The residual seasonality (`growth.seasonal_index`), the measured community and self uses, the
declared uses, and the distribution loss (`instances.with_network_loss`) are applied exactly as
today.

## 6. Cache keys (session 2)

**Instance key** (`instances._cache_key`): append `schedule.digest(until=maturity_months + 11)`,
and only when the schedule is not the whole census, the convention this codebase follows for
new parts of a key. *Corrected:* that does not keep every cached instance valid. The two
calibration tables are read at generation and so enter the demand fingerprint, and adding
them (or rewriting them, as the revision of section 4.7 does) invalidates every cached
instance and pool once. The digest also covers a schedule's departures and observed
productive users, where it has them.

**Pool key** (`scenarios.demand_paths._pool_path` and `demand_pool`). Today the file name
carries the site's name, the demand fingerprint, the trajectory and the age. Two gaps predate
progressive connection: the site's own description (`instances._site_fingerprint`) is not in
it, so an edited community of the same name is served the old pool; nor are the calendar year
and the seed base, so a pool drawn for 2025 would be served for a leap year. The key becomes a
digest of

    site fingerprint | demand fingerprint | year | seed | growth trajectory
    | village age | schedule.digest(until=village age + 11)

Keying on the schedule's digest rather than on the trajectory's name lets two trajectories that
agree up to the end of the year share a pool, and lets a refit invalidate exactly the pools it
changes. The change invalidates every stored pool once (about 75 minutes per site to rebuild).

**Fingerprint.** `connection.py` joins `instances._GENERATION_SOURCES` and
`build_connection_curves.py` joins `_OFFLINE_SOURCES`; the test that classifies every module of
the demand package refuses anything else.

**Number of pools.** Today, 3 growth trajectories times 5 stage ages, 15 pools of four years per
site. With progressive connection, 3 times 3 times 5, or 45, fewer where schedules coincide,
each year simulating only the active households.

## 7. Scenario paths (session 2)

- `scenarios/uncertainty_space.DemandAxis` gains `connection_probabilities`,
  `connection_pairing` and `connection_mode`, filled from `settings.connection` where the space
  is built from settings.
- `scenarios/mc_sampler.draw_path` draws the connection trajectory once per path, beside the
  growth trajectory and the cost future, and writes it to every stage (`stage["connection"]`).
  It is drawn from a second generator, created once in `sample_paths` from
  `np.random.SeedSequence([cfg.seed, 0xC0])` and consumed path after path, so that the existing
  stream (growth, costs, grid, pathways, policy) is untouched; and it is not drawn at all when
  the axis holds one trajectory (`mode = "census"`) or when `pairing = "paired"`.
- `scenarios/assemble.AxisDraw` gains `connection: str`, and `sample_scenario_paths` passes it
  to `simulate_stage_demand`.
- `scenarios/demand_paths.simulate_stage_demand(..., connection=...)`: the village age is
  `base_maturity_months + 12 * stage_year` as today (session 3 may move it, section 9.3), the
  schedule comes from section 4.4 or 4.5, the pool from section 6.

## 8. The reference year of the single certified year [decision 4]

`exact/certify.py` sizes a plant for one year. Today that year is unambiguous: the whole
census, twelve months old. Once households connect progressively, the year chosen decides how
much of the village is there.

| Option | Year certified | For | Against |
|---|---|---|---|
| A. A fixed village age | the year starting at `maturity_months`, central connection | continuity; reproduces today under `mode = "census"` | a new village at twelve months is still connecting; arbitrary |
| B. The root's year | the year the root node of the tree stands for (section 9.3), under the central connection and growth | the two halves of the one answer the README describes are the same year; it sizes what the year-0 plant has to carry | moves with the tree's convention |
| C. The settled village | the first year in which 95 % of the plateau is connected and every cohort is in the 25+ band | the typical year of most of the horizon, a natural base for the tariff | years away under a slow trajectory; the year nothing is decided for |
| D. The observed year | brownfield only: the year starting at the plan's year 0 from the observed state | the real village | brownfield only |

Default **B**. While the tree's convention is the first year of a span (today), B is A for a
new site and D for a brownfield one, so nothing moves until that convention does; under the
convention recommended in section 9.3 it becomes the plan's year 4. Command line:
`certify --connection {low,central,high}`, defaulting to `settings.connection.trajectory`; the
summary JSON records the connection trajectory, the village age and the connected stock by
category. `--brownfield` also switches the demand to the observed state of section 4.5, which is
the run the real Samionta still lacks: 41 months, a few dozen households, its own plant.

## 9. Persistent scenario tree (session 3)

### 9.1 What is drawn per path, and what is not

| Draw | Held over the path | Drawn per stage | In the tree |
|---|---|---|---|
| Connection trajectory | yes | | branched at the first milestone after the root, then held |
| Growth trajectory | yes | | idem |
| Cost future | yes | | idem |
| Grid arrival milestone, when `arrival_uncertain` | yes (already: `connected_from`) | | branched at the milestone it occurs; absorbing |
| Climate pathway | | yes | fan within the regime |
| Inter-annual variability: pool member, weather year, appliance noise | | yes | fan within the regime |
| Policy target | | yes | not branched: no constraint of `model/` reads it |

Revealing the regime at the first milestone after the root is a modelling assumption, stated in
the formulation: five years of operation show a village's connection plateau, the growth of its
consumption and the trend of prices, within the bracket.

### 9.2 Construction

Inputs: the Monte-Carlo ensemble of `assemble.sample_scenario_paths`, each path carrying its
regime and its grid-arrival milestone.

1. **Regimes.** Group the paths by regime. A regime's mass is its share of the paths.
2. **Regime reduction**, only when the regimes outnumber `cfg.regime_branches` (R). A regime's
   feature is the concatenation, over stages 1 to S-1, of the mean over its paths of today's
   stage features (`tree.reduce.stage_features`: energy, peak, daytime share, resource,
   demand-yield correlation, fuel and capital prices), each channel scaled by its spread across
   regimes. Weighted k-medoids (`timedomain.kmedoids`) over the regimes; a representative is a
   real regime and carries the mass of its cluster. When the regimes do not outnumber R, each
   is its own branch.
3. **Root.** One node, the here-and-now investment. Its own period, years 0 to 4, is
   **[decision 6]** (section 9.4).
4. **Within a regime.** For each representative regime and each stage `k >= 1`, take the paths
   whose regime *equals* the representative (not its whole cluster, or persistence breaks
   again), reduce their stage-k features to `cfg.regime_fan[k]` medoids, and nest them as a fan
   below every node of that regime at stage `k - 1`. Node data are the medoid path's stage-k
   arrays, as today.
5. **Grid.** When `arrival_uncertain` is on, the reduction at stage k is made separately for
   parents already connected (paths connected by stage `k - 1`) and for parents not yet
   connected (paths not connected before stage k), and an unconnected parent receives at least
   two children, one from the paths where the line arrives at k and one from those where it
   does not, weighted by their shares. No connected node then has an unconnected child. Off by
   default, and nothing changes then.
6. **Probabilities** are products along the path; `ScenarioTree.check_probabilities()` as
   today.

`NodeData` gains `connection: str`, `cost_scenario: str`, `connected_households: int` and
`village_age_months: int`, so that I3 can be checked on the tree itself and a certificate can
name what it was built on. A tree of one regime is the fan tree over all paths: the same
representatives, weights and node data.

### 9.3 The year a node stands for [decision 5]

A node at milestone `y` with a span of `D` years is charged `D` years of operation on one year
of data. Today that year is the first of the span. Under progressive connection the demand
rises within a span, most of all within the root's, since a new village connects during years 0
to 4, and the first year of the span is its least demanding. A plant sized on it is never asked
to carry the later years, and the energy it would leave unserved there is never counted, which
overstates what deferring capacity is worth.

Options: `first` (today); `last`, the year `y + D - 1`, the most demanding year of a monotone
path, which the plant really has to carry, at the price of overstating operating cost in a
growing span; `both`, two years per node at half weight each, which doubles the operating
sub-problems. Default **`last`** for the session-4 runs, the conservative choice for the claim
that the tree is worth something, with `first` kept to reproduce today and `both` measured once
on Samionta in session 4 to state the bias. It moves the demand only: the climate series exist
at the milestone years, and prices are the milestone's. Field `ModelConfig.node_year`, default
`first` until session 4.

### 9.4 The root's own period [decision 6]

The regime is revealed at year 5, but the root's plant operates years 0 to 4 under whichever
regime is true, and the root node holds one year of data, the medoid over all paths. The year-0
decision therefore never sees the spread of its own period, which under progressive connection
is the widest of the horizon.

Default: the root carries the investment and no operation. Below it sits one **operating-only**
node per representative regime, with the regime's mass as probability, data from that regime's
own paths for the root's period, its investment fixed at zero (capacity inherited from the
root) and the root's span. The stage-1 nodes of the regime hang below it. In node-indexed form
this is the two-stage structure of the year-0 decision: one plant, operated under every regime.
It needs a per-node flag `invests: bool` in the tree, module counts fixed at zero where it is
false (`model/investment_constraints.py`), and a descent (`exact/tree_oracle.py`,
`exact/tree_certify.py`) that never moves those nodes. `exact/first_stage.py` is unaffected: its
boxes are in root coordinates. The alternative keeps a single root node, as today: simpler, with
the bias stated.

### 9.5 Distortion

Reported in `tree.reduction_error` (kept, per stage) and in a new `tree.distortion`:

- `stage[y]`: the mean scaled distance of an outcome to the node standing for it, computed
  within the regime and weighted by regime mass. Today's measure, conditioned.
- `regime`: the mass-weighted distance between a regime's feature and its representative's;
  zero when no regime is reduced.
- `coverage`: the mean, over Monte-Carlo paths, of the distance from the path's whole
  trajectory (its stage features concatenated over the stages) to the nearest tree path.
- `plausibility`: the sum over leaves of the leaf's probability times the distance from the
  tree path's trajectory to the nearest Monte-Carlo path.
- `persistence_violations`: the tree paths along which the connected stock decreases, the
  regime changes after the branching, or the grid reverts. Zero by construction in a persistent
  tree, and counted for the fan tree as well.

Coverage is what the fan is good at, since it contains every combination of stage medoids;
plausibility is what it is bad at, since it gives weight to combinations no village follows,
fast at year 5 and slow at year 10. Together they are a cheap stand-in for the nested distance
of Pflug and Pichler, the rigorous measure, which is not required. Session 3 reports all five
for both trees on the same ensemble.

### 9.6 Size

With five milestones (0, 5, 10, 15, 20), R regimes and a within-regime fan `f_k` at stages 1 to
4, a persistent tree with operating-only root children has

    1 + R + R * (f_1 + f_1 f_2 + f_1 f_2 f_3 + f_1 f_2 f_3 f_4)

nodes, all but the root operating. Today's fan, branching (1, 3, 2, 2, 2), has
1 + 3 + 6 + 12 + 24 = 46 nodes, all operating.

| R | Fan (f_1, f_2, f_3, f_4) | Nodes | Operating nodes | Remark |
|---|---|---|---|---|
| 9 | (1, 1, 1, 1) | 46 | 45 | **default**: today's size; climate and inter-annual variability enter through each regime's medoid outcome |
| 6 | (1, 1, 1, 1) | 31 | 30 | |
| 9 | (1, 2, 1, 1) | 73 | 72 | |
| 3 | (1, 2, 2, 2) | 49 | 48 | |
| 27 | (1, 1, 1, 1) | 136 | 135 | every regime of independent draws, about three times today's programme |

Without operating-only children (the alternative of decision 6), subtract R. The programme grows
with the operating nodes, about 17 000 columns each at 64 representative days (777 538 over 46
nodes today), and a tree relaxation took about 6.6 minutes a box at 46 nodes.

**[decision 7]** Default R = 9 with no fan, which keeps the programme the size it is: nine
regimes are exactly the regimes of `pairing = "paired"`, or nine medoids of the 27 independent
ones. Fields: `ModelConfig.tree_mode` (`"fan"` or `"persistent"`, default `"fan"` until session
4), `ModelConfig.regime_branches = 9` and `ModelConfig.regime_fan = (1, 1, 1, 1, 1)`, root first.

## 10. The network-loss parameter (session 2)

State today:

- it is declared, `InfrastructureSpec.network_loss_fraction = 0.13`, validated in [0, 1) and
  applied by `instances.with_network_loss` to what travels the conductor (not to the plant's own
  supply), in the certified year and in the tree alike; it is copied as
  `ModelConfig.network_loss_fraction = 0.13`, because the tree is drawn before a settings object
  exists;
- its provenance lives in a comment only. The block's `provenance` is the balance of plant's
  and says nothing about the loss.

To do:

1. Add `InfrastructureSpec.network_loss_provenance: Provenance`. Source: Gbowele's two series
   distribution meters against the customers' meters, with the street lighting and the plant's
   own supply counted as the loads they are, 13 % of the energy injected; the operator's own
   energy balance gives 15 to 16 % over a longer window; Samionta has no distribution meter and
   carries Gbowele's figure. `verified=False`, with the note that in October 2026 the
   unexplained gap between what the plants delivered and what the metered loads account for was
   18.2 % at Samionta and 19.1 % at Gbowele, that at Gbowele most of it lies between the
   distribution meters and the customers' meters, that the gap is flat across the hours of the
   day rather than proportional to the load, and that the default is kept until the base of the
   comparison and the form of the loss are settled. Unverified because the latest measurement
   contradicts the default, so that the setting announces itself through
   `ProjectSettings.unverified()` and in the interface.
2. One definition: `ModelConfig.network_loss_fraction` either reads the settings' default or is
   refused when it disagrees with the project's, as `model.economics.check_one_discount_rate`
   does for the rate; a test holds the two defaults equal if none does yet.
3. The default stays at 0.13, and no code path changes.

**[decision 8]** Behind the default sit two questions for session 4, not session 2. The base of
the October figures: a share of what the plant delivered or of what entered the network, and,
at Samionta, which has no distribution meter, whether the street lighting the model counts as a
load is still inside the gap. And the form: a share of the injection (today) or a constant plus a
share. The measured gap does not follow the hourly load, and under progressive connection a
share shrinks with the demand where a constant would not.

## 11. Tests: properties, not snapshots

Session 2:

| Test | Property |
|---|---|
| `test_the_whole_census_reproduces_the_single_cohort_year` | `simulate_demand_year(site, maturity_months=M)` and the same call with `connection=ConnectionSchedule.whole_census(site)` give identical `hourly_kw`, `composition`, `enterprises`, `unbilled_kw` and `at_plant_kw` (`np.array_equal`), on a small synthetic site so that RAMP stays quick |
| `test_the_connected_stock_never_decreases` | for every trajectory, greenfield and brownfield, and every category: `N_k(a)` integer, non-decreasing, within `[0, H_k]`; cohort sizes non-negative |
| `test_each_cohort_ages_on_its_own_clock` | `census_by_band(a)` puts a cohort connected at month `u` in `maturity_band(a - u)`: cohorts of months 0 and 10 seen at village age 12 fall in 7-12 and 0-3 |
| `test_an_unconnected_household_draws_nothing` | a schedule with no connection gives no household load and an expected productive count of zero, while the community and self uses are present from the first month |
| `test_productive_users_follow_the_connected_households` | the mean passed to the Poisson draw is the intensity at `maturity_band(a)` times the connected stock under a progressive schedule and the active count under the whole census (section 5.3), so doubling every cohort doubles it |
| `test_the_brownfield_state_is_the_roster` | for each reference site, the schedule up to the roster's last month equals `connection_observed.csv`, and the derived village age matches the origin month |
| `test_a_trajectory_never_disconnects` | a plateau below the observed stock leaves the stock flat at the observation |
| `test_the_instant_curve_is_the_whole_census` | `ConnectionCurve(1.0, math.inf, 0)` yields `ConnectionSchedule.whole_census` |
| `test_the_connection_curves_are_admissible` | shares in (0, 1], positive rates, `identified` false wherever only a lower bound exists, every variant present for every reference site |
| `test_the_pool_key_covers_what_decides_the_pool` | the key changes with the schedule (one household more), the site's description, the year and the seed, and not with the name of a trajectory whose schedule is the same |
| `test_the_instance_key_covers_the_schedule` | the same for `instances._cache_key`, which is unchanged under the whole census |
| `test_the_connection_draw_leaves_the_stream_alone` | `mc_sampler.sample_paths` under `mode = "census"` returns exactly today's draws; under `progressive`, every stage of a path carries the same connection trajectory |
| `test_connection_settings_round_trip` | save and load give equal settings; unknown names and weights that do not sum to one are refused |
| `test_the_network_loss_has_a_provenance` | `infrastructure.network_loss_provenance` exists and is listed by `unverified()`; the configuration's default equals the settings' |
| `test_a_departure_leaves_its_own_cohort` | (section 4.7) a departure lowers the stock from its month, is taken off the cohort it joined in, enters the digest only from its month, and cannot exceed its cohort or precede its connection |
| `test_a_silent_meter_leaves_the_stock` | a meter is failed exactly when its last reading falls three months or more before the archive's end, its household leaves the month after, no record holds a meter that never recorded or a code that is no customer's, and the extended stock at `T` is what joined less what left |
| `test_the_observed_productive_users_are_held_on_the_record` | (section 5.3) a village's own mix splits its observed productive users exactly; on the record nothing is drawn, and beyond it the mean drawn is the rule's increment, never negative, on top of the users held |
| `test_the_interface_offers_the_connection_trajectory` | the field is offered in both languages with the three trajectories, and an unknown name is refused |

Session 3:

| Test | Property |
|---|---|
| `test_a_tree_path_keeps_its_regime` | along every root-to-leaf path the regime is constant from stage 1, the connected stock never decreases, the village age rises with the milestones, and the grid never reverts |
| `test_a_single_regime_tree_is_the_fan_tree` | with one regime, the persistent builder reproduces the fan builder's representatives, weights and node data, and the programme's value |
| `test_regime_masses_are_the_ensemble_frequencies` | each regime branch carries the share of paths of its cluster; leaves sum to one |
| `test_operating_only_nodes_do_not_invest` | (decision 6) module counts are fixed at zero there, and their capacities equal the root's in the solution |
| `test_the_distortion_report_is_complete` | the five measures exist in both tree modes, and the persistence violations are zero in persistent mode |
| `test_the_last_year_moves_only_the_demand` | (decision 5) under `last`, a node's demand is the year of village age `base + 12 * (y + D - 1)`, while its yield, temperature and prices are the milestone's |

## 12. Acceptance criteria

Session 2 is done when:

- **S2-A1.** The whole suite passes under the shipped settings (`mode = "census"`) and no stored
  result moves.
- **S2-A2.** Under the whole census, single-year instances and pools are bit for bit today's.
- **S2-A3.** Both calibration tables are written and documented; Samionta's plateau is reported
  with its standard error, and Gbowele's identification status, with its profile lower bound if
  it is not identified.
- **S2-A4.** The session's summary (not `results/`) gives, for each site and trajectory, the
  connected stock at village ages 12, 24, 36, 60 and 120 months, and the order of the curves.
- **S2-A5.** Under the observed state, the simulated active households of the roster's last
  month fall within two binomial standard deviations of the meters' count for that month, at
  both villages; given the connected stock, the number of households outside the `inactive`
  state is binomial under the mixture law, which sets the deviation. If they do not, the
  session reports it and stops; it does not tune anything.
- **S2-A6.** The productive users expected under the observed state are reported against the
  productive users metered in month `T` (customers of type productive user, roster or
  inferred, with more than 0.05 kWh in the month). The 15 and 43 first given here are that
  count in August 2026 under a classification made outside the repository.

S2-A5 is now made as section 4.7 states. Results, reported and not tuned (2026-11-07):

| Record, month `T` | Village | Households | Expected active (s.d.) | Metered | Within 2 s.d. | Without a reading in `T` | Expected over the rest |
|---|---|---|---|---|---|---|---|
| roster, May 2026 | Samionta | 49 | 46.9 (1.4) | 44 | no, by 0.1 | 3 | 44.0 (1.4) |
| roster, May 2026 | Gbowele | 57 | 53.2 (1.9) | 53 | yes | 0 | 53.2 (1.9) |
| extended, Oct. 2026 | Samionta | 48 | 46.2 (1.3) | 46 | yes | 0 | 46.2 (1.3) |
| extended, Oct. 2026 | Gbowele | 92 | 88.3 (1.9) | 84 | no | 4 | 84.4 (1.8) |

With the failed meters kept as inactive households, the extended record gives 47.2 (1.3)
against 46 at Samionta and 91.2 (1.9) against 84 at Gbowele; the roster record has no
departure before May. Every shortfall lies in households that have no reading at all in `T`:
three Samionta meters with a gap in May 2026 that record again afterwards, and four Gbowele
meters connected in May 2026 that have been silent since late August or early September, short
of the three months that would make them failed. The model's law was estimated on months with
readings, so a month without any is not an observation of the inactive state; read that way,
both villages pass under both records. Which reading the criterion takes is the author's
(section 14).

S2-A6 (2026-11-07), the site's own growth trajectory:

| Record, month `T` | Village | Metered | Anchored on the record | Rule, per connected household | Rule, per active household |
|---|---|---|---|---|---|
| roster, May 2026 | Samionta | 13 | 14 | 11.4 | 10.9 |
| roster, May 2026 | Gbowele | 41 | 42 | 58.3 | 52.6 |
| extended, Oct. 2026 | Samionta | 16 | 16 | 11.4 | 11.0 |
| extended, Oct. 2026 | Gbowele | 43 | 43 | 60.8 | 58.1 |

The anchored rule holds the connected productive users, one of whom at each village drew 0.05
kWh or less in May. The rule alone overstates Gbowele by about two fifths: its intensity at
13 to 24 months is an aggregate over months when few households were connected, before the 35
of May 2026.

Session 3 is done when:

- **S3-A1.** Every test of section 11 passes, and `tree_mode = "fan"` reproduces today's tree
  and objective.
- **S3-A2.** On Samionta, with the default ensemble, the persistent tree has no persistence
  violation, and the fan tree's count is reported beside it.
- **S3-A3.** The tree's size is the one section 9.6 gives for the chosen R and fan.
- **S3-A4.** The descent and the first-stage certificate run end to end on a persistent tree (a
  reduced ensemble suffices), and `first_stage` returns a root plant and a gap.
- **S3-A5.** The five distortion measures are reported for both trees on the same ensemble.

## 13. Files each session touches

Session 2, from the files read in session 1:

- new `src/microgrid_expansion/demand/connection.py`: curves, schedules, observed state; read
  at generation;
- new `src/microgrid_expansion/demand/build_connection_curves.py`: the fit and the observed
  table; offline;
- new `data/ramp_params/reference/connection_curves.csv` and `connection_observed.csv`, and the
  directory's README; and, from the revision of section 4.7, `meter_status.csv` (for
  inspection, listed in `instances._NOT_READ_AT_GENERATION`) and
  `data/demand/archive_customers.csv`, listed in `data/README.md`;
- `demand/generator.py`: `simulate_demand_year(connection=...)`, the composition by band,
  `DemandYear.connected`;
- `instances.py`: `_GENERATION_SOURCES`, `_OFFLINE_SOURCES`, `_cache_key`,
  `build_site_year(connection=...)`;
- `scenarios/demand_paths.py`: the pool key, `simulate_stage_demand(connection=...)`;
- `scenarios/mc_sampler.py`, `scenarios/assemble.py`, `scenarios/uncertainty_space.py`: the
  per-path draw;
- `settings.py`: `ConnectionWeights`, `ConnectionSettings`, `ProjectSettings.connection`,
  `validate`, `from_dict`, `InfrastructureSpec.network_loss_provenance`;
- `config.py`: the network-loss copy held to one definition; `maturity_months` documented as the
  village age;
- `exact/certify.py`: `--connection`, the brownfield demand, the summary fields;
- `ui/schema.py`, `ui/engine.py`, `ui/i18n.py`: the connection-trajectory field, with its English
  and French labels;
- `tests/`: the session-2 tests.
- Unchanged by design: `demand/maturity.py` (bands), `demand/growth.py` (laws),
  `demand/productive.py` (rule).

Session 3:

- `tree/build_tree.py`, `tree/reduce.py`, `tree/tree_model.py`: the persistent construction, the
  distortion report, the new node fields;
- `config.py`: `tree_mode`, `regime_branches`, `regime_fan`, `node_year`;
- `scenarios/assemble.py`: the demand year of a node under `node_year`;
- not read in session 1, to be confirmed by session 3: `model/build.py` and
  `model/investment_constraints.py` (no investment at operating-only nodes),
  `exact/tree_oracle.py` and `exact/tree_certify.py` (the descent must not move them), `run.py`
  (summary fields);
- `tests/`: the session-3 tests.

Noticed while reading, for whichever session next touches the file:

- `model/dispatch_constraints.py`: the module docstring says the storage recursion is "closed
  within each representative day"; the code chains it across the node's days and leaves the end
  free.
- `tree/build_tree.py`: the docstring says a late-stage node inherits the trajectory of the path
  it comes from; under the fan, consecutive nodes come from different paths.
- `demand/growth.py`: `main()` prints a French heading.
- Neither template village declares a place of worship (`community_mix`), whereas two churches
  are metered at each. It matters for the brownfield runs of session 4.

## 14. Points left to the author

| | Question | Default |
|---|---|---|
| 1 | High plateau when Gbowele's is not identified (4.3) | profile lower bound; census as sensitivity |
| 2 | Connection and growth trajectories drawn independently or paired (4.3) | independent |
| 3 | Bracket of a site with its own record (4.5) | its own fit |
| 4 | Reference year of the single certified year (8) | the root's year |
| 5 | Year a tree node stands for (9.3) | last year of its span, from session 4 |
| 6 | The root's own period operated under every regime (9.4) | yes, through operating-only nodes |
| 7 | Tree shape (9.6) | nine regimes, no fan: 46 nodes |
| 8 | Base and form of the network loss (10) | 13 % kept; settled in session 4 |
| 9 | Growth beyond 24 months (15) | maturity bands unchanged in sessions 2 and 3 |

**The author's choices (2026-11-07).** Points 1 to 9 stand at their defaults. An extra
milestone at year 2 was considered and rejected, as too close to the root to reinvest. The
points session 2 left open were decided as section 4.7 (record, silent meters, the S2-A5
test), section 5.3 (productive users) and section 4.5 (the `own` bracket) now state.

Left open by the revision, for session 4 unless the author settles them sooner:

| | Question | State |
|---|---|---|
| 10 | The census of households. The operator's field census counts 171 households at Gbowele (HH1 144, HH2 16, HH3 11) against the 159 (143, 5, 11) of `sites.py`, and 230 at Samionta against 231 | `sites.py` unchanged, so that no stored result moves; the bound `H` stays 159. With `H` = 171, Gbowele's plateau is still not identified: interval 92 to 171 on the roster record (127 to 171 on the extended one), the census variant at `r` = 0.094 per month and a midpoint at 28.0 months |
| 11 | Which record the tables hold | the roster record, both typing sources of the extended one exceeding 5 % (section 4.7); a fresh roster, or the field team's types for the seven profile-typed codes, would allow the extended record |
| 12 | A month without any reading in S2-A5 | counted inactive in the criterion as worded; read as no observation, both villages pass (section 12) |
| 13 | Meters silent for less than three months | four Gbowele households connected in May 2026 have recorded nothing since late August or early September 2026; by the next export they are failed meters or not |
| 14 | The productive intensity beyond the record | at Gbowele the rule expects about 0.63 productive users per connected household, against about 0.46 observed at `T` (42 for 92 households); under the anchored rule it only drives the increments after `T` |

## 15. Out of scope

- **Session 4**: change the defaults of `connection.mode`, `tree_mode` and `node_year` together;
  set `maturity_months = 0` for greenfield runs; recompute the greenfield test bench and the two
  real villages as brownfield; measure `both` against `last`; run the sensitivities of decisions
  1 and 8 (census plateau, a 19 % loss).
- **Growth beyond 24 months [decision 9].** Cohort ageing keeps the community's demand moving
  while households keep connecting, but each household still stops growing in the 25+ band,
  because no record runs much past two years: Gbowele's ends at 25 months and the fast trajectory
  inherits its last band. The default leaves the bands as they are. The alternatives are a 25-36
  band estimated on Samionta alone, or a long-run growth rate per household carried as a fourth
  persistent draw.
- A developer's own connection forecast on the `Site` record.
- Extending the meter archive in the repository past its last month.
- The optimisation of the distribution network and the control module, which are separate work.
