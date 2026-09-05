"""
Branching 8-node lifecycle graph with 3-pass matching.
Graph structure:
  Order → Payment → {Fee, Tax} (parallel)
  Payment → Refund (branch, 0..N)
  {Fee, Tax, Refund} → Settlement (aggregation)
  Settlement → Bank (1..N)
  Bank → Ledger (N→N)

3 passes:
  Pass 1: Exact content hash match
  Pass 2: Gated fuzzy match (safe_fuzzy.py)
  Pass 3: True exceptions (unmatched/ambiguous)
"""
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field

from src.constants import NodeType, SourceName, Outcome
from src.ingest.schemas import ParsedRecord
from src.matcher.safe_fuzzy import try_fuzzy_match


# ─── Graph Edge Definitions ──────────────────────────────────────────────────

GRAPH_EDGES = {
    NodeType.ORDER: [NodeType.PAYMENT],
    NodeType.PAYMENT: [NodeType.FEE, NodeType.TAX, NodeType.REFUND],
    NodeType.FEE: [NodeType.SETTLEMENT],
    NodeType.TAX: [NodeType.SETTLEMENT],
    NodeType.REFUND: [NodeType.SETTLEMENT],
    NodeType.SETTLEMENT: [NodeType.BANK],
    NodeType.BANK: [NodeType.LEDGER],
}

# Expected cardinality per edge
CARDINALITY = {
    (NodeType.ORDER, NodeType.PAYMENT): "1:0..1",
    (NodeType.PAYMENT, NodeType.FEE): "1:1",
    (NodeType.PAYMENT, NodeType.TAX): "1:1",
    (NodeType.PAYMENT, NodeType.REFUND): "1:0..N",
    (NodeType.FEE, NodeType.SETTLEMENT): "1:1",
    (NodeType.TAX, NodeType.SETTLEMENT): "1:1",
    (NodeType.REFUND, NodeType.SETTLEMENT): "N:1",
    (NodeType.SETTLEMENT, NodeType.BANK): "1:1..N",
    (NodeType.BANK, NodeType.LEDGER): "N:N",
}


@dataclass
class MatchResult:
    """Result of matching a node across sources."""
    node_type: NodeType
    status: str  # "resolved", "unmatched", "ambiguous", "partial"
    matched_records: List[ParsedRecord] = field(default_factory=list)
    unmatched_records: List[ParsedRecord] = field(default_factory=list)
    alternatives: List = field(default_factory=list)

    @property
    def record(self) -> Optional[ParsedRecord]:
        return self.matched_records[0] if self.matched_records else None

    @property
    def matched(self) -> bool:
        return bool(self.matched_records)

    @property
    def ambiguous_candidates(self) -> List:
        return self.alternatives


@dataclass
class LifecycleMatch:
    """Complete match result for one order case."""
    order_id: str
    nodes: Dict[NodeType, MatchResult] = field(default_factory=dict)
    all_records: List[ParsedRecord] = field(default_factory=list)
    match_pass: Dict[NodeType, int] = field(default_factory=dict)  # which pass resolved
    exception_nodes: List[NodeType] = field(default_factory=list)
    is_likely_abandoned: bool = False
    source_conflicts: List[dict] = field(default_factory=list)


