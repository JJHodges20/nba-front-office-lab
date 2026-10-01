# Create the virtual environment, install the project, and run the tests.
# Usage (from the project root):  .\scripts\bootstrap.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Host "Creating virtual environment in .venv"
    python -m venv (Join-Path $root ".venv")
    if ($LASTEXITCODE -ne 0) { throw "could not create the virtual environment" }
}

Write-Host "Installing the project and its development tools"
& $python -m pip install --quiet --upgrade pip
& $python -m pip install --quiet -e "$root[dev]"
if ($LASTEXITCODE -ne 0) { throw "installation failed" }

Write-Host "Running tests"
Push-Location $root
try {
    & $python -m pytest
    if ($LASTEXITCODE -ne 0) { throw "tests failed" }
} finally {
    Pop-Location
}

Write-Host "Ready. Try: .\.venv\Scripts\fol.exe info"
