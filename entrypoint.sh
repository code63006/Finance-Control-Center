#!/usr/bin/env bash
set -euo pipefail

echo "=== AI Finance Controller ==="
echo "Running evaluation on ${DATA_BATCH:-dev} batch..."

python evaluate_recon.py --data "${DATA_BATCH:-dev}" --seed "${SEED:-42}"
python evaluate_recon.py --data holdout --seed "${SEED:-42}" --output-dir outputs/holdout
python -m src.ui.html_generator

echo "Report generated. Starting server on port ${PORT:-8000}..."
echo "Open http://localhost:${PORT:-8000}/report.html"

exec python -m src.ui.server
