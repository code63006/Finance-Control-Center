param(
    [switch]$NoServer,
    [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'
$env:PORT = $Port

python evaluate_recon.py --data dev
python evaluate_recon.py --data holdout --output-dir outputs/holdout
python -m src.ui.html_generator

if (-not $NoServer) {
    python -m src.ui.server
}
