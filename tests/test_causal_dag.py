"""
Tests for the branching 8-node lifecycle graph matcher.
"""
import pytest
from src.constants import NodeType, MatchStatus
from src.ingest.schemas import ParsedRecord, SourceName
from src.matcher.graph_engine import LifecycleGraphMatcher, CaseGraph


def make_record(
    node_type: NodeType,
    case_id: str,
    amount_paise: int = 10000,
    timestamp: int = 1000000,
    reference_ids: dict = None,
    direction: str = "credit",
) -> ParsedRecord:
    """Helper to create test records."""
    return ParsedRecord(
        source=SourceName.RAZORPAY_RECON,
        record_type=node_type,
        case_id=case_id,
        reference_ids=reference_ids or {},
        amount_paise=amount_paise,
        direction=direction,
        timestamp=timestamp,
    )


class TestGraphMatching:
    def test_clean_case_matches(self):
        """A clean case should match all nodes correctly."""
        case_id = "TEST-001"
        
        # Create clean records
        order = make_record(NodeType.ORDER, case_id, reference_ids={"order_id": "ORD-001"})
        payment = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-001", "payment_id": "PAY-001"},
            direction="credit",
        )
        fee = make_record(
            NodeType.FEE, case_id, amount_paise=200,
            reference_ids={"payment_id": "PAY-001"},
            direction="debit",
        )
        tax = make_record(
            NodeType.TAX, case_id, amount_paise=36,
            reference_ids={"payment_id": "PAY-001"},
            direction="debit",
        )
        settlement = make_record(
            NodeType.SETTLEMENT, case_id, amount_paise=9764,
            reference_ids={"settlement_ref": "STL-001"},
            direction="debit",
        )
        bank = make_record(
            NodeType.BANK, case_id, amount_paise=9764,
            reference_ids={"settlement_ref": "STL-001"},
            direction="credit",
        )
        
        records = [order, payment, fee, tax, settlement, bank]
        
        matcher = LifecycleGraphMatcher()
        graphs, exceptions = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # All nodes should be matched
        for node_type in [NodeType.ORDER, NodeType.PAYMENT, NodeType.FEE,
                         NodeType.TAX, NodeType.SETTLEMENT, NodeType.BANK]:
            assert graph.nodes[node_type].matched
            assert graph.nodes[node_type].status == MatchStatus.RESOLVED
    
    def test_duplicate_webhook_ambiguity(self):
        """Duplicate webhooks should result in AMBIGUOUS_MATCH."""
        case_id = "TEST-002"
        
        order = make_record(NodeType.ORDER, case_id, reference_ids={"order_id": "ORD-002"})
        
        # Two identical payments (duplicate webhooks)
        payment1 = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-002", "payment_id": "PAY-002A"},
            direction="credit",
        )
        payment2 = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-002", "payment_id": "PAY-002B"},
            direction="credit",
        )
        
        records = [order, payment1, payment2]
        
        matcher = LifecycleGraphMatcher()
        graphs, exceptions = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # Payment should be ambiguous
        payment_node = graph.nodes[NodeType.PAYMENT]
        assert payment_node.status == MatchStatus.AMBIGUOUS_MATCH
        assert payment_node.ambiguous_candidates is not None
        assert len(payment_node.ambiguous_candidates) == 2
    
    def test_orphaned_refund_unmatched(self):
        """Orphaned refund (no matching payment) should be UNMATCHED."""
        case_id = "TEST-003"
        
        order = make_record(NodeType.ORDER, case_id, reference_ids={"order_id": "ORD-003"})
        payment = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-003", "payment_id": "PAY-003"},
            direction="credit",
        )
        
        # Orphaned refund with wrong payment_id
        refund = make_record(
            NodeType.REFUND, case_id,
            reference_ids={"payment_id": "PAY-NONEXISTENT"},
            direction="debit",
        )
        
        records = [order, payment, refund]
        
        matcher = LifecycleGraphMatcher()
        graphs, exceptions = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # Refund should be unmatched
        refund_node = graph.nodes[NodeType.REFUND]
        assert refund_node.status == MatchStatus.UNMATCHED
        assert not refund_node.matched
    
    def test_split_settlement_partial_matching(self):
        """Split settlement with misattribution should match correct entries."""
        case_id = "TEST-004"
        
        order = make_record(NodeType.ORDER, case_id, reference_ids={"order_id": "ORD-004"})
        payment = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-004", "payment_id": "PAY-004"},
            direction="credit",
        )
        settlement = make_record(
            NodeType.SETTLEMENT, case_id,
            reference_ids={"settlement_ref": "STL-004"},
            direction="debit",
        )
        
        # Two bank entries: one correct, one misattributed
        bank_correct = make_record(
            NodeType.BANK, case_id, amount_paise=5000,
            reference_ids={"settlement_ref": "STL-004", "entry_id": "BANK-001"},
            direction="credit",
        )
        bank_wrong = make_record(
            NodeType.BANK, case_id, amount_paise=5000,
            reference_ids={"settlement_ref": "STL-FAKE", "entry_id": "BANK-002"},
            direction="credit",
        )
        
        records = [order, payment, settlement, bank_correct, bank_wrong]
        
        matcher = LifecycleGraphMatcher()
        graphs, exceptions = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # Settlement should match one bank entry (exact match)
        bank_node = graph.nodes[NodeType.BANK]
        assert bank_node.matched
        assert bank_node.status == MatchStatus.RESOLVED
        
        # The wrong entry should remain unmatched
        # Check exceptions contain the wrong entry
        assert case_id in exceptions
        unmatched_bank = [r for r in exceptions[case_id] if r.record_type == NodeType.BANK]
        assert len(unmatched_bank) == 1
        assert unmatched_bank[0].reference_ids.get("settlement_ref") == "STL-FAKE"
    
    def test_branching_refund_independent_of_fee_tax(self):
        """Refund should branch independently of Fee/Tax."""
        case_id = "TEST-005"
        
        order = make_record(NodeType.ORDER, case_id, reference_ids={"order_id": "ORD-005"})
        payment = make_record(
            NodeType.PAYMENT, case_id,
            reference_ids={"order_id": "ORD-005", "payment_id": "PAY-005"},
            direction="credit",
        )
        fee = make_record(
            NodeType.FEE, case_id,
            reference_ids={"payment_id": "PAY-005"},
            direction="debit",
        )
        refund = make_record(
            NodeType.REFUND, case_id,
            reference_ids={"payment_id": "PAY-005"},
            direction="debit",
        )
        
        records = [order, payment, fee, refund]
        
        matcher = LifecycleGraphMatcher()
        graphs, exceptions = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # Both fee and refund should be matched independently
        assert graph.nodes[NodeType.FEE].matched
        assert graph.nodes[NodeType.REFUND].matched
        assert graph.nodes[NodeType.FEE].status == MatchStatus.RESOLVED
        assert graph.nodes[NodeType.REFUND].status == MatchStatus.RESOLVED
