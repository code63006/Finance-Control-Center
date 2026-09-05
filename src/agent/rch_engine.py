"""
Root-Cause Hypothesis (RCH) Engine.
Deterministic scoring of candidate hypotheses against evidence.
Lands on one of the 6 terminal outcomes from the Outcome enum.
"""
from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Any
from statistics import mean
from src.constants import (
    NodeType,
    HypothesisClass,
    CONFIRM_THRESHOLD,
    FLOOR_THRESHOLD,
    TIE_MARGIN,
    Outcome,
)
from src.agent.evidence import (
    CaseEvidence,
    EvidenceType,
)


@dataclass
class HypothesisDefinition:
    """Definition of a candidate root-cause hypothesis."""
    hypothesis_class: str  # maps to HypothesisClass enum value
    required_evidence: List[EvidenceType]  # evidence that must be present
    contradiction_checks: List[EvidenceType]  # evidence that CONTRADICTS this hypothesis
    description: str = ""


@dataclass(frozen=True)
class Hypothesis:
    """Compatibility representation accepted by the ablation tests."""
    ch: str
    label: str
    required_evidence: List[EvidenceType]
    contradiction_checks: List[EvidenceType] = None

    def __post_init__(self):
        if self.contradiction_checks is None:
            object.__setattr__(self, "contradiction_checks", [])


@dataclass
class HypothesisScore:
    """Score result for a single hypothesis."""
    status: str  # "STRONGLY_SUPPORTED" or "PLAUSIBLE_UNCONFIRMED"
    value: float  # [0, 1] composite score
    coverage: float = 0.0
    reliability: float = 0.0
    temporal_consistency: float = 0.0


@dataclass
class DiagnosisResult:
    """Final diagnosis output from the RCH engine."""
    outcome: Outcome
    best_hypothesis: Optional[str] = None  # HypothesisClass value
    best_score: Optional[HypothesisScore] = None
    candidates: List[Tuple[str, HypothesisScore]] = None  # top N for ties
    explanation: Optional[str] = None  # AI tie explanation (when UNRESOLVED_AMBIGUITY)
    
    def __post_init__(self):
        if self.candidates is None:
            self.candidates = []

    @property
    def hypothesis(self) -> Optional[Hypothesis]:
        if self.best_hypothesis is None:
            return None
        try:
            ch = HypothesisClass[self.best_hypothesis.upper()]
        except KeyError:
            ch = self.best_hypothesis
        return Hypothesis(ch=ch, label=self.best_hypothesis, required_evidence=[])

    @property
    def score(self) -> Optional[HypothesisScore]:
        return self.best_score

    @property
    def status(self) -> str:
        return self.outcome.value


Diagnosis = DiagnosisResult


# ── Hypothesis Definitions ─────────────────────────────────────────────────

HYPOTHESIS_DEFINITIONS: List[HypothesisDefinition] = [
    HypothesisDefinition(
        hypothesis_class="fee_missing",
        required_evidence=[
            EvidenceType.FEE_NODE_MISSING,
            EvidenceType.LEDGER_IMBALANCE,
        ],
        contradiction_checks=[
            EvidenceType.FEE_NODE_MATCHED,
            EvidenceType.LEDGER_BALANCED,
        ],
        description="Fee entry is missing from one or more sources",
    ),
    HypothesisDefinition(
        hypothesis_class="duplicate_payment",
        required_evidence=[
            EvidenceType.PAYMENT_NODE_AMBIGUOUS,
            EvidenceType.PAYMENT_DUPLICATE_DETECTED,
        ],
        contradiction_checks=[
            EvidenceType.PAYMENT_NODE_MATCHED,
        ],
        description="Duplicate payment webhook received",
    ),
    HypothesisDefinition(
        hypothesis_class="tax_calculation_error",
        required_evidence=[
            EvidenceType.TAX_MISMATCH,
        ],
        contradiction_checks=[],
        description="Tax amount calculated incorrectly",
    ),
    HypothesisDefinition(
        hypothesis_class="timestamp_inconsistency",
        required_evidence=[
            EvidenceType.PROVENANCE_VIOLATION,
        ],
        contradiction_checks=[
            EvidenceType.PROVENANCE_CLEAN,
        ],
        description="Timestamps violate causality (occurred > received > processed)",
    ),
    HypothesisDefinition(
        hypothesis_class="amount_mismatch",
        required_evidence=[
            EvidenceType.AMOUNT_MISMATCH,
        ],
        contradiction_checks=[
            EvidenceType.AMOUNT_MATCHED,
        ],
        description="Amounts disagree across sources for the same transaction",
    ),
    HypothesisDefinition(
        hypothesis_class="settlement_delay",
        required_evidence=[
            EvidenceType.SETTLEMENT_LATE,
        ],
        contradiction_checks=[
            EvidenceType.SETTLEMENT_ON_TIME,
        ],
        description="Settlement arrived later than expected",
    ),
    HypothesisDefinition(
        hypothesis_class="split_attribution_error",
        required_evidence=[
            EvidenceType.BANK_ENTRY_ORPHANED,
            EvidenceType.SOME_BANK_ENTRIES_ORPHANED,
        ],
        contradiction_checks=[
            EvidenceType.ALL_BANK_ENTRIES_MATCHED,
        ],
        description="One or more bank entries misattributed to wrong settlement",
    ),
    HypothesisDefinition(
        hypothesis_class="source_data_conflict",
        required_evidence=[
            EvidenceType.SOURCE_CONFLICT_DETECTED,
        ],
        contradiction_checks=[],  # conflicts don't self-contradict
        description="Two or more sources report conflicting values for the same fact",
    ),
    HypothesisDefinition(
        hypothesis_class="orphaned_entry",
        required_evidence=[
            EvidenceType.REFUND_NODE_ORPHANED,
            EvidenceType.SOME_REFUNDS_ORPHANED,
        ],
        contradiction_checks=[
            EvidenceType.ALL_REFUNDS_MATCHED,
        ],
        description="Refund entry exists with no matching payment",
    ),
    HypothesisDefinition(
        hypothesis_class="combo_hypothesis",
        required_evidence=[
            # Combo requires evidence from multiple base hypotheses
            EvidenceType.LEDGER_IMBALANCE,
        ],
        contradiction_checks=[
            EvidenceType.LEDGER_BALANCED,
            EvidenceType.AMOUNT_MATCHED,
        ],
        description="Multiple anomalies combined in a single case",
    ),
]

