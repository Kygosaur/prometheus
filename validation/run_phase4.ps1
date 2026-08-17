$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
New-Item -ItemType Directory -Force validation/results | Out-Null
python -m pytest -q | Tee-Object validation/results/pytest.txt
python -m validation.evaluate_rag | Tee-Object validation/results/rag.json
$env:ENV_FILE = ".env.production.example"
docker compose --env-file .env.production.example -f compose.production.yaml config | Out-File validation/results/compose-config.txt
kubectl kustomize deploy/kubernetes/overlays/production | Out-File validation/results/kubernetes-rendered.yaml
Write-Host "Static validation complete. Start the stack, then run benchmark_api.py, security_smoke.py, and hardware_monitor.py during a representative workload."
