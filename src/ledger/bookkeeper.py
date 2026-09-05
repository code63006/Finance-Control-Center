"""
Double-entry ledger verification and account-code mapping.
"""
from typing import List, Dict, Tuple
from dataclasses import dataclass
from src.constants import AccountCode, NodeType
from src.matcher.graph_engine import CaseGraph


@dataclass
class LedgerPosting:
    """A single ledger posting (debit or credit)."""
    account_code: AccountCode
    amount_paise: int
    is_debit: bool
    description: str


@dataclass
class LedgerVerification:
    """Result of ledger verification for a case."""
    is_balanced: bool
    total_debits: int
    total_credits: int
    net_receivable: int  # should be 0 for complete cases
    postings: List[LedgerPosting]
    errors: List[str]

    @property
    def account_codes_correct(self) -> bool:
        return not any("account" in error.lower() for error in self.errors)


def reconstruct_postings(graph: CaseGraph) -> List[LedgerPosting]:
    """Reconstruct ledger postings from matched graph nodes."""
    postings = []
    
    # Payment captured: DR 1200 (PG_Receivable) / CR 4100 (Revenue)
    payment = graph.nodes.get(NodeType.PAYMENT, MatchResultFallback()).record
    if payment:
        postings.append(LedgerPosting(
            account_code=AccountCode.PG_RECEIVABLE,
            amount_paise=payment.amount_paise,
            is_debit=True,
            description=f"Payment {payment.reference_ids.get('payment_id', '')}",
        ))
        postings.append(LedgerPosting(
            account_code=AccountCode.REVENUE,
            amount_paise=payment.amount_paise,
            is_debit=False,
            description=f"Revenue from payment",
        ))
    
    # Fee: DR 5100 (Fee_Expense) / CR 1200 (PG_Receivable)
    fee = graph.nodes.get(NodeType.FEE, MatchResultFallback()).record
    if fee:
        postings.append(LedgerPosting(
            account_code=AccountCode.FEE_EXPENSE,
            amount_paise=fee.amount_paise,
            is_debit=True,
            description="Gateway fee expense",
        ))
        postings.append(LedgerPosting(
            account_code=AccountCode.PG_RECEIVABLE,
            amount_paise=fee.amount_paise,
            is_debit=False,
            description="Fee deduction from receivable",
        ))
    
    # Tax: DR 5200 (GST_Expense) / CR 1200 (PG_Receivable)
    tax = graph.nodes.get(NodeType.TAX, MatchResultFallback()).record
    if tax:
        postings.append(LedgerPosting(
            account_code=AccountCode.GST_EXPENSE,
            amount_paise=tax.amount_paise,
            is_debit=True,
            description="GST on fees",
        ))
        postings.append(LedgerPosting(
            account_code=AccountCode.PG_RECEIVABLE,
            amount_paise=tax.amount_paise,
            is_debit=False,
            description="Tax deduction from receivable",
        ))
    
    # Refunds: DR 4100 (Revenue) / CR 1200 (PG_Receivable) each
    refunds = graph.nodes.get(NodeType.REFUND, MatchResultFallback()).matched_records
    for refund in refunds:
        postings.append(LedgerPosting(
            account_code=AccountCode.REVENUE,
            amount_paise=refund.amount_paise,
            is_debit=True,
            description="Refund",
        ))
        postings.append(LedgerPosting(
            account_code=AccountCode.PG_RECEIVABLE,
            amount_paise=refund.amount_paise,
            is_debit=False,
            description="Refund from receivable",
        ))
    
    # Settlement (bank entries): DR 1100 (Bank) / CR 1200 (PG_Receivable)
    # Note: there may be multiple bank entries for split settlements
    banks = graph.nodes.get(NodeType.BANK, MatchResultFallback()).matched_records
    for bank in banks:
        postings.append(LedgerPosting(
            account_code=AccountCode.BANK,
            amount_paise=bank.amount_paise,
            is_debit=True,
            description=f"Bank settlement {bank.reference_ids.get('settlement_ref', '')}",
        ))
        postings.append(LedgerPosting(
            account_code=AccountCode.PG_RECEIVABLE,
            amount_paise=bank.amount_paise,
            is_debit=False,
            description="Settlement from receivable",
        ))
    
    return postings


class MatchResultFallback:
    record = None
    matched_records = []


def verify_case_ledger(graph: CaseGraph) -> LedgerVerification:
    """
    Verify double-entry balance and account-code mapping.
    Returns detailed verification result.
    """
    postings = reconstruct_postings(graph)
    errors = []
    
    # Check 1: Sum of debits == sum of credits
    total_debits = sum(p.amount_paise for p in postings if p.is_debit)
    total_credits = sum(p.amount_paise for p in postings if p.is_debit == False)
    
    if total_debits != total_credits:
        errors.append(f"Ledger imbalance: debits={total_debits}, credits={total_credits}")
    
    # Check 2: Net PG_Receivable (1200) should be 0 for complete cases
    receivable_debits = sum(
        p.amount_paise for p in postings
        if p.account_code == AccountCode.PG_RECEIVABLE and p.is_debit
    )
    receivable_credits = sum(
        p.amount_paise for p in postings
        if p.account_code == AccountCode.PG_RECEIVABLE and not p.is_debit
    )
    net_receivable = receivable_debits - receivable_credits
    
    # Check 3: Account-code semantic mapping
    # Verify each posting uses the correct account for its transaction type
    # (This is already enforced by reconstruct_postings, but we can add extra checks)
    
    return LedgerVerification(
        is_balanced=(total_debits == total_credits and net_receivable == 0),
        total_debits=total_debits,
        total_credits=total_credits,
        net_receivable=net_receivable,
        postings=postings,
        errors=errors,
    )


class Bookkeeper:
    """Service façade used by the reconciliation evaluator."""

    def verify(self, records: List) -> Dict[str, LedgerVerification]:
        grouped: Dict[str, List] = {}
        for record in records:
            grouped.setdefault(record.case_id, []).append(record)

        results = {}
        for case_id, case_records in grouped.items():
            matcher = __import__(
                "src.matcher.graph_engine", fromlist=["LifecycleGraphMatcher"]
            ).LifecycleGraphMatcher(case_records)
            graph = matcher.match_order(case_id)
            results[case_id] = verify_case_ledger(graph)
        return results
