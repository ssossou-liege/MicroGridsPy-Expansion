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
