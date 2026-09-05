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
