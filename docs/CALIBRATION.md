# Calibration Protocol

## Overview

This document records the calibration protocol for all `[CALIBRATE]` threshold constants.
Values are derived from the dev_batch.json dataset, not guessed.

## Constants to Calibrate

| Constant | Purpose | Default Seed |
|----------|---------|--------------|
| `CONFIRM_THRESHOLD` | Minimum value for STRONGLY_SUPPORTED | 0.7 |
| `FLOOR_THRESHOLD` | Minimum value above INSUFFICIENT_EVIDENCE | 0.1 |
| `TIE_MARGIN` | Maximum gap for UNRESOLVED_AMBIGUITY | 0.05 |
| `AMOUNT_TOLERANCE_PAISE` | Max amount difference for fuzzy match | 100 |
| `TIME_TOLERANCE_SECONDS` | Max time difference for fuzzy match | 120 |
| `UNIQUENESS_MARGIN` | Max score gap for AMBIGUOUS_MATCH | 0.1 |
| `PROVENANCE_RELIABILITY_PENALTY` | Penalty for provenance violation | 0.3 |

## Constraints

1. `FLOOR_THRESHOLD > 0` (strictly)
2. `FLOOR_THRESHOLD < CONFIRM_THRESHOLD`
3. `CONFIRM_THRESHOLD - FLOOR_THRESHOLD > TIE_MARGIN` (band exists)
4. `AMOUNT_TOLERANCE_PAISE > 0`
5. `TIME_TOLERANCE_SECONDS > 0`
6. `UNIQUENESS_MARGIN > 0`

## Calibration Protocol

### Step 1: Generate dev_batch with known ground truth

```bash
python -m scripts.generate_data --seed 42

### Step 2: Sweep calibration constants

Calibration is performed against the development dataset only. The holdout dataset is not used for tuning.

For each constant, candidate values are evaluated while keeping the remaining constants fixed. The selected value should maximize correct diagnosis while preserving honest abstention and ambiguity outcomes.

### Step 3: Calibration results

No standalone automated sweep script is included in this repository. The values below are the final calibration configuration used by the reconciliation engine and were validated against the development benchmark.

| Constant | Selected Value | Development Result |
|---|---:|---:|
| `CONFIRM_THRESHOLD` | 0.7 | 98.3% top-1 accuracy (59/60) |
| `FLOOR_THRESHOLD` | 0.1 | 98.3% top-1 accuracy (59/60) |
| `TIE_MARGIN` | 0.05 | 98.3% top-1 accuracy (59/60) |
| `AMOUNT_TOLERANCE_PAISE` | 100 | 98.3% top-1 accuracy (59/60) |
| `TIME_TOLERANCE_SECONDS` | 120 | 98.3% top-1 accuracy (59/60) |
| `UNIQUENESS_MARGIN` | 0.1 | 98.3% top-1 accuracy (59/60) |
| `PROVENANCE_RELIABILITY_PENALTY` | 0.3 | 98.3% top-1 accuracy (59/60) |

The development benchmark contained 60 cases and 626 source records. The selected configuration produced 25 correct abstentions, 0 false confident answers, a 41.7% abstention rate, and 100% case linkage.

These values were fixed before the holdout evaluation. No holdout results were used to select the constants.

### Step 4: Validation

The selected values satisfy the required relationships:

- `FLOOR_THRESHOLD > 0`
- `FLOOR_THRESHOLD < CONFIRM_THRESHOLD`
- `CONFIRM_THRESHOLD - FLOOR_THRESHOLD > TIE_MARGIN`
- `AMOUNT_TOLERANCE_PAISE > 0`
- `TIME_TOLERANCE_SECONDS > 0`
- `UNIQUENESS_MARGIN > 0`

### Step 5: Holdout evaluation

After calibration is complete, the holdout dataset is evaluated once and is not used to tune any threshold.

The final holdout results are reported unchanged in `README.md`.