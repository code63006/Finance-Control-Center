"""
Composes dev_batch.json and holdout_batch.json.
Generates N clean cases, applies injectors, and ensures the four
required holdout-only properties are present.
"""
import json
import random
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

from src.constants import InjectedCause
from src.generate.entity_factory import generate_clean_case, case_to_dict
from src.generate.anomaly_injectors import INJECTORS
from src.config.pricing_rules import calculate_fee_paise, calculate_gst_paise

# Injectors that don't require Phase 3 thresholds to generate
INDEPENDENT_INJECTORS = [
    InjectedCause.MISSING_FEE_ENTRY,
    InjectedCause.DUPLICATE_WEBHOOK_PAYMENT,
    InjectedCause.WRONG_TAX_RATE,
    InjectedCause.PROVENANCE_TIMESTAMP_SKEW,
    InjectedCause.AMOUNT_ROUNDING_DRIFT,
    InjectedCause.LATE_SETTLEMENT,
    InjectedCause.SPLIT_SETTLEMENT_MISATTRIBUTION,
    InjectedCause.SOURCE_CONFLICT_SAME_FACT,
    InjectedCause.ORPHANED_REFUND,
]


def generate_clean_batch(
    rng: random.Random,
    n: int,
    start_time: datetime = None,
    start_index: int = 0,
) -> list[dict]:
    """Generate n clean (no-anomaly) cases."""
    if start_time is None:
        start_time = datetime(2024, 6, 1, tzinfo=timezone.utc)
    cases = []
    for i in range(n):
        base = start_time + timedelta(minutes=i * 15)
        case = generate_clean_case(rng, base_time=base, case_index=start_index + i)
        cases.append(case_to_dict(case))
    return cases


def generate_injected_batch(
    rng: random.Random,
    n: int,
    injectors: list[InjectedCause],
    start_time: datetime = None,
    start_index: int = 0,
) -> list[dict]:
    """Generate n cases, each with one anomaly injected."""
    if start_time is None:
        start_time = datetime(2024, 6, 1, tzinfo=timezone.utc)
    cases = []
    for i in range(n):
        oc = injectors[i % len(injectors)]
        injector = INJECTORS[oc]
        base = start_time + timedelta(minutes=(n + i) * 15)
        clean = case_to_dict(generate_clean_case(rng, base_time=base, case_index=start_index + i))
        d, gt = injector(clean)
        d["ground_truth"] = gt
        cases.append(d)
    return cases


def generate_dev_batch(
    seed: int = 42,
    total_records: int = 60,
    n_clean: int = None,
    n_injected: int = None,
) -> list[dict]:
    """
    Generate dev_batch.json with ~60 records.
    ~60/40 clean-to-injected split, all 10 OC types represented.
    """
    rng = random.Random(seed)

    if n_clean is None:
        n_clean = total_records // 3  # ~20 clean
    if n_injected is None:
        n_injected = total_records - n_clean

    cases = []
    start_time = datetime(2024, 6, 1, tzinfo=timezone.utc)

    # Clean cases
    clean = generate_clean_batch(rng, n_clean, start_time, start_index=0)
    cases.extend(clean)

    # Injected cases — distribute across all 10 OC types
    base_time = start_time + timedelta(hours=n_clean)
    injected = generate_injected_batch(
        rng, n_injected, INDEPENDENT_INJECTORS,
        start_time=base_time, start_index=n_clean,
    )
    cases.extend(injected)

    # One memorable, financially material example for the operations demo.
    # It replaces a normal case so the standard batch remains exactly 60 cases.
    flagship = generate_flagship_missing_bank_receipt(seed)
    for index, case in enumerate(cases):
        if case.get("ground_truth", {}).get("expected_ch") == "NO_ISSUE":
            cases[index] = flagship
            break

    # Shuffle to avoid ordering bias
    rng.shuffle(cases)

    return cases


