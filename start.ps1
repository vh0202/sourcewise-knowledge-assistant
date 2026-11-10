<#
.SYNOPSIS
    One-command start for Windows (PowerShell 5.1 or later).

.DESCRIPTION
    Creates .venv on the first run, installs the pinned requirements, loads the demo data if
    the database is empty, and serves the app on http://127.0.0.1:8102. Stop with Ctrl+C.

    Nothing is installed globally. Node.js is not needed: the built frontend is in frontend\dist.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\start.ps1
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

function Find-Python {
    # Returns the command line of the first Python 3.12+ interpreter found, or $null.
    foreach ($candidate in @("python", "py -3.12", "py -3")) {
        $parts = $candidate.Split(" ")
        $exe = $parts[0]
        if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
        $rest = @($parts | Select-Object -Skip 1)
        $previous = $ErrorActionPreference
        $ErrorActionPreference = "Continue"   # a failed probe must not stop the script
        try {
            & $exe @rest -c "import sys; raise SystemExit(sys.version_info < (3, 12))" 2>$null | Out-Null
            $found = ($LASTEXITCODE -eq 0)
        } catch {
            $found = $false
        }
        $ErrorActionPreference = $previous
        if ($found) { return $candidate }
    }
    return $null
}

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $system = Find-Python
    if ($null -eq $system) {
        throw "Python 3.12 or newer was not found. Install it from python.org and run this script again."
    }
    Write-Host "Creating the virtual environment (.venv) ..."
    $parts = $system.Split(" ")
    $exe = $parts[0]
    $rest = @($parts | Select-Object -Skip 1)
    & $exe @rest -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the virtual environment." }
}

# Install dependencies only when requirements.txt has changed since the last install.
$marker = Join-Path $PSScriptRoot ".venv\requirements.sha256"
$wanted = (Get-FileHash -LiteralPath (Join-Path $PSScriptRoot "requirements.txt") -Algorithm SHA256).Hash
$installed = ""
if (Test-Path -LiteralPath $marker) { $installed = (Get-Content -LiteralPath $marker -Raw).Trim() }
if ($wanted -ne $installed) {
    Write-Host "Installing Python dependencies into .venv ..."
    & $python -m pip install --disable-pip-version-check --quiet -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw "pip install failed." }
    Set-Content -LiteralPath $marker -Value $wanted -Encoding ascii
}

& $python -m sourcewise seed --if-empty
if ($LASTEXITCODE -ne 0) { throw "Loading the demo data failed." }

& $python -m sourcewise serve @args
exit $LASTEXITCODE
