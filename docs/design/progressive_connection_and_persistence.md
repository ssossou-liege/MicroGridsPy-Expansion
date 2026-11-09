# Progressive connection and persistent scenario trees

*Design specification, written 2026-11-06 (session 1 of the series). Session 2 implemented
sections 4 to 7 and 10, and session 3 section 9, both on 2026-11-07; section 9.7 records how
section 9 was built, and section 12 what each session measured. Section 8 spans both.
Session 4, the same day, closed the record (section 4.7), applied the author's decisions on
the points of section 14 and switched the defaults together (section 15); session 4 bis, on 7
and 8 November, recomputed the results and ran the sensitivities (section 12).*

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
it stood: it is kept as the degenerate case of I4, and it was the shipped default until
session 4 made progressive connection the default (section 4.6).

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
   *As shipped since session 4:* the tables hold the extended record of section 4.7, whose
   `T` is October 2026, the archive's last complete month.
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
    #: "progressive" follows the fitted curves; "census" connects the whole census at
    #: village month 0, the model before progressive connection.
    mode: str = "progressive"
    #: Trajectory of the single certified year.
    trajectory: str = "central"
    weights: ConnectionWeights = field(default_factory=ConnectionWeights)
    pairing: str = "independent"              # [decision 2]
    high_plateau: str = "profile_lower_bound" # [decision 1]
    brownfield_bracket: str = "own"           # [decision 3]
    provenance: Provenance = ...              # the fit, and the roster it rests on

