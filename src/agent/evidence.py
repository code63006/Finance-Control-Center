"""
Evidence collection, coverage scoring, and reliability computation.
After the 3-pass matcher and ledger verification, we aggregate all signals
into a structured evidence bag that rch_engine.py can score hypotheses against.
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Set
from enum import Enum


class EvidenceType(Enum):
    """Flat evidence taxonomy with context attributes."""
    # Node presence
    FEE_NODE_MATCHED = "fee_node_matched"
    FEE_NODE_MISSING = "fee_node_missing"
    PAYMENT_NODE_MATCHED = "payment_node_matched"
    PAYMENT_NODE_AMBIGUOUS = "payment_node_ambiguous"
    PAYMENT_NODE_UNMATCHED = "payment_node_unmatched"
    PAYMENT_DUPLICATE_DETECTED = "payment_duplicate_detected"
    TAX_NODE_MATCHED = "tax_node_matched"
    TAX_NODE_MISSING = "tax_node_missing"
    TAX_MISMATCH = "tax_mismatch"
    REFUND_NODE_MATCHED = "refund_node_matched"
    REFUND_NODE_ORPHANED = "refund_node_orphaned"
    BANK_ENTRY_MATCHED = "bank_entry_matched"
    BANK_ENTRY_ORPHANED = "bank_entry_orphaned"
    SETTLEMENT_NODE_MATCHED = "settlement_node_matched"
    SETTLEMENT_NODE_MISSING = "settlement_node_missing"
    LEDGER_NODE_MATCHED = "ledger_node_matched"
    
    # Aggregate flags for 1:N relationships
    ALL_BANK_ENTRIES_MATCHED = "all_bank_entries_matched"
    ALL_REFUNDS_MATCHED = "all_refunds_matched"
    SOME_BANK_ENTRIES_ORPHANED = "some_bank_entries_orphaned"
    SOME_REFUNDS_ORPHANED = "some_refunds_orphaned"
    
    # Integrity
    PROVENANCE_VIOLATION = "provenance_violation"
    PROVENANCE_CLEAN = "provenance_clean"
    
    # Math
    AMOUNT_MISMATCH = "amount_mismatch"
    AMOUNT_MATCHED = "amount_matched"
    LEDGER_IMBALANCE = "ledger_imbalance"
    LEDGER_BALANCED = "ledger_balanced"
    PG_RECEIVABLE_IMBALANCE = "pg_receivable_imbalance"
    PG_RECEIVABLE_ZERO = "pg_receivable_zero"
    
    # Time
    TIMESTAMP_ORDER_VIOLATION = "timestamp_order_violation"
    TIMESTAMP_ORDER_OK = "timestamp_order_ok"
    SETTLEMENT_LATE = "settlement_late"
    SETTLEMENT_ON_TIME = "settlement_on_time"
    
    # Source conflict
    SOURCE_CONFLICT_DETECTED = "source_conflict_detected"
    SOURCE_CONFLICT_ABSENT = "source_conflict_absent"
    
    # Account mapping
    ACCOUNT_MAPPING_CORRECT = "account_mapping_correct"
    ACCOUNT_MAPPING_VIOLATION = "account_mapping_violation"
    
    # Order-Payment gap
    ORDER_PAYMENT_GAP_NORMAL = "order_payment_gap_normal"
    ORDER_PAYMENT_GAP_LIKELY_ABANDONED = "order_payment_gap_likely_abandoned"
    TEMPORAL_CONSISTENT = "timestamp_order_ok"
    FEE_NODE_PRESENT = "fee_node_matched"
    TAX_NODE_PRESENT = "tax_node_matched"
    PROVENANCE_VALID = "provenance_clean"
    AMOUNTS_CONSISTENT = "amount_matched"
    AMOUNTS_DRIFTED = "amount_mismatch"
    ACCOUNT_CODE_CORRECT = "account_mapping_correct"
    ACCOUNT_CODE_WRONG = "account_mapping_violation"
    SETTLEMENT_MATCHED = "settlement_node_matched"
    SETTLEMENT_MISSING = "settlement_node_missing"
    BANK_ENTRIES_MATCHED = "bank_entry_matched"
    BANK_ENTRIES_MISSING = "bank_entry_orphaned"
    REFUND_FOUND = "refund_node_matched"
    REFUND_ORPHANED = "refund_node_orphaned"


@dataclass
class EvidenceItem:
    """Single piece of evidence with source attribution."""
    evidence_type: EvidenceType
    source_reliability: Any = 1.0  # [0, 1] after provenance penalty
    details: Any = field(default_factory=dict)
    source: Any = None

    def __post_init__(self):
        # Older callers used (evidence_type, source, reliability).
        if not isinstance(self.source_reliability, (int, float)):
            legacy_source = self.source_reliability
            legacy_reliability = self.details if isinstance(self.details, (int, float)) else 1.0
            self.source = self.source or legacy_source
            self.source_reliability = legacy_reliability
            self.details = {}


@dataclass
class CaseEvidence:
    """Complete evidence bag for one reconciled case."""
    case_id: str = "unknown"
    items: List[EvidenceItem] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> None:
        self.items.append(item)
    
    def has(self, evidence_type: EvidenceType) -> bool:
        """Check if this evidence type is present."""
        return any(item.evidence_type == evidence_type for item in self.items)
    
    def has_any(self, evidence_types: List[EvidenceType]) -> bool:
        """Check if any of these evidence types are present."""
        return any(self.has(et) for et in evidence_types)
    
    def contradicts(self, evidence_type: EvidenceType) -> bool:
        """Check if this evidence type contradicts a hypothesis."""
        return self.has(evidence_type)
    
    def source_reliability(self, evidence_type: EvidenceType) -> float:
        """Get the reliability of the source for this evidence type."""
        for item in self.items:
            if item.evidence_type == evidence_type:
                return item.source_reliability
        return 1.0  # default reliability if not found
    
    def get_matched_reliabilities(self, evidence_types: List[EvidenceType]) -> List[float]:
        """Get reliabilities for all matched evidence types."""
        reliabilities = []
        for et in evidence_types:
            if self.has(et):
                reliabilities.append(self.source_reliability(et))
        return reliabilities


def collect_evidence(
    case: Dict[str, Any],
    graph_match_result: Dict[str, Any],
    ledger_result: Dict[str, Any],
    tax_result: Optional[Dict[str, Any]],
    provenance_violations: List[str],
) -> CaseEvidence:
    """
    Collect all evidence from the reconciliation pipeline results.
    
    Args:
        case: Original case data
        graph_match_result: Output from LifecycleGraphMatcher
        ledger_result: Output from verify_case_ledger
        tax_result: Output from reconcile_invoice_taxes (optional)
        provenance_violations: List of source names with provenance violations
    
    Returns:
        CaseEvidence bag with all detected signals
    """
    evidence = CaseEvidence(case_id=case.get("case_id", "unknown"))
    
    # ── Node presence evidence ──────────────────────────────────────────
    matched_nodes = graph_match_result.get("matched_nodes", {})
    unmatched_nodes = graph_match_result.get("unmatched_nodes", {})
    ambiguous_nodes = graph_match_result.get("ambiguous_nodes", {})
    
    # Payment node evidence
    if "payment" in matched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PAYMENT_NODE_MATCHED,
            source_reliability=matched_nodes["payment"].get("reliability", 1.0),
        ))
    elif "payment" in ambiguous_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PAYMENT_NODE_AMBIGUOUS,
            source_reliability=ambiguous_nodes["payment"].get("reliability", 1.0),
        ))
        # Check for duplicate detection
        if ambiguous_nodes["payment"].get("duplicate_count", 0) > 1:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.PAYMENT_DUPLICATE_DETECTED,
                source_reliability=ambiguous_nodes["payment"].get("reliability", 1.0),
                details={"duplicate_count": ambiguous_nodes["payment"]["duplicate_count"]},
            ))
    elif "payment" in unmatched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PAYMENT_NODE_UNMATCHED,
            source_reliability=unmatched_nodes["payment"].get("reliability", 1.0),
        ))
    
    # Fee node evidence
    if "fee" in matched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.FEE_NODE_MATCHED,
            source_reliability=matched_nodes["fee"].get("reliability", 1.0),
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.FEE_NODE_MISSING,
            source_reliability=1.0,
        ))
    
    # Tax node evidence
    if "tax" in matched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.TAX_NODE_MATCHED,
            source_reliability=matched_nodes["tax"].get("reliability", 1.0),
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.TAX_NODE_MISSING,
            source_reliability=1.0,
        ))
    
    # Refund nodes (1:N - may have multiple)
    refund_matched = [r for r in matched_nodes if r.startswith("refund_")]
    refund_orphaned = [r for r in unmatched_nodes if r.startswith("refund_")]
    
    if refund_matched:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.REFUND_NODE_MATCHED,
            source_reliability=max(matched_nodes[r].get("reliability", 1.0) for r in refund_matched),
        ))
        if not refund_orphaned:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.ALL_REFUNDS_MATCHED,
                source_reliability=1.0,
            ))
    
    if refund_orphaned:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.REFUND_NODE_ORPHANED,
            source_reliability=max(unmatched_nodes[r].get("reliability", 1.0) for r in refund_orphaned),
        ))
        if refund_matched:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.SOME_REFUNDS_ORPHANED,
                source_reliability=1.0,
            ))
    
    # Bank entries (1:N - may have multiple)
    bank_matched = [b for b in matched_nodes if b.startswith("bank_")]
    bank_orphaned = [b for b in unmatched_nodes if b.startswith("bank_")]
    
    if bank_matched:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.BANK_ENTRY_MATCHED,
            source_reliability=max(matched_nodes[b].get("reliability", 1.0) for b in bank_matched),
        ))
        if not bank_orphaned:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.ALL_BANK_ENTRIES_MATCHED,
                source_reliability=1.0,
            ))
    
    if bank_orphaned:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.BANK_ENTRY_ORPHANED,
            source_reliability=max(unmatched_nodes[b].get("reliability", 1.0) for b in bank_orphaned),
        ))
        if bank_matched:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.SOME_BANK_ENTRIES_ORPHANED,
                source_reliability=1.0,
            ))
    
    # Settlement node
    if "settlement" in matched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_NODE_MATCHED,
            source_reliability=matched_nodes["settlement"].get("reliability", 1.0),
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_NODE_MISSING,
            source_reliability=1.0,
        ))
    
    # Ledger node
    if "ledger" in matched_nodes:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.LEDGER_NODE_MATCHED,
            source_reliability=matched_nodes["ledger"].get("reliability", 1.0),
        ))
    
    # ── Provenance evidence ─────────────────────────────────────────────
    if provenance_violations:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PROVENANCE_VIOLATION,
            source_reliability=1.0,
            details={"violating_sources": provenance_violations},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PROVENANCE_CLEAN,
            source_reliability=1.0,
        ))
    
    # ── Math evidence ───────────────────────────────────────────────────
    if ledger_result.get("is_balanced", False):
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.LEDGER_BALANCED,
            source_reliability=1.0,
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.LEDGER_IMBALANCE,
            source_reliability=1.0,
            details={"residual_paise": ledger_result.get("residual_paise", 0)},
        ))
    
    if ledger_result.get("pg_receivable_net", 0) == 0:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PG_RECEIVABLE_ZERO,
            source_reliability=1.0,
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.PG_RECEIVABLE_IMBALANCE,
            source_reliability=1.0,
            details={"net_paise": ledger_result.get("pg_receivable_net", 0)},
        ))
    
    # Amount mismatch detection
    amount_deltas = graph_match_result.get("amount_deltas", {})
    has_amount_mismatch = any(abs(delta) > 0 for delta in amount_deltas.values())
    if has_amount_mismatch:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.AMOUNT_MISMATCH,
            source_reliability=1.0,
            details={"deltas": amount_deltas},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.AMOUNT_MATCHED,
            source_reliability=1.0,
        ))
    
    # ── Time evidence ───────────────────────────────────────────────────
    timestamp_violations = graph_match_result.get("timestamp_violations", [])
    if timestamp_violations:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.TIMESTAMP_ORDER_VIOLATION,
            source_reliability=1.0,
            details={"violations": timestamp_violations},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.TIMESTAMP_ORDER_OK,
            source_reliability=1.0,
        ))
    
    # Settlement latency
    if graph_match_result.get("settlement_late", False):
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_LATE,
            source_reliability=1.0,
            details={"delay_hours": graph_match_result.get("settlement_delay_hours", 0)},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_ON_TIME,
            source_reliability=1.0,
        ))
    
    # Order-Payment gap
    order_payment_gap = graph_match_result.get("order_payment_gap_seconds", 0)
    if order_payment_gap > 300:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.ORDER_PAYMENT_GAP_LIKELY_ABANDONED,
            source_reliability=1.0,
            details={"gap_seconds": order_payment_gap},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.ORDER_PAYMENT_GAP_NORMAL,
            source_reliability=1.0,
        ))
    
    # ── Source conflict evidence ────────────────────────────────────────
    source_conflicts = graph_match_result.get("source_conflicts", [])
    if source_conflicts:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SOURCE_CONFLICT_DETECTED,
            source_reliability=1.0,
            details={"conflicts": source_conflicts},
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.SOURCE_CONFLICT_ABSENT,
            source_reliability=1.0,
        ))
    
    # ── Account mapping evidence ────────────────────────────────────────
    if ledger_result.get("account_mapping_valid", True):
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.ACCOUNT_MAPPING_CORRECT,
            source_reliability=1.0,
        ))
    else:
        evidence.items.append(EvidenceItem(
            evidence_type=EvidenceType.ACCOUNT_MAPPING_VIOLATION,
            source_reliability=1.0,
            details={"violations": ledger_result.get("account_violations", [])},
        ))
    
    # ── Tax evidence ────────────────────────────────────────────────────
    if tax_result:
        if tax_result.get("reconciled", False):
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.TAX_NODE_MATCHED,
                source_reliability=1.0,
            ))
        else:
            evidence.items.append(EvidenceItem(
                evidence_type=EvidenceType.TAX_MISMATCH,
                source_reliability=1.0,
                details={"variance_paise": tax_result.get("variance_paise", 0)},
            ))
    
    return evidence
