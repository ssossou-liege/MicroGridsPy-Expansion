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
