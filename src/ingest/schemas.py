from dataclasses import dataclass, field
from typing import Any
from typing import Optional, Dict
from src.constants import (
    NodeType,
    PROVENANCE_RELIABILITY_PENALTY,
    PROVENANCE_SKEW_TOLERANCE_SECONDS,
    SourceName,
)


@dataclass
class Record:
    order_id: str
    amount: float
    currency: str = "INR"
    tax_rate: float = 0.18
    captured_at: str = "2026-01-02"
    provenance: str = "system"
    metadata: dict[str, Any] = field(default_factory=dict)
    occurred_at: int | None = None
    received_at: int | None = None
    processed_at: int | None = None
    direction: str = "credit"
    payment_id: str | None = None
    settlement_ref: str | None = None
    record_type: str = "record"
    reliability_penalty: float = 0.0

    @property
    def reliability(self) -> float:
        base = {"system": 1.0, "partner": 0.85, "manual": 0.65, "unknown": 0.45}.get(self.provenance, 0.45)
        return max(0.0, base - self.reliability_penalty)


@dataclass
class ParsedRecord:
    """Unified record schema for all source types."""
    source: SourceName
    record_type: Optional[NodeType] = None
    case_id: Optional[str] = None
    reference_ids: Dict[str, str] = field(default_factory=dict)
    amount_paise: int = 0
    direction: str = "credit"
    timestamp: Any = 0
    metadata: Dict[str, Any] = field(default_factory=dict)
    reliability: float = 1.0
    provenance_violation: bool = False
    # Compatibility fields used by older fixtures and resilience tests.
    node_type: Optional[NodeType] = None
    order_id: Optional[str] = None
    reference_id: Optional[str] = None
    content_hash: Optional[str] = None
    occurred_at: Any = None
    received_at: Any = None
    processed_at: Any = None

    def __post_init__(self):
        if self.record_type is None:
            self.record_type = self.node_type
        if self.node_type is None:
            self.node_type = self.record_type
        if self.case_id is None:
            self.case_id = self.order_id
        if self.order_id is None:
            self.order_id = self.case_id
        if not self.reference_ids and self.reference_id:
            self.reference_ids = {"reference_id": self.reference_id}
        if self.reference_id is None and self.reference_ids:
            self.reference_id = next(iter(self.reference_ids.values()))
        if self.occurred_at is None:
            self.occurred_at = self.timestamp
        if self.received_at is None:
            self.received_at = self.timestamp
        if self.processed_at is None:
            self.processed_at = self.timestamp

    @property
    def source_type(self) -> SourceName:
        return self.source

    @property
    def record_id(self) -> str:
        return next(iter(self.reference_ids.values()), "")

    @property
    def provenance_valid(self) -> bool:
        return bool(
            self.occurred_at <= self.received_at <= self.processed_at
        )


def check_provenance(
    occurred_at: Optional[int],
    received_at: Optional[int] = None,
    processed_at: Optional[int] = None,
) -> float:
    """Return a reliability penalty for timestamp order violations."""
    if isinstance(occurred_at, ParsedRecord):
        record = occurred_at
        occurred_at, received_at, processed_at = (
            record.occurred_at, record.received_at, record.processed_at
        )
    if not all([occurred_at, received_at, processed_at]):
        return 0.0
    tolerance = PROVENANCE_SKEW_TOLERANCE_SECONDS
    if hasattr(received_at, "tzinfo"):
        from datetime import timedelta
        tolerance = timedelta(seconds=tolerance)
    if occurred_at > received_at:
        return PROVENANCE_RELIABILITY_PENALTY
    if received_at > processed_at:
        return PROVENANCE_RELIABILITY_PENALTY
    return 0.0


def check_provenance_skew(occurred_at: int, received_at: int, processed_at: int) -> float:
    """Compatibility alias for the provenance checker."""
    return check_provenance(occurred_at, received_at, processed_at)


def validate_record(payload: dict[str, Any]) -> tuple[Record, float]:
    """Validate shape while penalizing weak provenance instead of rejecting it."""
    required = {"order_id", "amount"}
    missing = required - payload.keys()
    if missing:
        raise ValueError(f"missing required fields: {sorted(missing)}")
    record = Record(**{key: value for key, value in payload.items() if key in Record.__dataclass_fields__})
    return record, record.reliability


def build_parsed_record(node: dict[str, Any], source: SourceName) -> ParsedRecord:
    """Build a normalized record from a generated lifecycle node."""
    raw_type = node.get("node_type", node.get("type", node.get("kind", "order")))
    try:
        record_type = NodeType(raw_type)
    except ValueError:
        record_type = NodeType.ORDER

    reference_ids = {
        key: str(node[key])
        for key in ("order_id", "payment_id", "refund_id", "settlement_ref")
        if node.get(key) is not None
    }
    timestamp = node.get("timestamp", node.get("created_at", 0))
    if isinstance(timestamp, str):
        # Preserve business-event time for the matcher and SLA checks.  The old
        # implementation replaced every ISO timestamp with 0, which made a
        # time-aware reconciliation impossible after ingestion.
        from datetime import datetime
        try:
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            timestamp = 0

    return ParsedRecord(
        source=source,
        record_type=record_type,
        case_id=node.get("case_id", node.get("order_id")),
        reference_ids=reference_ids,
        amount_paise=int(node.get("amount_paise", round(float(node.get("amount", 0)) * 100))),
        direction=node.get("direction", "credit"),
        timestamp=timestamp,
        metadata=dict(node.get("metadata", {})),
        reliability=float(node.get("reliability", 1.0)),
        provenance_violation=False,
        content_hash=node.get("content_hash"),
        occurred_at=node.get("occurred_at", timestamp),
        received_at=node.get("received_at", timestamp),
        processed_at=node.get("processed_at", timestamp),
    )
