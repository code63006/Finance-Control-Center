"""
Single source of truth for the AI Finance Controller.
All outcome vocabulary, calibrated constants, and enums live here.
"""
from enum import Enum
from typing import Any


# ─── Outcome Vocabulary (used everywhere, never as string literals) ──────────

class Outcome(str, Enum):
    STRONGLY_SUPPORTED = "STRONGLY_SUPPORTED"
    PLAUSIBLE_UNCONFIRMED = "PLAUSIBLE_UNCONFIRMED"
    UNRESOLVED_AMBIGUITY = "UNRESOLVED_AMBIGUITY"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONTRADICTED = "CONTRADICTED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    # Matcher-level outcomes (reported in match stats, not diagnosis)
    UNMATCHED = "UNMATCHED"
    AMBIGUOUS_MATCH = "AMBIGUOUS_MATCH"
    RESOLVED = "RESOLVED"
    LIKELY_ABANDONED = "LIKELY_ABANDONED"
    # No-issue ground truth
    NO_ISSUE = "NO_ISSUE"
    # Source conflict flag
    OC_SOURCE_CONFLICT = "OC_SOURCE_CONFLICT"


# ─── Source Names ────────────────────────────────────────────────────────────

class SourceName(str, Enum):
    ORDERS_DB = "orders_db"
    RAZORPAY_RECON = "razorpay_recon"
    BANK_STATEMENT = "bank_statement"
    TAX_INVOICE = "tax_invoice"
    SYSTEM = "system"


# ─── Node Types (8-node lifecycle graph) ────────────────────────────────────

class NodeType(str, Enum):
    ORDER = "order"
    PAYMENT = "payment"
    FEE = "fee"
    TAX = "tax"
    REFUND = "refund"
    SETTLEMENT = "settlement"
    BANK = "bank"
    LEDGER = "ledger"


# ─── Injected Cause (ground-truth anomaly type) ─────────────────────────────

class InjectedCause(str, Enum):
    NO_ISSUE = "NO_ISSUE"
    MISSING_FEE_ENTRY = "missing_fee_entry"
    DUPLICATE_WEBHOOK_PAYMENT = "duplicate_webhook_payment"
    WRONG_TAX_RATE = "wrong_tax_rate"
    PROVENANCE_TIMESTAMP_SKEW = "provenance_timestamp_skew"
    AMOUNT_ROUNDING_DRIFT = "amount_rounding_drift"
    LATE_SETTLEMENT = "late_settlement"
    SPLIT_SETTLEMENT_MISATTRIBUTION = "split_settlement_misattribution"
    SOURCE_CONFLICT_SAME_FACT = "source_conflict_same_fact"
    ORPHANED_REFUND = "orphaned_refund"
    PROVENANCE_SKEW = "provenance_timestamp_skew"
    AMOUNT_DRIFT = "amount_rounding_drift"
    SPLIT_MISATTRIBUTION = "split_settlement_misattribution"
    SOURCE_CONFLICT = "source_conflict_same_fact"


# ─── Hypothesis Class (classification label for per-class precision/recall) ──

class HypothesisClass(str, Enum):
    NO_ISSUE = "NO_ISSUE"
    FEE_MISSING = "FEE_MISSING"
    DUPLICATE_PAYMENT = "DUPLICATE_PAYMENT"
    TAX_RATE_ERROR = "TAX_RATE_ERROR"
    PROVENANCE_SKEW = "PROVENANCE_SKEW"
    AMOUNT_DRIFT = "AMOUNT_DRIFT"
    LATE_SETTLEMENT = "LATE_SETTLEMENT"
    SPLIT_MISATTRIBUTION = "SPLIT_MISATTRIBUTION"
    SOURCE_CONFLICT = "SOURCE_CONFLICT"
    ORPHANED_REFUND = "ORPHANED_REFUND"
    TAX_CALCULATION_ERROR = "TAX_RATE_ERROR"
    TIMESTAMP_INCONSISTENCY = "PROVENANCE_SKEW"
    AMOUNT_MISMATCH = "AMOUNT_DRIFT"
    SETTLEMENT_DELAY = "LATE_SETTLEMENT"
    SPLIT_ATTRIBUTION_ERROR = "SPLIT_MISATTRIBUTION"
    SOURCE_DATA_CONFLICT = "SOURCE_CONFLICT"
    ORPHANED_ENTRY = "ORPHANED_REFUND"


# ─── Account Codes (chart of accounts) ──────────────────────────────────────

class AccountCode(str, Enum):
    PAYMENT_RECEIVABLE = "PAYMENT_RECEIVABLE"     # 1200
    MERCHANT_PAYOUT = "MERCHANT_PAYOUT"           # 2100
    FEE_INCOME = "FEE_INCOME"                     # 4100
    GST_OUTPUT = "GST_OUTPUT"                     # 2300
    GST_INPUT = "GST_INPUT"                       # 1310
    REFUND_LIABILITY = "REFUND_LIABILITY"         # 2200
    BANK_CASH = "BANK_CASH"                       # 1100
    # Legacy ledger names retained as aliases for the current chart.
    PG_RECEIVABLE = "PAYMENT_RECEIVABLE"
    REVENUE = "FEE_INCOME"
    FEE_EXPENSE = "FEE_INCOME"
    GST_EXPENSE = "GST_INPUT"
    BANK = "BANK_CASH"


