"""
AI Tie Explainer for genuine UNRESOLVED_AMBIGUITY cases.
This module explains competing hypotheses but NEVER decides between them.
It's explicitly not load-bearing — the case stays UNRESOLVED_AMBIGUITY
no matter what it says.
"""
from typing import List, Tuple, Dict, Any, Optional
from src.constants import Outcome


def explain_tie(
    candidates: List[Tuple[str, Dict[str, Any]]],
    evidence: Any,
    context: Optional[Dict[str, Any]] = None,
    case_id: Optional[str] = None,
) -> str:
    """
    Generate an explanation for a genuine tie between hypotheses.
    
    This function is AI-enhanced but deterministic in output structure.
    It names the competing hypotheses and the evidence that would resolve them.
    The case stays UNRESOLVED_AMBIGUITY regardless of what this returns.
    
    Args:
        candidates: List of (hypothesis_class, score_dict) for top N tied candidates
        evidence: CaseEvidence bag
        context: Optional additional context (case data, etc.)
    
    Returns:
        Explanation string (never a decision)
    """
    if not candidates:
        return "No candidates to explain."
    
    # Build explanation structure
    parts = []
    
    # 1. Name the competing hypotheses
    hyp_names = [f"'{name}'" for name, _ in candidates]
    if len(hyp_names) == 2:
        competition = f"{hyp_names[0]} and {hyp_names[1]}"
    else:
        competition = ", ".join(hyp_names[:-1]) + f", and {hyp_names[-1]}"
    
    parts.append(
        f"The evidence supports multiple competing hypotheses: {competition}."
    )
    
    # 2. Describe what distinguishes them (and why it's insufficient)
    parts.append(
        "The current evidence does not provide sufficient discriminatory signal "
        "to conclusively favor one hypothesis over the others."
    )
    
    # 3. Name what would resolve the tie
    resolution_gaps = _identify_resolution_gaps(candidates, evidence)
    if resolution_gaps:
        parts.append(
            "The following additional evidence would help distinguish between "
            "the competing hypotheses:"
        )
        for gap in resolution_gaps:
            parts.append(f"- {gap}")
    
    # 4. Explicitly state this is NOT a decision
    parts.append(
        "NOTE: This explanation is for informational purposes only. "
        "The system maintains UNRESOLVED_AMBIGUITY status for this case. "
        "No automated decision has been made."
    )
    
    return "\n".join(parts)


def _identify_resolution_gaps(
    candidates: List[Tuple[str, Dict[str, Any]]],
    evidence: Any,
) -> List[str]:
    """
    Identify what additional evidence would help resolve the tie.
    This is deterministic — looks at what each hypothesis requires
    that isn't currently present.
    """
    from src.agent.rch_engine import HYPOTHESIS_DEFINITIONS
    
    gaps = []
    hyp_classes = [name for name, _ in candidates]
    
    # Find definitions for tied hypotheses
    tied_defs = [
        h for h in HYPOTHESIS_DEFINITIONS 
        if h.hypothesis_class in hyp_classes
    ]
    
    # Collect all required evidence across tied hypotheses
    all_required = set()
    for h in tied_defs:
        all_required.update(h.required_evidence)
    
    # Find what's missing from the evidence bag
    if hasattr(evidence, 'has'):
        from src.agent.evidence import EvidenceType
        missing = [
            et for et in all_required 
            if not evidence.has(et)
        ]
        
        # Translate to human-readable gaps
        gap_descriptions = {
            "FEE_NODE_MISSING": "Confirmation from fee source records",
            "FEE_NODE_MATCHED": "Fee source records to contradict fee_missing hypothesis",
            "PAYMENT_NODE_AMBIGUOUS": "Additional payment records or webhook audit trail",
            "TAX_MISMATCH": "Tax calculation verification from invoice source",
            "PROVENANCE_VIOLATION": "Source system clock synchronization audit",
            "AMOUNT_MISMATCH": "Amount reconciliation across all four sources",
            "SETTLEMENT_LATE": "Settlement SLA documentation and bank processing timeline",
            "BANK_ENTRY_ORPHANED": "Bank settlement attribution audit trail",
            "SOURCE_CONFLICT_DETECTED": "Source system conflict resolution log",
            "REFUND_NODE_ORPHANED": "Refund-payment linkage verification",
            "LEDGER_IMBALANCE": "Double-entry ledger audit for the transaction",
        }
        
        for et in missing:
            if et in gap_descriptions:
                gaps.append(gap_descriptions[et])
    
    return gaps


def enhance_explanation_with_ai(
    deterministic_explanation: str,
    candidates: List[Tuple[str, Dict[str, Any]]],
    evidence: Any,
    context: Optional[Dict[str, Any]] = None,
) -> str:
    """
    AI-enhanced explanation (optional layer).
    
    This function can be called by the AI layer to add natural language
    enhancement to the deterministic explanation. The core message
    (UNRESOLVED_AMBIGUITY) never changes.
    
    For the initial implementation, this returns the deterministic version.
    AI enhancement can be added in Phase 5.
    """
    # For now, return deterministic explanation
    # AI enhancement will be added in Phase 5
    return deterministic_explanation
