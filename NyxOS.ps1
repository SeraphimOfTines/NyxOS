# NyxOS Startup Script for Windows

# Set location to script directory to ensure relative paths work
Set-Location $PSScriptRoot

# 1. Auto-Setup Virtual Environment
if (-not (Test-Path "venv")) {
    Write-Host "📦 Creating virtual environment..." -ForegroundColor Cyan
    python -m venv venv
}

# 2. Activate Environment
if ($env:VIRTUAL_ENV -eq $null) {
    if (Test-Path "venv\Scripts\Activate.ps1") {
        Write-Host "🔌 Activating virtual environment..." -ForegroundColor Cyan
        . .\venv\Scripts\Activate.ps1
    } else {
        Write-Error "❌ Could not find venv activation script."
        exit 1
    }
}

# 3. Install/Update Dependencies
Write-Host "📥 Checking dependencies..." -ForegroundColor Cyan
pip install -r requirements.txt --quiet

# 4. Cleanup Previous Instances
Write-Host "🧹 Cleaning up previous instances..." -ForegroundColor Cyan
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*python*NyxOS.py*" -and $_.ProcessId -ne $PID } | ForEach-Object { 
    Write-Host "   Stopping process $($_.ProcessId)..." -ForegroundColor Yellow
    Stop-Process -Id $_.ProcessId -Force 
}

# 5. Launch Bot
Write-Host "🚀 Starting NyxOS..." -ForegroundColor Green
python NyxOS.py