"""
Generates clean (no-anomaly) cases through the full 8-node lifecycle.
Order → Payment → Fee+Tax → Refund(s) → Settlement → Bank(s) → Ledger
"""
import random
import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field
from typing import Any

from src.constants import NodeType, SourceName
from src.config.pricing_rules import (
    calculate_fee_paise,
    calculate_gst_paise,
    settlement_delay,
)


@dataclass
class LifecycleNode:
    node_type: NodeType
    source: SourceName
    amount_paise: int
    timestamp: datetime
    reference_id: str          # unique within source
    order_id: str              # shared across all nodes in the case
    metadata: dict = field(default_factory=dict)
    # Provenance
    occurred_at: datetime = None
    received_at: datetime = None
    processed_at: datetime = None

    def __post_init__(self):
        if self.occurred_at is None:
            self.occurred_at = self.timestamp
        if self.received_at is None:
            self.received_at = self.occurred_at + timedelta(seconds=30)
        if self.processed_at is None:
            self.processed_at = self.received_at + timedelta(seconds=60)

    def content_hash(self) -> str:
        """Deterministic hash for exact-match pass."""
        raw = f"{self.node_type.value}:{self.source.value}:{self.amount_paise}:{self.order_id}:{self.reference_id}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]


@dataclass
class CleanCase:
    """A fully generated clean case with all 8 node types."""
    order_id: str
    order: LifecycleNode
    payment: LifecycleNode
    fee: LifecycleNode
    tax: LifecycleNode
    refunds: list  # list[LifecycleNode], 0..N
    settlement: LifecycleNode
    bank_entries: list  # list[LifecycleNode], 1..N (can be split)
    ledger_postings: list  # list[LifecycleNode], one per node
    ground_truth: dict = field(default_factory=dict)
    # Metadata
    payment_method: str = "upi"
    amount_paise: int = 0
    created_at: datetime = None

    def all_nodes(self) -> list:
        """Flatten all nodes into a single list."""
        nodes = [
            self.order, self.payment, self.fee, self.tax,
            self.settlement,
        ]
        nodes.extend(self.refunds)
        nodes.extend(self.bank_entries)
        nodes.extend(self.ledger_postings)
        return nodes


def _random_ts(base: datetime, spread_seconds: int = 60) -> datetime:
    """Random timestamp within spread_seconds of base."""
    offset = timedelta(seconds=random.randint(0, spread_seconds))
    return base + offset


def _make_reference(prefix: str, rng: random.Random) -> str:
    return f"{prefix}_{rng.getrandbits(48):012x}"


