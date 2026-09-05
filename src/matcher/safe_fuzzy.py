"""
Two-stage fuzzy matching gate.
AMBIGUOUS_MATCH (multiple plausible) vs UNMATCHED (nothing fits) —
these are opposite findings and must be reported as such.
"""
from typing import Optional, List, Tuple
from types import SimpleNamespace

from src.constants import (
    AMOUNT_TOLERANCE_PAISE,
    TIME_TOLERANCE_SECONDS,
    UNIQUENESS_MARGIN,
    MatchStatus,
)
from src.ingest.schemas import ParsedRecord


class MatchResult(dict):
    """Dictionary result with attribute access for legacy callers."""

    def __init__(self, status: str, match=None, alternatives=None):
        alternatives = alternatives or []
        super().__init__(status=status, match=match, alternatives=alternatives)
        self.status = status
        self.match = match
        self.alternatives = alternatives
        self.candidates = alternatives


def fuzzy_score(a: ParsedRecord, b: ParsedRecord) -> float:
    """
    Compute fuzzy match score between two records.
    Score ∈ [0, 1]; higher is better.
    """
    score = 0.0
    total_weight = 0.0

    # Amount similarity (weight: 0.5)
    amount_weight = 0.5
    if a.amount_paise > 0:
        diff = abs(a.amount_paise - b.amount_paise)
        amount_score = max(0.0, 1.0 - (diff / a.amount_paise))
        score += amount_score * amount_weight
    total_weight += amount_weight

    # Timestamp proximity (weight: 0.3)
    time_weight = 0.3
    timestamp_delta = a.timestamp - b.timestamp
    diff_seconds = abs(
        timestamp_delta.total_seconds()
        if hasattr(timestamp_delta, "total_seconds")
        else timestamp_delta
    )
    time_score = max(0.0, 1.0 - (diff_seconds / TIME_TOLERANCE_SECONDS))
    score += time_score * time_weight
    total_weight += time_weight

    # Direction/type match (weight: 0.2)
    type_weight = 0.2
    type_score = 1.0 if a.node_type == b.node_type else 0.0
    score += type_score * type_weight
    total_weight += type_weight

    return score / total_weight if total_weight > 0 else 0.0


def try_fuzzy_match(
    candidate: ParsedRecord,
    pool: List[ParsedRecord],
    amount_tolerance: int = None,
    time_tolerance: int = None,
    uniqueness_margin: float = None,
) -> dict:
    """
    Attempt fuzzy matching for candidate against a pool.
    Returns a MatchStatus-compatible dict:
      {"status": "resolved"|"ambiguous"|"unmatched", "match": record_or_none, "alternatives": [...]}
    """
    legacy = amount_tolerance is not None or time_tolerance is not None or uniqueness_margin is not None
    amount_tolerance = AMOUNT_TOLERANCE_PAISE if amount_tolerance is None else amount_tolerance
    time_tolerance = TIME_TOLERANCE_SECONDS if time_tolerance is None else time_tolerance
    uniqueness_margin = UNIQUENESS_MARGIN if uniqueness_margin is None else uniqueness_margin

    def normalize(record):
        if isinstance(record, dict):
            return SimpleNamespace(
                amount_paise=record.get("amount_paise", 0),
                timestamp=record.get("timestamp", 0),
                node_type=record.get("node_type", record.get("record_type")),
            )
        return record

    def time_difference(left, right):
        difference = left - right
        return abs(difference.total_seconds()) if hasattr(difference, "total_seconds") else abs(difference)

    candidate = normalize(candidate)
    pool = [normalize(record) for record in pool]
    plausible = []
    for c in pool:
        if abs(candidate.amount_paise - c.amount_paise) > amount_tolerance:
            continue
        if time_difference(candidate.timestamp, c.timestamp) > time_tolerance:
            continue
        if candidate.node_type is not None and c.node_type is not None and candidate.node_type != c.node_type:
            continue
        score = fuzzy_score(candidate, c)
        plausible.append((c, score))

    if not plausible:
        return MatchResult("UNMATCHED" if legacy else "unmatched")

    plausible.sort(key=lambda x: x[1], reverse=True)
    best, best_score = plausible[0]

    if len(plausible) == 1:
        return MatchResult("RESOLVED" if legacy else "resolved", match=best)

    second_score = plausible[1][1]
    if (best_score - second_score) < uniqueness_margin:
        return MatchResult("AMBIGUOUS_MATCH" if legacy else "ambiguous", alternatives=[(c, s) for c, s in plausible[:3]])

    return MatchResult("RESOLVED" if legacy else "resolved", match=best)
