"""
One function per injected cause (OC).
Each injector:
  1. Takes a clean case dict
  2. Mutates it in exactly ONE well-defined way
  3. Returns (mutated_case, ground_truth_dict)

Ground truth dict has keys:
  is_clean, injected_oc, affected_node, expected_ch,
  counterfactual_correct_values, expected_terminal_outcome
"""
from typing import Any, Dict, Tuple
from src.constants import (
    InjectedCause,
    HypothesisClass,
    Outcome,
    NodeType,
)
from src.ingest.schemas import Record


def _clean_gt(oc: InjectedCause, ch: HypothesisClass,
              affected: str, counterfactual: Dict[str, int],
              outcome: Outcome) -> Dict[str, Any]:
    """Build a ground-truth dict."""
    return {
        "is_clean": False,
        "injected_oc": oc.value,
        "affected_node": affected,
        "expected_ch": ch.value,
        "counterfactual_correct_values": counterfactual,
        "expected_terminal_outcome": outcome.value,
    }


def inject_missing_fee_entry(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: MISSING_FEE_ENTRY
    Remove the fee node from razorpay_recon source only.
    Canonical case is unchanged — the fee "exists" but is missing from recon.
    """
    mutated = _deep_copy_case(case)
    mutated["nodes"]["fee"] = None
    gt = _clean_gt(
        oc=InjectedCause.MISSING_FEE_ENTRY,
        ch=HypothesisClass.FEE_MISSING,
        affected="fee",
        counterfactual={"fee_amount_paise": case["nodes"]["fee"]["amount_paise"]},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_duplicate_webhook_payment(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: DUPLICATE_WEBHOOK_PAYMENT
    Duplicate the payment entry in razorpay_recon.
    The canonical case has one payment; recon has two.
    """
    mutated = _deep_copy_case(case)
    payment_rec = dict(mutated["nodes"]["payment"])
    payment_rec["reference_id"] = payment_rec.get("reference_id", "PAY") + "-DUP"
    mutated["nodes"].setdefault("duplicate_payments", []).append(payment_rec)

    gt = _clean_gt(
        oc=InjectedCause.DUPLICATE_WEBHOOK_PAYMENT,
        ch=HypothesisClass.DUPLICATE_PAYMENT,
        affected="payment",
        counterfactual={"expected_payment_count": 1},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_wrong_tax_rate(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: WRONG_TAX_RATE
    Mutate the tax amount in razorpay_recon to use 12% instead of 18%.
    Canonical tax remains correct; recon has wrong value.
    """
    mutated = _deep_copy_case(case)
    correct_tax = case["nodes"]["tax"]["amount_paise"]
    # 12% of fee instead of 18%
    wrong_tax = (case["nodes"]["fee"]["amount_paise"] * 1200 + 5000) // 10000
    # UPI can have a zero fee.  Still inject an observable wrong tax amount so
    # this scenario remains a tax anomaly rather than silently becoming clean.
    if wrong_tax == correct_tax:
        wrong_tax = correct_tax + 1

    mutated["nodes"]["tax"]["amount_paise"] = wrong_tax

    gt = _clean_gt(
        oc=InjectedCause.WRONG_TAX_RATE,
        ch=HypothesisClass.TAX_CALCULATION_ERROR,
        affected="tax",
        counterfactual={"correct_tax_paise": correct_tax, "reported_tax_paise": wrong_tax},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_provenance_skew(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: PROVENANCE_SKEW
    In razorpay_recon, set payment captured_at BEFORE order created_at,
    violating occurred_at ≤ received_at ≤ processed_at.
    """
    mutated = _deep_copy_case(case)
    mutated["nodes"]["payment"]["occurred_at"] = "2024-01-01T00:00:00+00:00"

    gt = _clean_gt(
        oc=InjectedCause.PROVENANCE_SKEW,
        ch=HypothesisClass.TIMESTAMP_INCONSISTENCY,
        affected="payment",
        counterfactual={
            "correct_captured_at": case["nodes"]["payment"]["occurred_at"],
        },
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_amount_drift(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: AMOUNT_DRIFT
    Add a 1-paise rounding error to the payment in bank_statement.
    The canonical and recon amounts are correct; bank shows +1 or -1 paise.
    """
    mutated = _deep_copy_case(case)
    drift = 1  # 1 paise drift

    mutated["nodes"]["bank_entries"][0]["amount_paise"] += drift

    gt = _clean_gt(
        oc=InjectedCause.AMOUNT_DRIFT,
        ch=HypothesisClass.AMOUNT_MISMATCH,
        affected="bank_entries",
        counterfactual={"drift_paise": drift},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_late_settlement(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: LATE_SETTLEMENT
    Move settlement created_at to 7 days later (well beyond normal SLA).
    """
    mutated = _deep_copy_case(case)
    from datetime import datetime, timedelta
    original_settlement = datetime.fromisoformat(
        case["nodes"]["settlement"]["timestamp"].replace("Z", "+00:00")
    )
    late_settlement = original_settlement + timedelta(days=7)
    mutated["nodes"]["settlement"]["timestamp"] = late_settlement.isoformat()
    for entry in mutated["nodes"]["bank_entries"]:
        original_bank = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
        entry["timestamp"] = (original_bank + timedelta(days=7)).isoformat()

    correct_settlement = case["nodes"]["settlement"]["timestamp"]
    gt = _clean_gt(
        oc=InjectedCause.LATE_SETTLEMENT,
        ch=HypothesisClass.SETTLEMENT_DELAY,
        affected="settlement",
        counterfactual={"correct_settlement_created_at": correct_settlement},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_split_misattribution(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: SPLIT_MISATTRIBUTION
    For split settlements, assign wrong settlement_ref to one bank entry.
    If settlement has only 1 bank entry, force a split first.
    """
    mutated = _deep_copy_case(case)
    if len(mutated["nodes"]["bank_entries"]) <= 1:
        original = mutated["nodes"]["bank_entries"][0]
        total = original["amount_paise"]
        if total >= 2:
            half1 = total // 2
            half2 = total - half1
            entry2 = dict(original)
            entry2["reference_id"] = original["reference_id"] + "-B"
            entry2["amount_paise"] = half2
            original["amount_paise"] = half1
            mutated["nodes"]["bank_entries"].append(entry2)

        mutated["nodes"]["bank_entries"][-1]["settlement_ref"] = "STL-FAKE"

    gt = _clean_gt(
        oc=InjectedCause.SPLIT_MISATTRIBUTION,
        ch=HypothesisClass.SPLIT_ATTRIBUTION_ERROR,
        affected="bank_entries",
        counterfactual={"correct_settlement_ref": case["nodes"]["settlement"]["reference_id"]},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_missing_settlement(settlements: list[Record], order: Record) -> list[Record]:
    return [item for item in settlements if item.order_id != order.order_id]


def inject_underpayment(settlements: list[Record], order: Record, amount: float = 90.0) -> list[Record]:
    return [Record(order.order_id, amount, provenance="partner", metadata={"kind": "settlement"}) if item.order_id == order.order_id else item for item in settlements]


def inject_duplicate_amount(settlements: list[Record], order: Record) -> list[Record]:
    return settlements + [Record(f"DUP-{order.order_id}", order.amount, provenance="partner", metadata={"kind": "settlement"})]


def inject_source_conflict(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: SOURCE_CONFLICT
    Give different payment amounts in orders_db vs razorpay_recon.
    """
    mutated = _deep_copy_case(case)
    correct_amount = case["nodes"]["order"]["amount_paise"]
    wrong_amount = correct_amount + 100  # ₹1 difference

    mutated["nodes"]["order"]["amount_paise"] = wrong_amount

    gt = _clean_gt(
        oc=InjectedCause.SOURCE_CONFLICT,
        ch=HypothesisClass.SOURCE_DATA_CONFLICT,
        affected="order",
        counterfactual={
            "orders_db_amount": wrong_amount,
            "razorpay_amount": correct_amount,
        },
        outcome=Outcome.UNRESOLVED_AMBIGUITY,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


def inject_orphaned_refund(case: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """
    OC: ORPHANED_REFUND
    Add a refund to razorpay_recon that references a non-existent payment.
    Existing valid refunds remain untouched.
    """
    mutated = _deep_copy_case(case)
    refund_nodes = mutated["nodes"].get("refunds", [])
    orphaned_refund = dict(refund_nodes[0] if refund_nodes else mutated["nodes"]["payment"])
    orphaned_refund.update({
        "reference_id": "REF-ORPHAN-" + case["order_id"][-5:],
        "order_id": "ORD-NONEXISTENT",
        "amount_paise": 500_00,
    })
    mutated["nodes"].setdefault("refunds", []).append(orphaned_refund)

    gt = _clean_gt(
        oc=InjectedCause.ORPHANED_REFUND,
        ch=HypothesisClass.ORPHANED_ENTRY,
        affected="refund",
        counterfactual={"orphaned_refund_id": orphaned_refund["reference_id"]},
        outcome=Outcome.PLAUSIBLE_UNCONFIRMED,
    )
    mutated["ground_truth"] = gt
    mutated["is_clean"] = False
    return mutated, gt


# ── Registry ──────────────────────────────────────────────────────────

INJECTORS = {
    InjectedCause.MISSING_FEE_ENTRY: inject_missing_fee_entry,
    InjectedCause.DUPLICATE_WEBHOOK_PAYMENT: inject_duplicate_webhook_payment,
    InjectedCause.WRONG_TAX_RATE: inject_wrong_tax_rate,
    InjectedCause.PROVENANCE_SKEW: inject_provenance_skew,
    InjectedCause.AMOUNT_DRIFT: inject_amount_drift,
    InjectedCause.LATE_SETTLEMENT: inject_late_settlement,
    InjectedCause.SPLIT_MISATTRIBUTION: inject_split_misattribution,
    InjectedCause.SOURCE_CONFLICT: inject_source_conflict,
    InjectedCause.ORPHANED_REFUND: inject_orphaned_refund,
}


# ── Helpers ───────────────────────────────────────────────────────────

def _deep_copy_case(case: Dict[str, Any]) -> Dict[str, Any]:
    """Shallow-ish deep copy sufficient for our case dicts (no nested refs)."""
    import copy
    return copy.deepcopy(case)
