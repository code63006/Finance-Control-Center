"""
Tests for ledger balance and account-code mapping invariants.
"""
import pytest
from src.constants import AccountCode, NodeType
from src.ingest.schemas import ParsedRecord, SourceName
from src.matcher.graph_engine import LifecycleGraphMatcher
from src.ledger.bookkeeper import verify_case_ledger, reconstruct_postings


def make_clean_case_records(case_id: str) -> list:
    """Create records for a clean case that should balance."""
    order = ParsedRecord(
        source=SourceName.ORDERS_DB,
        record_type=NodeType.ORDER,
        case_id=case_id,
        reference_ids={"order_id": "ORD-100"},
        amount_paise=10000,
        direction="credit",
        timestamp=1000000,
    )
    payment = ParsedRecord(
        source=SourceName.RAZORPAY_RECON,
        record_type=NodeType.PAYMENT,
        case_id=case_id,
        reference_ids={"order_id": "ORD-100", "payment_id": "PAY-100"},
        amount_paise=10000,
        direction="credit",
        timestamp=1000000,
    )
    fee = ParsedRecord(
        source=SourceName.RAZORPAY_RECON,
        record_type=NodeType.FEE,
        case_id=case_id,
        reference_ids={"payment_id": "PAY-100"},
        amount_paise=200,  # 2% MDR
        direction="debit",
        timestamp=1000000,
    )
    tax = ParsedRecord(
        source=SourceName.RAZORPAY_RECON,
        record_type=NodeType.TAX,
        case_id=case_id,
        reference_ids={"payment_id": "PAY-100"},
        amount_paise=36,  # 18% GST on fee
        direction="debit",
        timestamp=1000000,
    )
    settlement = ParsedRecord(
        source=SourceName.RAZORPAY_RECON,
        record_type=NodeType.SETTLEMENT,
        case_id=case_id,
        reference_ids={"settlement_ref": "STL-100"},
        amount_paise=9764,  # 10000 - 200 - 36
        direction="debit",
        timestamp=1000000,
    )
    bank = ParsedRecord(
        source=SourceName.BANK_STATEMENT,
        record_type=NodeType.BANK,
        case_id=case_id,
        reference_ids={"settlement_ref": "STL-100"},
        amount_paise=9764,
        direction="credit",
        timestamp=1000000,
    )
    return [order, payment, fee, tax, settlement, bank]