# Account code mapping: NodeType → correct AccountCode for each transaction type
ACCOUNT_CODE_MAP = {
    NodeType.PAYMENT: AccountCode.PAYMENT_RECEIVABLE,
    NodeType.FEE: AccountCode.FEE_INCOME,
    NodeType.TAX: AccountCode.GST_OUTPUT,
    NodeType.REFUND: AccountCode.REFUND_LIABILITY,
    NodeType.SETTLEMENT: AccountCode.MERCHANT_PAYOUT,
    NodeType.BANK: AccountCode.BANK_CASH,
}


# ─── Match Status ────────────────────────────────────────────────────────────

class MatchStatus(str, Enum):
    EXACT = "exact"
    FUZZY_RESOLVED = "fuzzy_resolved"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"
    RESOLVED = "resolved"
    AMBIGUOUS_MATCH = "ambiguous"


# ─── Evidence Types ──────────────────────────────────────────────────────────

class EvidenceType(str, Enum):
    """Evidence items that can appear in a CaseEvidence bag."""
    FEE_NODE_PRESENT = "FEE_NODE_PRESENT"
    FEE_NODE_MISSING = "FEE_NODE_MISSING"
    TAX_NODE_PRESENT = "TAX_NODE_PRESENT"
    TAX_NODE_MISSING = "TAX_NODE_MISSING"
    LEDGER_BALANCED = "LEDGER_BALANCED"
    LEDGER_IMBALANCE = "LEDGER_IMBALANCE"
    ACCOUNT_CODE_CORRECT = "ACCOUNT_CODE_CORRECT"
    ACCOUNT_CODE_WRONG = "ACCOUNT_CODE_WRONG"
    SETTLEMENT_MATCHED = "SETTLEMENT_MATCHED"
    SETTLEMENT_MISSING = "SETTLEMENT_MISSING"
    BANK_ENTRIES_MATCHED = "BANK_ENTRIES_MATCHED"
    BANK_ENTRIES_MISSING = "BANK_ENTRIES_MISSING"
    REFUND_FOUND = "REFUND_FOUND"
    REFUND_ORPHANED = "REFUND_ORPHANED"
    PROVENANCE_VALID = "PROVENANCE_VALID"
    PROVENANCE_VIOLATION = "PROVENANCE_VIOLATION"
    AMOUNTS_CONSISTENT = "AMOUNTS_CONSISTENT"
    AMOUNTS_DRIFTED = "AMOUNTS_DRIFTED"
    SOURCE_CONFLICT_DETECTED = "SOURCE_CONFLICT_DETECTED"
    TEMPORAL_CONSISTENT = "TEMPORAL_CONSISTENT"
    TEMPORAL_INCONSISTENT = "TEMPORAL_INCONSISTENT"


# ─── [CALIBRATE] Thresholds ─────────────────────────────────────────────────
# All values below are calibrated via the sweep documented in docs/CALIBRATION.md.
# Do NOT change any value without re-running the sweep.

CONFIRM_THRESHOLD: float = 0.8        # value >= this AND coverage == 1.0 → STRONGLY_SUPPORTED
FLOOR_THRESHOLD: float = 0.15         # best.value < this → INSUFFICIENT_EVIDENCE (must be > 0)
TIE_MARGIN: float = 0.05              # gap between top-2 < this → UNRESOLVED_AMBIGUITY

AMOUNT_TOLERANCE_PAISE: int = 100     # ₹1 max diff for fuzzy match eligibility
TIME_TOLERANCE_SECONDS: int = 120     # 2 min max time diff for fuzzy match
UNIQUENESS_MARGIN: float = 0.15       # fuzzy score gap needed for unique match

PROVENANCE_RELIABILITY_PENALTY: float = 0.3  # penalty per provenance violation

# occurred_at <= received_at <= processed_at within clock-drift tolerance
PROVENANCE_SKEW_TOLERANCE_SECONDS: int = 300  # [CALIBRATE] 5-minute tolerance

# Distinct from TIME_TOLERANCE_SECONDS — this is the soft "likely abandoned" label
LIKELY_ABANDONED_SECONDS: int = 300   # 5 min order→payment gap

# Calendar / SLA
PAYMENT_PROCESSING_SECONDS: int = 300  # SLA for payment processing


# ─── Validation ──────────────────────────────────────────────────────────────

def validate_calibration():
    """Run at startup to catch calibration relationship violations."""
    errors = []
    if FLOOR_THRESHOLD <= 0:
        errors.append("FLOOR_THRESHOLD must be > 0 (strictly)")
    if FLOOR_THRESHOLD >= CONFIRM_THRESHOLD:
        errors.append("FLOOR_THRESHOLD must be < CONFIRM_THRESHOLD")
    if (CONFIRM_THRESHOLD - FLOOR_THRESHOLD) <= TIE_MARGIN:
        errors.append(
            "CONFIRM_THRESHOLD - FLOOR_THRESHOLD must be > TIE_MARGIN "
            f"(got {CONFIRM_THRESHOLD - FLOOR_THRESHOLD:.3f} vs {TIE_MARGIN})"
        )
    if AMOUNT_TOLERANCE_PAISE <= 0:
        errors.append("AMOUNT_TOLERANCE_PAISE must be > 0")
    if TIME_TOLERANCE_SECONDS <= 0:
        errors.append("TIME_TOLERANCE_SECONDS must be > 0")
    if errors:
        raise ValueError(f"Calibration invariant violations: {'; '.join(errors)}")
    return True


# Compatibility export for callers that historically imported evidence types
# from constants rather than the evidence module.
from src.agent.evidence import EvidenceType
