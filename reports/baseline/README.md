# Baseline measurements (current solver, before any optimizer change)

**Status: NOT YET GENERATED.** The baseline must be produced with the real
OR-Tools CP-SAT solver, which was unavailable in the sandbox used to write the
validator. No numbers are recorded here on purpose.

Generate it on a machine with the project dependencies installed:

```bash
python scripts/generate_samples.py --out reports/baseline --time-limit 5
```

This writes, per configuration in `tests/fixtures/sample_configs.py`:

- `<id>.json` – requested inputs, solver status/time, the raw output coordinates
  (`snapshot`) and the full validator `report`
- `<id>_floorN.png` – the floor plans exactly as the current app renders them
- `summary.csv` / `summary.md` – one row of headline metrics per layout
- `environment.json` – Python/OR-Tools versions and the time limit used

To re-run only the validator on saved layouts (no solver needed):

```bash
python scripts/validate_snapshot.py reports/baseline
```

Notes for reading the results:

- Gate and entrance points are `legacy_projection`: the current app draws them
  after solving by projecting room/parking centers to the road edge. The solver
  itself has no gate variables (this changes in Steps 2, 9 and 10).
- Solver time limits are wall-clock, so metrics can differ slightly between
  machines. Record `environment.json` alongside any comparison.
- Quality thresholds in `testfit/validation/report.py` are provisional and not
  dataset-derived.
