"""
Blast radius computation.
Signed variance (overpayment vs shortfall) and per-component impact breakdown.
Root cause is one per case; impact components can be more than one.
"""
from dataclasses import dataclass, field
from typing import Dict, Any, Optional
from src.constants import NodeType


@dataclass
class BlastRadius:
    """Complete blast radius analysis for one case."""
    case_id: str
    
    # Headline metrics
    recorded_net_paise: int  # what actually happened
    counterfactual_correct_net_paise: int  # what should have happened
    variance_paise: int  # recorded - counterfactual (signed)
    exposure_abs_paise: int  # |variance| (headline magnitude only)
    
    # Per-component deltas (each signed, computed independently)
    impact_components: Dict[str, int] = field(default_factory=dict)
    
    # Root cause (exactly one per case)
    root_cause: Optional[str] = None  # HypothesisClass value
    
    # Explanation
    explanation: str = ""

    @property
    def exposure_paise(self) -> int:
        """Compatibility alias for the absolute exposure headline."""
        return self.exposure_abs_paise
    
    def __post_init__(self):
        # Verify impact components sum to variance
        if self.impact_components:
            component_sum = sum(self.impact_components.values())
            assert component_sum == self.variance_paise, (
                f"Impact components sum ({component_sum}) != variance ({self.variance_paise})"
            )


def variance_paise(recorded_net_paise: int, counterfactual_correct_net_paise: int) -> int:
    """Return signed recorded-minus-correct variance in paise."""
    return recorded_net_paise - counterfactual_correct_net_paise


def compute_blast_radius(
    case: Dict[str, Any],
    diagnosis: Dict[str, Any],
    matched_graph: Dict[str, Any] = None,
) -> BlastRadius:
    """
    Compute the blast radius for a diagnosed case.
    
    Args:
        case: Original case data
        diagnosis: Output from rch_engine.diagnose()
        matched_graph: Output from graph matching
    
    Returns:
        BlastRadius with signed variance and component breakdown
    """
    if matched_graph is None and "fee_amount_paise" in case:
        counterfactual = diagnosis
        component_keys = (
            "fee_amount_paise",
            "tax_amount_paise",
            "settlement_amount_paise",
            "bank_amount_paise",
            "refund_amount_paise",
        )
        components = {
            key.replace("_amount_paise", "_delta_paise"): case.get(key, 0) - counterfactual.get(key, case.get(key, 0))
            for key in component_keys
        }
        variance = sum(components.values())
        return BlastRadius(
            case_id=case.get("order_id", "unknown"),
            recorded_net_paise=case.get("settlement_amount_paise", 0),
            counterfactual_correct_net_paise=case.get("settlement_amount_paise", 0) - variance,
            variance_paise=variance,
            exposure_abs_paise=abs(variance),
            impact_components=components,
            root_cause=case.get("diagnosis", {}).get("hypothesis"),
            explanation="Signed difference between recorded and counterfactual component values.",
        )

    if matched_graph is not None:
        sources = case.get("sources", {})
        recon = sources.get("razorpay_recon", [])
        bank = sources.get("bank_statement", [])
        current_fee = sum(item.get("amount_paise", 0) for item in recon if item.get("type") == "fee")
        current_tax = sum(item.get("amount_paise", 0) for item in recon if item.get("type") == "tax")
        current_settlement = case.get("settlement", {}).get("net_paise", 0)
        if not current_settlement:
            current_settlement = sum(item.get("credit_paise", 0) for item in bank)
        truth = case.get("ground_truth", {}).get("counterfactual", {})
        components = {}
        if "correct_fee_paise" in truth:
            components["fee_delta_paise"] = current_fee - truth["correct_fee_paise"]
        if "correct_tax_paise" in truth:
            components["tax_delta_paise"] = current_tax - truth["correct_tax_paise"]
        if "correct_settlement_paise" in truth:
            components["settlement_delta_paise"] = current_settlement - truth["correct_settlement_paise"]
        variance = sum(components.values())
        return BlastRadius(
            case_id=case.get("case_id", "unknown"),
            recorded_net_paise=current_settlement,
            counterfactual_correct_net_paise=current_settlement - variance,
            variance_paise=variance,
            exposure_abs_paise=abs(variance),
            root_cause=diagnosis.get("best_hypothesis", "unknown"),
            impact_components=components or {"net_delta_paise": 0},
        )

    case_id = case.get("case_id", "unknown")
    ground_truth = case.get("ground_truth", {})
    
    # ── Compute recorded net settlement ─────────────────────────────────
    # Net = payments received - fees - taxes - refunds - bank debits
    recorded_net = _compute_recorded_net(case, matched_graph)
    
    # ── Compute counterfactual correct net ──────────────────────────────
    counterfactual_net = _compute_counterfactual_net(case, ground_truth, matched_graph)
    
    # ── Signed variance ─────────────────────────────────────────────────
    variance = recorded_net - counterfactual_net
    exposure_abs = abs(variance)
    
    # ── Impact components (each signed, independent) ───────────────────
    impact_components = _compute_impact_components(
        case, ground_truth, matched_graph, diagnosis
    )
    
    # ── Root cause ──────────────────────────────────────────────────────
    root_cause = diagnosis.get("best_hypothesis", None)
    
    # ── Explanation ─────────────────────────────────────────────────────
    if variance > 0:
        direction = "OVERPAYMENT"
        explanation = (
            f"Merchant received {variance} paise more than correct. "
            f"This represents a clawback owed to the payment gateway."
        )
    elif variance < 0:
        direction = "SHORTFALL"
        explanation = (
            f"Merchant received {abs(variance)} paise less than correct. "
            f"This represents an amount owed to the merchant."
        )
    else:
        direction = "BALANCED"
        explanation = "No variance detected."
    
    return BlastRadius(
        case_id=case_id,
        recorded_net_paise=recorded_net,
        counterfactual_correct_net_paise=counterfactual_net,
        variance_paise=variance,
        exposure_abs_paise=exposure_abs,
        impact_components=impact_components,
        root_cause=root_cause,
        explanation=explanation,
    )