# Public registry retained as a list because callers select candidate slices.
# Combo is a dynamic diagnosis for an explicitly detected multi-factor case.
# Including it in every ordinary evaluation made any ledger imbalance look like
# a competing root cause and manufactured ties.
HYPOTHESIS_REGISTRY = [
    definition for definition in HYPOTHESIS_DEFINITIONS
    if definition.hypothesis_class != "combo_hypothesis"
]


def temporal_consistency(
    hypothesis: HypothesisDefinition,
    evidence: CaseEvidence,
) -> float:
    """
    Compute temporal consistency score.
    1.0 = chronology respects causal DAG
    0.5 = minor violation within tolerance
    0.0 = impossible chronology
    """
    # Check if timestamps are in correct order
    if evidence.has(EvidenceType.TIMESTAMP_ORDER_OK):
        return 1.0
    elif evidence.has(EvidenceType.TIMESTAMP_ORDER_VIOLATION):
        return 0.0
    
    # Default: no time evidence available
    return 0.75  # neutral score


def score_hypothesis(
    hypothesis: HypothesisDefinition,
    evidence: CaseEvidence,
) -> HypothesisScore:
    """
    Score a single hypothesis against the evidence bag.
    
    Algorithm (from spec):
    1. Check contradictions first → CONTRADICTED (value=0.0)
    2. Compute coverage = matched_required / total_required
    3. Compute mean reliability from matched evidence sources
    4. Clamp reliability to [0, 1]
    5. value = coverage * reliability * temporal_consistency
    6. If value >= CONFIRM_THRESHOLD → STRONGLY_SUPPORTED
    7. Else → PLAUSIBLE_UNCONFIRMED
    """
    # Step 1: Check contradictions
    for contra in hypothesis.contradiction_checks:
        if evidence.contradicts(contra):
            return HypothesisScore(
                status="CONTRADICTED",
                value=0.0,
                coverage=0.0,
                reliability=0.0,
                temporal_consistency=0.0,
            )
    
    # Step 2: Compute coverage
    required = hypothesis.required_evidence
    if not required:
        # No evidence required - cannot confirm
        return HypothesisScore(
            status="PLAUSIBLE_UNCONFIRMED",
            value=0.0,
            coverage=0.0,
            reliability=0.0,
            temporal_consistency=0.0,
        )
    
    matched = [et for et in required if evidence.has(et)]
    coverage = len(matched) / len(required) if required else 0.0
    
    # Step 3: Compute mean reliability
    reliabilities = evidence.get_matched_reliabilities(matched)
    reliability = mean(reliabilities) if reliabilities else 0.0
    
    # Step 4: Clamp reliability to [0, 1]
    reliability = max(0.0, min(1.0, reliability))
    
    # Step 5: Temporal consistency
    tc = temporal_consistency(hypothesis, evidence)
    
    # Step 6: Compute value
    value = coverage * reliability * tc
    
    # Step 7: Determine status
    if coverage == 1.0 and value >= CONFIRM_THRESHOLD:
        status = "STRONGLY_SUPPORTED"
    else:
        status = "PLAUSIBLE_UNCONFIRMED"
    
    return HypothesisScore(
        status=status,
        value=value,
        coverage=coverage,
        reliability=reliability,
        temporal_consistency=tc,
    )