def generate_clean_case(
    rng: random.Random,
    base_time: datetime = None,
    case_index: int = 0,
) -> CleanCase:
    """Generate one clean case with no anomalies."""

    if base_time is None:
        base_time = datetime(2024, 6, 1, tzinfo=timezone.utc)

    order_id = f"ORD_{case_index:06d}_{rng.getrandbits(32):08x}"
    payment_methods = ["upi", "card", "netbanking", "wallet"]
    pm = rng.choice(payment_methods)

    # ── Amount (non-round, realistic) ────────────────────────────────────────
    amount_paise = rng.randint(1500, 500_000)  # ₹15 to ₹5000
    # Add some non-roundness: sometimes a 99-paise suffix
    if rng.random() < 0.3:
        amount_paise = (amount_paise // 100) * 100 + 99

    # ── Order node ───────────────────────────────────────────────────────────
    order_ts = base_time + timedelta(hours=case_index * 0.1)
    order = LifecycleNode(
        node_type=NodeType.ORDER,
        source=SourceName.ORDERS_DB,
        amount_paise=amount_paise,
        timestamp=order_ts,
        reference_id=_make_reference("ORD", rng),
        order_id=order_id,
        metadata={"payment_method": pm, "currency": "INR"},
    )

    # ── Payment node (1–45 min after order) ──────────────────────────────────
    payment_delay = timedelta(seconds=rng.randint(10, 2700))
    payment_ts = order_ts + payment_delay
    payment = LifecycleNode(
        node_type=NodeType.PAYMENT,
        source=SourceName.RAZORPAY_RECON,
        amount_paise=amount_paise,
        timestamp=payment_ts,
        reference_id=_make_reference("PAY", rng),
        order_id=order_id,
        metadata={"payment_method": pm, "status": "captured"},
    )

    # ── Fee node ─────────────────────────────────────────────────────────────
    fee_paise = calculate_fee_paise(amount_paise, pm)
    fee_ts = payment_ts + timedelta(seconds=rng.randint(1, 30))
    fee = LifecycleNode(
        node_type=NodeType.FEE,
        source=SourceName.RAZORPAY_RECON,
        amount_paise=fee_paise,
        timestamp=fee_ts,
        reference_id=_make_reference("FEE", rng),
        order_id=order_id,
        metadata={"payment_method": pm},
    )

    # ── Tax node (GST on fee) ────────────────────────────────────────────────
    tax_paise = calculate_gst_paise(fee_paise)
    tax_ts = fee_ts + timedelta(seconds=rng.randint(1, 15))
    tax = LifecycleNode(
        node_type=NodeType.TAX,
        source=SourceName.TAX_INVOICE,
        amount_paise=tax_paise,
        timestamp=tax_ts,
        reference_id=_make_reference("TAX", rng),
        order_id=order_id,
        metadata={"tax_type": "GST", "rate": 0.18},
    )

    # ── Refunds (0..N) ──────────────────────────────────────────────────────
    refunds = []
    n_refunds = 0
    if rng.random() < 0.25:  # 25% chance of refund
        n_refunds = rng.randint(1, 2)
        for i in range(n_refunds):
            refund_paise = rng.randint(
                min(100, amount_paise), amount_paise
            )
            refund_ts = payment_ts + timedelta(days=rng.randint(1, 14))
            refunds.append(LifecycleNode(
                node_type=NodeType.REFUND,
                source=SourceName.RAZORPAY_RECON,
                amount_paise=refund_paise,
                timestamp=refund_ts,
                reference_id=_make_reference("REF", rng),
                order_id=order_id,
                metadata={"refund_index": i, "status": "processed"},
            ))

    # ── Settlement ───────────────────────────────────────────────────────────
    delay_days = settlement_delay(pm)
    settlement_ts = payment_ts + timedelta(days=delay_days)
    # A refund reduces the cash ultimately payable to the merchant.  Keeping it
    # as a deduction also makes the generated settlement agree with the
    # double-entry receivable ledger.
    total_refund_paise = sum(r.amount_paise for r in refunds)
    settlement_paise = amount_paise - fee_paise - tax_paise - total_refund_paise
    settlement_paise = max(settlement_paise, 0)

    settlement = LifecycleNode(
        node_type=NodeType.SETTLEMENT,
        source=SourceName.RAZORPAY_RECON,
        amount_paise=settlement_paise,
        timestamp=settlement_ts,
        reference_id=_make_reference("STL", rng),
        order_id=order_id,
        metadata={"net_settlement": True},
    )

    # ── Bank entries (1..N, possibly split) ──────────────────────────────────
    bank_entries = []
    if rng.random() < 0.2:
        # Split settlement across 2-3 bank entries
        n_bank = rng.randint(2, 3)
        remaining = settlement_paise
        for i in range(n_bank):
            if i == n_bank - 1:
                entry_paise = remaining
            else:
                entry_paise = rng.randint(
                    settlement_paise // (n_bank * 2),
                    settlement_paise // n_bank
                )
                remaining -= entry_paise
            bank_ts = settlement_ts + timedelta(
                hours=rng.randint(1, 24)
            )
            bank_entries.append(LifecycleNode(
                node_type=NodeType.BANK,
                source=SourceName.BANK_STATEMENT,
                amount_paise=entry_paise,
                timestamp=bank_ts,
                reference_id=_make_reference("BNK", rng),
                order_id=order_id,
                metadata={"split_index": i, "n_splits": n_bank},
            ))
    else:
        bank_ts = settlement_ts + timedelta(hours=rng.randint(1, 24))
        bank_entries.append(LifecycleNode(
            node_type=NodeType.BANK,
            source=SourceName.BANK_STATEMENT,
            amount_paise=settlement_paise,
            timestamp=bank_ts,
            reference_id=_make_reference("BNK", rng),
            order_id=order_id,
        ))

    # ── Ledger postings ──────────────────────────────────────────────────────
    ledger_postings = []
    # Payment → PAYMENT_RECEIVABLE
    ledger_postings.append(LifecycleNode(
        node_type=NodeType.LEDGER,
        source=SourceName.RAZORPAY_RECON,
        amount_paise=amount_paise,
        timestamp=payment_ts + timedelta(seconds=rng.randint(1, 60)),
        reference_id=_make_reference("LED", rng),
        order_id=order_id,
        metadata={"account_code": "PAYMENT_RECEIVABLE", "debit": True},
    ))
    # Fee → FEE_INCOME
    if fee_paise > 0:
        ledger_postings.append(LifecycleNode(
            node_type=NodeType.LEDGER,
            source=SourceName.RAZORPAY_RECON,
            amount_paise=fee_paise,
            timestamp=fee_ts + timedelta(seconds=rng.randint(1, 60)),
            reference_id=_make_reference("LED", rng),
            order_id=order_id,
            metadata={"account_code": "FEE_INCOME", "debit": False},
        ))
    # Tax → GST_OUTPUT
    if tax_paise > 0:
        ledger_postings.append(LifecycleNode(
            node_type=NodeType.LEDGER,
            source=SourceName.TAX_INVOICE,
            amount_paise=tax_paise,
            timestamp=tax_ts + timedelta(seconds=rng.randint(1, 60)),
            reference_id=_make_reference("LED", rng),
            order_id=order_id,
            metadata={"account_code": "GST_OUTPUT", "debit": False},
        ))
    # Refunds → REFUND_LIABILITY
    for ref in refunds:
        ledger_postings.append(LifecycleNode(
            node_type=NodeType.LEDGER,
            source=SourceName.RAZORPAY_RECON,
            amount_paise=ref.amount_paise,
            timestamp=ref.timestamp + timedelta(seconds=rng.randint(1, 60)),
            reference_id=_make_reference("LED", rng),
            order_id=order_id,
            metadata={"account_code": "REFUND_LIABILITY", "debit": True},
        ))
    # Settlement → MERCHANT_PAYOUT
    ledger_postings.append(LifecycleNode(
        node_type=NodeType.LEDGER,
        source=SourceName.RAZORPAY_RECON,
        amount_paise=settlement_paise,
        timestamp=settlement_ts + timedelta(seconds=rng.randint(1, 60)),
        reference_id=_make_reference("LED", rng),
        order_id=order_id,
        metadata={"account_code": "MERCHANT_PAYOUT", "debit": True},
    ))

    case = CleanCase(
        order_id=order_id,
        order=order,
        payment=payment,
        fee=fee,
        tax=tax,
        refunds=refunds,
        settlement=settlement,
        bank_entries=bank_entries,
        ledger_postings=ledger_postings,
        ground_truth={
            "injected_oc": "NO_ISSUE",
            "expected_ch": "NO_ISSUE",
            "affected_node": None,
            "counterfactual_correct_values": {},
            "expected_terminal_outcome": "NO_ISSUE",
        },
        payment_method=pm,
        amount_paise=amount_paise,
        created_at=order_ts,
    )

    return case


def case_to_dict(case: CleanCase) -> dict:
    """Serialize a CleanCase to a dict suitable for JSON."""
    def node_to_dict(n: LifecycleNode) -> dict:
        result = {
            "node_type": n.node_type.value,
            "source": n.source.value,
            "amount_paise": n.amount_paise,
            "timestamp": n.timestamp.isoformat(),
            "occurred_at": n.occurred_at.isoformat(),
            "received_at": n.received_at.isoformat(),
            "processed_at": n.processed_at.isoformat(),
            "reference_id": n.reference_id,
            "order_id": n.order_id,
            "content_hash": n.content_hash(),
            "metadata": n.metadata,
        }
        # Explicit parent references make the source fixtures representative of
        # real gateway and bank exports, rather than relying on a hidden
        # canonical grouping to infer the lifecycle graph.
        if n.node_type in (NodeType.FEE, NodeType.TAX, NodeType.REFUND):
            result["payment_id"] = case.payment.reference_id
        if n.node_type == NodeType.SETTLEMENT:
            result["settlement_ref"] = n.reference_id
        if n.node_type == NodeType.BANK:
            result["settlement_ref"] = case.settlement.reference_id
        return result

    return {
        "order_id": case.order_id,
        "payment_method": case.payment_method,
        "amount_paise": case.amount_paise,
        "created_at": case.created_at.isoformat() if case.created_at else None,
        "nodes": {
            "order": node_to_dict(case.order),
            "payment": node_to_dict(case.payment),
            "fee": node_to_dict(case.fee),
            "tax": node_to_dict(case.tax),
            "refunds": [node_to_dict(r) for r in case.refunds],
            "settlement": node_to_dict(case.settlement),
            "bank_entries": [node_to_dict(b) for b in case.bank_entries],
            "ledger_postings": [node_to_dict(l) for l in case.ledger_postings],
        },
        "ground_truth": case.ground_truth,
    }
