# Superseded certificates

These six certificates are kept for one reason and should be read for one reason: they
record the comparison between the two pure coupling architectures, and nothing else in the
repository does.

| instance | winner | runner-up | margin |
|---|---|---|---|
| Gbowele, central | direct | alternating | 1 096 $/yr |
| Samionta, slow | direct | alternating | 969 $/yr |
| Samionta, central (VOLL 0.5 / 1 / 3) | direct | alternating | 1 640 / 1 638 / 1 632 $/yr |
| Samionta, fast | direct | alternating | 2 210 $/yr |

**Their costs are wrong.** They were produced on 31 August 2026 and predate three
corrections that landed afterwards:

- the storage double charge, which recovered the pack's capital over its calendar life
  *and* charged its throughput at the cycle-life price. Removing it lowered the levelised
  cost by fifteen to sixteen per cent;
- the cost boundary, which stopped at the plant and left out the low-voltage network, the
  connections, the civil works and the development — about half the capital of a mini-grid;
- the operating quantities, which were reported in writing and archived nowhere.

You can tell them apart from the current certificates without opening them: a corrected one
carries `battery_life_years`, `infrastructure_usd`, `collection_rate` and the operating
record (`generator_hours`, `solar_penetration_pct`, `equivalent_full_cycles_per_year`,
`storage_throughput_kwh`, `inverter_peak_fraction`). These carry none of them.

**They cannot be regenerated.** The tool settled on the divided array, so
`settings.coupling.architectures()` returns `("mixed",)` and there is no command-line
switch to ask for another. A certificate under direct coupling would need that setting
changed and the run repeated — which is worth doing if the architecture comparison is ever
to be restated on the corrected pricing, and is the only way these figures become citable
again.

Until then: the margins above are the finding; the costs beside them are not.

## The nine records of 2026-11-03, set aside before the demand was recalibrated

`2026-11-03_before_recalibration/` holds the six certificates, the two tree summaries and
the value-of-the-tree study as they stood when the meter archive was extended from 1 June
to 1 November 2026 and the whole calibration chain was re-run on it. They were in the
working tree and uncommitted, so they existed nowhere else; the recalibration overwrites
the files they were written to. The study's figure is beside it, uncommitted as every
figure in this repository is, so that the record it was drawn from is not alone.

They are kept because they are the last state computed on the shorter record, and a reader
comparing the certificates before and after wants both halves of that comparison. They are
not citable on their own: they predate the extended archive, they predate the correction
that attached each measured hourly shape to the archetype whose appliances it belongs to,
and the trees among them predate the landed equipment prices.

## The two one-off studies of September 2026

`2026-09_one_off_studies/` holds the first-stage certification of 28 September and the
descent study of 29 September. Both were computed at commit 424a09b by calculations run
once, by hand, and both were written into `results/` where every other file is produced by
a command.

They are set aside for two reasons. They predate the recalibration of 3 November 2026 and
the landed equipment prices of 4 November, so their costs describe a plant priced and a
demand measured differently: the plan they cost at 167 381 $ is the same object the current
record costs at 87 556 $, which is not a correction of five per cent but a different study.
And the figure the first one is cited for -- a bound of 159 009 $ against a descent at
167 381 $, a gap of five per cent -- can now be produced again:
`python -m microgrid_expansion.exact.first_stage` runs that search and writes
`summary_first_stage_<site>_<architecture>.json`, which is where the citable version of it
belongs.

The descent study has no command, and it does not need one: its two halves are expressible
with the parameters `certify_tree` already takes. The neighbourhood variants are its
`scales` and `max_rounds`; the restarts are the `plans` argument itself, called with the
programme's plan scaled up in storage or in array. What was done once in a script can be
done again in a script, and the finding it reached -- that enlarging the neighbourhood
changes nothing and restarting from a larger plant finds 166 165 $ -- is the part worth
carrying forward. Its figures are not citable on the current prices.

## The twenty-two records of 2026-11-07, set aside before progressive connection

`2026-11-07_before_progressive_connection/` holds every result `results/` carried when the
defaults were switched to progressive connection and the persistent tree (commit c710e03):
the six single-year certificates, the bare-ground-against-extension comparison of the two
villages, the two trees, the first-stage certificate, the value of the tree, the two
build-once studies and the two price sensitivities, with the seven figures that stood
beside them. The summaries were computed at commits 9a05453, d526ae9 and 61638c7, from 4 to
6 November 2026, and the comparison was written by hand at ca6ee85; the figures, untracked
as every figure in this repository is, are kept with the records they were drawn from.

They are superseded by six changes, each of which moves the plant:

- **The whole census at year 0.** Every household of the census, 231 at Samionta and 159 at
  Gbowele, was connected from the plan's first month, all of them twelve months old
  (`maturity_months = 12`), and the demand was stationary from the fifth year. The two
  villages connected a fifth and three fifths of theirs in two and a half years. Under
  progressive connection the households join on a logistic curve bracketed by the two
  villages, in monthly cohorts that each age on their own clock, and a village with a plant
  starts from its own record.
- **The fan tree.** The scenario tree nested the stage medoids as a fan, so a path of the
  tree did not keep its growth trajectory or its cost future: no path of the stored trees
  holds one regime from year 5 to year 20. The persistent tree branches over regimes and
  holds each along its path.
- **A root that was the first path drawn.** A feature channel that does not vary was divided
  by its rounding spread, which made every distance zero at year 0, where every cost future
  starts from the same prices: the root of every stored tree was path 0 rather than the
  medoid of year 0.
- **A first-stage bound that could prune the optimum.** The costless bound of
  `summary_first_stage_samionta_mixed.json` charged the box's capital at the root's prices
  with the whole tree's weight, more than the programme charges, since every cost future
  of the shipped settings has the prices fall.
- **The meter archive as the roster indexed it.** The calibration rested on the archive
  read by the customer roster's codes. It is now rebuilt from the operator's exports by the
  code that held each meter at each reading, the connection record runs to October 2026,
  and the calibration chain was run again on it.
- **No places of worship.** Neither village declared the two churches metered at each, so
  every plan left them out.

You can tell the records apart without opening them. A current certificate carries a
`connection` block (`mode` `progressive`, the `node_year`, the `plan_year`, the village age
and the households connected) and is named after the age of the year it certifies, `_m48_`
for a new site, with `_ccentral` for its connection trajectory and `_brownfield` for a
village with its plant; these are `_m12_` and carry no such block. A current tree carries
`tree_mode` `persistent`, its `node_year`, its `operating_nodes` and its `distortion`, and
has 9 leaves; these have 24 and none of those fields. The studies built on a tree record
the commit they were computed at and their tree's leaves, 24 here.

The comparison of bare ground against extension has no command and is not regenerated as a
file: its current counterpart is the pair of certificates and the pair of trees of each
village, greenfield and brownfield. Its own premise no longer holds either, since a
village with its record now starts from that record and a new site from the curve, so the
two halves of a pair no longer share a demand.

## The records of 2026-11-11, set aside before the fan and the anchored demand

`2026-11-11_before_fan_and_anchored_demand/` holds every result `results/` carried after
session 4 bis, the sensitivities under its own `sensitivities/`. Its README says why they are
superseded: the tree of those defaults built no fan within a regime, and the demand changed in
sessions 4 ter, 4 quinquies and 4 quater, greenfield and brownfield alike.
