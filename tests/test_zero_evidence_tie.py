"""
Critical tests for the forced-answer bug.
test_zero_evidence_tie_is_insufficient — THE key regression guardrail.
"""
import pytest
from src.constants import Outcome, FLOOR_THRESHOLD, TIE_MARGIN
from src.agent.evidence import EvidenceType, CaseEvidence
from src.agent.rch_engine import diagnose


class TestZeroEvidenceBug:
    """Test that zero-evidence ties are INSUFFICIENT_EVIDENCE, not AMBIGUOUS."""

    def test_zero_evidence_tie_is_insufficient(self):
        """Zero evidence must not be forced into an ambiguity result."""
        evidence = CaseEvidence(case_id="test-zero-evidence")
        outcome = diagnose(evidence)
        assert outcome.status == "INSUFFICIENT_EVIDENCE", (
            f"Zero-evidence case should be INSUFFICIENT_EVIDENCE, got {outcome.status}. "
            f"This is the forced-answer bug. FLOOR_THRESHOLD={FLOOR_THRESHOLD}, "
            f"TIE_MARGIN={TIE_MARGIN}. Check that FLOOR_THRESHOLD > 0."
        )

    def test_floor_threshold_positive(self):
        assert FLOOR_THRESHOLD > 0, (
            f"FLOOR_THRESHOLD={FLOOR_THRESHOLD} must be > 0. "
            "Otherwise zero-evidence ties slip through to AMBIGUOUS."
        )

    def test_floor_below_confirm(self):
        from src.constants import CONFIRM_THRESHOLD
        assert FLOOR_THRESHOLD < CONFIRM_THRESHOLD, (
            f"FLOOR_THRESHOLD={FLOOR_THRESHOLD} must be < CONFIRM_THRESHOLD={CONFIRM_THRESHOLD}"
        )
        assert (CONFIRM_THRESHOLD - FLOOR_THRESHOLD) > TIE_MARGIN, (
            f"Gap between FLOOR_THRESHOLD and CONFIRM_THRESHOLD ({CONFIRM_THRESHOLD - FLOOR_THRESHOLD}) "
            f"must exceed TIE_MARGIN ({TIE_MARGIN}) to preserve PLAUSIBLE_UNCONFIRMED band"
        )

    def test_tie_margin_positive(self):
        assert TIE_MARGIN > 0, f"TIE_MARGIN={TIE_MARGIN} must be > 0"