ProjectSettings.connection: ConnectionSettings
```

`mode` stayed `"census"` through sessions 2 and 3, so that they moved no stored result and
every existing test kept passing. Session 4 changed it to `"progressive"` together with the
tree's defaults (section 15), and session 4 bis recomputes the results; the tests that pin
the stored results set `"census"` explicitly. `validate()` refuses unknown names and weights
that do not sum to one, and `from_dict` round-trips the block.

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
  7 November 2026: its type column first and its category column where that is empty (session 4;
  the category column was read first before), read as a household of that category (HH1 to
  HH3), a productive user (SME) or a church (CHU). Where the census
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
above the 5 % the author set for the extended record, so the tables of sessions 2 bis and 3
held the roster record.

**The record shipped since session 4 is the extended one** (section 14, point 11). The 5 %
test measured the wrong thing. What the record feeds is the connected stock, not the types,
and the codes the profile types can move the stock at `T` by at most 4 households of the 96
Gbowele has on its grid, and by 1 of Samionta's 49 (`build_connection_curves.profile_bound`;
a test holds the bound under a twentieth of the stock). The roster, meanwhile, ends five months
before the meters do, and Gbowele connects in campaigns: 16 households and 28 productive users
in November and December 2025, 8 households in April 2026 and 35 in May. Between June and
October the meters show 6 more households, 4 of them in October, and 3 that left on a failed
meter; with 0074GBO, connected in December 2025 and absent from the roster, Gbowele has 93
households on its grid at the end of May and 96 at the end of October, against the roster's
92 in May. The census is
read type column first: its category column follows a taxonomy of its own for the household
tiers (it puts 78 of the roster's 128 HH1 in HH2), and read that way it differs from the roster
for 27.9 % of the 204 customers rather than 67.6 %. The profile types only what the census
leaves untyped; the change of column moves one code, 0074GBO, from HH2 to HH1.

Two figures given when this was decided do not hold, and the decision does not rest on them.
The roster record's own bracket puts Gbowele at 93, 101 and 105 households in October 2026
(village age 28 months), and the meters count 96, within it, not 123: 123 was the lower end of
Gbowele's plateau interval under the extended record before the corrections below (124 after
them), read as the stock. Nor did about thirty households connect in October; four did. What
the extended record changes is Gbowele's bracket: its plateau's lower bound rises from 92
households to 124, the logistic reading the campaign of May 2026 as the middle of a rise that
the five slow months after it do not undo (section 14, point 20). The roster record stays a
sensitivity, `build_connection_curves --record roster`.

**The archive, corrected (session 4) [decision 3].** A reading belongs to the code that held
the meter when it was taken, and a reading under a test code belongs to no customer. The
archive keeps neither the meter serial nor the code as the export recorded it, and the
readings of 0193GBO had been dropped when it was built, so it could not be corrected in place:
it was rebuilt from the operator's exports by `build_meter_archive`, whose rules changed three
ways. A code readable once its spaces are removed is that code, before the register's owner of
the meter (the register is written after the fact); a test code ("test1" to "test11") is
nobody's; and a code the roster or the field census knows is a customer whatever the type of
its meter, the exclusion by type staying for the codes neither knows. Under the old rules the
rebuild reproduces the archive to the reading, so the differences are the corrections alone:

- *0074GBO.* Its readings of 2025 were recorded under "test1" on the meter it holds today, and
  given to it through the register, hence a connection month of January 2025. Its readings
  from 17 December 2025 to 11 May 2026, recorded as " 0074GBO" on the meter 0173GBO holds
  today (the two exchanged meters on 11 May 2026), had gone to 0173GBO and been lost under its
  own. It is now connected in December 2025, its first month under its own code, with 5 721
  readings more, and 0173GBO loses 90 quarter-hours that were 0074GBO's.
- *Five more customers of Gbowele* held a meter of the test period and inherited its months
  under a test code: 0079GBO, 0169GBO, 0187GBO, 0190GBO and 0205GBO, each with a first reading in
  January 2025. They are roster customers, whose connection month is the roster's, so the stock
  does not move; their first readings now fall in their own months.
- *Samionta.* A meter recorded "0048SAM " from June 2024 to February 2025 and "0097SAM" since,
  and the register gives it to the second: eight months of 0048SAM were 0097SAM's. Both are
  roster customers, and nothing in the stock moves.
- *0193GBO*, a productive user of the roster whose meter the register types as a bench meter,
  comes back with its 29 259 readings since December 2025: Gbowele's productive users at `T`
  rise from 43 to 44. *0004SAM*, a place of worship, recovers three weeks of July 2024 on the
  meter that later served the plant room.

In the stock and the curves this moves one household's month: Samionta's curves and stock are
unchanged, and at Gbowele the stock from January to November 2025 is one lower, the plateau's
lower bound goes from 123 to 124 households, the rate at the census from 0.1135 to 0.1156 a
month and that of the lower bound from 0.1311 to 0.1329. The archive is read at generation as
well, and the calibration chain of `data/README.md` was run again on it: the segmentation loses
nine household-months and gains eight, all before their household's connection (0169GBO and
0187GBO under a test code, 0048SAM's recovered months), and one label, 0173GBO in May 2026, moves
from archetype 1 to inactive. Archetype 1 is measured on 1 256 household-months rather than
1 258, its mean peak at 40.7 W rather than 41.2; the mixture law moves in the 4-6 band only, the
inactive share of HH1 going from 2.15 to 2.40 %; Gbowele's productive mix counts 43 enterprises
rather than 42; and the exploratory clustering, a table for inspection, renumbers two of its
clusters. The scaling factors of `archetype_scaling.csv` were not fitted again: their own fit
leaves residuals of about 8 % on the energy and 10 % on the peak, and fitting them again would
add Monte-Carlo noise of that order for a shift of 1.3 %. The community profiles read another
archive, which already leaves the recovered codes out, and do not move.

Not corrected, because the rule does not reach them: readings with an empty code before the
owner's own code first appears on the meter. At Samionta those are the households' own trial
period, August to December 2023, on the meters they kept, and dropping them would remove
72 000 readings of real consumption. At Gbowele two meters recorded an empty code from the
morning of 15 January 2025, when the eleven test meters were installed, until their owners'
codes appeared: 0204GBO's, in December 2025, and 0023GBO's, in February 2025. They are most
likely two more meters of the test bench, and 0204GBO is a household of the register, whose
five months of 2025 before its connection, all at zero, enter the segmentation (not the
mixture law, which starts at the connection); 0037GBO and 0154GBO carry
months of empty codes before their roster dates around the commissioning of the plant. These
are a question for the operator (section 14, point 19).

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

*Decided (session 4, section 14, point 12).* A household with no reading at all in month `T`
is not observed, and it leaves both sides of the test: the mixture law was estimated on months
with readings, so a month without any is not an observation of the inactive state. This reading
was chosen after the result was seen, the criterion as first worded having failed on the
households without a reading and on them alone. The other reading, those households counted
inactive, is kept as a reported sensitivity (`active_check` returns both, `within` and
`within_counted_inactive`).

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
  record). Under the extended record shipped since session 4 the record holds 16 and 44,
  customers of the archive the roster does not list among them, while the mix rests on the 14
  and 43 enterprises of the roster metered over the last year: the split keeps the total and
  puts each class within one of its share. It is
  the simplest form that reproduces the observed count at `T` exactly: nothing is drawn on the
  record, and beyond it the observed users stay and only the rule's increment is drawn, never
  negative. A site that declares its own enterprises
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

Default **B**. While the tree's convention is the first year of a span, B is A for a new site
and D for a brownfield one; under the convention of section 9.3 it is the plan's year 4.
Command line: `certify --connection {low,central,high}`, defaulting to
`settings.connection.trajectory`; the summary JSON records the connection trajectory, the
village age and the connected stock by category. `--brownfield` also switches the demand to
the observed state of section 4.5, which is the run the real Samionta still lacks: 41 months,
a few dozen households, its own plant.

*As built (session 4).* `exact/certify.py` reads the node year: `certified_year(year0_age,
node_year)` returns the plan year the certified year is, `ModelConfig.demand_year(0)`, and the
village age at its first month, the year-0 age plus twelve months a year. Under the default
`node_year = "last"` that is the plan's year 4, and the village age 48 months for a new site
(year-0 age 0) or the derived year-0 age plus 48 for a village with its record.
`certify --node-year first` certifies the plan's year 0, options A and D. The summary records,
under `connection`, the node year, the plan year, the village age of the certified year, the
year-0 age and whether it was derived, and the connected stock by category in the first and
the last month of the year; `--out` writes it elsewhere than `results/`, and a brownfield run
carries `_brownfield` in its name. The interface's certificate (`ui/engine.size_site`) takes
its year from the same function.

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
`first` until session 4 and `last` since. `both` is not built (section 14, point 18).

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
4 and `"persistent"` since), `ModelConfig.regime_branches = 9` and `ModelConfig.regime_fan`,
root first. Since session 4 `regime_fan` defaults to `None`, one child at every milestone of
the calendar, so that the default tree accepts any stage calendar; on the five milestones it is
`(1, 1, 1, 1, 1)`, and `ModelConfig.fan()` returns the tuple.

### 9.7 As built (session 3)

Session 3 built sections 9.1 to 9.6 as written, with decisions 1, 5, 6 and 7 at their defaults,
and settled the following points the text left open. None of them moves the fan tree, which
stays the default.

- **The root's period is a field.** `ModelConfig.root_period` is `"regimes"` (decision 6, the
  default under `tree_mode = "persistent"`) or `"root"`, the alternative, in which the root
  operates its span on the medoid of the whole ensemble and the regime branches hang directly
  below it. It is read only by the persistent builder. The operating-only nodes stand at stage
  0, beside the root, with the root's discount factor and span; the root's span is then
  `n_years = 0`, and `ScenarioTree.operates(n)` is `n_years[n] > 0`.
- **A root that operates nothing has no operating block.** `model/dispatch_constraints.py` and
  `model/economics.py` skip a node with `n_years = 0`: its flows are in no constraint and at no
  cost, so they rest at zero, and its capital is charged at the operating-only nodes, which hold
  its plant. `model/investment_constraints.py` fixes `b_pv`, `b_batt`, `b_inv` and `b_pv_ac` at
  zero at a node that does not invest (`ScenarioTree.invests`, absent meaning true) and sets its
  generator binaries equal to its parent's.
- **The descent.** `exact/tree_certify._monotone` sets a node that does not invest to its
  parent's plant, and such a node is never a coordinate of the search. The controller is still
  simulated at the root, at zero weight, so that every node has a trace.
- **`exact/first_stage.py` is not wholly unaffected.** Its boxes are in root coordinates and need
  nothing. Its costless bound was affected twice. The energy term was weighted by the root's
  operating weight, which is zero at a persistent root; it now sums over the root and every node
  that holds the root's plant alone, each with its own year (`FreeBound.held`), which on a fan is
  the root alone, as before. And the capital term was wrong on every tree: it charged the box's
  cheapest corner at the root's prices with the whole tree's weight, whereas the programme charges
  a node's capacity at that node's prices, and every cost future of the shipped settings has
  them fall (the array at 0.47 to 0.82 of its year-0 price by year 20). The term exceeded what
  the programme charges, so the bound could prune the optimum. It now uses the node annuities
  averaged with the tree's weights. The first-stage certificates stored in `results/` were
  computed with the overstated term and are not re-run here.
- **A flat channel chose the medoids (a defect older than this session).** `tree.reduce`
  scaled each feature channel by its spread and replaced a spread of zero by one. A channel
  that does not vary has a spread of zero in exact arithmetic and of a few units of rounding in
  floating point, depending on its value and on how many outcomes there are: thirty prices of
  151.2 $/kW give 2.8e-14. Divided by that, the channel became a constant of order 1e15, and
  `timedomain.kmedoids.pairwise_distances`, which computes the distances in their expanded form,
  lost every other channel to cancellation: all distances came out zero, and the medoid was the
  first outcome of the list. Two places meet such channels. At year 0 every cost future starts
  from the same prices, so the fan's root has been the first path drawn rather than the medoid
  of year 0, in every stored tree. Within one regime the cost future is fixed, so the prices
  are flat at every stage, and the first version of the persistent builder took the first path
  of each regime at every milestone: its tree paths were Monte-Carlo paths, and its
  plausibility came out zero. `_scaled` now centres the features and sets to zero a channel
  whose spread is below a billionth of its magnitude. The persistent builder, the regime
  features and the distortion always use it. The fan uses it only under
  `ModelConfig.centre_features = True`; the default stayed `False` through session 3, so that
  the fan and its objective were those of the stored results, and is `True` since session 4
  (section 14, point 15).
- **Regime features** are the unscaled stage features of section 9.2, grid channel included,
  averaged over a regime's paths, concatenated over stages 1 to S-1, then centred and scaled
  across regimes. The k-medoids is weighted by regime mass.
- **The grid split (9.2, step 5)** is made whenever the grid state differs between paths at some
  milestone, which is what `arrival_uncertain` produces. An unconnected parent with a fan of `f`
  receives `max(1, round(f s))` children from the arrivals and `max(1, f - round(f s))` from the
  rest, `s` being the arrivals' share. A grid present at year 0 on some paths and not others is
  refused: the root's span cannot be split on it.
- **`NodeData`** carries `connection`, `cost_scenario`, `connected_households` (the stock, all
  categories together, in the first month of the year the demand stands for) and
  `village_age_months` (that month's village age); `AxisDraw` carries the last two.
- **`node_year`** takes `"first"` and `"last"`. The demand of a node under `"last"` is read at
  village age `base + 12 * (y + D - 1)`; the yield, the temperature and the prices stay the
  milestone's, and the stream of draws is unchanged, since the demand consumes one draw whatever
  age it is read at. `"both"` is refused with a message: it would give every node two operating
  years, which changes how the programme is indexed, for a bias `"first"` and `"last"`
  bracket. Session 4 decides whether it is needed. `exact/certify.py` does not read
  `node_year`, so option B of section 8 stays the first year of the span until session 4 makes it
  follow. *Session 4:* it reads it (section 8), and `both` stays refused.
- **Distortion (9.5), on one scale.** Every distance of `tree.distortion` is taken in the stage
  features of the whole ensemble, scaled by their spread across it, so that the two trees are
  measured with one ruler. `tree.reduction_error` keeps its meaning, the error of each reduction
  in its own scale: for a persistent tree, the within-regime errors weighted by branch mass, whose
  scale is a regime's own and therefore narrower. The two are not comparable; the distortion is.
  - `stage[y]`: each path to the nearest operating node of its branch at `y`, averaged over the
    paths, which weights each regime by its mass. On a fan it equals `reduction_error`.
  - `regime`: the mass-weighted distance from each regime to the nearest regime the tree *holds*,
    one that some path keeps from the first milestone on. On a persistent tree that is the
    representative, and the measure is the one section 9.5 defines. A fan that holds no regime
    along any path has none, and reports `None`.
  - `persistence_violations` counts the root-to-leaf paths with a violation, and
    `violations_by_kind` splits them. The stock is compared over the operating nodes only: the
    root of a persistent tree carries the medoid of the whole ensemble, which belongs to no
    regime, and operates nothing. Under `root_period = "root"` the root operates, and a fall from
    it to a low regime is counted.

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

**Decided (session 4).** The loss stays 13 % of the energy injected, proportional. The 18 to
19 % gap of October 2026 included the street lighting; net of it, the gaps are about 13 % at
Samionta and 11 % at Gbowele, so the level holds and the 19 % sensitivity of section 15 is
dropped. The loss measured is flat over the day: about 0.3 kW at Gbowele, uncorrelated with the
load, and Samionta's residual, which mixes the loss with other uses, is flat too, about 0.6 kW.
Its form is left to the work on the distribution network, which will model the conductors
themselves. `network_loss_provenance` says so and stays unverified, the form being the
measured one's opposite: a share shrinks with the demand of a village still connecting, where
the measured loss does not.

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

As built (`tests/test_persistent_tree.py`), the single-regime property is two tests: with
`root_period = "root"` the persistent builder gives the fan's tree, node for node, and
`test_moving_the_root_period_below_it_keeps_the_programme_value` checks that with the
operating-only node the programme's value is the fan's. Four tests were added:
`test_a_flat_channel_does_not_decide_the_medoid` (section 9.7),
`test_a_tree_of_every_regime_has_no_regime_distortion`,
`test_the_tree_shapes_are_refused_when_they_do_not_fit` (an unknown mode or year, `"both"`, a
fan that branches at the root) and `test_the_tree_has_the_size_section_9_6_gives`, on four
rows of the table of section 9.6. Every ensemble there is synthetic; the file runs in about
twenty seconds.

Session 4, in `tests/test_progressive_connection.py`:

| Test | Property |
|---|---|
| `test_the_tables_hold_the_extended_record` | the curves end at the archive's last complete month at both villages, the archive's own customers enter the record, and the profile's types can move the stock at `T` by no more than a twentieth of it |
| `test_the_census_type_column_is_believed_before_its_category` | on a synthetic workbook, the type column decides, the category column fills its blanks, and a type the census does not use leaves the code untyped |
| `test_a_reading_belongs_to_the_code_that_held_the_meter` | on synthetic exports: a test code is nobody's, a code readable once its spaces are removed is that code before the meter's owner, an unreadable one goes to the owner, a known code is a customer on a bench meter and an unknown one is not, and a recovered reading never displaces a recorded one |
| `test_the_archive_holds_the_corrected_codes` | 0074GBO connects in December 2025, 0193GBO records as a productive user, and the six customers who inherited a test meter's months start with their own |
| `test_the_templates_declare_the_churches_their_record_holds` | each template declares as many places of worship as its record holds on the grid at `T`, all connected before the plan's year 0 |
| `test_the_active_households_are_counted_over_the_observed_ones` | S2-A5 holds on the shipped record at both villages, over the households with a reading in `T` |
| `test_the_defaults_are_the_progressive_model` | the settings, the uncertainty space and the configuration switched together, and `both` is refused |
| `test_the_certified_year_is_the_root_s` | the certified year is the plan's year 0 under `first` and year 4 under `last`, the village age twelve months a year older, and the command line and the interface take it from one function |

Two tests were rewritten for the extended record: the brownfield state is compared net of
the record's departures, and the split of the observed productive users keeps its total and
puts each class within one of its share. The tests that draw trees or simulate the template
villages set the stored settings explicitly (`connection.mode = "census"`, `tree_mode =
"fan"`, `node_year = "first"`, `centre_features = False`, `maturity_months = 12`), so that they
keep holding what they held, on the census pools: `test_layer4_tree.py`,
`test_the_first_stage_can_be_certified.py`, `test_the_plant_already_built_is_not_bought_again.py`,
`test_the_project_reaches_every_calculation.py`, `test_the_tree_is_worth_what_it_costs_to_ignore.py`
and `test_the_tree_says_what_futures_it_weighs.py`; the fans of `test_persistent_tree.py`
name their mode.

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

Results (2026-11-07), on Samionta, seed 0, both trees drawn from one ensemble each time; the
fan is the shipped one (`centre_features = False`), and "fan, centred" is the same fan with the
corrected scaling of section 9.7, for what session 4 will see.

**S3-A1.** The fourteen tests of `tests/test_persistent_tree.py` pass in about fifteen seconds.
The fan and its objective were compared with the code of commit 9855f67, run on the same cache:
on the default ensemble (1 000 paths, five milestones, branching (1, 3, 2, 2, 2), eight
representative days) and on two milestones (100 paths, four days), the nodes, parents,
probabilities, discount factors, operating years, reduction errors, every node's arrays,
costs, pathway, policy, grid state and trajectory, the objective (78 171.102 $ and
106 578.771 $) and the root plant are identical bit for bit. The full suite, in `mgpy_dev`: 468 passed and 1 skipped, in 8 min 17 s, every pool it reads having been built beforehand.

**S3-A2.** The pools: session 2 bis invalidated them, and the five-milestone ensembles need
fifteen under the whole census and forty-five under progressive connection (three growth
trajectories, three connection trajectories, five village ages). They were built in parallel
before the ensembles were drawn: the nine census pools of 132, 192 and 252 months in 944 s on
nine processes (those of 12 and 72 months were already cached), and the forty-five progressive
pools in 1 598 s on eleven, about 300 to 570 s each. Drawing 1 000 paths from cached pools then
takes 326 s, so both ensembles were drawn at the default size, 1 000 paths;
`connection.mode = "progressive"` was set in memory for that run only.

| Ensemble | Regimes | Fan: paths violating, of 24 | of which the stock falls / the regime changes / the grid leaves | Persistent: paths violating, of 9 |
|---|---|---|---|---|
| default, whole census | 9 | 24 | 0 / 24 / 0 | 0 |
| progressive connection | 27 | 23 | 8 / 23 / 0 | 0 |

Under the whole census the stock is 231 at every node, so only the regime can change, and it
does on every path of the fan: no path of it keeps one regime. Under progressive connection the
connected stock falls along a third of the fan's paths, the village losing households between
two milestones.

**S3-A3.** Both persistent trees have 46 nodes, of which 45 operate, and 9 leaves: nine regimes
of independent growth and cost draws under the census, each its own branch, and twenty-seven
under progressive connection reduced to nine, as section 9.6 gives for R = 9 and no fan. The
fan has 46 nodes, all operating, and 24 leaves.

**S3-A4.** `python -m microgrid_expansion.exact.first_stage --tree-mode persistent --mc-paths
200 --rep-days 4 --max-programmes 20 --max-seconds 2400`, its record written outside `results/`.
The persistent tree, 46 nodes of which 45 operate, was drawn in 52 s from cached pools. Under
the divided array, the project's first coupling, and Gurobi, the programme gives a bound of
82 773 $, and the descent takes the programme's plan from 106 353 $ to 94 484 $ in 17 809
evaluations and 86 s, the operating-only nodes held at the root's plant throughout. The search
over the first stage then solved its 20 programmes in 945 s without a proof. The year-0 plant
is 45.5 kW of array on the battery's bus and 34.5 kW on the load's, 195 kWh of storage, 35 kW of
conversion and the 8 kW set, at 94 484 $ against a lower bound of 83 561 $: a gap of 10 922 $,
11.56 %, with no plant unresolved. The costless bound, 19 170 $ over the whole lattice, pruned
no box; four boxes were infeasible, their converters unable to admit their arrays. The run took
1 149 s. The gap is mostly the price of the heuristic itself, the anticipative programme lying
12.4 % below the descent, and it closes with more programmes rather than with another tree.
A first run, made before the flat-channel defect of section 9.7 was found, drew its tree from
the first path of each regime and was stopped.

**S3-A5.** The five measures, each distance in the stage features of the whole ensemble,
centred and scaled by their spread across it (section 9.7):

| Measure | Census: fan | fan, centred | persistent | Progressive: fan | fan, centred | persistent |
|---|---|---|---|---|---|---|
| `stage[0]` | 2.207 | 2.082 | 0.969 | 2.427 | 2.132 | 1.699 |
| `stage[5]` | 1.946 | 1.946 | 1.156 | 2.087 | 2.087 | 1.883 |
| `stage[10]` | 2.277 | 2.277 | 1.117 | 2.373 | 2.373 | 1.752 |
| `stage[15]` | 2.314 | 2.314 | 1.119 | 2.415 | 2.415 | 1.793 |
| `stage[20]` | 2.321 | 2.321 | 1.120 | 2.445 | 2.445 | 1.785 |
| `regime` | none held | none held | 0.000 | 7.260 (1 held) | 7.260 (1 held) | 2.657 |
| `coverage` | 5.178 | 5.119 | 2.661 | 5.454 | 5.324 | 4.128 |
| `plausibility` | 3.448 | 3.416 | 1.315 | 4.192 | 4.157 | 1.898 |
| `persistence_violations` | 24 of 24 | 24 of 24 | 0 of 9 | 23 of 24 | 23 of 24 | 0 of 9 |

Three readings. The persistent tree is closer to the ensemble on every measure, with nine
paths against twenty-four. Coverage was expected to favour the fan (section 9.5), and it does
not: two or three medoids a milestone stand for at most three of the nine or twenty-seven
regimes there, whereas each persistent path is one regime throughout, so a sampled path finds a
nearer tree path among the nine than among the twenty-four combinations. And the corrected
scaling moves only the fan's year 0, where every price is the same: its later medoids are
unchanged, and its root moves from path 0, the first drawn, to path 733 under the census and
781 under progressive connection, which are also the persistent root's.

Session 4 (2026-11-07) is done when the record is closed, the author's decisions applied and
the defaults switched, and the runs of session 4 bis can be planned: the record below, the
reduced runs after it. Nothing in `results/` was written.

**The record shipped**, extended, after the corrections of section 4.7:

| Village | Origin | `T` | Village age at `T` | Households on the grid at `T` | Productive users at `T` | Plateau interval at 95 % | Identified |
|---|---|---|---|---|---|---|---|
| Samionta | June 2023 | October 2026 | 40 months | 49 | 16 | 49 to 53 | yes |
| Gbowele | June 2024 | October 2026 | 28 months | 96 | 44 | 124 to 159 | no |

The curves (`connection_curves.csv`), plateau in households, rate per month, midpoint in
months of village age:

| Village | Estimate | Profile lower bound | Profile upper bound | Census |
|---|---|---|---|---|
| Samionta | 49.0 (s.e. 1.9), 0.131, 13.2 | 49, 0.131, 13.2 | 53, 0.110, 15.0 | 231, 0.040, 68.5 |
| Gbowele | 159 at its bound, 0.116, 24.3 | 124, 0.133, 20.2 | 159, 0.116, 24.3 | 159, 0.116, 24.3 |

Samionta's curves are those of session 2 bis; at Gbowele the lower bound rose from 92
households on the roster record to 124 (section 14, point 20). The bracket of a new site
(section 4.3) is therefore `low` at a share of 0.212, `high` at 0.780 and `central` at 0.496,
against 0.212, 0.579 and 0.395 on the roster record, and a village with its own record
follows its own bracket: Samionta 49, 49 and 53 households, Gbowele 124, 141.5 and 159.

**S2-A4**, the connected stock of a new site with each village's census at village ages 12,
24, 36, 48, 60 and 120 months (48 is the certified year under `last`), the high plateau at
its default, the profile lower bound:

| Census | `low` | `central` | `high` |
|---|---|---|---|
| Samionta, 231 | 23, 39, 47, 48, 49, 49 | 40, 83, 106, 113, 114, 115 | 45, 112, 161, 176, 179, 180 |
| Gbowele, 159 | 15, 27, 32, 33, 33, 33 | 28, 57, 73, 77, 78, 78 | 31, 77, 110, 121, 124, 125 |

With the census as the high plateau (decision 1's sensitivity), `central` reaches 136 and
`high` 217 households at Samionta at 48 months, and 93 and 149 at Gbowele. The curves keep
their order at every age: none crosses another. A village with its own record, from its
record: Samionta 44 households in January 2026, the plan's year 0 (village age 31), and 48,
48 and 48 at 36 months, 49, 49 and 53 at 60; Gbowele 50 in January 2026 (age 19), and 113, 120
and 126 at 36 months, 124, 140 and 157 at 60.

**S2-A5**, in October 2026, over the households connected before it began, net of
departures:

| Village | Households | Without a reading in `T` | Expected active over the observed (s.d.) | Metered | Within 2 s.d. | Counted inactive instead: expected (s.d.), within | And the failed meters kept: households, expected (s.d.), within |
|---|---|---|---|---|---|---|---|
| Samionta | 48 | 0 | 46.2 (1.3) | 46 | yes | 46.2 (1.3), yes | 49, 47.2 (1.3), yes |
| Gbowele | 92 | 4 | 84.3 (1.9) | 84 | yes | 88.1 (1.9), no | 95, 91.0 (1.9), no |

The criterion holds at both villages under the reading decided (section 4.7); counted
inactive, the four Gbowele households silent since late August or early September fail it,
as in session 2 bis.

**S2-A6**, in October 2026, each village under its own growth trajectory: metered 16 at
Samionta and 44 at Gbowele; anchored on the record 16 and 44; the rule alone, per connected
household, 11.4 and 60.8, and per active household 11.0 and 58.0. 0193GBO is the one more at
Gbowele than in session 2 bis.

**What decisions 2 and 3 changed.** Decision 2 changed the type of one code, 0074GBO, from
HH2 to HH1, which moves one household between categories at Gbowele and nothing in the total.
Decision 3 moved 0074GBO's connection from January to December 2025, which lowers Gbowele's
stock by one from January to November 2025 and raises the lower bound of its plateau from 123
to 124 households, the rate at the census from 0.1135 to 0.1156 a month and that at the lower
bound from 0.1311 to 0.1329; S2-A5 at Gbowele moves from 84.4 to 84.3 expected over the
observed, and S2-A6 from 43 to 44 with 0193GBO. Nothing moves at Samionta. Before either,
the extended record of session 2 bis already had 96 households at Gbowele and 49 at
Samionta on the grid at `T`.

**Reduced runs under the new defaults** (2026-11-07, Gurobi, sixteen cores, each run alone on
the machine, written outside `results/`):

| Run | What it is | What it returns | Time |
|---|---|---|---|
| `certify --site Samionta` | the greenfield bench at Samionta's census, central connection | plan year 4, village age 48 months (0 at year 0), 113 households in the first month and 114 in the last; 26.0 kW of array on the battery's bus and 19.0 kW on the load's, 115 kWh, 20.0 kW of conversion, the 8 kW set, at 4 262 $/yr, proven, 5.5 % above the cost-optimal bound | 79 s, of which 16 s of certification |
| `certify --site Samionta --brownfield` | its own plant and record, the central trajectory of its own bracket | plan year 4, village age 79 months (31 at year 0, from the record), 49 households; the standing plant itself (25.5 kW of array in whole modules, 95 kWh, 47.5 kW, 16 kW), nothing added, at 2 057 $/yr, proven | 28 s |
| `certify --site Gbowele --brownfield` | the same at Gbowele | plan year 4, village age 67 months (19 at year 0), 140 households; 42.2 kW of array on the battery's bus and 12.8 kW on the load's, 150 kWh, 32.5 kW, 16 kW, against the standing 22.45 kWp, 40 kWh and 24 kW, at 4 341 $/yr, proven, 5.9 % | 67 s |
| `run --mc-paths 100 --rep-days 4` | the persistent tree, Samionta greenfield | 46 nodes, 9 leaves, 26 regimes reduced to 9, no path violating persistence; programme bound 57 223 $ in 12 s, descent from 72 821 to 66 534 $ in 68 s; year-0 plant 35.0 kW and 21.0 kW of array, 135 kWh, 27.5 kW, 8 kW; price of the heuristic 16.3 % | 133 s |
| `first_stage --mc-paths 100 --rep-days 4 --max-programmes 8 --max-seconds 1200` | the same tree | the same year-0 plant at 66 534 $ against a lower bound of 57 809 $, a gap of 13.1 % with no plant unresolved; 8 boxes, one infeasible, none pruned by the costless bound (17 505 $) | 457 s: tree 24 s, incumbent 118 s, programmes 315 s |

Three remarks. The tree's year-0 plant is larger than the single certified year's: the root's
span is operated under each of the nine regimes, and the high connection trajectory has 176
households at 48 months where the certified year has the central one's 113. The brownfield
certificate of Samionta reports a price of the heuristic of 18 $/yr and 1 835 %: the relative
figure is read against the cost the dispatch can move, net of the standing plant's annuity,
which is about a dollar a year when nothing is bought, and only the absolute figure means
something there (a display defect older than this session). Gurobi warns of 1 537 unknown
variables in the bounds section of each tree programme: the flows of the root, which operates
nothing and enters no constraint (section 9.7), and which the modelling layer still bounds.

**For session 4 bis**, with the stored settings (1 000 paths, 64 days, first stage at most 40
programmes and four hours):

- *Pools.* The 45 progressive pools of Samionta's greenfield tree (village ages 48 to 288
  months) are in the cache, built in 37.5 minutes on twelve processes together with the six
  census pools the tests read: about 180 s a pool on the low trajectory, 430 s on the central,
  640 s on the high and 900 s for the whole census, four simulated years each. They stay valid
  as long as nothing the demand fingerprint covers changes. Every other tree needs its own
  45, which on twelve processes take about 12 minutes for Samionta brownfield (some 50
  households), 35 for Gbowele brownfield (124 to 159), 30 for `first` against `last`, 30 for
  the census plateau of decision 1 (30 pools) and 35 for 171 households at Gbowele.
- *A single certified year*: half a minute to two minutes, the simulated year included; the
  runs above are already at full settings.
- *`run`*: drawing 1 000 paths from cached pools took 326 s in session 3, and the incumbent of
  the stored first-stage run, programme and descent at 64 days, 320 s: a quarter of an hour
  or so with the reduction to representative days.
- *`first_stage`*: the stored run, a fan of 46 nodes at 64 days, took 2.2 hours, of which 66
  minutes for the tree and 59 for 40 programmes, 88 s each; the reduced run here spends 39 s
  a programme at 4 days. Expect 1.5 to 2.5 hours for each first-stage certificate within its
  four-hour budget, for each village and each case.

Session 4 bis (2026-11-07 and 08) is done when every result `results/` held is computed
again under the shipped defaults, the old ones are archived, and the sensitivities the
specification left to it are run. The old results are in
`results/superseded/2026-11-07_before_progressive_connection/`, and
`results/superseded/README.md` says why they are superseded and how to tell them apart.
Every new result was computed with the stored settings (1 000 paths, 64 representative days,
seed 0, the stored programme budgets, Gurobi), on the working tree of commit c710e03 with this
session's changes, which the session's commit holds; the studies that record a commit record
c710e03.

**What the runs needed or proved broken.** Five changes, none of which moves a default:

- *The price of the heuristic of a single year* (`exact/certify._price_relative`) is read
  against what the plant costs under the cost-optimal dispatch, `z_opt` less the grid
  connection and the infrastructure, which are not the plant; the standing plant now stays
  in. It was netted out with them, so an extension that buys nothing was read against its
  fuel alone: Samionta's plant, 18 $/yr dearer under the controller, reported 1 835 %, and
  now reports 0.9 %. On bare ground nothing stands and no figure moves. The tree reads its
  price the same way (`run.py`).
- *The descent fell below the standing plant* (`exact/tree_certify._standing`). It moves
  totals, and the upper oracle charges only what a total adds over the plant that stands, so
  a node moved below it was charged nothing for capacity that was not there: stepped down,
  the 16 kW set became a free 8 or 12 kW set and the pack fell to zero. Every node is now
  raised to the standing plant, and the ratings below the set on site are not offered.
  Found reading the code before the first brownfield tree; the test that shows it failed
  before the change.
- *The tree's report left the standing plant out* (`post/kpis.expected_npc_lcoe`,
  `run.py`). Neither oracle carries what it still owes, being the same under every plan, and
  the first brownfield tree reported Samionta at 0.0001 $/kWh and a price of the heuristic of
  16.2 % of 41 $. The report now charges it every operating year, on the terms the certificate
  does (2 054 $/yr at Samionta, 1 234 $/yr at Gbowele), and says so
  (`standing_plant_usd_yr`, `standing_plant_usd`); a plan on bare ground reports as it did.
  Both brownfield trees were run again after it; the plans did not change.
- *Options*: `run --brownfield` (the tree could not be asked for an extension), its summary
  named `_brownfield` as the certificate's is, and `--project` on `certify` and `run`, which
  reads a project's parameters from YAML in place of the shipped ones. The sensitivities run
  through them (`results/sensitivities/README.md`).
- *`ProjectSettings.productive_intensity_scale`*, default 1, a factor on the intensity the
  productive-use rule reads, for the certified year: `build_site_year` passes it to the
  generator and adds it to the key only away from one, `certify` and the interface's
  certificate read it, and the tree refuses a value other than one rather than ignoring it.
  The generator's code is digested into the demand key, so the fingerprint moved from
  85a1c1293f51 to 75451880b1f4 and every pool was built once more (240 pools, below); the
  bench certificate at the new fingerprint is the one session 4 computed, to the dollar. The
  certificate also records, under `connection`, the high plateau, the census and the factor.

**Old against new.** Plant as array on the battery's bus + array on the load's bus,
storage, conversion, generating set. For a single year the cost is the annual cost under the
controller, the gap is to the cost-optimal bound over the proven lattice, and the price of the
controller is `price_rel_pct`; for a tree the cost is the expected cost under the controller,
the bound is the programme's and the price is against it. Files are in `results/` (new) and
`results/superseded/2026-11-07_before_progressive_connection/` (old).

| Result | Old | New | New file |
|---|---|---|---|
| Bench, Samionta central, VOLL 1 | 42.25 + 30.25 kWp, 180 kWh, 32.5 kW, 8 kW; 6 373 $/yr; proven, 4.8 %; controller 306 $/yr, 5.0 %; 0.0870 $/kWh (twelve months, 231 households) | 26 + 19 kWp, 115 kWh, 20 kW, 8 kW; 4 262 $/yr; proven, 5.5 %; controller 233 $/yr, 5.8 %; 0.0896 $/kWh (plan year 4, 48 months, 113 households) | `summary_certification_samionta_central_mixed_m48_voll1_ccentral.json` |
| Bench, VOLL 0.5 and 3 | as at VOLL 1 | as at VOLL 1, to the dollar | `..._m48_voll0.5_ccentral.json`, `..._m48_voll3_ccentral.json` |
| Bench, slow growth | 26 + 19 kWp, 130 kWh, 20 kW, 8 kW; 4 493 $/yr; proven, 5.2 %; 5.4 % | 19.5 + 12 kWp, 85 kWh, 15 kW, 8 kW; 3 139 $/yr; proven, 5.5 %; 5.8 % | `summary_certification_samionta_slow_mixed_m48_voll1_ccentral.json` |
| Bench, fast growth | 55.25 + 42.25 kWp, 240 kWh, 42.5 kW, 8 kW; 8 549 $/yr; proven, 4.5 %; 4.7 % | 39 + 25.5 kWp, 150 kWh, 30 kW, 8 kW; 5 512 $/yr; proven, 4.4 %; 4.7 % | `summary_certification_samionta_fast_mixed_m48_voll1_ccentral.json` |
| Bench, Gbowele central | 29.25 + 21.25 kWp, 130 kWh, 22.5 kW, 8 kW; 4 821 $/yr; proven, 5.5 %; 5.8 % (159 households) | 19.5 + 14.5 kWp, 80 kWh, 15 kW, 8 kW; 3 150 $/yr; proven, 6.2 %; 6.6 % (77 households) | `summary_certification_gbowele_central_mixed_m48_voll1_ccentral.json` |
| Samionta with its plant, one year | 65 + 6 kWp, 180 kWh, 50 kW, 16 kW; 4 979 $/yr; proven, 5.8 % (twelve months, 231 households, the direct coupling of the comparison) | the standing plant, 25.5 + 0 kWp in whole modules, 95 kWh, 47.5 kW, 16 kW, nothing added; 2 057 $/yr; proven, 0.9 %; controller 18 $/yr, 0.9 %; 0.1626 $/kWh (plan year 4, 79 months, 49 households) | `summary_certification_samionta_central_mixed_m79_voll1_ccentral_brownfield.json` |
| Gbowele with its plant, one year | 32.5 + 17.5 kWp, 135 kWh, 25 kW, 16 kW; 4 075 $/yr; proven, 5.8 % (twelve months, 159 households) | 42.25 + 12.75 kWp, 150 kWh, 32.5 kW, 16 kW; 4 341 $/yr; proven, 5.9 %; 6.2 %; 0.0901 $/kWh (plan year 4, 67 months, 140 households) | `summary_certification_gbowele_central_mixed_m67_voll1_ccentral_brownfield.json` |
| Tree, Samionta | root 41.5 + 22 kWp, 175 kWh, 32.5 kW, 8 kW; 87 556 $ against 82 517 $; controller 6.1 %; 0.0729 $/kWh; fan, 24 leaves | root 29 + 21 kWp, 125 kWh, 22.5 kW, 12 kW; 66 492 $ against 61 871 $; controller 7.5 %; 0.1013 $/kWh; persistent, 9 leaves | `summary_tree_samionta.json` |
| Tree, Gbowele | root 26 + 20 kWp, 125 kWh, 20 kW, 8 kW; 65 659 $ against 61 319 $; 7.1 %; 0.0803 $/kWh | root 19.5 + 15 kWp, 95 kWh, 15 kW, 8 kW; 44 461 $ against 41 991 $; 5.9 %; 0.0961 $/kWh | `summary_tree_gbowele.json` |
| Tree, Samionta with its plant | none | the standing plant at every node, nothing added; 48 $ of operation against 41 $, controller 0.02 %; with the standing plant, 27 511 $ and 0.0859 $/kWh | `summary_tree_samionta_brownfield.json` |
| Tree, Gbowele with its plant | none | root 30.81 + 23.64 kWp, 155 kWh, 24 kW, 16 kW; 43 294 $ against 39 433 $; controller 6.9 %; with the standing plant, 59 786 $ and 0.0728 $/kWh | `summary_tree_gbowele_brownfield.json` |
| Value of the tree, Samionta: building the certified central plant at year 0 against the tree's root | 88 226 $ against 87 556 $, 0.77 % | 67 921 $ against 66 492 $, 2.15 % | `summary_value_of_tree_samionta.json` |
| Value of the tree, the other fixed roots (slow, fast, mean value) | 25.4 %, 12.8 %, 1.5 % | 16.5 %, 2.8 %, 2.2 % | the same |
| Value of the tree, perfect information (growth; everything) | 5.4 %; 0.13 % | 5.0 %; 24.9 % | the same |
| Value of the tree, seed to seed | 34.7 % of the expected cost | 8.0 % | the same |
| Build once, Samionta | flexibility worth 16 960 $ (19.4 %); a campaign above 16 218 $ makes building once cheaper | 9 949 $ (15.0 %); above 17 791 $ | `summary_build_once_samionta.json` |
| Build once, Gbowele | 16 815 $ (25.6 %); above 20 958 $ | 2 684 $ (6.0 %); above 4 003 $ | `summary_build_once_gbowele.json` |
| Price sensitivity, Samionta | every set within the seed-to-seed noise (15.1 % of the cost) | the noise falls to 5.5 %, and the high and the landed-battery sets move the root beyond it: high prices 40 kWp, 85 kWh, 8 kW against 50 kWp, 125 kWh, 12 kW | `summary_price_sensitivity_samionta.json` |
| Price sensitivity, Gbowele | every set within the noise (11.2 %) | noise 5.9 %; high and landed-battery sets beyond it (27.5 and 30.5 kWp, 65 and 70 kWh against 34.5 kWp, 95 kWh) | `summary_price_sensitivity_gbowele.json` |
| First stage, Samionta | 41.5 + 22 kWp, 175 kWh, 32.5 kW, 8 kW at 87 556 $ against 82 846 $, gap 5.38 %, 40 programmes, bound that could prune the optimum | 29 + 21 kWp, 125 kWh, 22.5 kW, 12 kW, the tree's own root, at 66 492 $ against 62 376 $, gap 6.19 %, not proven; 40 programmes, 9 boxes pruned by a programme, none by the costless bound (17 556 $), 2 plants unresolved, bounded by the descent from above only | `summary_first_stage_samionta_mixed.json` |

Five readings. The bench plant at the plan's year 4 is about two thirds of the old one, the
village there being 113 households of 231 rather than all of them, and every certificate is
still proven. The price of the real controller on the single year is 5.8 % rather than 5.0 %;
the cost it is read against shrank by a third and the dollars by a quarter. The tree's year-0
plant is now smaller than the old one and close to the single year's: 50 kWp, 125 kWh and
22.5 kW against 45 kWp, 115 kWh and 20 kW, with a 12 kW set rather than an 8 kW one, the
root's span being operated under all nine regimes, the high connection trajectory among them. Building the single year's plant at once, rather than following the
tree, now costs 2.15 % in expectation, three times the 0.77 % of the old record, and the
noise from one seed to another, which used to be a third of the cost, is a twelfth of it: the
persistent tree is what makes the value of waiting measurable. And knowing the regime in
advance, the connection trajectory with the growth and the cost future, would save a quarter of
the expected cost, where the old record put the value of all information at 0.13 %: the old
tree drew no connection trajectory and held no regime along its paths.

**What each real village must add.** Samionta's plant (25.86 kWp on the battery's bus, 95 kWh
since 29 July 2026, 48 kW of conversion, the 16 kW set) carries its own record's future. The
single year needs nothing added, and the tree adds nothing at any node, under any of the nine
regimes, to year 20: its own bracket ends at 53 households. Gbowele's (22.45 kWp, 16.31 on the
battery's bus and 6.14 on the load's, 40 kWh, 24 kW, the 16 kW set) does not:

| Milestone | Added, in expectation over the tree | Range over the nodes |
|---|---|---|
| Year 0 | 14.5 kWp on the battery's bus and 17.5 kWp on the load's, 115 kWh of storage; the converter and the set as they stand | the same at every node |
| Year 5 | 5.7 kWp, 11.7 kWh, 3.0 kW of conversion | nothing on 46 % of the mass; at most 14 + 8.5 kWp, 50 kWh, 11 kW |
| Year 10 | 0.5 kWp, 0.4 kWh, 0.5 kW | |
| Year 15 | 0.6 kWp, 2.8 kWh, 0.2 kW | |
| Year 20 | 2.0 kWp, 0.2 kWh, 1.2 kW | at most 49.8 + 33.6 kWp, 210 kWh and 40 kW in all |

The single certified year (plan year 4, 140 households) asks for more conversion at once:
55 kWp split 42.25 and 12.75, 150 kWh and 32.5 kW, where the tree's root keeps the standing
24 kW and extends at year 5 on half the mass.

**Sensitivities** (`results/sensitivities/`, one directory each; the base case is the row
above it):

| Sensitivity | Run | Base | With the reading changed |
|---|---|---|---|
| 7a, node year `first` (point 18) | Samionta's tree | `last`: root 29 + 21 kWp, 125 kWh, 22.5 kW, 12 kW; 66 492 $ against 61 871 $; controller 7.5 % | root 6.5 + 4.5 kWp, 25 kWh, 5 kW, 8 kW, extended at year 5 on every path (26.5 + 17.4 kWp, 115 kWh, 20.4 kW in expectation); 34 877 $ against 34 153 $; controller 2.1 % |
| 7b, high plateau at the census (decision 1) | bench certificate | 113 households; 26 + 19 kWp, 115 kWh, 20 kW, 8 kW; 4 262 $/yr | 136 households; 32.5 + 25 kWp, 145 kWh, 25 kW, 8 kW; 5 296 $/yr, proven; controller 5.3 % |
| 7b | Samionta's tree | as in 7a | root 32.5 + 25 kWp, 150 kWh, 25 kW, 8 kW, extended at year 5 on 44 % of the mass; 74 175 $ (+11.6 %) against 70 546 $; controller 5.1 % |
| 7c, Gbowele at 171 households (point 10), curves refitted (plateau 128 to 171) | greenfield certificate | 159: 77 households; 19.5 + 14.5 kWp, 80 kWh, 15 kW, 8 kW; 3 150 $/yr | 81 households; 19.5 + 14.5 kWp, 90 kWh, 15 kW, 8 kW; 3 249 $/yr, proven; 5.7 % |
| 7c | brownfield certificate | 140 households; 42.25 + 12.75 kWp, 150 kWh, 32.5 kW, 16 kW; 4 341 $/yr | 149 households; 42.25 + 18.75 kWp, 155 kWh, 32.5 kW, 16 kW; 4 923 $/yr, proven; 5.7 % |
| 7d, productive intensity × 44/60.8 = 0.724 (point 14) | bench certificate | 26 + 19 kWp, 115 kWh, 20 kW, 8 kW; 4 262 $/yr | 26 + 16.5 kWp, 115 kWh, 20 kW, 8 kW; 4 013 $/yr (−5.8 %), proven; 5.0 % |
| 7d, × 16/11.4 = 1.404 | bench certificate | the same | 35.75 + 24.25 kWp, 140 kWh, 27.5 kW, 8 kW; 5 189 $/yr (+21.8 %), proven; 5.0 % |

The node year is the largest of the four. Under `first` the root carries the plan's year 0,
when a new village has hardly begun to connect, so the year-0 plant is a fifth of the one under
`last` and every path extends at year 5; and since each node charges its whole span at its
first, least demanding year, the expected cost falls by nearly half. That is the bias of section
9.3, measured: under `first` a plant is never asked to carry the later years of its span, and
the plan looks half as dear as under `last`, which overstates the operating cost of a growing
span instead. The two bracket the year a node stands for, and they are a factor of two apart on
a new village. The census plateau raises the tree's cost by 11.6 % and the bench year's by 24 %, the
tree's root keeping the 8 kW set and deferring part of the plant to year 5.

The productive intensity moves the bench as much as the plateau does, and not symmetrically:
Samionta's ratio of observed to expected users, 1.40, raises its cost by 21.8 %, with a larger
array and converter; Gbowele's, 0.72, lowers it by 5.8 %. The field census matters less: it
adds four households at year 4 on bare ground, and 10 kWh of storage, and nine with the
village's record, and 6 kWp on the load's bus and 5 kWh; the costs rise by 3 % and 13 %.

**Times**, against the estimates above. The machine was shared throughout: until 19 h on
7 November three to four jobs ran at once with the pools beside them, and the Windows virtual
machine of the host held 10 GB; past about 50 GB of programmes the host swapped, which is what
the longest times below record. Two jobs at a time from then on.

| Run | Estimate | Taken |
|---|---|---|
| Pools, Samionta and Gbowele greenfield, 90 (the moved fingerprint) | 37.5 min for Samionta's 45 on 12 processes | 61 min on 11 |
| Pools, both villages with their plant, 75 | 12 + 35 min on 12 | 206 min on 5, beside two programmes |
| Pools, node year `first` and the census plateau, 75 new | 30 + 30 min on 12 | 273 min on 6, beside two programmes |
| A single certified year, 13 runs | half a minute to two minutes | 5 to 220 s of certification, 52 to 387 s in all with the year built |
| `run`, each tree | a quarter of an hour | Samionta 40 min and Gbowele 113 min (swapping); with their plant 15 and 21 min |
| Value of the tree, 16 cases and the wait-and-see | none given; 8 to 27 min a case in the stored study | 5 to 30 min a case, 6 h in all |
| Build once | none given; 15 min stored | 21 min (Samionta), 37 min (Gbowele) |
| Price sensitivity, 4 sets and 3 seeds | none given; 83 and 95 min stored | 104 min (Samionta), 114 min (Gbowele) |
| `first_stage`, Samionta | 1.5 to 2.5 h within four | 1 h 23 min: tree 9 min, incumbent 6 min, 40 programmes in 67 min, about 100 s each |

A first run of the first stage, beside a tree and two pool builds, was stopped after 2 h 15:
its programmes cost 980 s each, against 88 s in the stored run, and with a budget of four hours
of wall clock its gap would have measured the machine. It was run again alone, the last
quarter of an hour of the test suite beside it. Its first programme took 378 s, and it
announced that 40 might not fit in four hours; the later boxes are narrower and the 40 took
67 minutes. The gap is wider than the stored 5.38 %, with the same number of programmes, and
two plants of the lattice remain unresolved, which the stored run had none of: the persistent
tree's programme is harder per box, and the gap is mostly the price of the heuristic, the
programme lying 7.0 % below the descent at the root.

The full suite, run once at the end in `mgpy_dev`: 481 passed and 1 skipped, in 1 h 12 min,
building the census pools it reads beside the other runs.

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

As built: `model/build.py` and `exact/tree_oracle.py` needed nothing, the first because
`model/coords.py` now carries which nodes hold their parent's plant, the second because it
weights a node by its operating years, zero at a persistent root. The session touched
`model/coords.py`, `model/investment_constraints.py`, `model/dispatch_constraints.py` and
`model/economics.py` (section 9.7), `exact/tree_certify.py`, `exact/first_stage.py` (the
costless bound, section 9.7, and the `--tree-mode` and `--node-year` options),
`exact/tree_value.py` (a chain carved from a persistent tree keeps its operating-only node),
`post/report.py` and `run.py` (the summary names the nesting, the node year, the operating
nodes and the distortion; `run` takes `--tree-mode` and `--node-year`),
`docs/formulation/model.tex` (the root's span and the node year) and the new
`tests/test_persistent_tree.py`.

Noticed while reading, for whichever session next touches the file:

- `model/dispatch_constraints.py`: the module docstring said the storage recursion is "closed
  within each representative day"; the code chains it across the node's days and leaves the end
  free. Corrected in session 3.
- `tree/build_tree.py`: the docstring said a late-stage node inherits the trajectory of the path
  it comes from; under the fan, consecutive nodes come from different paths. Corrected in
  session 3.
- `demand/growth.py`: `main()` prints a French heading.
- Neither template village declares a place of worship (`community_mix`), whereas two churches
  are metered at each. It matters for the brownfield runs of session 4. *Done in session 4.*

Session 4:

- `demand/build_meter_archive.py`: the code that held the meter, test codes, known customers on
  any meter, `--census`; `data/demand/{sam,gbo}_meter_readings.parquet` rebuilt from the exports;
- the calibration chain run again on the archive: `archetype_profiles.csv`,
  `archetype_hourly_shapes.csv`, `mixture_by_maturity.csv`,
  `mixture_probabilities_type_month.csv`, `pue_class_mix.csv`, `pue_class_profiles.csv` and the
  tables of the segmentation kept for inspection; `archetype_scaling.csv`,
  `community_class_profiles.csv` and `pue_connection_intensity.csv` unchanged;
- `demand/build_connection_curves.py`: the extended record by default, the census's type column
  first, `profile_bound`, the S2-A5 reading over the observed households; the three tables
  and `data/demand/archive_customers.csv` rebuilt; `data/README.md`;
- `sites.py`: two places of worship at each template;
- `settings.py`: `connection.mode = "progressive"`, `maturity_months = 0`, the provenance of the
  connection curves and of the network loss;
- `config.py`: `tree_mode = "persistent"`, `node_year = "last"`, `centre_features = True`,
  `maturity_months = 0`, `regime_fan = None` and `ModelConfig.fan()`;
  `scenarios/uncertainty_space.py`: `DemandAxis.connection_mode = "progressive"`;
  `tree/build_tree.py` and `exact/first_stage.py` read `fan()`;
- `exact/certify.py`: `certified_year`, `--node-year`, `--out`, the summary fields and the
  `_brownfield` suffix; `ui/engine.py`: the interface's certificate on the same year, and
  `ui/i18n.py` and `ui/schema.py`: the hint of the connection trajectory, which no longer says
  it changes nothing;
  `run.py`: `--out`, and the defaults of the configuration rather than of the command line's
  own; `exact/tree_value.py`: the mean-value problem also fixes the connection trajectory;
- `docs/formulation/model.tex`: the node year, the base of the productive intensity, the network
  loss and the certified year;
- `tests/`: the session-4 tests of section 11 and the stored settings where tests pin them.

Session 4 bis, beside `results/` (section 12):

- `exact/certify.py`: `_price_relative` keeps the standing plant in its denominator,
  `--project`, the productive factor passed to the year, and the high plateau, the census and
  the factor recorded under `connection`;
- `exact/tree_certify.py`: `_standing`, every node raised to the standing plant, and no rating
  below the set on site;
- `run.py`: `--brownfield`, `--project`, the `_brownfield` summary, the price of the heuristic
  read with the standing plant; `post/kpis.py`: `expected_npc_lcoe(standing_plant_usd_yr=...)`;
- `settings.py`: `ProjectSettings.productive_intensity_scale` and its validation;
  `demand/generator.py` and `instances.py`: `productive_scale`, in the key only away from one;
  `scenarios/assemble.py`: the tree refuses a factor other than one; `ui/engine.py`: the
  interface's certificate passes it;
- `tests/`: the price of the heuristic over a standing plant, the descent's floor, the standing
  plant in the tree's report, the factor at one and away from it, and the tree's refusal;
- `results/superseded/README.md` and `results/sensitivities/README.md`.

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
| 8 | Base and form of the network loss (10) | 13 % of the injection, proportional, kept (session 4); the form is left to the work on the distribution network |
| 9 | Growth beyond 24 months (15) | maturity bands unchanged in sessions 2 and 3 |

**The author's choices (2026-11-07).** Points 1 to 9 stand at their defaults. An extra
milestone at year 2 was considered and rejected, as too close to the root to reinvest. The
points session 2 left open were decided as section 4.7 (record, silent meters, the S2-A5
test), section 5.3 (productive users) and section 4.5 (the `own` bracket) now state.

Left open by the revision, for session 4 unless the author settles them sooner:

| | Question | State |
|---|---|---|
| 10 | The census of households. The operator's field census counts 171 households at Gbowele (HH1 144, HH2 16, HH3 11) against the 159 (143, 5, 11) of `sites.py`, and 230 at Samionta against 231 | **Decided (session 4):** `sites.py` keeps 159 at Gbowele, and 171 is a sensitivity for session 4 bis. With `H` = 171, Gbowele's plateau was not identified on either record in session 2 bis (92 to 171 on the roster record, 127 to 171 on the extended one) *Measured (session 4 bis):* refitted at 171, the plateau runs from 128 to 171 households; Gbowele's greenfield certificate rises by 3 % and its brownfield one by 13 %, with 6 kWp more on the load's bus (section 12, session 4 bis) |
| 11 | Which record the tables hold | **Decided (session 4):** the extended record, `T` = October 2026 (section 4.7); the roster record is a sensitivity |
| 12 | A month without any reading in S2-A5 | **Decided (session 4):** a household without any reading in `T` is not observed and leaves both sides; chosen after the result was seen, the other reading reported as a sensitivity (sections 4.7 and 12) |
| 13 | Meters silent for less than three months | **Unchanged (session 4):** the four Gbowele households silent for less than three months (0133, 0146, 0196 and 0198GBO) stay in the stock. All four are among the seven roster customers absent from the field census, with 0007, 0137 and 0158GBO, and the question is now put to the operator |
| 14 | The productive intensity beyond the record | **Unchanged (session 4), for session 4 bis:** at Gbowele the rule expects about 0.63 productive users per connected household, against 44 for 96 households, about 0.46, observed at `T` on the extended record; under the anchored rule it only drives the increments after `T` *Measured (session 4 bis):* the bench certificate with the intensity scaled by 44/60.8 costs 5.8 % less, by 16/11.4 21.8 % more (`ProjectSettings.productive_intensity_scale`, section 12) |

Left open by session 3, for session 4:

| | Question | State |
|---|---|---|
| 15 | The fan's feature scaling | **Decided (session 4):** `ModelConfig.centre_features = True` by default; `False` reproduces the stored fans, whose root is the first path drawn rather than the medoid of year 0 (section 9.7) |
| 16 | The stored first-stage certificates | computed with a costless bound whose capital term was charged at the root's prices (section 9.7); **re-run in session 4 bis:** Samionta's year-0 plant is the tree's root, 29 + 21 kWp, 125 kWh, 22.5 kW and 12 kW, at a gap of 6.19 % with two plants unresolved (section 12) |
| 17 | The certified year under `node_year = "last"` | **Built (session 4):** `exact/certify.py` reads `node_year`, and the certified year is the root's, the plan's year 4 under `last` (section 8) |
| 18 | `node_year = "both"` | **Decided (session 4):** stays refused; session 4 bis measures `first` against `last` instead *Measured (session 4 bis):* under `first` Samionta's year-0 plant is a fifth of the one under `last` and the plan's expected cost 47.5 % lower (section 12) |

Left open by session 4:

| | Question | State |
|---|---|---|
| 19 | Empty codes before an owner's own code | not corrected (section 4.7): two Gbowele meters recorded an empty code from the morning the test meters were installed, 15 January 2025, until 0204GBO's code appeared in December 2025 and 0023GBO's in February 2025, and are most likely bench meters; 0037GBO and 0154GBO carry months of empty codes before their roster dates. 0204GBO is a household of the register, whose five months at zero before its connection enter the segmentation. A question for the operator |
| 20 | Gbowele's high plateau under the extended record | the plateau's lower bound is 124 households of 159 (share 0.78), against 92 on the roster record, because the logistic reads the campaign of May 2026 as the middle of a rise; it is the high trajectory of a new site and the low end of Gbowele's own bracket (section 12). **Decided (session 4 bis):** decision 1 stands, the profile lower bound is the high plateau, and the census is its sensitivity, run on the bench certificate and Samionta's tree (section 12, session 4 bis) |
| 21 | The scaling factors | `archetype_scaling.csv` was not fitted again on the corrected archive (section 4.7); a refit belongs with the next change to the appliance calibration. **Decided (session 4 bis):** left unfitted. The correction shifts the fit's target by 1.3 %, below the residuals the fit itself leaves, about 8 % on the energy and 10 % on the peak, so a refit would trade a shift smaller than its own noise for Monte-Carlo noise of that order |

## 15. Out of scope

- **Session 4** changed the defaults together: `connection.mode = "progressive"`, `tree_mode =
  "persistent"`, `node_year = "last"`, `centre_features = True` (point 15) and `maturity_months =
  0`, a site with its own record keeping the age derived from it. `both` stays unbuilt
  (point 18).
- **Session 4 bis** recomputed the greenfield test bench and the two real villages as
  brownfield under those defaults, re-ran the first-stage certificate (point 16), measured
  `first` against `last` (point 18) and ran the sensitivities: the census plateau (decision 1),
  171 households at Gbowele (point 10) and the productive intensity (point 14), section 12. The
  roster record (point 11) was not run as a sensitivity: the author's list for the session did
  not hold it, and it stays one to run. The 19 % loss sensitivity is dropped: it came from a gap
  that included the street lighting (section 10).
- **Left open after session 4 bis.** Points 13 and 19 are questions put to the operator. The
  first-stage certificate of Gbowele was not part of the stored results and was not computed.
  The comparison of bare ground against extension is no longer a file of its own (section 12).
- **Growth beyond 24 months [decision 9].** Cohort ageing keeps the community's demand moving
  while households keep connecting, but each household still stops growing in the 25+ band,
  because no record runs much past two years: Gbowele's ends at 25 months and the fast trajectory
  inherits its last band. The default leaves the bands as they are. The alternatives are a 25-36
  band estimated on Samionta alone, or a long-run growth rate per household carried as a fourth
  persistent draw.
- A developer's own connection forecast on the `Site` record.
- Extending the meter archive in the repository past its last month.
- The optimisation of the distribution network and the control module, which are separate work.
