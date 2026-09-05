# AI Finance Controller

An audit-safe reconciliation copilot for a finance-operations close. It ingests a batch of orders, gateway reconciliation data, bank credits, and tax invoices; links the lifecycle; verifies books and cash; explains exceptions; and abstains when the evidence is not sufficient.

## What it closes

```mermaid
flowchart LR
  A[Orders] --> D[Normalize source records]
  B[Gateway reconciliation] --> D
  C[Bank statement] --> D
  E[Tax invoice] --> D
  D --> F[8-node lifecycle matcher]
  F --> G[Ledger and GST verification]
  G --> H[Evidence-gated diagnosis]
  H --> I[Cash position and exception queue]
  I --> J[Grounded investigation copilot]
```

The deterministic reconciliation and financial calculations remain authoritative. The copilot explains evidence and recommends a next investigation step; it never posts a journal, approves a settlement, or creates a financial action.

## Benchmark results

The bundled benchmark contains a 60-case development batch and a separately generated 120-case holdout batch. Each anomaly class has at least ten holdout examples; every miss is retained with its predicted cause, outcome, and evidence gap in `outputs/holdout/metrics_report.json`.

| Measure | Development | Holdout |
|---|---:|---:|
| Cases / source records | 60 / 626 | 120 / 1,241 |
| Top-1 root-cause accuracy | Reproduced by evaluator | Reproduced by evaluator |
| Macro-F1 | Reproduced by evaluator | Reproduced by evaluator |
| Per-class holdout support | — | At least 10 per anomaly class |
| Abstention rate | Reproduced by evaluator | Reproduced by evaluator |
| Case linkage | Reproduced by evaluator | Reproduced by evaluator |

“Case linkage” means records were assigned to a lifecycle case. It is deliberately distinct from a clean reconciliation: node-level ambiguity and unmatched records remain visible and feed the exception queue. Accuracy is calculated as correct top-1 diagnosis divided by all evaluated cases; macro-F1 weights each anomaly class equally.

## Supported root causes

- Missing fee record
- Duplicate payment webhook
- Incorrect GST calculation
- Provenance or timestamp skew
- Amount drift
- Settlement delay against the payment-method SLA
- Split-settlement misattribution
- Conflicting source values
- Orphaned refund

## Run it

### Docker

```bash
docker-compose up
```

Open `http://localhost:8000/report.html`.

### Windows PowerShell

```powershell
pip install -r requirements.txt
.\run.ps1
```

The script generates both benchmarks, writes the report to `outputs/report.html`, and serves it at `http://localhost:8000/report.html`.

### Tests

```bash
pytest -q
```

Tests include end-to-end guards from anomaly injection through ingest, matching, evidence, and diagnosis for every supported root cause.



## What this does not yet solve

- The supplied benchmark is synthetic; production deployment needs versioned source contracts, authentication, retention controls, and observed merchant data.
- The dashboard actions are explicitly demo-only workflow signals; they do not persist assignments or modify books.
- The copilot uses a local grounded responder. A production LLM integration would need policy controls, evaluation, and tenant isolation.
- The system detects exceptions but does not automatically release, reverse, or settle money.
