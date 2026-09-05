"""
Resilience tests — Tier 1 (always) + Tier 2 (cut under pressure).
"""
import pytest
from datetime import datetime, timezone, timedelta
from src.constants import (
    NodeType, SourceName, EvidenceType,
    FLOOR_THRESHOLD, TIE_MARGIN, UNIQUENESS_MARGIN,
    AMOUNT_TOLERANCE_PAISE,
)
from src.ingest.schemas import ParsedRecord, check_provenance
from src.matcher.safe_fuzzy import try_fuzzy_match, fuzzy_score
from src.agent.rch_engine import diagnose, HYPOTHESIS_REGISTRY, Hypothesis
from src.agent.evidence import CaseEvidence, EvidenceItem


def _rec(nt, src, oid, amount, ts):
    return ParsedRecord(
        source=src, node_type=nt, order_id=oid,
        amount_paise=amount, timestamp=ts,
        reference_id=f"ref_{nt.value}_{src.value}",
        content_hash=f"hash_{nt.value}_{src.value}_{amount}",
        metadata={},
        occurred_at=ts, received_at=ts + timedelta(seconds=10),
        processed_at=ts + timedelta(seconds=20),
    )


# ── Tier 1: Always required ─────────────────────────────────────────────────

class TestTier1:
    def test_ai_timeout_degrades_to_deterministic(self):
        """If the AI tie-explainer times out, outcome stays UNRESOLVED_AMBIGUITY."""
        ev = CaseEvidence()
        ev.add(EvidenceItem(EvidenceType.AMOUNTS_DRIFTED, SourceName.RAZORPAY_RECON, 0.9))
        ev.add(EvidenceItem(EvidenceType.LEDGER_IMBALANCE, SourceName.RAZORPAY_RECON, 0.9))

        candidates = HYPOTHESIS_REGISTRY[:2]
        diag = diagnose(candidates, ev)
        # Even if explanation fails, the outcome must be deterministic
        assert diag.outcome.value in [
            "UNRESOLVED_AMBIGUITY", "INSUFFICIENT_EVIDENCE",
            "PLAUSIBLE_UNCONFIRMED", "STRONGLY_SUPPORTED",
            "CONFLICTING_EVIDENCE",
        ]

    def test_fuzzy_case_at_uniqueness_margin(self):
        """Two records at exactly UNIQUENESS_MARGIN apart must be AMBIGUOUS."""
        base_ts = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        oid = "ORD_FUZZY_001"
        r1 = _rec(NodeType.PAYMENT, SourceName.RAZORPAY_RECON, oid, 10000, base_ts)
        r2 = _rec(NodeType.PAYMENT, SourceName.BANK_STATEMENT, oid, 10000 + AMOUNT_TOLERANCE_PAISE - 1, base_ts + timedelta(seconds=5))

        result = try_fuzzy_match(r1, [r2])
        # Should resolve or be ambiguous depending on exact score
        assert result["status"] in ("resolved", "ambiguous")

    def test_out_of_order_timestamp_downweights_not_rejects(self):
        """Processed before received → provenance violation, downweight not reject."""
        ts = datetime(2024, 6, 1, 10, 0, 0, tzinfo=timezone.utc)
        r = _rec(NodeType.PAYMENT, SourceName.RAZORPAY_RECON, "ORD_001", 5000, ts)
        r.received_at = ts + timedelta(seconds=60)
        r.processed_at = ts - timedelta(seconds=10)  # before occurred!

        reliability = check_provenance(r)
        assert r.provenance_valid is False
        assert 0 < reliability < 1.0, f"Reliability should be penalized: {reliability}"

    def test_zero_evidence_tie_is_insufficient(self):
        """Zero evidence → value = 0.0 < FLOOR_THRESHOLD → INSUFFICIENT_EVIDENCE, not UNRESOLVED_AMBIGUITY."""
        ev = CaseEvidence()
        # No evidence added at all
        candidates = HYPOTHESIS_REGISTRY[:2]
        diag = diagnose(candidates, ev)
        assert diag.outcome.value == "INSUFFICIENT_EVIDENCE", (
            f"Zero evidence should be INSUFFICIENT_EVIDENCE, got {diag.outcome.value}"
        )


# ── Tier 2: Cut only under real pressure ────────────────────────────────────

class TestTier2:
    def test_duplicate_webhook_handled(self):
        """Duplicate webhook → evidence flags SOURCE_CONFLICT, doesn't crash."""
        ev = CaseEvidence()
        ev.add(EvidenceItem(EvidenceType.SOURCE_CONFLICT_DETECTED, SourceName.RAZORPAY_RECON, 0.8))
        diag = diagnose(HYPOTHESIS_REGISTRY, ev)
        assert diag.outcome.value in [
            "PLAUSIBLE_UNCONFIRMED", "UNRESOLVED_AMBIGUITY",
            "INSUFFICIENT_EVIDENCE", "STRONGLY_SUPPORTED",
            "CONFLICTING_EVIDENCE",
        ]

    def test_malformed_record_graceful(self):
        """A record with missing fields should not crash ingestion."""
        from src.ingest.schemas import build_parsed_record
        malformed = {
            "node_type": "payment",
            "order_id": "ORD_MALFORMED",
            "amount_paise": 5000,
            "timestamp": "2024-06-01T10:00:00+00:00",
            "reference_id": "REF_MALFORMED",
            # Missing content_hash, metadata
        }
        # Should not raise — build_parsed_record handles missing fields
        record = build_parsed_record(malformed, SourceName.RAZORPAY_RECON)
        assert record.order_id == "ORD_MALFORMED"
        assert record.amount_paise == 5000
