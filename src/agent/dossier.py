"""
Exception dossier generation.
Produces an honest list of unresolved cases including ambiguity explanations.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from src.constants import Outcome


@dataclass
class ExceptionEntry:
    """Single exception in the dossier."""
    case_id: str
    outcome: Outcome
    fod_point: Optional[str] = None  # First Observed Divergence node
    best_hypothesis: Optional[str] = None
    best_score_value: Optional[float] = None
    explanation: str = ""
    evidence_summary: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ExceptionDossier:
    """Complete exception dossier for all unresolved cases."""
    entries: List[ExceptionEntry] = field(default_factory=list)
    total_cases: int = 0
    resolved_count: int = 0
    unresolved_count: int = 0
    
    def add_entry(self, entry: ExceptionEntry):
        self.entries.append(entry)
        self.unresolved_count = len(self.entries)
        self.resolved_count = self.total_cases - self.unresolved_count
    
    def to_markdown(self) -> str:
        """Generate markdown report."""
        lines = [
            "# Exception Dossier",
            "",
            f"**Total Cases:** {self.total_cases}",
            f"**Resolved:** {self.resolved_count} ({100*self.resolved_count//self.total_cases if self.total_cases else 0}%)",
            f"**Unresolved:** {self.unresolved_count}",
            "",
            "---",
            "",
        ]
        
        for entry in self.entries:
            lines.extend([
                f"## {entry.case_id}",
                "",
                f"**Outcome:** {entry.outcome.value}",
                f"**FOD Point:** {entry.fod_point or 'N/A'}",
                f"**Best Hypothesis:** {entry.best_hypothesis or 'N/A'}",
                f"**Score:** {entry.best_score_value:.4f}" if entry.best_score_value else "**Score:** N/A",
                "",
                f"### Explanation",
                entry.explanation,
                "",
            ])
            
            if entry.evidence_summary:
                lines.append("**Evidence Summary:**")
                for item in entry.evidence_summary:
                    lines.append(f"- {item}")
                lines.append("")
            
            if entry.recommendations:
                lines.append("**Recommendations:**")
                for rec in entry.recommendations:
                    lines.append(f"- {rec}")
                lines.append("")
            
            lines.append("---")
            lines.append("")
        
        return "\n".join(lines)


def generate_dossier(
    cases: List[Dict[str, Any]],
    diagnoses: Dict[str, Dict[str, Any]],
    evidence_bags: Dict[str, Any],
    total_cases: int,
) -> ExceptionDossier:
    """
    Generate the exception dossier for all unresolved cases.
    
    Args:
        cases: List of original case data
        diagnoses: Dict mapping case_id → diagnosis result
        evidence_bags: Dict mapping case_id → CaseEvidence
        total_cases: Total number of cases processed
    
    Returns:
        ExceptionDossier with all unresolved entries
    """
    dossier = ExceptionDossier(total_cases=total_cases)
    
    for case in cases:
        case_id = case.get("case_id", "unknown")
        diagnosis = diagnoses.get(case_id, {})
        outcome = Outcome(diagnosis.get("outcome", "UNRESOLVED_AMBIGUITY"))
        
        # Only include non-resolved cases
        if outcome in (
            Outcome.INSUFFICIENT_EVIDENCE,
            Outcome.UNRESOLVED_AMBIGUITY,
            Outcome.CONFLICTING_EVIDENCE,
        ):
            evidence = evidence_bags.get(case_id)
            
            # Determine FOD point
            fod_point = _find_fod_point(case, diagnosis)
            
            # Generate explanation
            explanation = _generate_explanation(outcome, diagnosis, evidence)
            
            # Generate recommendations
            recommendations = _generate_recommendations(outcome, diagnosis)
            
            # Evidence summary
            evidence_summary = _summarize_evidence(evidence)
            
            entry = ExceptionEntry(
                case_id=case_id,
                outcome=outcome,
                fod_point=fod_point,
                best_hypothesis=diagnosis.get("best_hypothesis"),
                best_score_value=diagnosis.get("best_score", {}).get("value"),
                explanation=explanation,
                evidence_summary=evidence_summary,
                recommendations=recommendations,
            )
            
            dossier.add_entry(entry)
    
    return dossier


def _find_fod_point(
    case: Dict[str, Any],
    diagnosis: Dict[str, Any],
) -> Optional[str]:
    """
    Find the First Observed Divergence point.
    Uses each node's business-event timestamp, never calculation_timestamp_utc.
    """
    ground_truth = case.get("ground_truth", {})
    return ground_truth.get("affected_node")


def _generate_explanation(
    outcome: Outcome,
    diagnosis: Dict[str, Any],
    evidence: Any,
) -> str:
    """Generate human-readable explanation for the exception."""
    if outcome == Outcome.INSUFFICIENT_EVIDENCE:
        return (
            f"The best hypothesis scored {diagnosis.get('best_score', {}).get('value', 0):.4f}, "
            f"below the confidence threshold. There is insufficient evidence to make a "
            f"determinate diagnosis. This is an honest outcome — the system acknowledges "
            f"it cannot resolve this case with available data."
        )
    
    elif outcome == Outcome.UNRESOLVED_AMBIGUITY:
        candidates = diagnosis.get("candidates", [])
        if candidates:
            names = []
            for candidate in candidates:
                if isinstance(candidate, dict):
                    names.append(
                        f"'{candidate.get('hypothesis', 'unknown')}' "
                        f"(score={candidate.get('score', 0):.4f})"
                    )
                else:
                    names.append(f"'{candidate[0]}' (score={candidate[1].get('value', 0):.4f})")
            return (
                f"Multiple hypotheses are within the tie margin: {', '.join(names)}. "
                f"The evidence does not conclusively distinguish between these candidates. "
                f"This is a genuine ambiguity, not a system limitation."
            )
        return "Multiple hypotheses could not be distinguished."
    
    elif outcome == Outcome.CONFLICTING_EVIDENCE:
        return (
            "All candidate hypotheses were contradicted by the evidence. "
            "The observed state is inconsistent with any single root cause. "
            "This may indicate a multi-factor failure or data corruption."
        )
    
    return "Unknown exception type."


def _generate_recommendations(
    outcome: Outcome,
    diagnosis: Dict[str, Any],
) -> List[str]:
    """Generate actionable recommendations for the exception."""
    if outcome == Outcome.INSUFFICIENT_EVIDENCE:
        return [
            "Request additional data sources (e.g., gateway logs, bank reconciliation file)",
            "Manually review transaction timeline for the affected period",
            "Consider lowering confidence threshold only if false negatives are acceptable",
        ]
    
    elif outcome == Outcome.UNRESOLVED_AMBIGUITY:
        return [
            "Investigate the specific evidence gaps between candidate hypotheses",
            "Request source-specific audit trail for the disputed transaction",
            "Consider domain expertise to break the tie if business context is available",
        ]
    
    elif outcome == Outcome.CONFLICTING_EVIDENCE:
        return [
            "Escalate to manual review — multi-factor failure detected",
            "Check for system-wide data corruption in the affected time window",
            "Verify source system integrity before attempting automated resolution",
        ]
    
    return []


def _summarize_evidence(evidence: Any) -> List[str]:
    """Summarize key evidence items for the dossier."""
    if evidence is None:
        return ["No evidence bag available"]
    
    summary = []
    # Extract key evidence types
    key_evidence = [
        ("Fee Node", "FEE_NODE_MISSING", "FEE_NODE_MATCHED"),
        ("Payment Node", "PAYMENT_NODE_AMBIGUOUS", "PAYMENT_NODE_MATCHED"),
        ("Ledger", "LEDGER_IMBALANCE", "LEDGER_BALANCED"),
        ("Provenance", "PROVENANCE_VIOLATION", "PROVENANCE_CLEAN"),
        ("Tax", "TAX_MISMATCH", "TAX_NODE_MATCHED"),
    ]
    
    for label, bad_type, good_type in key_evidence:
        from src.agent.evidence import EvidenceType
        bad_et = EvidenceType[bad_type]
        good_et = EvidenceType[good_type]
        
        if hasattr(evidence, 'has'):
            if evidence.has(bad_et):
                summary.append(f"{label}: Anomaly detected")
            elif evidence.has(good_et):
                summary.append(f"{label}: OK")
    
    return summary if summary else ["No significant evidence patterns detected"]


def build_dossier(
    cases: List[Dict[str, Any]],
    diagnoses: Dict[str, Dict[str, Any]],
    impact: Dict[str, Any],
) -> ExceptionDossier:
    """Compatibility façade for the evaluator's compact diagnosis payload."""
    normalized_cases = []
    normalized_diagnoses = {}
    normalized_evidence = {}
    for case in cases:
        case_id = case.get("case_id", case.get("order_id", "unknown"))
        normalized_case = dict(case)
        normalized_case["case_id"] = case_id
        normalized_cases.append(normalized_case)

        diagnosis = diagnoses.get(case_id, {})
        normalized_diagnoses[case_id] = {
            **diagnosis,
            "best_hypothesis": diagnosis.get("best_hypothesis", diagnosis.get("hypothesis")),
            "best_score": {"value": diagnosis.get("score", 0)},
        }
        normalized_evidence[case_id] = impact.get(case_id, {})

    return generate_dossier(
        normalized_cases,
        normalized_diagnoses,
        normalized_evidence,
        len(normalized_cases),
    )


def dossier_to_markdown(dossier: ExceptionDossier) -> str:
    """Render a dossier returned by build_dossier."""
    return dossier.to_markdown()
