# Decisions Log — AI Finance Controller

## Phase 1 (Generator)

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | Non-round amounts with 99-paise suffix | Prevents round-number matching shortcuts; stresses tolerance logic |
| 2 | 25% chance of refund per case | Enough to exercise refund branch without dominating |
| 3 | 20% chance of split settlement | Exercises 1..N bank entry branch; avoids all 1:1 |
| 4 | Separate `calculate_gst_paise` as integer math | Ensures money is always int paise, never float |
| 5 | Holdout uses different seed (seed+1000) | Ensures holdout cases are truly independent of dev |

## Phase 2 (Deterministic Core)

| # | Decision | Rationale |
|---|----------|-----------|
| 6 | Provenance: downweight, never discard | Bad clock ≠ bad event; per spec |
| 7 | 3-pass: exact → fuzzy → exception | Progressive matching avoids premature exceptions |
| 8 | AMBIGUOUS ≠ UNMATCHED | Previously conflated; these are opposite findings |
| 9 | Ledger tolerance 1 paise | Accounts for rounding in GST calculations |
| 10 | Graph edges as dict, not class hierarchy | Simpler, more testable, spec-aligned |
| 11 | 300s LIKELY_ABANDONED separate from 120s fuzzy tolerance | Per spec: "don't merge them" |

## Phase 3 (Evidence Engine)

| # | Decision | Rationale |
|---|----------|-----------|
| 12 | OC = "Observed/injected Cause" | Best-guess from spec context; see README glossary |
| 13 | CH = "Candidate Hypothesis" class | Best-guess from spec context; see README glossary |
| 14 | Temporal consistency is ternary (1.0, 0.5, 0.0) | Simple, interpretable, avoids false precision |
| 15 | Clamp reliability to [0,1] after penalty | Prevents negative reliability from distorting value ordering |
| 16 | FLOOR_THRESHOLD > 0 (strictly) | Prevents zero-evidence tie from reaching tie check |
| 17 | EvidenceType enum covers all node presence/absence | Ensures hypotheses have clean evidence vocabulary |

## Phase 4 (Metrics)

| # | Decision | Rationale |
|---|----------|-----------|
| 18 | NO_ISSUE as explicit confusion matrix class | Prevents "calls everything clean" false-positive |
| 19 | Throughput = full pipeline wall time | Simplest meaningful measure |
| 20 | Holdout behind --data flag | Prevents accidental tuning |
| 21 | Impact components computed independently | Tax delta ≠ fee delta × rate; per spec |
| 22 | Ablation A: stub tie-explainer to empty string | Proves AI is not load-bearing |

## Phase 5 (AI Layer)

| # | Decision | Rationale |
|---|----------|-----------|
| 23 | Deterministic tie-explainer (no LLM needed) | Works offline; structured for LLM swap-in |
| 24 | Q&A tool registry with strict schemas | Prevents free-form queries; security |
| 25 | Every answer traces numbers to tool calls | Grounding guarantee per spec |

## Phase 6 (Resilience)

| # | Decision | Rationale |
|---|----------|-----------|
| 26 | Tier 1 tests are mandatory | AI timeout, fuzzy edge, out-of-order timestamps |
| 27 | Tier 2 deferred under time pressure | Duplicate webhook, malformed records |

## Phase 7 (UI + Docker)

| # | Decision | Rationale |
|---|----------|-----------|
| 28 | HTML over TUI | Judges can open browser; zero learning curve |
| 29 | Single docker-compose entry point | Per spec: "pick ONE real entry point" |
| 30 | No external API keys in .env | AI layer is deterministic stub |
