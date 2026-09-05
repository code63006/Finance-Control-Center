"""
Tests for the synthetic generator — asserts holdout properties programmatically.
"""
import pytest
import json
import os


def _load(path):
    if not os.path.exists(path):
        pytest.skip(f"{path} not found — run scenario_builder.py first")
    with open(path) as f:
        return json.load(f)


class TestGeneratorProperties:
    def test_dev_batch_has_records(self):
        dev = _load("data/dev_batch.json")
        assert len(dev) >= 50, f"dev_batch has {len(dev)} records, expected >= 50"

    def test_holdout_batch_has_records(self):
        holdout = _load("data/holdout_batch.json")
        assert len(holdout) >= 30, f"holdout_batch has {len(holdout)} records, expected >= 30"

    def test_holdout_has_unseen_combo(self):
        """At least one holdout case with injection_count >= 2."""
        holdout = _load("data/holdout_batch.json")
        combos = [
            c for c in holdout
            if c.get("ground_truth", {}).get("injection_count", 0) >= 2
        ]
        assert len(combos) >= 1, "Holdout missing unseen-combo case"

    def test_holdout_has_near_threshold_inside(self):
        """At least one holdout case with fuzzy_position == 'inside_gate'."""
        holdout = _load("data/holdout_batch.json")
        inside = [
            c for c in holdout
            if c.get("ground_truth", {}).get("fuzzy_position") == "inside_gate"
        ]
        assert len(inside) >= 1, "Holdout missing near-threshold (inside) case"

    def test_holdout_has_near_threshold_outside(self):
        """At least one holdout case with fuzzy_position == 'outside_gate'."""
        holdout = _load("data/holdout_batch.json")
        outside = [
            c for c in holdout
            if c.get("ground_truth", {}).get("fuzzy_position") == "outside_gate"
        ]
        assert len(outside) >= 1, "Holdout missing near-threshold (outside) case"

    def test_holdout_has_insufficient_evidence(self):
        """At least one holdout case with expected_terminal_outcome == INSUFFICIENT_EVIDENCE."""
        holdout = _load("data/holdout_batch.json")
        ie = [
            c for c in holdout
            if c.get("ground_truth", {}).get("expected_terminal_outcome") == "INSUFFICIENT_EVIDENCE"
        ]
        assert len(ie) >= 1, "Holdout missing INSUFFICIENT_EVIDENCE case"

    def test_holdout_has_unresolved_ambiguity(self):
        """At least one holdout case with expected_terminal_outcome == UNRESOLVED_AMBIGUITY."""
        holdout = _load("data/holdout_batch.json")
        ua = [
            c for c in holdout
            if c.get("ground_truth", {}).get("expected_terminal_outcome") == "UNRESOLVED_AMBIGUITY"
        ]
        assert len(ua) >= 1, "Holdout missing UNRESOLVED_AMBIGUITY case"

    def test_all_cases_have_ground_truth(self):
        """Every case must have a ground_truth dict with injected_oc."""
        for batch_name in ["dev_batch.json", "holdout_batch.json"]:
            cases = _load(f"data/{batch_name}")
            for c in cases:
                gt = c.get("ground_truth", {})
                assert "injected_oc" in gt, (
                    f"Case {c.get('order_id', '?')} in {batch_name} missing injected_oc"
                )

    def test_clean_cases_represented(self):
        """Dev batch should have at least some clean (NO_ISSUE) cases."""
        dev = _load("data/dev_batch.json")
        clean = [
            c for c in dev
            if c.get("ground_truth", {}).get("injected_oc") == "NO_ISSUE"
        ]
        assert len(clean) >= 5, f"Only {len(clean)} clean cases in dev"

    def test_all_oc_types_in_dev(self):
        """Dev batch should represent all major OC types."""
        dev = _load("data/dev_batch.json")
        ocs = {c.get("ground_truth", {}).get("injected_oc") for c in dev}
        expected = {
            "NO_ISSUE", "missing_fee_entry", "duplicate_webhook_payment",
            "wrong_tax_rate", "provenance_timestamp_skew", "amount_rounding_drift",
            "late_settlement", "split_settlement_misattribution",
            "source_conflict_same_fact", "orphaned_refund",
        }
        missing = expected - ocs
        assert not missing, f"Missing OC types in dev: {missing}"
