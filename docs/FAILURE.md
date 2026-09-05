# Failure Log — AI Finance Controller

## What broke and how we got out

### 1. AMBIGUOUS_MATCH vs UNMATCHED conflation
**What:** Early implementation returned UNMATCHED for both "nothing fits" and "several plausible things."
**Why it matters:** These are opposite findings — "I found nothing" vs "I found several."
**Fix:** Split into MatchStatus.AMBIGUOUS and MatchStatus.UNMATCHED; regression test `test_no_plausible_is_unmatched` added.

### 2. Tie-break silently picks a winner
**What:** Sorting candidates by score and taking `[0]` when scores are equal produces a deterministic but arbitrary winner.
**Why it matters:** This is exactly the "manufactured answer" failure mode the spec warns about.
**Fix:** UNRESOLVED_AMBIGUITY fires when gap < TIE_MARGIN. Test `test_tie_never_silently_broken` locks this in.

### 3. Zero-evidence tie misfires as ambiguity
**What:** When FLOOR_THRESHOLD = 0, a case where all candidates score 0.0 falls through the floor check and hits the tie check.
**Why it matters:** Reports UNRESOLVED_AMBIGUITY for a case with literally no evidence.
**Fix:** FLOOR_THRESHOLD must be strictly > 0; test `test_zero_evidence_tie_is_insufficient` added.

### 4. Graph modeled as chain
**What:** Initially implemented Order→Payment→Fee→Tax→... as a linear chain.
**Why it matters:** Refund branch independence is a core architectural requirement.
**Fix:** Branching graph with explicit edge definitions; test `test_refund_independent_of_fee_tax_branch`.

### 5. Provenance violation discards record
**What:** Early version treated provenance violation as grounds for rejection.
**Why it matters:** "A bad clock doesn't mean the event didn't happen."
**Fix:** Downweight only (PROVENANCE_RELIABILITY_PENALTY); record stays in pool.
