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
