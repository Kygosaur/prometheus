$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"
$consolePythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$serverScript = Join-Path $projectRoot "scripts\run_web.py"
$workbookScript = Join-Path $projectRoot "scripts\create_example_workbook.py"
$workbookPath = Join-Path $projectRoot "data\planning.xlsx"
$modelFile = Join-Path $projectRoot "models\Kimi.Modelfile"
$dataDirectory = Join-Path $projectRoot "data"
$logPath = Join-Path $dataDirectory "prometheus_launcher.log"
$serverLogPath = Join-Path $dataDirectory "prometheus_server.log"
$errorLogPath = Join-Path $dataDirectory "prometheus_error.log"
$modelLogPath = Join-Path $dataDirectory "prometheus_model_setup.log"
$port = if ($env:PLANNING_WEB_PORT) { [int]$env:PLANNING_WEB_PORT } else { 8010 }
$env:PLANNING_WEB_PORT = [string]$port
$healthUrl = "http://127.0.0.1:$port/api/status"
$chatUrl = "http://127.0.0.1:$port"

function Show-PlanningError([string]$message) {
    if ($env:PLANNINGAI_HEADLESS -eq "true") { throw $message }
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($message, "Prometheus Planning AI could not start", "OK", "Error") | Out-Null
}

function Write-LauncherLog([string]$message) {
    "$(Get-Date -Format o) $message" | Add-Content -LiteralPath $logPath
}

function Test-PlanningReady {
    try {
        $status = Invoke-RestMethod -Uri $healthUrl -TimeoutSec 2
        return [bool]$status.ready -and $status.application -eq "Prometheus Planning AI"
    } catch {
        return $false
    }
}

try {
    if (-not (Test-Path -LiteralPath $pythonPath)) {
        throw "Prometheus Planning AI is not installed yet. The expected Python environment was not found at:`n$pythonPath"
    }

    New-Item -ItemType Directory -Path $dataDirectory -Force | Out-Null
    Write-LauncherLog "Launcher started"

    # Conservative defaults for a 16 GB desktop GPU. Existing explicit user
    # settings are preserved.
    if (-not $env:OLLAMA_NUM_PARALLEL) { $env:OLLAMA_NUM_PARALLEL = "1" }
    if (-not $env:OLLAMA_MAX_LOADED_MODELS) { $env:OLLAMA_MAX_LOADED_MODELS = "1" }
    if (-not $env:OLLAMA_MAX_QUEUE) { $env:OLLAMA_MAX_QUEUE = "64" }

    if (-not (Test-Path -LiteralPath $workbookPath)) {
        Write-LauncherLog "No workbook found; creating the sanitized example workbook"
        $workbookProcess = Start-Process -FilePath $consolePythonPath -ArgumentList @($workbookScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -Wait -PassThru
        if ($workbookProcess.ExitCode -ne 0 -or -not (Test-Path -LiteralPath $workbookPath)) {
            throw "The example planning workbook could not be created."
        }
    }

    if (-not (Test-PlanningReady)) {
        $ollamaCommand = Get-Command "ollama.exe" -ErrorAction SilentlyContinue
        $ollamaPath = if ($ollamaCommand) { $ollamaCommand.Source } else { $null }
        if (-not $ollamaPath) {
            $commonOllama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
            if (Test-Path -LiteralPath $commonOllama) { $ollamaPath = $commonOllama }
        }
        Write-LauncherLog "Ollama found"
        if (-not $ollamaPath) {
            throw "Ollama was not found. Install Ollama and create the planning-kimi model before using PlanningAI."
        }

        try {
            Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
        } catch {
            Start-Process -FilePath $ollamaPath -ArgumentList "serve" -WindowStyle Hidden
            $ollamaReady = $false
            for ($attempt = 0; $attempt -lt 60; $attempt++) {
                try {
                    Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/tags" -TimeoutSec 2 | Out-Null
                    $ollamaReady = $true
                    break
                } catch {
                    Start-Sleep -Seconds 1
                }
            }
            if (-not $ollamaReady) { throw "Ollama did not become ready within one minute." }
        }

        $modelList = & $ollamaPath list 2>$null
        if (($modelList -join "`n") -notmatch "planning-kimi") {
            if (-not (Test-Path -LiteralPath $modelFile)) { throw "The Kimi model definition is missing: $modelFile" }
            Write-LauncherLog "planning-kimi is missing; beginning first-time local model setup"
            $modelProcess = Start-Process -FilePath $ollamaPath -ArgumentList @("create", "planning-kimi", "-f", $modelFile) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $modelLogPath -RedirectStandardError $errorLogPath -Wait -PassThru
            if ($modelProcess.ExitCode -ne 0) {
                throw "The first-time Kimi model setup failed. Check:`n$modelLogPath`n$errorLogPath"
            }
        }
        Write-LauncherLog "planning-kimi model found"

        Write-LauncherLog "Starting FastAPI"
        Start-Process -FilePath $pythonPath -ArgumentList @($serverScript) -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput $serverLogPath -RedirectStandardError $errorLogPath

        $ready = $false
        for ($attempt = 0; $attempt -lt 120; $attempt++) {
            if (Test-PlanningReady) { $ready = $true; break }
            Start-Sleep -Seconds 1
        }
        if (-not $ready) {
            throw "Prometheus Planning AI did not become ready within two minutes. See:`n$logPath`n$errorLogPath"
        }
        Write-LauncherLog "FastAPI is ready"
    }

    Write-LauncherLog "Opening browser"
    Start-Process $chatUrl
} catch {
    try { Write-LauncherLog "ERROR: $($_.Exception.Message)" } catch {}
    Show-PlanningError $_.Exception.Message
    exit 1
}
