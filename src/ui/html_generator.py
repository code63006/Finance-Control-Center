#!/usr/bin/env python3
"""
Reads outputs/metrics_report.json + outputs/exception_dossier.md
and generates a self-contained outputs/report.html.
"""
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

from src.config.pricing_rules import settlement_delay


def _get(d, *keys, default="N/A"):
    """Safely traverse nested dicts; return default on any KeyError."""
    cur = d
    for k in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(k, default)
    return cur if cur is not default else default


def _table(headers, rows):
    """Render an HTML table."""
    hdr = "".join(f"<th>{h}</th>" for h in headers)
    body = ""
    for row in rows:
        body += "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>\n"
    return f'<table class="tbl"><thead><tr>{hdr}</tr></thead><tbody>\n{body}</tbody></table>\n'


def _md_to_html(md_text):
    """Minimal markdown → HTML: headings, bullets, bold, code, paragraphs."""
    lines = md_text.split("\n")
    html_lines = []
    in_list = False
    for line in lines:
        escaped = line.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        if escaped.startswith("### "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h3>{escaped[4:]}</h3>")
        elif escaped.startswith("## "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h2>{escaped[3:]}</h2>")
        elif escaped.startswith("# "):
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<h1>{escaped[2:]}</h1>")
        elif escaped.startswith("- "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            content = escaped[2:]
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            content = re.sub(r"`(.*?)`", r"<code>\1</code>", content)
            html_lines.append(f"<li>{content}</li>")
        elif re.match(r"^\d+\. ", escaped):
            content = re.sub(r"^\d+\. ", "", escaped)
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            if not in_list:
                html_lines.append("<ol>")
                in_list = True
            html_lines.append(f"<li>{content}</li>")
        elif escaped.strip() == "":
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            escaped = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", escaped)
            escaped = re.sub(r"`(.*?)`", r"<code>\1</code>", escaped)
            html_lines.append(f"<p>{escaped}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
       max-width: 960px; margin: 0 auto; padding: 20px; background: #fafafa; color: #333; }
h1 { color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 10px; }
h2 { color: #16213e; margin-top: 30px; }
h3 { color: #0f3460; }
.tbl { border-collapse: collapse; width: 100%; margin: 15px 0; }
.tbl th, .tbl td { border: 1px solid #ddd; padding: 8px 12px; text-align: left; }
.tbl th { background: #16213e; color: white; }
.tbl tr:nth-child(even) { background: #f2f2f2; }
.metric-card { background: white; border-radius: 8px; padding: 15px; margin: 10px 0;
               box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
code { background: #eee; padding: 2px 5px; border-radius: 3px; font-size: 0.9em; }
.pass { color: #27ae60; font-weight: bold; }
.fail { color: #e74c3c; font-weight: bold; }
"""


def generate_report(
    metrics_path="outputs/metrics_report.json",
    dossier_path="outputs/exception_dossier.md",
    output_path="outputs/report.html",
):
    """Generate the HTML report."""
    # Load metrics
    metrics = {}
    if os.path.exists(metrics_path):
        with open(metrics_path) as f:
            metrics = json.load(f)
    else:
        print(f"WARNING: {metrics_path} not found", file=sys.stderr)

    # Load dossier
    dossier_md = ""
    if os.path.exists(dossier_path):
        with open(dossier_path) as f:
            dossier_md = f.read()
    else:
        print(f"WARNING: {dossier_path} not found", file=sys.stderr)

    # Build HTML sections
    sections = []

    # ── Throughput ──
    sections.append("<h2>Throughput</h2>")
    sections.append("<div class='metric-card'>")
    sections.append(_table(
        ["Metric", "Value"],
        [
            ["Total Records", _get(metrics, "throughput", "total_records")],
            ["Records/sec", _get(metrics, "throughput", "records_per_sec")],
        ]
    ))
    sections.append("</div>")

    # ── Match Resolution ──
    sections.append("<h2>Match Resolution</h2>")
    sections.append("<div class='metric-card'>")
    mr = _get(metrics, "match_resolution", default={})
    rows = []
    for k, v in mr.items():
        rows.append([k, v])
    if rows:
        sections.append(_table(["Metric", "Value"], rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Ledger Verification ──
    sections.append("<h2>Ledger Verification</h2>")
    sections.append("<div class='metric-card'>")
    lv = _get(metrics, "ledger_verification", default={})
    rows = []
    for k, v in lv.items():
        rows.append([k, v])
    if rows:
        sections.append(_table(["Check", "Result"], rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Confusion Matrix ──
    sections.append("<h2>Confusion Matrix (Precision/Recall per CH)</h2>")
    sections.append("<div class='metric-card'>")
    cm = _get(metrics, "confusion_matrix", default={})
    if cm:
        headers = ["Class", "Precision", "Recall", "F1", "Support"]
        rows = []
        for cls_name, vals in cm.items():
            rows.append([
                cls_name,
                _get(vals, "precision", default="N/A"),
                _get(vals, "recall", default="N/A"),
                _get(vals, "f1", default="N/A"),
                _get(vals, "support", default="N/A"),
            ])
        sections.append(_table(headers, rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Outcome Vocabulary Counts ──
    sections.append("<h2>Outcome Vocabulary</h2>")
    sections.append("<div class='metric-card'>")
    oc = _get(metrics, "outcome_counts", default={})
    if oc:
        rows = [[k, v] for k, v in oc.items()]
        sections.append(_table(["Outcome", "Count"], rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Financial Exposure ──
    sections.append("<h2>Financial Exposure</h2>")
    sections.append("<div class='metric-card'>")
    fe = _get(metrics, "financial_exposure", default={})
    rows = []
    for k, v in fe.items():
        rows.append([k, v])
    if rows:
        sections.append(_table(["Metric", "Value"], rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Ablation ──
    sections.append("<h2>Ablation Study</h2>")
    sections.append("<div class='metric-card'>")
    abl = _get(metrics, "ablation", default={})
    rows = []
    for k, v in abl.items():
        if isinstance(v, dict):
            for sk, sv in v.items():
                rows.append([f"{k} / {sk}", sv])
        else:
            rows.append([k, v])
    if rows:
        sections.append(_table(["Metric", "Value"], rows))
    else:
        sections.append("<p>N/A</p>")
    sections.append("</div>")

    # ── Exception Dossier ──
    sections.append("<h2>Exception Dossier</h2>")
    sections.append("<div class='metric-card'>")
    if dossier_md:
        sections.append(_md_to_html(dossier_md))
    else:
        sections.append("<p>No dossier generated.</p>")
    sections.append("</div>")

    # ── Assemble ──
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI Finance Controller — Reconciliation Report</title>
<style>{CSS}</style>
</head>
<body>
<h1>AI Finance Controller — Reconciliation Report</h1>
<p>Generated by <code>evaluate_recon.py</code>. All metrics computed from synthetic data.</p>
{"".join(sections)}
<hr>
<p><small>AI Finance Controller — Razorpay Buildathon Submission</small></p>
</body>
</html>"""

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w") as f:
        f.write(html)
    print(f"Report generated → {output_path}")


def _escape(value):
    """Escape values inserted into the self-contained dashboard."""
    import html
    return html.escape(str(value), quote=True)


def _money(paise):
    try:
        amount = float(paise) / 100
    except (TypeError, ValueError):
        amount = 0
    return f"₹{amount:,.2f}"


def _parse_timestamp(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _format_ist(value):
    """Render source timestamps in the finance team's operating timezone."""
    timestamp = _parse_timestamp(value)
    if not timestamp:
        return "Not available"
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    # IST is a fixed UTC+05:30 offset and needs no optional timezone database.
    local = timestamp.astimezone(timezone(timedelta(hours=5, minutes=30)))
    return local.strftime("%d %b %Y, ") + str(int(local.strftime("%I"))) + local.strftime(":%M %p IST")


def _severity(exposure_paise, outcome):
    if exposure_paise >= 100_000:
        return "Critical"
    if exposure_paise >= 25_000:
        return "High"
    if "AMBIGUITY" in outcome or exposure_paise > 0:
        return "Medium"
    return "Low"


def _exception_rows(dossier_md, qa_state=None):
    rows = []
    chunks = re.split(r"^## (.+)$", dossier_md, flags=re.MULTILINE)
    for index in range(1, len(chunks), 2):
        case_id = chunks[index].strip()
        body = chunks[index + 1]
        outcome = re.search(r"\*\*Outcome:\*\* (.+)", body)
        fod = re.search(r"\*\*FOD Point:\*\* (.+)", body)
        hypothesis = re.search(r"\*\*Best Hypothesis:\*\* (.+)", body)
        score = re.search(r"\*\*Score:\*\* (.+)", body)
        rows.append({
            "case_id": case_id,
            "outcome": outcome.group(1).strip() if outcome else "UNKNOWN",
            "fod": fod.group(1).strip() if fod else "N/A",
            "hypothesis": hypothesis.group(1).strip() if hypothesis else "N/A",
            "score": score.group(1).strip() if score else "N/A",
        })
        if qa_state and case_id in qa_state:
            case = qa_state[case_id].get("case", {})
            row = rows[-1]
            row["amount"] = _money(case.get("amount_paise", 0))
            row["evidence"] = _friendly_evidence(qa_state[case_id].get("evidence", [])) or "None"
            row["action"] = {
                "INSUFFICIENT_EVIDENCE": "Request source audit trail",
                "UNRESOLVED_AMBIGUITY": "Review competing hypotheses",
                "CONFLICTING_EVIDENCE": "Escalate source conflict",
            }.get(row["outcome"], "Review")
            row["exposure_paise"] = qa_state[case_id].get("blast_radius", {}).get("exposure_paise", 0)

    # The investigation queue includes the designated high-impact demo case
    # even when its diagnosis is strong. The dossier stays reserved for cases
    # that require human evidence; the queue is the finance team's risk view.
    known_case_ids = {row["case_id"] for row in rows}
    for case_id, state in (qa_state or {}).items():
        case = state.get("case", {})
        if not case.get("demo_priority") or case_id in known_case_ids:
            continue
        diagnosis = state.get("diagnosis", {})
        rows.append({
            "case_id": case_id,
            "outcome": diagnosis.get("outcome", "UNKNOWN"),
            "fod": "bank receipt",
            "hypothesis": diagnosis.get("hypothesis") or "N/A",
            "score": f'{diagnosis.get("score", 0):.4f}',
            "amount": _money(case.get("amount_paise", 0)),
            "evidence": _friendly_evidence(state.get("evidence", [])) or "None",
            "action": "Hold booking and request settlement advice",
            "exposure_paise": state.get("blast_radius", {}).get("exposure_paise", 0),
        })
    return sorted(rows, key=lambda row: row.get("exposure_paise", 0), reverse=True)


def _friendly_evidence(values):
    labels = {
        "FEE_NODE_MATCHED": "Fee record found",
        "FEE_NODE_MISSING": "Fee record missing",
        "TAX_NODE_MATCHED": "Tax record found",
        "TAX_MISMATCH": "Tax amount differs",
        "PROVENANCE_CLEAN": "Source timing valid",
        "PROVENANCE_VIOLATION": "Source timing conflict",
        "AMOUNT_MATCHED": "Amounts agree",
        "AMOUNT_MISMATCH": "Amounts differ",
        "LEDGER_BALANCED": "Ledger balances",
        "LEDGER_IMBALANCE": "Ledger imbalance",
        "SETTLEMENT_NODE_MATCHED": "Settlement found",
        "BANK_ENTRY_MATCHED": "Bank entry found",
        "BANK_ENTRY_ORPHANED": "Bank entry lacks settlement link",
        "PAYMENT_DUPLICATE_DETECTED": "Duplicate payment signal",
    }
    return ", ".join(labels.get(value, value.replace("_", " ").title()) for value in values[:4])


def _investigation_guidance(state, row, actual_paise):
    """Translate deterministic diagnosis outputs into finance-review guidance."""
    diagnosis = state.get("diagnosis", {})
    outcome = diagnosis.get("outcome", "UNKNOWN")
    hypothesis = diagnosis.get("hypothesis") or ""
    candidates = diagnosis.get("candidates", [])
    alternatives = [
        f'{item.get("hypothesis", "unknown").replace("_", " ").title()} ({item.get("score", 0):.0%})'
        for item in candidates
        if item.get("hypothesis") != hypothesis
    ]
    evidence = state.get("evidence", [])
    if actual_paise == 0 and "AMOUNT_MISMATCH" in evidence:
        missing = "Bank statement line and processor settlement advice"
        decision = "Hold"
        rationale = "Do not book the settlement until the expected receipt is verified."
    elif outcome in ("INSUFFICIENT_EVIDENCE", "UNRESOLVED_AMBIGUITY", "CONFLICTING_EVIDENCE"):
        missing = "Source-specific audit trail needed to distinguish the candidate causes"
        decision = "Escalate" if outcome == "CONFLICTING_EVIDENCE" else "Hold"
        rationale = "Do not post an adjustment while the evidence is incomplete or ambiguous."
    elif hypothesis in ("AMOUNT_DRIFT", "SOURCE_CONFLICT"):
        missing = "Settlement advice or bank confirmation before any adjustment"
        decision = "Hold"
        rationale = "A cash variance is present and needs source confirmation."
    else:
        missing = "No additional evidence required for the current diagnosis"
        decision = "Book" if outcome == "STRONGLY_SUPPORTED" else "Hold"
        rationale = "Use the documented evidence and route the exception to the responsible owner."
    confidence = diagnosis.get("score", 0)
    confidence_label = "High" if confidence >= 0.85 else "Medium" if confidence >= 0.5 else "Low"
    return {
        "competing_causes": "; ".join(alternatives) or "No material competing cause identified",
        "missing_evidence": missing,
        "decision": decision,
        "decision_rationale": rationale,
        "confidence": f"{confidence_label} ({confidence:.0%})",
    }


def generate_dashboard_report(
    metrics_path="outputs/metrics_report.json",
    dossier_path="outputs/exception_dossier.md",
    output_path="outputs/report.html",
):
    """Generate the operational control-center dashboard."""
    with open(metrics_path, encoding="utf-8") as handle:
        metrics = json.load(handle)
    with open(dossier_path, encoding="utf-8") as handle:
        dossier_md = handle.read()
    qa_state_path = os.path.join(os.path.dirname(metrics_path), "qa_state.json")
    qa_state = {}
    if os.path.exists(qa_state_path):
        with open(qa_state_path, encoding="utf-8") as handle:
            qa_state = json.load(handle)

    throughput = metrics.get("throughput", {})
    resolution = metrics.get("match_resolution", {})
    ledger = metrics.get("ledger_verification", {})
    exposure = metrics.get("financial_exposure", {})
    cash = metrics.get("cash_position", {})
    outcomes = metrics.get("outcome_counts", {})
    holdout_metrics_path = os.path.join(os.path.dirname(metrics_path), "holdout", "metrics_report.json")
    holdout = {}
    if os.path.exists(holdout_metrics_path):
        with open(holdout_metrics_path, encoding="utf-8") as handle:
            holdout = json.load(handle)
    exceptions = _exception_rows(dossier_md, qa_state)
    flagship_case_id = next(
        (case_id for case_id, state in qa_state.items() if state.get("case", {}).get("demo_priority") is True),
        exceptions[0]["case_id"] if exceptions else "",
    )
    total = throughput.get("total_cases", throughput.get("total_records", 0))
    source_records = throughput.get("source_records", total)
    cases_per_sec = throughput.get("cases_per_sec", throughput.get("records_per_sec", 0))
    quality = metrics.get("diagnosis_quality", {})
    unresolved = quality.get("abstained_or_escalated", sum(
        outcomes.get(key, 0)
        for key in ("INSUFFICIENT_EVIDENCE", "UNRESOLVED_AMBIGUITY", "PLAUSIBLE_UNCONFIRMED", "CONFLICTING_EVIDENCE")
    ))
    diagnosed = quality.get("confident_or_plausible", max(total - unresolved, 0))
    diagnosis_coverage = round(diagnosed / total * 100, 1) if total else 0
    ledger_rate = ledger.get("balance_pass_rate", 0)
    clean_ledger_rate = ledger.get("clean_case_balance_rate", 0)
    clean_ledger_count = ledger.get("clean_case_count", 0)
    clean_balanced_count = ledger.get("clean_case_balanced_count", 0)
    flagged_imbalances = ledger.get("flagged_imbalance_count", 0)
    silent_failures = ledger.get("unflagged_ledger_imbalance_count", 0)
    linkage_rate = resolution.get("case_linkage_rate", resolution.get("resolution_rate", 0))
    node_exception_rate = resolution.get("case_exception_rate", 0)
    exposure_value = exposure.get("total_absolute_exposure_paise", 0)
    pending_cash = cash.get("pending_settlement_paise", 0)
    holdout_resolution = holdout.get("match_resolution", {}).get("case_linkage_rate")
    confusion = metrics.get("confusion_matrix", {})
    holdout_confusion = holdout.get("confusion_matrix", {})
    macro_f1 = round(sum(item.get("f1", 0) for item in confusion.values()) / max(len(confusion), 1) * 100, 1)
    holdout_macro_f1 = round(sum(item.get("f1", 0) for item in holdout_confusion.values()) / max(len(holdout_confusion), 1) * 100, 1)
    holdout_quality = holdout.get("diagnosis_quality", {})
    holdout_accuracy = holdout_quality.get("top_1_accuracy", 0)
    cash_label = "Pending settlement" if pending_cash >= 0 else "Over-received cash"
    holdout_label = (
        f"Holdout linkage is {holdout_resolution}% across "
        f"{holdout.get('throughput', {}).get('total_cases', 0)} cases."
        if holdout_resolution is not None else "Holdout benchmark has not been generated."
    )
    status = "REVIEW REQUIRED" if unresolved or ledger_rate < 100 else "CONTROL CLEAR"
    status_class = "review" if status == "REVIEW REQUIRED" else "clear"

    outcome_order = [
        ("INSUFFICIENT_EVIDENCE", "Insufficient evidence", "amber"),
        ("UNRESOLVED_AMBIGUITY", "Unresolved ambiguity", "coral"),
        ("PLAUSIBLE_UNCONFIRMED", "Plausible, unconfirmed", "blue"),
        ("CONFLICTING_EVIDENCE", "Conflicting evidence", "red"),
    ]
    outcome_rows = []
    for key, label, color in outcome_order:
        count = outcomes.get(key, 0)
        width = round((count / total) * 100) if total else 0
        outcome_rows.append(
            f'<div class="bar-row"><span>{label}</span><strong>{count}</strong>'
            f'<div class="bar-track"><i class="{color}" style="width:{width}%"></i></div></div>'
        )
    case_details = {}
    for row in exceptions:
        state = qa_state.get(row["case_id"], {})
        case = state.get("case", {})
        nodes = case.get("nodes", {})
        expected = (nodes.get("settlement") or {}).get("amount_paise", 0)
        actual = sum(item.get("amount_paise", 0) for item in nodes.get("bank_entries", []) or [])
        timeline_events = []
        event_times = []
        for label, node in (("Order", nodes.get("order")), ("Payment", nodes.get("payment")), ("Settlement", nodes.get("settlement"))):
            if node and node.get("timestamp"):
                timeline_events.append(f"{label}: {_format_ist(node['timestamp'])}")
                event_times.append(_parse_timestamp(node["timestamp"]))
        for bank in nodes.get("bank_entries", []) or []:
            if bank.get("timestamp"):
                timeline_events.append(f"Bank: {_format_ist(bank['timestamp'])}")
                event_times.append(_parse_timestamp(bank["timestamp"]))
        event_times = [timestamp for timestamp in event_times if timestamp]
        payment_time = _parse_timestamp((nodes.get("payment") or {}).get("timestamp"))
        settlement_time = _parse_timestamp((nodes.get("settlement") or {}).get("timestamp"))
        if not settlement_time:
            sla_status = "Awaiting settlement evidence"
        elif payment_time:
            due_at = payment_time + timedelta(days=settlement_delay(case.get("payment_method", "card")))
            late_by = settlement_time - due_at
            sla_status = (
                f"SLA breached by {late_by.days} day(s)"
                if late_by.total_seconds() > 0 else "Within settlement SLA"
            )
        else:
            sla_status = "Payment time unavailable"
        if len(event_times) >= 2:
            span = max(event_times) - min(event_times)
            source_span = f"{span.days}d {span.seconds // 3600}h within batch"
        else:
            source_span = "Not enough source timestamps"
        row["severity"] = _severity(row.get("exposure_paise", 0), row["outcome"])
        row["sla_status"] = sla_status
        guidance = _investigation_guidance(state, row, actual)
        case_details[row["case_id"]] = {
            "case": row["case_id"], "status": row["outcome"].replace("_", " "),
            "cause": row["hypothesis"].replace("_", " "), "first_divergence": row["fod"],
            "expected": _money(expected), "actual": _money(actual),
            "variance": _money(state.get("blast_radius", {}).get("variance_paise", 0)),
            "evidence": row.get("evidence", "No evidence summary available"),
            "timeline": " · ".join(timeline_events) or "No source timeline available",
            "source_span": source_span,
            "severity": row["severity"],
            "sla_status": sla_status,
            "recommendation": row.get("action", "Review the source audit trail"),
            **guidance,
        }
    case_details_json = json.dumps(case_details).replace("</", "<\\/")
    confusion_rows = "".join(
        f'<tr><td>{_escape(name)}</td><td>{values.get("precision", 0):.3f}</td>'
        f'<td>{values.get("recall", 0):.3f}</td><td>{values.get("f1", 0):.3f}</td>'
        f'<td>{values.get("support", 0)}</td></tr>'
        for name, values in sorted(holdout_confusion.items())
    )

    exception_html = []
    for row in exceptions:
        outcome_class = "danger" if "AMBIGUITY" in row["outcome"] else "warning"
        exception_html.append(
            f'<tr data-search="{_escape(" ".join(str(value) for value in row.values()))}">'
            f'<td><strong>{_escape(row["case_id"])}</strong></td>'
            f'<td><span class="pill {outcome_class}">{_escape(row["outcome"].replace("_", " "))}</span></td>'
            f'<td>{_escape(row["fod"])}</td><td>{_escape(row["hypothesis"].replace("_", " "))}</td>'
            f'<td class="mono">{_escape(row["score"])}</td></tr>'
        )
    if not exception_html:
        exception_html.append('<tr><td colspan="5" class="empty">No unresolved cases in this batch.</td></tr>')

    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Finance Control Center</title>
<style>
:root {{ --ink:#17212b; --muted:#687580; --line:#dce3e7; --paper:#f5f7f6; --white:#fff;
 --navy:#18324a; --mint:#1c8c78; --amber:#d99025; --coral:#d95d53; --blue:#4c7ea8; }}
* {{ box-sizing:border-box; }} body {{ margin:0; background:var(--paper); color:var(--ink);
 font-family:"Trebuchet MS", "Segoe UI", sans-serif; letter-spacing:0; }}
.shell {{ display:grid; grid-template-columns:240px 1fr; min-height:100vh; }}
aside {{ background:var(--navy); color:#dbe7ed; padding:28px 20px; display:flex; flex-direction:column; gap:28px; }}
.brand {{ color:white; font-family:Georgia,serif; font-size:23px; line-height:1.05; }}
.brand small {{ display:block; color:#96b4be; font:11px "Trebuchet MS",sans-serif; letter-spacing:1.5px; margin-top:8px; text-transform:uppercase; }}
nav {{ display:grid; gap:6px; }} nav a {{ color:#b5c8d0; padding:12px 13px; text-decoration:none; border-left:3px solid transparent; }}
nav a.active, nav a:hover {{ color:white; background:#24465f; border-left-color:#edb45b; }}
.side-note {{ margin-top:auto; border-top:1px solid #31536a; padding-top:18px; color:#9eb4be; font-size:12px; line-height:1.5; }}
main {{ max-width:1500px; width:100%; padding:34px 44px 60px; }}
.topline {{ display:flex; justify-content:space-between; align-items:flex-start; gap:20px; margin-bottom:28px; }}
h1 {{ margin:0 0 8px; font:700 42px/1.05 Georgia,serif; color:var(--navy); }}
.subtitle {{ color:var(--muted); margin:0; }} .status {{ padding:11px 15px; border-radius:3px; font-size:12px; font-weight:bold; letter-spacing:1px; white-space:nowrap; }}
.status.review {{ background:#fff0d8; color:#985b08; }} .status.clear {{ background:#dff4ed; color:#14715f; }}
.notice {{ border-left:4px solid var(--amber); background:#fffaf0; padding:13px 16px; margin-bottom:22px; color:#6e552c; font-size:13px; }}
.kpis {{ display:grid; grid-template-columns:repeat(6,1fr); gap:12px; margin-bottom:25px; }}
.kpi {{ background:var(--white); border:1px solid var(--line); padding:18px; min-height:118px; }}
.kpi .label {{ color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:1px; }}
.kpi .value {{ display:block; color:var(--navy); font:700 30px Georgia,serif; margin:12px 0 4px; }}
.kpi .meta {{ font-size:12px; color:var(--muted); }} .kpi.alert .value {{ color:var(--coral); }} .kpi.good .value {{ color:var(--mint); }}
.grid {{ display:grid; grid-template-columns:1.3fr .7fr; gap:18px; margin-bottom:18px; }}
.panel {{ background:var(--white); border:1px solid var(--line); padding:22px; }}
.panel h2 {{ color:var(--navy); font:700 21px Georgia,serif; margin:0 0 5px; }} .panel .hint {{ color:var(--muted); font-size:12px; margin-bottom:18px; }}
.bar-row {{ display:grid; grid-template-columns:190px 35px 1fr; align-items:center; gap:10px; margin:15px 0; font-size:13px; }}
.bar-row strong {{ text-align:right; color:var(--navy); }} .bar-track {{ height:10px; background:#edf1f2; overflow:hidden; }} .bar-track i {{ display:block; height:100%; }}
.amber {{ background:var(--amber); }} .coral {{ background:var(--coral); }} .blue {{ background:var(--blue); }} .red {{ background:#a33d49; }}
.health {{ display:grid; gap:16px; }} .health-line {{ display:flex; justify-content:space-between; font-size:13px; }} .health-line b {{ color:var(--navy); }}
.meter {{ height:8px; background:#edf1f2; margin-top:7px; }} .meter i {{ display:block; height:100%; background:var(--mint); }} .meter.warn i {{ background:var(--amber); }}
.queue {{ margin-top:18px; }} .queue-head {{ display:flex; justify-content:space-between; align-items:end; gap:15px; margin-bottom:16px; }}
.queue-head input, .queue-head select {{ border:1px solid var(--line); padding:10px; background:white; color:var(--ink); }}
.queue-head input {{ min-width:240px; }} table {{ border-collapse:collapse; width:100%; font-size:13px; }} th {{ color:var(--muted); text-align:left; font-size:11px; letter-spacing:.8px; text-transform:uppercase; padding:11px 10px; border-bottom:2px solid var(--line); }} td {{ padding:13px 10px; border-bottom:1px solid #edf0f1; }} tr:hover td {{ background:#f8fbfa; }}
.pill {{ display:inline-block; padding:5px 8px; font-size:10px; font-weight:bold; letter-spacing:.5px; }} .pill.warning {{ color:#8b5a10; background:#fff0d8; }} .pill.danger {{ color:#963f39; background:#fde4e0; }}
.mono {{ font-family:Consolas,monospace; }} .empty {{ color:var(--muted); text-align:center; padding:28px; }}
.investigate {{ border:1px solid var(--navy); background:white; color:var(--navy); padding:7px 9px; cursor:pointer; font:inherit; font-size:12px; }} .investigate:hover {{ background:#edf4f6; }}
.case-detail {{ margin-top:18px; border-left:4px solid var(--mint); }} .case-detail[hidden] {{ display:none; }} .detail-grid {{ display:grid; grid-template-columns:repeat(3,1fr); gap:12px; margin-top:15px; }} .detail-item {{ background:#f7faf9; padding:12px; }} .detail-item span {{ display:block; color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.7px; margin-bottom:5px; }} .detail-actions {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:16px; }}
.qa {{ margin-top:18px; }} .qa-form {{ display:flex; gap:10px; }} .qa-form input {{ flex:1; border:1px solid var(--line); padding:12px; font:inherit; }} .qa-form button {{ border:0; background:var(--navy); color:white; padding:0 20px; cursor:pointer; }} .qa-answer {{ margin-top:14px; padding:15px; background:#f1f7f5; color:var(--navy); min-height:48px; white-space:pre-wrap; }}
footer {{ color:var(--muted); font-size:11px; margin-top:25px; display:flex; justify-content:space-between; }}
@media(max-width:1200px) {{ .kpis {{ grid-template-columns:repeat(3,1fr); }} }}
@media(max-width:1000px) {{ .shell {{ grid-template-columns:1fr; }} aside {{ padding:16px 20px; }} nav {{ display:flex; flex-wrap:wrap; overflow:visible; }} .side-note {{ display:none; }} main {{ padding:25px 20px 45px; }} .kpis {{ grid-template-columns:repeat(2,1fr); }} .grid {{ grid-template-columns:1fr; }} }}
@media(max-width:600px) {{ h1 {{ font-size:32px; }} .topline {{ display:block; }} .status {{ display:inline-block; margin-top:16px; }} .kpis {{ grid-template-columns:1fr; }} .bar-row {{ grid-template-columns:145px 25px 1fr; }} .queue-head {{ display:block; }} .queue-head input, .queue-head select {{ width:100%; margin-top:8px; }} table {{ min-width:700px; }} .table-wrap {{ overflow-x:auto; }} }}
</style></head><body>
<div class="shell"><aside><div class="brand">Finance<br>Control Center<small>Reconciliation command view</small></div>
<nav><a class="active" href="#overview">Overview</a><a href="#exceptions">Exception queue</a><a href="#accuracy">Holdout quality</a><a href="#health">Control health</a><a href="#qa">Ask controller</a></nav>
<div class="side-note">Synthetic benchmark mode<br>Batch size: {_escape(total)} cases<br>Generated by evaluate_recon.py</div></aside>
<main id="overview"><div class="topline"><div><h1>Control room</h1><p class="subtitle">Know what reconciled, what did not, and where human review belongs.</p></div><div class="status {status_class}">{status}</div></div>
<div class="notice"><strong>Close status:</strong> {unresolved} cases require human evidence review; {diagnosed} have a supported or plausible diagnosis. Exposure is {_money(exposure_value)} and {cash_label.lower()} is {_money(abs(pending_cash))}. <span>Holdout top-1 accuracy: {holdout_accuracy}%; macro-F1: {holdout_macro_f1}%.</span></div>
<div class="notice"><strong>Demo focus:</strong> ₹8.30 lakh expected card settlement with no matching bank receipt. <a href="#exceptions">Inspect the highest-impact exception</a>.</div>
<section class="panel" id="sources"><h2>Input sources</h2><div class="hint">Local demo imports are validated before reconciliation. This is sample workflow state only; no external systems are connected.</div><div class="detail-grid"><div class="detail-item"><span>Payment gateway export</span><strong>Validated gateway transactions</strong></div><div class="detail-item"><span>Settlement report</span><strong>Expected settlement records</strong></div><div class="detail-item"><span>Bank statement CSV</span><strong>Bank receipt records</strong></div></div><div class="detail-grid"><div class="detail-item"><span>Refund export</span><strong>Refund and reversal records</strong></div><div class="detail-item"><span>ERP / ledger export</span><strong>Posting and account-code records</strong></div><div class="detail-item"><span>Validation result</span><strong>{source_records} source records accepted · lineage retained</strong></div></div></section>
<section class="kpis"><div class="kpi"><span class="label">Cases processed</span><span class="value">{total}</span><span class="meta">{source_records} source records · {cases_per_sec} cases/sec</span></div>
<div class="kpi good"><span class="label">Diagnosis coverage</span><span class="value">{diagnosis_coverage}%</span><span class="meta">{diagnosed} supported or plausible</span></div>
<div class="kpi alert"><span class="label">Needs review</span><span class="value">{unresolved}</span><span class="meta">{outcomes.get("UNRESOLVED_AMBIGUITY", 0)} ambiguous</span></div>
<div class="kpi good"><span class="label">Clean-case integrity</span><span class="value">{clean_ledger_rate}%</span><span class="meta">{clean_balanced_count} of {clean_ledger_count} clean cases balanced</span></div>
<div class="kpi"><span class="label">Absolute exposure</span><span class="value">{_money(exposure_value)}</span><span class="meta">Net {_money(exposure.get("net_variance_paise", 0))}</span></div>
<div class="kpi"><span class="label">{cash_label}</span><span class="value">{_money(abs(pending_cash))}</span><span class="meta">Bank received {_money(cash.get("bank_received_paise", 0))}</span></div></section>
<div class="grid"><section class="panel" id="evidence"><h2>Evidence review queue</h2><div class="hint">Cases are held back rather than guessed when the evidence does not support one cause.</div>{"".join(outcome_rows)}</section>
<section class="panel" id="health"><h2>Control health and model quality</h2><div class="hint">Clean-case integrity uses cases without graph exceptions. Detected exceptions remain open until finance resolves them.</div><div class="health"><div><div class="health-line"><span>Case linkage</span><b>{linkage_rate}%</b></div><div class="meter"><i style="width:{linkage_rate}%"></i></div></div><div><div class="health-line"><span>Exception detection coverage</span><b>{node_exception_rate}%</b></div><div class="meter warn"><i style="width:{node_exception_rate}%"></i></div></div><div><div class="health-line"><span>Clean-case ledger integrity</span><b>{clean_ledger_rate}%</b></div><div class="meter"><i style="width:{clean_ledger_rate}%"></i></div></div><div><div class="health-line"><span>Flagged ledger imbalances</span><b>{flagged_imbalances}</b></div><div class="meter warn"><i style="width:{min(flagged_imbalances / max(ledger.get("total_with_ledger", 1), 1) * 100, 100)}%"></i></div></div><div><div class="health-line"><span>Silent posting failures</span><b>{silent_failures}</b></div><div class="meter"><i style="width:{100 if silent_failures == 0 else 0}%"></i></div></div><div><div class="health-line"><span>Dev macro-F1</span><b>{macro_f1}%</b></div><div class="meter"><i style="width:{macro_f1}%"></i></div></div><div><div class="health-line"><span>Holdout top-1 / macro-F1</span><b>{holdout_accuracy}% / {holdout_macro_f1}%</b></div><div class="meter"><i style="width:{holdout_accuracy}%"></i></div></div></div></section></div>
<section class="panel" id="accuracy"><h2>Holdout accuracy by hypothesis</h2><div class="hint">Measured on the separate {holdout.get("throughput", {}).get("total_cases", 0)}-case holdout. Support is ground-truth cases; abstention rate is {holdout_quality.get("abstention_rate", 0)}%. Miss analysis: {len(holdout_quality.get("miss_analysis", []))} cases retained in the benchmark report.</div><div class="table-wrap"><table><thead><tr><th>Class</th><th>Precision</th><th>Recall</th><th>F1</th><th>Support</th></tr></thead><tbody>{confusion_rows}</tbody></table></div></section>
<section class="panel queue" id="exceptions"><div class="queue-head"><div><h2>Exception queue</h2><div class="hint">Cases are ranked by financial exposure. Filter the list, then inspect a case to compare cash movement, evidence, and the next human action.</div></div><div><input id="caseSearch" type="search" placeholder="Search case, cause, or evidence" aria-label="Search exception cases"><select id="outcomeFilter" aria-label="Filter outcomes"><option value="">All outcomes</option><option value="INSUFFICIENT_EVIDENCE">Insufficient evidence</option><option value="UNRESOLVED_AMBIGUITY">Unresolved ambiguity</option><option value="CONFLICTING_EVIDENCE">Conflicting evidence</option></select></div></div><div class="table-wrap"><table><thead><tr><th>Case</th><th>Amount</th><th>Severity</th><th>Settlement SLA</th><th>Status</th><th>First divergence</th><th>Candidate cause</th><th>Evidence</th><th>Recommended action</th><th>Score</th><th>Review</th></tr></thead><tbody id="exceptionBody">{"".join(f'<tr data-search="{_escape(" ".join(str(value) for value in row.values()))}" data-outcome="{_escape(row["outcome"])}"><td><strong>{_escape(row["case_id"])}</strong></td><td>{_escape(row.get("amount", "N/A"))}</td><td><span class="pill {"danger" if row.get("severity") in ("Critical", "High") else "warning"}">{_escape(row.get("severity", "Medium"))}</span></td><td>{_escape(row.get("sla_status", "Not available"))}</td><td><span class="pill {"danger" if "AMBIGUITY" in row["outcome"] else "warning"}">{_escape(row["outcome"].replace("_", " "))}</span></td><td>{_escape(row["fod"])}</td><td>{_escape(row["hypothesis"].replace("_", " "))}</td><td class="mono">{_escape(row.get("evidence", "None"))}</td><td>{_escape(row.get("action", "Review"))}</td><td class="mono">{_escape(row["score"])}</td><td><button class="investigate" type="button" data-case="{_escape(row["case_id"])}">Inspect</button></td></tr>' for row in exceptions)}</tbody></table></div>
<section class="panel case-detail" id="caseDetail" hidden aria-live="polite"><h2 id="detailTitle">Case investigation</h2><div class="hint" id="detailSummary"></div><div class="detail-grid"><div class="detail-item"><span>Expected settlement</span><strong id="detailExpected"></strong></div><div class="detail-item"><span>Bank received</span><strong id="detailActual"></strong></div><div class="detail-item"><span>Financial variance</span><strong id="detailVariance"></strong></div></div><div class="detail-grid"><div class="detail-item"><span>Decision</span><strong id="detailDecision"></strong></div><div class="detail-item"><span>Confidence</span><strong id="detailConfidence"></strong></div><div class="detail-item"><span>Settlement SLA</span><strong id="detailSla"></strong></div></div><div class="detail-grid"><div class="detail-item"><span>Leading cause</span><strong id="detailCause"></strong></div><div class="detail-item"><span>Competing causes</span><strong id="detailCompeting"></strong></div><div class="detail-item"><span>Missing evidence</span><strong id="detailMissing"></strong></div></div><div class="detail-grid"><div class="detail-item"><span>Supporting evidence</span><strong id="detailEvidence"></strong></div><div class="detail-item"><span>Recommended action</span><strong id="detailAction"></strong></div><div class="detail-item"><span>Why this decision</span><strong id="detailRationale"></strong></div></div><div class="detail-item"><span>Source timeline (IST)</span><strong id="detailTimeline"></strong></div><div class="detail-actions"><button class="investigate" type="button" data-demo-action="Book">Book — demo only</button><button class="investigate" type="button" data-demo-action="Hold">Hold — demo only</button><button class="investigate" type="button" data-demo-action="Escalate">Escalate — demo only</button><span class="hint" id="actionFeedback"></span></div></section></section>
<section class="panel qa" id="qa"><h2>Ask the controller</h2><div class="hint">Answers are generated from the reconciled state through allowlisted tools. Numbers are not invented.</div><div class="qa-form"><input id="qaQuestion" type="text" placeholder="Why is this settlement blocked?" aria-label="Ask the controller"><button id="qaAsk" type="button">Ask</button></div><div id="qaAnswer" class="qa-answer">Try: “Why is this settlement blocked?” or “Can this settlement be booked?”</div></section>
<footer><span>AI Finance Controller · synthetic benchmark</span><span>Last generated from current metrics and dossier</span></footer></main></div>
<script>
const search = document.getElementById('caseSearch');
const filter = document.getElementById('outcomeFilter');
const rows = [...document.querySelectorAll('#exceptionBody tr[data-search]')];
const details = {case_details_json};

function applyFilter() {{
  const query = search.value.trim().toLowerCase();
  const outcome = filter.value;
  rows.forEach(row => {{
    const matchesSearch = !query || row.dataset.search.toLowerCase().includes(query);
    const matchesOutcome = !outcome || row.dataset.outcome === outcome;
    row.hidden = !(matchesSearch && matchesOutcome);
  }});
}}

function inspectCase(caseId) {{
  const item = details[caseId];
  if (!item) return;
  document.getElementById('caseDetail').hidden = false;
  document.getElementById('detailTitle').textContent = item.case + ' - ' + item.status;
  document.getElementById('detailSummary').textContent = 'Candidate cause: ' + item.cause;
  document.getElementById('detailExpected').textContent = item.expected;
  document.getElementById('detailActual').textContent = item.actual;
  document.getElementById('detailVariance').textContent = item.variance;
  document.getElementById('detailDecision').textContent = item.decision;
  document.getElementById('detailConfidence').textContent = item.confidence;
  document.getElementById('detailSla').textContent = item.sla_status;
  document.getElementById('detailCause').textContent = item.cause;
  document.getElementById('detailCompeting').textContent = item.competing_causes;
  document.getElementById('detailMissing').textContent = item.missing_evidence;
  document.getElementById('detailEvidence').textContent = item.evidence;
  document.getElementById('detailAction').textContent = item.recommendation;
  document.getElementById('detailRationale').textContent = item.decision_rationale;
  document.getElementById('detailTimeline').textContent = item.timeline;
  document.getElementById('actionFeedback').textContent = '';
  document.getElementById('caseDetail').scrollIntoView({{behavior: 'smooth', block: 'nearest'}});
}}

search.addEventListener('input', applyFilter);
filter.addEventListener('change', applyFilter);
document.querySelectorAll('[data-case]').forEach(button => button.addEventListener('click', () => inspectCase(button.dataset.case)));
document.querySelectorAll('[data-demo-action]').forEach(button => button.addEventListener('click', () => {{
  document.getElementById('actionFeedback').textContent = button.dataset.demoAction + ' recorded for this demo session.';
}}));

const ask = document.getElementById('qaAsk');
const question = document.getElementById('qaQuestion');
const answer = document.getElementById('qaAnswer');
async function askController() {{
  const value = question.value.trim();
  if (!value) return;
  answer.textContent = 'Checking reconciled evidence...';
  try {{
    const response = await fetch('/api/ask', {{method: 'POST', headers: {{'Content-Type': 'application/json'}}, body: JSON.stringify({{question: value}})}});
    const data = await response.json();
    answer.textContent = data.error || data.answer + '\\n\\nTools: ' + data.tool_calls.map(call => call.tool).join(', ') + '\\nConfidence: ' + Math.round(data.confidence * 100) + '%';
  }} catch (error) {{
    answer.textContent = 'QA endpoint unavailable: ' + error;
  }}
}}
ask.addEventListener('click', askController);
question.addEventListener('keydown', event => {{ if (event.key === 'Enter') askController(); }});
</script>
</body></html>'''

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html)
    print(f"Dashboard generated -> {output_path}")


if __name__ == "__main__":
    generate_dashboard_report()