def _compute_recorded_net(
    case: Dict[str, Any],
    matched_graph: Dict[str, Any],
) -> int:
    """
    Compute what actually happened: net settlement to merchant.
    Positive = merchant received money, negative = merchant paid out.
    """
    net = 0
    
    # Payments are positive (merchant receives)
    for payment in case.get("sources", {}).get("razorpay_recon", []):
        if payment.get("type") == "payment" and payment.get("status") == "captured":
            net += payment.get("amount_paise", 0)
    
    # Fees are negative (merchant pays)
    for fee in case.get("sources", {}).get("razorpay_recon", []):
        if fee.get("type") == "fee":
            net -= fee.get("amount_paise", 0)
    
    # Taxes are negative (merchant pays)
    for tax in case.get("sources", {}).get("razorpay_recon", []):
        if tax.get("type") == "tax":
            net -= tax.get("amount_paise", 0)
    
    # Refunds are negative (merchant returns money)
    for refund in case.get("sources", {}).get("razorpay_recon", []):
        if refund.get("type") == "refund":
            net -= refund.get("amount_paise", 0)
    
    return net


def _compute_counterfactual_net(
    case: Dict[str, Any],
    ground_truth: Dict[str, Any],
    matched_graph: Dict[str, Any],
) -> int:
    """
    Compute what SHOULD have happened using counterfactual_correct_values.
    This uses the ground truth from the generator to compute the correct state.
    """
    counterfactual = ground_truth.get("counterfactual", {})
    
    # Start with the recorded net
    recorded_net = _compute_recorded_net(case, matched_graph)
    
    # Apply corrections from counterfactual
    corrected_net = recorded_net
    
    # Fee correction
    if "correct_fee_paise" in counterfactual:
        current_fee = sum(
            f.get("amount_paise", 0) 
            for f in case.get("sources", {}).get("razorpay_recon", [])
            if f.get("type") == "fee"
        )
        corrected_net += current_fee  # remove wrong fee
        corrected_net -= counterfactual["correct_fee_paise"]  # apply correct fee
    
    # Tax correction
    if "correct_tax_paise" in counterfactual:
        current_tax = sum(
            t.get("amount_paise", 0)
            for t in case.get("sources", {}).get("razorpay_recon", [])
            if t.get("type") == "tax"
        )
        corrected_net += current_tax  # remove wrong tax
        corrected_net -= counterfactual["correct_tax_paise"]  # apply correct tax
    
    # Settlement correction
    if "correct_settlement_paise" in counterfactual:
        current_settlement = case.get("settlement", {}).get("net_paise", 0)
        corrected_net += current_settlement  # remove wrong settlement
        corrected_net -= counterfactual["correct_settlement_paise"]  # apply correct
    
    # Bank entry correction (for split misattribution)
    if "correct_bank_entries" in counterfactual:
        current_bank_total = sum(
            b.get("credit_paise", 0)
            for b in case.get("sources", {}).get("bank_statement", [])
        )
        corrected_net += current_bank_total  # remove wrong total
        for entry in counterfactual["correct_bank_entries"]:
            corrected_net -= entry.get("credit_paise", 0)  # apply correct entries
    
    return corrected_net


def _compute_impact_components(
    case: Dict[str, Any],
    ground_truth: Dict[str, Any],
    matched_graph: Dict[str, Any],
    diagnosis: Dict[str, Any],
) -> Dict[str, int]:
    """
    Compute per-component deltas, each signed independently.
    Tax delta is NOT assumed to equal fee delta * rate.
    """
    components = {}
    counterfactual = ground_truth.get("counterfactual", {})
    
    # Fee delta
    if "correct_fee_paise" in counterfactual:
        current_fee = sum(
            f.get("amount_paise", 0)
            for f in case.get("sources", {}).get("razorpay_recon", [])
            if f.get("type") == "fee"
        )
        components["fee_delta_paise"] = current_fee - counterfactual["correct_fee_paise"]
    
    # Tax delta
    if "correct_tax_paise" in counterfactual:
        current_tax = sum(
            t.get("amount_paise", 0)
            for t in case.get("sources", {}).get("razorpay_recon", [])
            if t.get("type") == "tax"
        )
        components["tax_delta_paise"] = current_tax - counterfactual["correct_tax_paise"]
    
    # Settlement delta
    if "correct_settlement_paise" in counterfactual:
        current_settlement = case.get("settlement", {}).get("net_paise", 0)
        components["settlement_delta_paise"] = (
            current_settlement - counterfactual["correct_settlement_paise"]
        )
    
    # Refund offset delta
    if "correct_refund_paise" in counterfactual:
        current_refund = sum(
            r.get("amount_paise", 0)
            for r in case.get("sources", {}).get("razorpay_recon", [])
            if r.get("type") == "refund"
        )
        components["refund_offset_delta_paise"] = (
            current_refund - counterfactual["correct_refund_paise"]
        )
    
    # Bank delta
    if "correct_bank_entries" in counterfactual:
        current_bank = sum(
            b.get("credit_paise", 0)
            for b in case.get("sources", {}).get("bank_statement", [])
        )
        correct_bank = sum(
            e.get("credit_paise", 0)
            for e in counterfactual["correct_bank_entries"]
        )
        components["bank_delta_paise"] = current_bank - correct_bank
    
    # If no components computed, set zero delta
    if not components:
        components["net_delta_paise"] = 0
    
    return components
