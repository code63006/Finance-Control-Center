#!/usr/bin/env python3
"""One-command generation of deterministic synthetic finance data."""
import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.generate.scenario_builder import (
    export_source_files,
    generate_dev_batch,
    generate_holdout_batch,
    generate_demo_case,
)


def strip_internal(case: dict) -> dict:
    """Remove private graph metadata before writing public fixtures."""
    def clean(value):
        if isinstance(value, dict):
            return {key: clean(item) for key, item in value.items() if not key.startswith("_")}
        if isinstance(value, list):
            return [clean(item) for item in value]
        return value

    return clean(case)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate synthetic finance data")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed (default: 42)")
    parser.add_argument("--output-dir", type=str, default="data", help="Output directory")
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Generating dev_batch with seed={args.seed}...")
    dev = generate_dev_batch(total_records=60, seed=args.seed)
    (output_dir / "dev_batch.json").write_text(
        json.dumps([strip_internal(case) for case in dev], indent=2), encoding="utf-8"
    )
    print(f"  dev_batch.json: {len(dev)} cases")

    print(f"Generating holdout_batch with seed={args.seed}...")
    holdout = generate_holdout_batch(total_records=40, seed=args.seed)
    (output_dir / "holdout_batch.json").write_text(
        json.dumps([strip_internal(case) for case in holdout], indent=2), encoding="utf-8"
    )
    print(f"  holdout_batch.json: {len(holdout)} cases")

    (output_dir / "demo_case.json").write_text(
        json.dumps(strip_internal(generate_demo_case(args.seed)), indent=2), encoding="utf-8"
    )
    print("  demo_case.json: deterministic wrong-GST scenario")

    sources = export_source_files(dev, prefix="dev")
    (output_dir / "orders_db.json").write_text(
        json.dumps(sources["orders_db"], indent=2), encoding="utf-8"
    )
    (output_dir / "razorpay_recon.json").write_text(
        json.dumps(sources["razorpay_recon"], indent=2), encoding="utf-8"
    )
    with (output_dir / "bank_statement.csv").open("w", newline="", encoding="utf-8") as handle:
        rows = sources["bank_statement"]
        if rows:
            fields = sorted({key for row in rows for key in row.keys()})
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
    (output_dir / "tax_invoice.json").write_text(
        json.dumps(sources["tax_invoice"], indent=2), encoding="utf-8"
    )
    print("  Source files exported from dev batch")

    print("\nDev batch OC distribution:")
    for cause, count in sorted(Counter(case["ground_truth"]["injected_oc"] for case in dev).items()):
        print(f"  {cause}: {count}")

    print("\nHoldout batch expected outcome distribution:")
    for outcome, count in sorted(Counter(case["ground_truth"]["expected_terminal_outcome"] for case in holdout).items()):
        print(f"  {outcome}: {count}")

    print("\nDone.")


if __name__ == "__main__":
    main()