def generate_flagship_missing_bank_receipt(seed: int = 42) -> dict:
    """Create a clearly labelled synthetic ₹8.5 lakh card-settlement exception."""
    rng = random.Random(seed + 850_000)
    case = case_to_dict(generate_clean_case(
        rng,
        base_time=datetime(2024, 6, 4, tzinfo=timezone.utc),
        case_index=850_000,
    ))
    amount_paise = 85_000_000  # ₹8.5 lakh
    payment_method = "card"
    fee_paise = calculate_fee_paise(amount_paise, payment_method)
    tax_paise = calculate_gst_paise(fee_paise)
    expected_settlement = amount_paise - fee_paise - tax_paise
    nodes = case["nodes"]

    case["amount_paise"] = amount_paise
    case["payment_method"] = payment_method
    for key in ("order", "payment"):
        nodes[key]["amount_paise"] = amount_paise
        nodes[key].setdefault("metadata", {})["payment_method"] = payment_method
    nodes["fee"]["amount_paise"] = fee_paise
    nodes["fee"].setdefault("metadata", {})["payment_method"] = payment_method
    nodes["tax"]["amount_paise"] = tax_paise
    nodes["settlement"]["amount_paise"] = expected_settlement

    # Settlement exists at the gateway, but the expected bank receipt is absent.
    # This produces an auditable cash shortfall rather than an invented balance.
    nodes["bank_entries"] = []
    for posting in nodes.get("ledger_postings", []):
        account = posting.get("metadata", {}).get("account_code")
        posting["amount_paise"] = {
            "PAYMENT_RECEIVABLE": amount_paise,
            "FEE_INCOME": fee_paise,
            "GST_OUTPUT": tax_paise,
            "MERCHANT_PAYOUT": expected_settlement,
        }.get(account, posting["amount_paise"])

    case["demo_label"] = "Flagship demo: ₹8.5 lakh card settlement missing from bank receipt"
    case["demo_priority"] = True
    case["ground_truth"] = {
        "is_clean": False,
        "injected_oc": "FLAGSHIP_MISSING_BANK_RECEIPT",
        "expected_ch": "AMOUNT_DRIFT",
        "affected_node": "bank_entries",
        "counterfactual_correct_values": {
            "bank_amount_paise": expected_settlement,
            "settlement_amount_paise": expected_settlement,
        },
        "expected_terminal_outcome": "STRONGLY_SUPPORTED",
    }
    return case


def generate_holdout_batch(
    seed: int = 42,
    total_records: int = 120,
) -> list[dict]:
    """
    Generate holdout_batch.json with ~40 records.
    Contains the four required holdout-only properties:
    1. Unseen combination of two injectors on same case
    2. Near-threshold fuzzy cases
    3. Case with no hypothesis clearing FLOOR_THRESHOLD → true INSUFFICIENT_EVIDENCE
    4. Case with two hypotheses within TIE_MARGIN → true UNRESOLVED_AMBIGUITY

    Properties 2-4 use calibrated thresholds from src.constants.
    """
    rng = random.Random(seed + 1000)  # different seed from dev
    cases = []
    start_time = datetime(2024, 8, 1, tzinfo=timezone.utc)

    # ── Property 1: Unseen combination (missing_fee + late_settlement) ───────
    clean = case_to_dict(generate_clean_case(rng, start_time, case_index=0))
    d1, gt1 = INJECTORS[InjectedCause.MISSING_FEE_ENTRY](clean)
    d1, gt2 = INJECTORS[InjectedCause.LATE_SETTLEMENT](d1)
    # Combined ground truth: both injectors applied
    d1["ground_truth"] = {
        "injected_oc": "MISSING_FEE_ENTRY+LATE_SETTLEMENT",
        "expected_ch": "FEE_MISSING",  # primary
        "affected_node": "fee,settletement",
        "counterfactual_correct_values": {
            **gt1.get("counterfactual_correct_values", {}),
            **gt2.get("counterfactual_correct_values", {}),
        },
        "expected_terminal_outcome": "COMBINED_EXCEPTION",
        "injection_count": 2,
    }
    cases.append(d1)

    # ── Property 2: Near-threshold fuzzy cases ───────────────────────────────
    # Create two cases with amounts just inside/outside AMOUNT_TOLERANCE_PAISE
    from src.constants import AMOUNT_TOLERANCE_PAISE
    near_base = generate_clean_case(rng, start_time + timedelta(hours=1), case_index=100)
    near_inside = generate_clean_case(rng, start_time + timedelta(hours=1, minutes=30), case_index=101)

    # Mutate amount to be just inside tolerance
    d_inside = case_to_dict(near_inside)
    d_inside["nodes"]["payment"]["amount_paise"] = (
        near_base.amount_paise + AMOUNT_TOLERANCE_PAISE - 1  # just inside
    )
    d_inside["ground_truth"] = {
        "injected_oc": "AMOUNT_ROUNDING_DRIFT",
        "expected_ch": "AMOUNT_DRIFT",
        "affected_node": "payment",
        "counterfactual_correct_values": {},
        "expected_terminal_outcome": "EXCEPTION_AMOUNT_DRIFT",
        "fuzzy_position": "inside_gate",
    }
    cases.append(d_inside)

    d_outside = case_to_dict(near_base)
    d_outside["nodes"]["payment"]["amount_paise"] = (
        near_base.amount_paise + AMOUNT_TOLERANCE_PAISE + 5  # just outside
    )
    d_outside["ground_truth"] = {
        "injected_oc": "AMOUNT_ROUNDING_DRIFT",
        "expected_ch": "AMOUNT_DRIFT",
        "affected_node": "payment",
        "counterfactual_correct_values": {},
        "expected_terminal_outcome": "UNMATCHED",
        "fuzzy_position": "outside_gate",
    }
    cases.append(d_outside)

    # ── Property 3: True INSUFFICIENT_EVIDENCE ───────────────────────────────
    # Minimal evidence case: remove all nodes except order + payment with
    # conflicting amounts → no hypothesis clears FLOOR_THRESHOLD
    ie_case = generate_clean_case(rng, start_time + timedelta(hours=2), case_index=200)
    d_ie = case_to_dict(ie_case)
    # Strip most evidence
    d_ie["nodes"]["fee"] = None
    d_ie["nodes"]["tax"] = None
    d_ie["nodes"]["refunds"] = []
    d_ie["nodes"]["settlement"] = None
    d_ie["nodes"]["bank_entries"] = []
    d_ie["nodes"]["ledger_postings"] = []
    d_ie["ground_truth"] = {
        "injected_oc": "MISSING_FEE_ENTRY",
        "expected_ch": "FEE_MISSING",
        "affected_node": "fee",
        "counterfactual_correct_values": {},
        "expected_terminal_outcome": "INSUFFICIENT_EVIDENCE",
    }
    cases.append(d_ie)

    # ── Property 4: True UNRESOLVED_AMBIGUITY ────────────────────────────────
    # Two hypotheses score within TIE_MARGIN → genuine tie
    ua_case = generate_clean_case(rng, start_time + timedelta(hours=3), case_index=300)
    d_ua = case_to_dict(ua_case)
    # Create ambiguous state: fee exists but tax has wrong amount,
    # AND bank amount doesn't match settlement — both FEE_MISSING and
    # AMOUNT_DRIFT are plausible
    d_ua["nodes"]["tax"]["amount_paise"] = d_ua["nodes"]["fee"]["amount_paise"] // 3
    d_ua["nodes"]["bank_entries"][0]["amount_paise"] = (
        d_ua["nodes"]["settlement"]["amount_paise"] - 20
    )
    d_ua["ground_truth"] = {
        "injected_oc": "TAX_RATE_ERROR",
        "expected_ch": "TAX_RATE_ERROR",
        "affected_node": "tax",
        "counterfactual_correct_values": {},
        "expected_terminal_outcome": "UNRESOLVED_AMBIGUITY",
    }
    cases.append(d_ua)

    # ── Fill remaining with regular injected + clean cases ────────────────────
    remaining = total_records - len(cases)
    # A benchmark support count below ten per anomaly is too small to defend.
    # With the default 120 cases this yields ten unseen examples per injector.
    remaining_injected = min(remaining, len(INDEPENDENT_INJECTORS) * 10)
    remaining_clean = remaining - remaining_injected

    base_time = start_time + timedelta(hours=4)
    for i in range(remaining_clean):
        c = generate_clean_case(rng, base_time + timedelta(minutes=i * 10), case_index=400 + i)
        cases.append(case_to_dict(c))

    base_time = start_time + timedelta(hours=6)
    for i in range(remaining_injected):
        oc = INDEPENDENT_INJECTORS[i % len(INDEPENDENT_INJECTORS)]
        d, gt = INJECTORS[oc](case_to_dict(
            generate_clean_case(rng, base_time + timedelta(minutes=i * 10), case_index=500 + i)
        ))
        d["ground_truth"] = gt
        cases.append(d)

    rng.shuffle(cases)
    return cases


