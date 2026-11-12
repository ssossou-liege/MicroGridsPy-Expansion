# The records of 2026-11-11, set aside before the fan and the anchored demand

This directory holds every result `results/` carried after session 4 bis (commit c20bc6d, 9
November 2026): the eight single-year certificates (the bench at Samionta, central at a value
of lost load of 0.5, 1 and 3, slow and fast; Gbowele central; the two villages with their
plant), the four trees (both villages on bare ground and with their plant), the value of the
tree, the two build-once studies, the two price sensitivities, the first-stage certificate of
Samionta, the seven figures that stood beside them, and the sensitivities 7a to 7d under
`sensitivities/`, each in the directory it had there. The summaries were computed on the
working tree of commit c710e03 with the changes commit c20bc6d holds; the figures, untracked
as every figure in this repository is, are kept with the records they were drawn from.

They are superseded by two changes, each of which moves the plant.

- **The tree had no fan.** The defaults of sessions 4 and 4 bis, nine regimes and one child at
  every milestone (`regime_branches = 9`, `regime_fan` of ones), branched over regimes at year
  5 and then ran every regime as a single chain to year 20. The formulation clusters a
  regime's own outcomes at each milestone and nests them as a fan, so that climate and the
  year-to-year variability branch within the regime; these trees did not. The default is now
  three regimes and a fan of two below every node from year 5 (`(1, 1, 2, 2, 2)`): 49 nodes and
  24 futures against 46 and 9. Every result built on a tree moves with it: the four trees, the
  value of the tree, build once, the price sensitivities, the first stage and sensitivities 7a
  and 7b.
- **The demand changed three times.** Session 4 ter drew the productive users of a village with
  a plant at their own measured levels; session 4 quinquies did the same for its households
  and places of worship, made a brownfield run follow the village's own growth, read every
  reading over its own period in the household calibration, rebuilt the class tables with
  Samionta's second mill as a mill, and drew a busy day of a recorded customer longer rather
  than harder; session 4 quater required 28 days of readings for a customer's own level, put a
  ceiling per class on a busy day of a class unit, and gave the anchored households without a
  year of readings the households' seasonal index. Every certified year and every pool moved,
  greenfield and brownfield alike, so no result here stands, the single-year certificates
  included.

You can tell the records apart without opening them. A current tree summary has 24 leaves and
48 operating nodes; these have 9 and 45. A current certificate of a village with its plant
carries the village's own growth trajectory (`slow` at Samionta, `fast` at Gbowele) in its
`trajectory` field; these carry `central`. The studies built on a tree record their tree's
leaves, 9 here. Section 12 of `docs/design/progressive_connection_and_persistence.md` (session 4
quater) sets each of these records against the one that replaces it.