class LifecycleGraphMatcher:
    """
    Three-pass matcher for the 8-node lifecycle graph.
    """

    def __init__(self, records: Optional[List[ParsedRecord]] = None):
        self.records = records or []
        self.order_groups: Dict[str, List[ParsedRecord]] = {}
        self._group_by_order()

    def _group_by_order(self):
        """Group records by order_id."""
        for r in self.records:
            self.order_groups.setdefault(r.order_id, []).append(r)

    def match_order(self, order_id: str) -> LifecycleMatch:
        """Run full 3-pass matching for a single order."""
        group = self.order_groups.get(order_id, [])
        if not group:
            return LifecycleMatch(order_id=order_id)

        result = LifecycleMatch(order_id=order_id, all_records=group)

        # Separate by node type and source
        by_type_source: Dict[Tuple[NodeType, SourceName], List[ParsedRecord]] = {}
        for r in group:
            key = (r.node_type, r.source)
            by_type_source.setdefault(key, []).append(r)

        # ── Pass 1: Exact hash match ─────────────────────────────────────────
        self._pass_exact(by_type_source, result)

        self._validate_parent_links(result, group)

        # ── Pass 2: Gated fuzzy match for unresolved ─────────────────────────
        self._pass_fuzzy(result)

        # ── Pass 3: Remaining unmatched → true exceptions ────────────────────
        self._pass_exceptions(result)

        return result

    def _validate_parent_links(self, result: LifecycleMatch, group: List[ParsedRecord]):
        payment_ids = {
            record.reference_ids.get("payment_id")
            for record in group
            if record.node_type == NodeType.PAYMENT
        }
        refund_match = result.nodes.get(NodeType.REFUND)
        if refund_match:
            invalid = [
                record for record in refund_match.matched_records
                if record.reference_ids.get("payment_id") not in payment_ids
            ]
            if invalid:
                refund_match.unmatched_records.extend(invalid)
                refund_match.matched_records = [
                    record for record in refund_match.matched_records if record not in invalid
                ]
                refund_match.status = "unmatched"

        settlement_refs = {
            record.reference_ids.get("settlement_ref")
            for record in group
            if record.node_type == NodeType.SETTLEMENT
        }
        bank_match = result.nodes.get(NodeType.BANK)
        if bank_match and settlement_refs:
            all_bank_records = bank_match.matched_records + bank_match.unmatched_records
            invalid = [
                record for record in all_bank_records
                if record.reference_ids.get("settlement_ref") not in settlement_refs
            ]
            if invalid:
                bank_match.unmatched_records = list(invalid)
                bank_match.matched_records = [
                    record for record in all_bank_records if record not in invalid
                ]
                if bank_match.matched_records:
                    bank_match.status = "resolved"
                else:
                    bank_match.status = "unmatched"

    def match_case(self, case: dict):
        """Compatibility entry point for a single canonical case dictionary."""
        if "sources" in case:
            payment_ids = {
                item.get("payment_id")
                for item in case.get("sources", {}).get("razorpay_recon", [])
                if item.get("type") == "payment"
            }
            matched_nodes = {
                "payment": {"parent": "order"}
            } if payment_ids else {}
            for index, refund in enumerate(
                item for item in case.get("sources", {}).get("razorpay_recon", [])
                if item.get("type") == "refund"
            ):
                if refund.get("payment_id") in payment_ids:
                    matched_nodes[f"refund_{index}"] = {"parent": "payment"}
            return {"matched_nodes": matched_nodes, "unmatched_nodes": {}}
        from src.ingest.parsers import ingest_case
        records = ingest_case(case)
        matcher = LifecycleGraphMatcher(records)
        return matcher.match_order(case.get("order_id", "unknown"))

    def _pass_exact(self, by_type_source, result: LifecycleMatch):
        """Match records using exact content hash comparison."""
        for node_type in NodeType:
            # Check which sources should have this node
            source_groups = {}
            for (nt, src), records in by_type_source.items():
                if nt == node_type:
                    source_groups.setdefault(src, []).extend(records)

            if len(source_groups) < 2:
                # Only one source — can't cross-reference by hash
                # but still mark as resolved if present
                for src, records in source_groups.items():
                    # Refunds, bank entries, and ledger postings are naturally
                    # one-to-many.  Multiple records from one source are not an
                    # ambiguity by themselves.
                    if len(records) > 1 and node_type not in (NodeType.REFUND, NodeType.BANK, NodeType.LEDGER):
                        result.nodes[node_type] = MatchResult(
                            node_type=node_type,
                            status="ambiguous",
                            matched_records=[records[0]],
                            unmatched_records=records[1:],
                            alternatives=list(records),
                        )
                        result.match_pass[node_type] = 2
                        continue
                    for r in records:
                        result.nodes.setdefault(
                            node_type, MatchResult(node_type=node_type, status="resolved")
                        )
                        result.nodes[node_type].matched_records.append(r)
                        result.match_pass[node_type] = 1
                continue

            # Cross-source hash matching
            all_hashes = {}
            for src, records in source_groups.items():
                for r in records:
                    all_hashes.setdefault(r.content_hash, []).append(r)

            matched_hashes = {h for h, recs in all_hashes.items() if len(recs) > 1}
            unmatched = []

            for src, records in source_groups.items():
                for r in records:
                    if r.content_hash in matched_hashes:
                        mr = result.nodes.setdefault(
                            node_type, MatchResult(node_type=node_type, status="resolved")
                        )
                        mr.matched_records.append(r)
                        result.match_pass[node_type] = 1
                    else:
                        unmatched.append(r)

            if unmatched and not result.nodes.get(node_type):
                result.nodes[node_type] = MatchResult(
                    node_type=node_type, status="pending", unmatched_records=unmatched
                )
            elif unmatched and result.nodes.get(node_type):
                result.nodes[node_type].unmatched_records.extend(unmatched)

    def _pass_fuzzy(self, result: LifecycleMatch):
        """Fuzzy match for nodes still pending after Pass 1."""
        for node_type in NodeType:
            mr = result.nodes.get(node_type)
            if mr is None or mr.status != "pending":
                continue

            if not mr.unmatched_records:
                continue

            # Pick the first unmatched as candidate, try against others
            candidate = mr.unmatched_records[0]
            pool = mr.unmatched_records[1:] if len(mr.unmatched_records) > 1 else []

            if not pool:
                # Single record, no one to match against
                # Check LIKELY_ABANDONED for payment nodes
                if node_type == NodeType.PAYMENT:
                    result.is_likely_abandoned = True
                mr.status = "resolved"
                mr.matched_records.append(candidate)
                result.match_pass[node_type] = 2
                continue

            fuzz = try_fuzzy_match(candidate, pool)
            if fuzz["status"] == "resolved":
                mr.status = "resolved"
                mr.matched_records.extend([candidate, fuzz["match"]])
                result.match_pass[node_type] = 2
            elif fuzz["status"] == "ambiguous":
                mr.status = "ambiguous"
                mr.alternatives = fuzz["alternatives"]
                mr.matched_records.append(candidate)
                result.match_pass[node_type] = 2
            else:
                mr.status = "unmatched"
                mr.matched_records.append(candidate)
                result.match_pass[node_type] = 3

    def _pass_exceptions(self, result: LifecycleMatch):
        """Final pass: remaining unmatched/ambiguous are true exceptions."""
        for node_type in NodeType:
            mr = result.nodes.get(node_type)
            if mr is None:
                # Node type not present at all
                if node_type not in (NodeType.REFUND,):
                    # Refunds are optional (0..N)
                    result.nodes[node_type] = MatchResult(
                        node_type=node_type, status="unmatched"
                    )
                    result.exception_nodes.append(node_type)
                continue

            if mr.status in ("unmatched", "ambiguous") or mr.unmatched_records:
                result.exception_nodes.append(node_type)

    def match_all(self, records: Optional[List[ParsedRecord]] = None):
        """Match all orders."""
        if records is not None:
            self.records = records
            self.order_groups = {}
            self._group_by_order()
            results = {order_id: self.match_order(order_id) for order_id in self.order_groups}
            exceptions = {
                order_id: [
                    record
                    for node_type in graph.exception_nodes
                    for record in graph.nodes.get(node_type, MatchResult(node_type, "unmatched")).unmatched_records
                ]
                for order_id, graph in results.items()
                if graph.exception_nodes
            }
            return results, exceptions
        results = []
        for order_id in self.order_groups:
            results.append(self.match_order(order_id))
        return results


CaseGraph = LifecycleMatch
