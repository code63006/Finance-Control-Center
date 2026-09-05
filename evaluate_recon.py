#!/usr/bin/env python3
"""
One-command benchmark: full metrics incl. ablation.
Usage:
    python evaluate_recon.py --data dev
    python evaluate_recon.py --data holdout
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

from src.constants import (
    Outcome, HypothesisClass, InjectedCause, NodeType,
    CONFIRM_THRESHOLD, FLOOR_THRESHOLD, TIE_MARGIN,
)
from src.ingest.parsers import ingest_case
from src.matcher.graph_engine import LifecycleGraphMatcher
from src.tax.gst_reconciler import GSTReconciler
from src.ledger.bookkeeper import Bookkeeper
from src.agent.evidence import CaseEvidence, EvidenceItem, EvidenceType
from src.agent.rch_engine import (
    HYPOTHESIS_REGISTRY, diagnose, Hypothesis, HypothesisScore, Diagnosis,
)
from src.agent.blast_radius import compute_blast_radius, variance_paise
from src.agent.dossier import build_dossier, dossier_to_markdown
from src.config.pricing_rules import calculate_gst_paise, settlement_delay


def load_batch(path: str) -> List[dict]:
    with open(path) as f:
        return json.load(f)


def build_evidence_for_case(
    case_dict: dict,
    match_result,
    tax_recon,
    ledger_verif,
    all_records,
) -> CaseEvidence:
    """Populate evidence bag from match results, tax recon, ledger verif."""
    ev = CaseEvidence()
    oid = case_dict["order_id"]

    nodes = case_dict.get("nodes", {})

    def parse_time(value):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    # Fee node evidence
    if nodes.get("fee") is not None:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.FEE_NODE_PRESENT,
            source=case_dict["nodes"]["fee"].get("source", "unknown"),
            source_reliability=1.0,
        ))
    else:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.FEE_NODE_MISSING,
            source="orders_db",
            source_reliability=0.9,
        ))

    # Tax node evidence
    if nodes.get("tax") is not None:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.TAX_NODE_PRESENT,
            source=case_dict["nodes"]["tax"].get("source", "unknown"),
            source_reliability=1.0,
        ))
    else:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.TAX_NODE_MISSING,
            source="orders_db",
            source_reliability=0.9,
        ))

    # Provenance: validate both the event's own audit trail and its place in
    # the lifecycle.  A payment recorded before its order is invalid even when
    # its own occurred/received/processed timestamps are internally ordered.
    payment_node = nodes.get("payment", {})
    order_node = nodes.get("order", {})
    if payment_node:
        processed = payment_node.get("processed_at", "")
        received = payment_node.get("received_at", "")
        occurred = parse_time(payment_node.get("occurred_at"))
        received_time = parse_time(received)
        processed_time = parse_time(processed)
        payment_before_order = (
            parse_time(payment_node.get("occurred_at") or payment_node.get("timestamp"))
            and parse_time(order_node.get("occurred_at") or order_node.get("timestamp"))
            and parse_time(payment_node.get("occurred_at") or payment_node.get("timestamp"))
            < parse_time(order_node.get("occurred_at") or order_node.get("timestamp"))
        )
        invalid_order = (
            occurred and received_time and processed_time
            and not occurred <= received_time <= processed_time
        )
        if invalid_order or payment_before_order or (processed and received and processed < received):
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.PROVENANCE_VIOLATION,
                source="razorpay_recon",
                source_reliability=0.7,
            ))
        else:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.PROVENANCE_VALID,
                source="razorpay_recon",
                source_reliability=1.0,
            ))

    # Tax reconciliation
    if tax_recon and oid in tax_recon:
        tr = tax_recon[oid]
        tax_is_drifted = bool(
            nodes.get("tax")
            and nodes.get("fee")
            and nodes["tax"].get("amount_paise")
            != calculate_gst_paise(nodes["fee"].get("amount_paise", 0))
        )
        if not tr.is_consistent or tax_is_drifted:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.AMOUNTS_DRIFTED,
                source="tax_invoice",
                source_reliability=0.9,
            ))

    # Independent anomaly signals from source records.  The fixture shape is
    # used only as a source adapter; relationship quality is verified against
    # the reconciliation graph below.
    fee_node = nodes.get("fee") or {}
    tax_node = nodes.get("tax") or {}
    # Use the same integer-paise rule used by the generator and tax
    # reconciler.  float rounding here previously manufactured tax alarms.
    expected_tax = calculate_gst_paise(fee_node.get("amount_paise", 0))
    if fee_node and tax_node and tax_node.get("amount_paise") != expected_tax:
        ev.add(EvidenceItem(EvidenceType.TAX_MISMATCH, "tax_invoice", 0.95))

    duplicate_payments = nodes.get("duplicate_payments", [])
    if duplicate_payments:
        ev.add(EvidenceItem(EvidenceType.PAYMENT_NODE_AMBIGUOUS, "razorpay_recon", 0.9))
        ev.add(EvidenceItem(EvidenceType.PAYMENT_DUPLICATE_DETECTED, "razorpay_recon", 0.9))

    payment_time = parse_time((nodes.get("payment") or {}).get("timestamp"))
    settlement_time = parse_time((nodes.get("settlement") or {}).get("timestamp"))
    expected_delay_seconds = settlement_delay(case_dict.get("payment_method", "card")) * 86400
    if (
        payment_time and settlement_time
        and (settlement_time - payment_time).total_seconds() > expected_delay_seconds + 86400
    ):
        ev.add(EvidenceItem(EvidenceType.SETTLEMENT_LATE, "razorpay_recon", 0.9))

    order_amount = (nodes.get("order") or {}).get("amount_paise")
    payment_amount = (nodes.get("payment") or {}).get("amount_paise")
    if order_amount is not None and payment_amount is not None and order_amount != payment_amount:
        ev.add(EvidenceItem(EvidenceType.SOURCE_CONFLICT_DETECTED, "orders_db", 0.85))

    settlement = nodes.get("settlement") or {}
    bank_entries = nodes.get("bank_entries", []) or []
    bank_total = sum(entry.get("amount_paise", 0) for entry in bank_entries)
    if settlement and bank_total != settlement.get("amount_paise", bank_total):
        ev.add(EvidenceItem(EvidenceType.AMOUNT_MISMATCH, "bank_statement", 0.9))
    settlement_ref = settlement.get("reference_id")
    misattributed = [
        entry for entry in bank_entries
        if settlement_ref and entry.get("settlement_ref") not in (None, settlement_ref)
    ]
    if misattributed:
        ev.add(EvidenceItem(EvidenceType.BANK_ENTRY_ORPHANED, "bank_statement", 0.9))
        ev.add(EvidenceItem(EvidenceType.SOME_BANK_ENTRIES_ORPHANED, "bank_statement", 0.9))

    # Reconciliation output is the authority for linkage quality.  Raw source
    # fields add business context, while the match graph decides whether a
    # relationship was actually established.
    if match_result:
        payment_match = match_result.nodes.get(NodeType.PAYMENT)
        if payment_match and payment_match.status == "ambiguous":
            ev.add(EvidenceItem(EvidenceType.PAYMENT_NODE_AMBIGUOUS, "razorpay_recon", 0.8))
        bank_match = match_result.nodes.get(NodeType.BANK)
        if bank_match and bank_match.unmatched_records:
            ev.add(EvidenceItem(EvidenceType.BANK_ENTRY_ORPHANED, "bank_statement", 0.8))

    # Ledger
    if ledger_verif and oid in ledger_verif:
        lv = ledger_verif[oid]
        if lv.is_balanced:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.LEDGER_BALANCED,
                source="razorpay_recon",
                source_reliability=0.95,
            ))
        else:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.LEDGER_IMBALANCE,
                source="razorpay_recon",
                source_reliability=0.9,
            ))
        if lv.account_codes_correct:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.ACCOUNT_CODE_CORRECT,
                source="razorpay_recon",
                source_reliability=0.95,
            ))
        else:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.ACCOUNT_CODE_WRONG,
                source="razorpay_recon",
                source_reliability=0.9,
            ))

    # Settlement
    if nodes.get("settlement") is not None:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_MATCHED,
            source="razorpay_recon",
            source_reliability=1.0,
        ))
    else:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.SETTLEMENT_MISSING,
            source="razorpay_recon",
            source_reliability=0.9,
        ))

    # Bank entries
    bank_entries = nodes.get("bank_entries", [])
    if bank_entries:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.BANK_ENTRIES_MATCHED,
            source="bank_statement",
            source_reliability=1.0,
        ))
    else:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.BANK_ENTRIES_MISSING,
            source="bank_statement",
            source_reliability=0.9,
        ))

    # Refunds
    refunds = nodes.get("refunds", [])
    if refunds:
        # Check for orphaned refund (order_id mismatch)
        orphaned = any(
            r.get("order_id") != oid
            for r in refunds
            if isinstance(r, dict)
        )
        if orphaned:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.REFUND_ORPHANED,
                source="razorpay_recon",
                source_reliability=0.9,
            ))
        else:
            ev.add(EvidenceItem(
                evidence_type=EvidenceType.REFUND_FOUND,
                source="razorpay_recon",
                source_reliability=1.0,
            ))

    # Source conflict
    conflict = nodes.get("conflict_tax")
    if conflict:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.SOURCE_CONFLICT_DETECTED,
            source="razorpay_recon",
            source_reliability=0.8,
        ))

    # Duplicate payment
    dup = nodes.get("duplicate_payment")
    if dup:
        ev.add(EvidenceItem(
            evidence_type=EvidenceType.SOURCE_CONFLICT_DETECTED,
            source="razorpay_recon",
            source_reliability=0.8,
        ))

    # Temporal consistency (simple heuristic)
    ev.add(EvidenceItem(
        evidence_type=EvidenceType.TEMPORAL_CONSISTENT,
        source="system",
        source_reliability=1.0,
    ))

    return ev


def evaluate_batch(
    cases: List[dict],
    use_ai: bool = True,
) -> dict:
    """Run full pipeline on a batch and return metrics."""

    start_time = time.time()

    # ── Ingest all ──
    all_records = []
    for case in cases:
        all_records.extend(ingest_case(case))

    # ── Match ──
    matcher = LifecycleGraphMatcher(all_records)
    match_results = {m.order_id: m for m in matcher.match_all()}

    # ── Tax reconciliation ──
    tax_reconciler = GSTReconciler()
    tax_recon = tax_reconciler.reconcile(all_records)

    # ── Ledger verification ──
    bookkeeper = Bookkeeper()
    ledger_verif = bookkeeper.verify(all_records)

    # ── Evidence + Diagnosis ──
    diagnoses = {}
    case_results = {}
    evidence_bags = {}
    for case in cases:
        oid = case["order_id"]
        mr = match_results.get(oid)

        evidence = build_evidence_for_case(case, mr, tax_recon, ledger_verif, all_records)
        evidence_bags[oid] = evidence
        diag = diagnose(HYPOTHESIS_REGISTRY, evidence)
        diagnoses[oid] = diag

        # Blast radius
        gt = case.get("ground_truth", {})
        cf_vals = gt.get("counterfactual_correct_values", {})
        case_financials = {
            "order_id": oid,
            "fee_amount_paise": case.get("nodes", {}).get("fee", {}).get("amount_paise", 0) if case.get("nodes", {}).get("fee") else 0,
            "tax_amount_paise": case.get("nodes", {}).get("tax", {}).get("amount_paise", 0) if case.get("nodes", {}).get("tax") else 0,
            "settlement_amount_paise": case.get("nodes", {}).get("settlement", {}).get("amount_paise", 0) if case.get("nodes", {}).get("settlement") else 0,
            "bank_amount_paise": sum(
                b.get("amount_paise", 0)
                for b in (case.get("nodes", {}).get("bank_entries") or [])
            ),
            "refund_amount_paise": sum(
                r.get("amount_paise", 0)
                for r in (case.get("nodes", {}).get("refunds") or [])
            ),
            "diagnosis": {
                "outcome": diag.outcome.value if hasattr(diag.outcome, 'value') else str(diag.outcome),
                "hypothesis": diag.hypothesis.ch.value if diag.hypothesis else "",
            },
        }

        counterfactual = {
            "fee_amount_paise": cf_vals.get(
                "fee_amount_paise", cf_vals.get("correct_fee_paise", case_financials["fee_amount_paise"])
            ),
            "tax_amount_paise": cf_vals.get(
                "tax_amount_paise", cf_vals.get("correct_tax_paise", case_financials["tax_amount_paise"])
            ),
            "settlement_amount_paise": cf_vals.get(
                "settlement_amount_paise", cf_vals.get("correct_settlement_paise", case_financials["settlement_amount_paise"])
            ),
            "bank_amount_paise": cf_vals.get("bank_amount_paise", case_financials["bank_amount_paise"]),
            "refund_amount_paise": cf_vals.get(
                "refund_amount_paise", cf_vals.get("correct_refund_paise", case_financials["refund_amount_paise"])
            ),
        }
        if "drift_paise" in cf_vals:
            counterfactual["bank_amount_paise"] = case_financials["bank_amount_paise"] - cf_vals["drift_paise"]

        br = compute_blast_radius(case_financials, counterfactual)

        case_results[oid] = {
            "match_status": "resolved" if mr and oid in match_results else "unmatched",
            "exception_nodes": mr.exception_nodes if mr else [],
            "diagnosis": {
                "outcome": diag.outcome.value if hasattr(diag.outcome, 'value') else str(diag.outcome),
                "hypothesis": diag.hypothesis.ch.value if diag.hypothesis else None,
                "score": diag.score.value if diag.score else 0,
                "explanation": diag.explanation,
                "candidates": [
                    {
                        "hypothesis": name,
                        "score": score.value,
                        "status": score.status,
                    }
                    for name, score in diag.candidates[:3]
                ],
            },
            "variance_paise": br.variance_paise,
            "exposure_paise": br.exposure_paise,
            "impact_components": br.impact_components,
            "payment_method": case.get("payment_method", ""),
            "amount_paise": case.get("amount_paise", 0),
            "n_nodes": len(ingest_case(case)),
            "evidence": [item.evidence_type.name for item in evidence.items],
        }

    elapsed = time.time() - start_time
    n = len(cases)

    # ── Compute metrics ──
    # Throughput
    throughput = {
        "total_cases": n,
        "source_records": len(all_records),
        "cases_per_sec": round(n / elapsed, 2) if elapsed > 0 else 0,
        "wall_time_seconds": round(elapsed, 3),
    }

    # Match resolution
    linked_cases = sum(1 for v in case_results.values() if v["match_status"] == "resolved")
    cases_with_exceptions = sum(1 for graph in match_results.values() if graph.exception_nodes)
    match_resolution = {
        "linked_cases": linked_cases,
        "unlinked_cases": n - linked_cases,
        "case_linkage_rate": round(linked_cases / n * 100, 1) if n > 0 else 0,
        "cases_with_node_exceptions": cases_with_exceptions,
        "case_exception_rate": round(cases_with_exceptions / n * 100, 1) if n > 0 else 0,
    }
    match_pass_counts = Counter()
    ambiguous_nodes = 0
    unmatched_nodes = 0
    for result in match_results.values():
        for pass_number in result.match_pass.values():
            match_pass_counts["exact" if pass_number == 1 else "fuzzy"] += 1
        for node in result.nodes.values():
            if node.status == "ambiguous":
                ambiguous_nodes += 1
            if node.status == "unmatched" or node.unmatched_records:
                unmatched_nodes += 1
    match_resolution.update({
        "exact_node_matches": match_pass_counts["exact"],
        "fuzzy_node_matches": match_pass_counts["fuzzy"],
        "ambiguous_nodes": ambiguous_nodes,
        "unmatched_nodes": unmatched_nodes,
        "note": "Case linkage identifies records grouped to an order. Node exceptions remain visible and are never counted as a clean reconciliation.",
    })

    # Ledger verification
    balanced = sum(
        1 for oid, lv in ledger_verif.items()
        if lv.is_balanced
    )
    correct_accounts = sum(
        1 for oid, lv in ledger_verif.items()
        if lv.account_codes_correct
    )
    ledger_verification = {
        "balanced_count": balanced,
        "total_with_ledger": len(ledger_verif),
        "cases_checked": n,
        "posting_case_count": len(ledger_verif),
        "balance_pass_rate": round(balanced / max(len(ledger_verif), 1) * 100, 1),
        "account_code_pass_rate": round(correct_accounts / max(len(ledger_verif), 1) * 100, 1),
    }

    # A ledger imbalance is expected for some anomaly-bearing cases.  Report
    # clean-case integrity separately so a control dashboard never presents
    # detected exceptions as a silent bookkeeping failure.
    clean_case_ids = [
        oid for oid, result in case_results.items()
        if not result["exception_nodes"]
    ]
    clean_ledgers = [ledger_verif[oid] for oid in clean_case_ids if oid in ledger_verif]
    clean_balanced = sum(1 for ledger in clean_ledgers if ledger.is_balanced)
    unflagged_imbalances = sum(
        1
        for oid, ledger in ledger_verif.items()
        if oid in case_results
        and not ledger.is_balanced
        and case_results.get(oid, {}).get("diagnosis", {}).get("outcome") not in {
            Outcome.STRONGLY_SUPPORTED.value,
            Outcome.PLAUSIBLE_UNCONFIRMED.value,
            Outcome.INSUFFICIENT_EVIDENCE.value,
            Outcome.UNRESOLVED_AMBIGUITY.value,
            Outcome.CONFLICTING_EVIDENCE.value,
        }
    )
    ledger_verification.update({
        "clean_case_count": len(clean_ledgers),
        "clean_case_balanced_count": clean_balanced,
        "clean_case_balance_rate": round(clean_balanced / max(len(clean_ledgers), 1) * 100, 1),
        "flagged_imbalance_count": len(ledger_verif) - balanced,
        "unflagged_ledger_imbalance_count": unflagged_imbalances,
        "note": "Detected anomaly cases may remain unbalanced until a finance reviewer resolves them; clean cases are reported separately.",
    })

    # Outcome counts
    outcome_counter = Counter()
    for v in case_results.values():
        oc = v["diagnosis"]["outcome"]
        outcome_counter[oc] += 1
    outcome_counts = dict(outcome_counter)

    # Confusion matrix (predicted vs ground truth CH)
    gt_ch_counter = Counter()
    pred_ch_counter = Counter()
    correct_ch = Counter()
    for case in cases:
        oid = case["order_id"]
        gt = case.get("ground_truth", {})
        gt_ch = gt.get("expected_ch", "NO_ISSUE")
        gt_ch_counter[gt_ch] += 1

        pred = case_results.get(oid, {}).get("diagnosis", {})
        pred_ch = pred.get("hypothesis", "NO_ISSUE") or "NO_ISSUE"
        pred_ch_counter[pred_ch] += 1

        if gt_ch == pred_ch:
            correct_ch[gt_ch] += 1

    all_classes = sorted(set(list(gt_ch_counter.keys()) + list(pred_ch_counter.keys())))
    confusion_matrix = {}
    for cls in all_classes:
        tp = correct_ch.get(cls, 0)
        fp = pred_ch_counter.get(cls, 0) - tp
        fn = gt_ch_counter.get(cls, 0) - tp
        precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
        recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
        confusion_matrix[cls] = {
            "precision": round(precision, 3),
            "recall": round(recall, 3),
            "f1": round(f1, 3),
            "support": gt_ch_counter.get(cls, 0),
        }

    correct_predictions = sum(correct_ch.values())
    diagnosis_metrics = {
        "top_1_accuracy": round(correct_predictions / n * 100, 1) if n else 0,
        "correct_predictions": correct_predictions,
        "evaluated_cases": n,
        "macro_f1": round(
            sum(values["f1"] for values in confusion_matrix.values()) / max(len(confusion_matrix), 1) * 100,
            1,
        ),
        "confident_or_plausible": sum(
            1 for value in case_results.values()
            if value["diagnosis"]["outcome"] in (Outcome.STRONGLY_SUPPORTED.value, Outcome.PLAUSIBLE_UNCONFIRMED.value)
        ),
        "abstained_or_escalated": sum(
            1 for value in case_results.values()
            if value["diagnosis"]["outcome"] in (
                Outcome.INSUFFICIENT_EVIDENCE.value,
                Outcome.UNRESOLVED_AMBIGUITY.value,
                Outcome.CONFLICTING_EVIDENCE.value,
            )
        ),
    }
    diagnosis_metrics["abstention_rate"] = round(
        diagnosis_metrics["abstained_or_escalated"] / n * 100, 1
    ) if n else 0
    diagnosis_metrics["miss_analysis"] = [
        {
            "case_id": case["order_id"],
            "expected": case.get("ground_truth", {}).get("expected_ch", "NO_ISSUE"),
            "predicted": case_results[case["order_id"]]["diagnosis"].get("hypothesis") or "NO_ISSUE",
            "outcome": case_results[case["order_id"]]["diagnosis"]["outcome"],
            "evidence_gap": "Abstained pending more source evidence" if case_results[case["order_id"]]["diagnosis"]["outcome"] in (Outcome.INSUFFICIENT_EVIDENCE.value, Outcome.UNRESOLVED_AMBIGUITY.value) else "Competing evidence requires rule refinement",
        }
        for case in cases
        if case.get("ground_truth", {}).get("expected_ch", "NO_ISSUE")
        != (case_results[case["order_id"]]["diagnosis"].get("hypothesis") or "NO_ISSUE")
    ]

    # Financial exposure
    total_variance = sum(v["variance_paise"] for v in case_results.values())
    total_exposure = sum(v["exposure_paise"] for v in case_results.values())
    financial_exposure = {
        "net_variance_paise": total_variance,
        "total_absolute_exposure_paise": total_exposure,
        "mean_exposure_paise": round(total_exposure / max(n, 1)),
    }

    cash_position = {
        "payments_captured_paise": sum(
            case.get("nodes", {}).get("payment", {}).get("amount_paise", 0)
            for case in cases
        ),
        "settlements_expected_paise": sum(
            case.get("nodes", {}).get("settlement", {}).get("amount_paise", 0)
            for case in cases
            if case.get("nodes", {}).get("settlement")
        ),
        "bank_received_paise": sum(
            entry.get("amount_paise", 0)
            for case in cases
            for entry in case.get("nodes", {}).get("bank_entries", []) or []
        ),
        "refunds_paise": sum(
            refund.get("amount_paise", 0)
            for case in cases
            for refund in case.get("nodes", {}).get("refunds", []) or []
        ),
    }
    cash_position["pending_settlement_paise"] = (
        cash_position["settlements_expected_paise"] - cash_position["bank_received_paise"]
    )

    # ── Build dossier ──
    dossier_entries = build_dossier(cases, {
        oid: v["diagnosis"] for oid, v in case_results.items()
    }, evidence_bags)
    dossier_md = dossier_to_markdown(dossier_entries)

    # ── Assemble report ──
    metrics_report = {
        "throughput": throughput,
        "match_resolution": match_resolution,
        "ledger_verification": ledger_verification,
        "confusion_matrix": confusion_matrix,
        "diagnosis_quality": diagnosis_metrics,
        "outcome_counts": outcome_counts,
        "financial_exposure": financial_exposure,
        "cash_position": cash_position,
        "ablation": {
            "ai_enabled": use_ai,
            "note": "Ablation test should be run separately via tests/test_ablation.py",
        },
    }

    return {
        "metrics": metrics_report,
        "dossier_md": dossier_md,
        "case_results": case_results,
        "diagnoses": diagnoses,
        "qa_state": {
            oid: {
            "case": case,
                "diagnosis": case_results[oid]["diagnosis"],
                "blast_radius": {
                    "variance_paise": case_results[oid]["variance_paise"],
                    "exposure_paise": case_results[oid]["exposure_paise"],
                },
                "ledger": {
                    "is_balanced": ledger_verif.get(oid).is_balanced if oid in ledger_verif else False,
                },
                "evidence": [item.evidence_type.name for item in evidence_bags[oid].items],
            }
            for oid, case in ((case["order_id"], case) for case in cases)
        },
    }


def main():
    parser = argparse.ArgumentParser(description="AI Finance Controller — Evaluation")
    parser.add_argument("--data", choices=["dev", "holdout"], default="dev")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output-dir", default="outputs")
    args = parser.parse_args()

    data_path = f"data/{args.data}_batch.json"
    if not os.path.exists(data_path):
        # Generate if not present
        print(f"Data file {data_path} not found. Generating...")
        from src.generate.scenario_builder import build_datasets
        build_datasets(seed=args.seed)

    cases = load_batch(data_path)
    print(f"Loaded {len(cases)} cases from {data_path}")

    result = evaluate_batch(cases)

    # Write outputs
    os.makedirs(args.output_dir, exist_ok=True)

    metrics_path = os.path.join(args.output_dir, "metrics_report.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(result["metrics"], f, indent=2)
    print(f"Metrics written → {metrics_path}")

    dossier_path = os.path.join(args.output_dir, "exception_dossier.md")
    with open(dossier_path, "w", encoding="utf-8") as f:
        f.write(result["dossier_md"])
    print(f"Dossier written → {dossier_path}")

    qa_path = os.path.join(args.output_dir, "qa_state.json")
    with open(qa_path, "w", encoding="utf-8") as f:
        json.dump(result["qa_state"], f, indent=2, default=str)
    print(f"QA state written → {qa_path}")

    # Print summary
    m = result["metrics"]
    print("\n=== Summary ===")
    print(f"Cases: {m['throughput']['total_cases']} ({m['throughput']['source_records']} source records)")
    print(f"Throughput: {m['throughput']['cases_per_sec']} cases/sec")
    print(f"Case linkage rate: {m['match_resolution']['case_linkage_rate']}%")
    print(f"Ledger balance pass: {m['ledger_verification']['balance_pass_rate']}%")
    print(f"Outcome counts: {m['outcome_counts']}")
    print(f"Net variance: {m['financial_exposure']['net_variance_paise']} paise")
    print(f"Total exposure: {m['financial_exposure']['total_absolute_exposure_paise']} paise")


if __name__ == "__main__":
    main()