def diagnose(
    candidates_or_evidence,
    evidence: Optional[CaseEvidence] = None,
    combo_components: Optional[List[str]] = None,
) -> DiagnosisResult:
    """
    Score all hypotheses and determine the final diagnosis.
    
    Algorithm (from spec):
    1. Score all candidates
    2. Remove CONTRADICTED
    3. If no candidates remain → CONFLICTING_EVIDENCE
    4. Sort by value descending
    5. If best.value < FLOOR_THRESHOLD → INSUFFICIENT_EVIDENCE
    6. If best-second gap < TIE_MARGIN → UNRESOLVED_AMBIGUITY
    7. Otherwise → best hypothesis
    """
    if evidence is None:
        evidence = candidates_or_evidence
        candidates = list(HYPOTHESIS_DEFINITIONS)
    else:
        candidates = list(candidates_or_evidence.values()) if isinstance(candidates_or_evidence, dict) else list(candidates_or_evidence)

    # Handle compatibility Hypothesis objects and string evidence labels.
    normalized_candidates = []
    for candidate in candidates:
        if isinstance(candidate, HypothesisDefinition):
            normalized_candidates.append(candidate)
            continue
        required = [_coerce_evidence_type(item) for item in candidate.required_evidence]
        contradictions = [_coerce_evidence_type(item) for item in candidate.contradiction_checks]
        normalized_candidates.append(HypothesisDefinition(
            hypothesis_class=str(candidate.ch),
            required_evidence=[item for item in required if item is not None],
            contradiction_checks=[item for item in contradictions if item is not None],
            description=candidate.label,
        ))
    candidates = normalized_candidates

    # Handle combo cases specially
    if combo_components:
        # Create a dynamic combo hypothesis that requires evidence from both components
        combo_hyp = HypothesisDefinition(
            hypothesis_class="combo_hypothesis",
            required_evidence=[
                EvidenceType.LEDGER_IMBALANCE,  # always present in combos
            ],
            contradiction_checks=[
                EvidenceType.LEDGER_BALANCED,
                EvidenceType.AMOUNT_MATCHED,
            ],
            description=f"Combo: {' + '.join(combo_components)}",
        )
        candidates = [combo_hyp]
    elif not candidates:
        candidates = list(HYPOTHESIS_DEFINITIONS)
    
    # Step 1: Score all candidates
    scored: List[Tuple[str, HypothesisScore]] = []
    if evidence.has(EvidenceType.FEE_NODE_MISSING) and evidence.has(EvidenceType.FEE_NODE_MATCHED):
        return DiagnosisResult(
            outcome=Outcome.CONFLICTING_EVIDENCE,
            explanation="Evidence both supports and contradicts fee absence.",
        )
    
    for hyp in candidates:
        score = score_hypothesis(hyp, evidence)
        scored.append((hyp.hypothesis_class, score))
    
    # Step 2: Remove CONTRADICTED
    scored = [(h, s) for h, s in scored if s.status != "CONTRADICTED"]
    
    # Step 3: If no candidates remain
    if not scored:
        return DiagnosisResult(
            outcome=Outcome.CONFLICTING_EVIDENCE,
            candidates=[],
        )
    
    # Step 4: Sort by value descending
    scored.sort(key=lambda x: x[1].value, reverse=True)
    
    best_name, best_score = scored[0]
    second_name, second_score = scored[1] if len(scored) > 1 else (None, None)
    
    # Step 5: Floor check — FLOOR_THRESHOLD strictly > 0
    if best_score.value < FLOOR_THRESHOLD:
        return DiagnosisResult(
            outcome=Outcome.INSUFFICIENT_EVIDENCE,
            candidates=scored[:3],
            explanation=(
                f"Best hypothesis '{best_name}' scored {best_score.value:.4f}, "
                f"below FLOOR_THRESHOLD ({FLOOR_THRESHOLD}). "
                f"Insufficient evidence to diagnose."
            ),
        )
    
    # Step 6: Tie check
    if second_score is not None:
        gap = best_score.value - second_score.value
        if gap < TIE_MARGIN:
            # Genuine tie — AI explains but does not decide
            return DiagnosisResult(
                outcome=Outcome.UNRESOLVED_AMBIGUITY,
                best_hypothesis=best_name,
                best_score=best_score,
                candidates=scored[:3],
                explanation=_generate_tie_explanation(scored[:3], evidence),
            )
    
    # Step 7: Clear winner
    return DiagnosisResult(
        outcome=Outcome(best_score.status),
        best_hypothesis=best_name,
        best_score=best_score,
        candidates=scored[:3],
    )


def _coerce_evidence_type(value):
    if isinstance(value, EvidenceType):
        return value
    if isinstance(value, str):
        try:
            return EvidenceType[value]
        except KeyError:
            try:
                return EvidenceType(value)
            except ValueError:
                return None
    return None


def _generate_tie_explanation(
    candidates: List[Tuple[str, HypothesisScore]],
    evidence: CaseEvidence,
) -> str:
    """
    Generate an explanation for a tie situation.
    This is deterministic — AI layer enhances in rch_tie_explainer.py.
    """
    if not candidates:
        return "No candidates to explain."
    
    names = [f"'{name}' (score={score.value:.4f})" for name, score in candidates]
    
    return (
        f"Multiple hypotheses are within TIE_MARGIN of each other: "
        f"{', '.join(names)}. "
        f"The evidence does not conclusively distinguish between these candidates. "
        f"Additional investigation required."
    )