def generate_demo_case(seed: int = 42) -> dict:
    """Create one deterministic, visibly diagnosable wrong-GST scenario."""
    rng = random.Random(seed + 9000)
    clean = case_to_dict(generate_clean_case(
        rng,
        base_time=datetime(2024, 9, 1, tzinfo=timezone.utc),
        case_index=900,
    ))
    demo, ground_truth = INJECTORS[InjectedCause.WRONG_TAX_RATE](clean)
    demo["demo_label"] = "Wrong GST rate: expected 18%, reported 12%"
    demo["ground_truth"] = ground_truth
    return demo


def export_source_files(cases: list[dict], prefix: str = "") -> dict:
    """Export canonical cases into the four source-oriented fixture shapes."""
    orders = []
    razorpay = []
    bank = []
    tax = []
    for case in cases:
        nodes = case.get("nodes", {})
        if nodes.get("order"):
            orders.append(nodes["order"])
        for key in ("payment", "fee", "settlement"):
            if nodes.get(key):
                razorpay.append(nodes[key])
        razorpay.extend(nodes.get("refunds", []) or [])
        bank.extend(nodes.get("bank_entries", []) or [])
        if nodes.get("tax"):
            tax.append(nodes["tax"])
    return {
        "orders_db": orders,
        "razorpay_recon": razorpay,
        "bank_statement": bank,
        "tax_invoice": tax,
    }


def build_datasets(output_dir: str = "data", seed: int = 42):
    """Generate both dev and holdout datasets and write to disk."""
    os.makedirs(output_dir, exist_ok=True)

    dev = generate_dev_batch(seed=seed)
    holdout = generate_holdout_batch(seed=seed)

    dev_path = os.path.join(output_dir, "dev_batch.json")
    holdout_path = os.path.join(output_dir, "holdout_batch.json")

    with open(dev_path, "w") as f:
        json.dump(dev, f, indent=2, default=str)
    print(f"Generated {len(dev)} dev cases -> {dev_path}")

    with open(holdout_path, "w") as f:
        json.dump(holdout, f, indent=2, default=str)
    print(f"Generated {len(holdout)} holdout cases -> {holdout_path}")

    return dev, holdout


if __name__ == "__main__":
    build_datasets()
