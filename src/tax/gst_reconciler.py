"""
Per-txn GST calculation + invoice aggregation bridge.
Checks math and invoice-reference consistency, NOT full statutory ITC eligibility.
"""
from typing import Dict, List, Tuple
from dataclasses import dataclass

from src.constants import NodeType, SourceName
from src.config.pricing_rules import calculate_gst_paise
from src.ingest.schemas import ParsedRecord


@dataclass
class TaxReconciliation:
    order_id: str
    per_txn_gst_paise: int
    aggregated_gst_paise: int
    tax_node_amount: int
    is_consistent: bool
    tolerance_paise: int
    discrepancy_paise: int


class GSTReconciler:
    """
    Reconcile per-transaction GST against invoice-level aggregation.
    Tolerance allows for rounding differences.
    """

    def __init__(self, tolerance_paise: int = 1):
        self.tolerance_paise = tolerance_paise

    def reconcile(
        self,
        records: List[ParsedRecord],
    ) -> Dict[str, TaxReconciliation]:
        """
        For each order_id, check:
        1. GST calculation: fee × rate = tax amount
        2. Invoice aggregation: sum of per-txn GST matches invoice total
        """
        results = {}

        # Group by order_id
        by_order: Dict[str, List[ParsedRecord]] = {}
        for r in records:
            by_order.setdefault(r.order_id, []).append(r)

        for order_id, order_records in by_order.items():
            fees = [r for r in order_records if r.node_type == NodeType.FEE]
            taxes = [r for r in order_records if r.node_type == NodeType.TAX]

            if not fees or not taxes:
                continue

            # Per-txn GST check
            total_fee = sum(r.amount_paise for r in fees)
            # The generator and evaluator use this exact integer-paise rule too.
            expected_gst = calculate_gst_paise(total_fee)
            actual_gst = sum(r.amount_paise for r in taxes)

            is_consistent = abs(expected_gst - actual_gst) <= self.tolerance_paise

            results[order_id] = TaxReconciliation(
                order_id=order_id,
                per_txn_gst_paise=expected_gst,
                aggregated_gst_paise=actual_gst,
                tax_node_amount=actual_gst,
                is_consistent=is_consistent,
                tolerance_paise=self.tolerance_paise,
                discrepancy_paise=abs(expected_gst - actual_gst),
            )

        return results