class TestLedgerInvariants:
    def test_ledger_balances_for_clean_case(self):
        """Sum of debits should equal sum of credits for a clean case."""
        case_id = "LEDGER-001"
        records = make_clean_case_records(case_id)
        
        matcher = LifecycleGraphMatcher()
        graphs, _ = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        verification = verify_case_ledger(graph)
        
        assert verification.is_balanced
        assert verification.total_debits == verification.total_credits
        assert verification.net_receivable == 0
    
    def test_account_code_mapping(self):
        """Each transaction type should map to the correct account codes."""
        case_id = "LEDGER-002"
        records = make_clean_case_records(case_id)
        
        matcher = LifecycleGraphMatcher()
        graphs, _ = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        postings = reconstruct_postings(graph)
        
        # Check account codes for each posting
        for posting in postings:
            if posting.description.startswith("Payment"):
                assert posting.account_code == AccountCode.PG_RECEIVABLE
                assert posting.is_debit
            elif posting.description == "Revenue from payment":
                assert posting.account_code == AccountCode.REVENUE
                assert not posting.is_debit
            elif posting.description == "Payment gateway fee":
                assert posting.account_code == AccountCode.FEE_EXPENSE
                assert posting.is_debit
            elif posting.description == "Fee deduction from receivable":
                assert posting.account_code == AccountCode.PG_RECEIVABLE
                assert not posting.is_debit
            elif posting.description == "GST on fees":
                assert posting.account_code == AccountCode.GST_EXPENSE
                assert posting.is_debit
            elif posting.description == "Tax deduction from receivable":
                assert posting.account_code == AccountCode.PG_RECEIVABLE
                assert not posting.is_debit
            elif posting.description.startswith("Bank settlement"):
                assert posting.account_code == AccountCode.BANK
                assert posting.is_debit
            elif posting.description == "Settlement from receivable":
                assert posting.account_code == AccountCode.PG_RECEIVABLE
                assert not posting.is_debit
    
    def test_pg_receivable_net_zero(self):
        """PG_Receivable (1200) should net to zero for complete cases."""
        case_id = "LEDGER-003"
        records = make_clean_case_records(case_id)
        
        matcher = LifecycleGraphMatcher()
        graphs, _ = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        verification = verify_case_ledger(graph)
        
        assert verification.net_receivable == 0
    
    def test_split_settlement_postings(self):
        """Split settlement should create multiple bank postings that sum correctly."""
        case_id = "LEDGER-004"
        
        # Create case with split settlement
        order = ParsedRecord(
            source=SourceName.ORDERS_DB,
            record_type=NodeType.ORDER,
            case_id=case_id,
            reference_ids={"order_id": "ORD-104"},
            amount_paise=10000,
            direction="credit",
            timestamp=1000000,
        )
        payment = ParsedRecord(
            source=SourceName.RAZORPAY_RECON,
            record_type=NodeType.PAYMENT,
            case_id=case_id,
            reference_ids={"order_id": "ORD-104", "payment_id": "PAY-104"},
            amount_paise=10000,
            direction="credit",
            timestamp=1000000,
        )
        fee = ParsedRecord(
            source=SourceName.RAZORPAY_RECON,
            record_type=NodeType.FEE,
            case_id=case_id,
            reference_ids={"payment_id": "PAY-104"},
            amount_paise=200,
            direction="debit",
            timestamp=1000000,
        )
        tax = ParsedRecord(
            source=SourceName.RAZORPAY_RECON,
            record_type=NodeType.TAX,
            case_id=case_id,
            reference_ids={"payment_id": "PAY-104"},
            amount_paise=36,
            direction="debit",
            timestamp=1000000,
        )
        settlement = ParsedRecord(
            source=SourceName.RAZORPAY_RECON,
            record_type=NodeType.SETTLEMENT,
            case_id=case_id,
            reference_ids={"settlement_ref": "STL-104"},
            amount_paise=9764,
            direction="debit",
            timestamp=1000000,
        )
        
        # Two bank entries (split settlement)
        bank1 = ParsedRecord(
            source=SourceName.BANK_STATEMENT,
            record_type=NodeType.BANK,
            case_id=case_id,
            reference_ids={"settlement_ref": "STL-104", "entry_id": "BANK-104A"},
            amount_paise=5000,
            direction="credit",
            timestamp=1000000,
        )
        bank2 = ParsedRecord(
            source=SourceName.BANK_STATEMENT,
            record_type=NodeType.BANK,
            case_id=case_id,
            reference_ids={"settlement_ref": "STL-104", "entry_id": "BANK-104B"},
            amount_paise=4764,
            direction="credit",
            timestamp=1000000,
        )
        
        records = [order, payment, fee, tax, settlement, bank1, bank2]
        
        matcher = LifecycleGraphMatcher()
        graphs, _ = matcher.match_all(records)
        
        assert case_id in graphs
        graph = graphs[case_id]
        
        # The matcher should have matched one bank entry to the node
        bank_node = graph.nodes[NodeType.BANK]
        assert bank_node.matched
        
        # Reconstruct postings
        postings = reconstruct_postings(graph)
        
        # Find bank postings
        bank_postings = [p for p in postings if p.account_code == AccountCode.BANK]
        
        # Every split bank credit must reach the books; dropping all but the
        # first entry hides a real cash movement and creates a false imbalance.
        assert len(bank_postings) == 2
        assert sum(posting.amount_paise for posting in bank_postings) == 9764
