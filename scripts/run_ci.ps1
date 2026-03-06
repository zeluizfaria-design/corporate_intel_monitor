param(
    [switch]$SkipNpmCi
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$frontendDir = Join-Path $projectRoot "frontend"
$npmCacheDir = Join-Path $frontendDir ".npm-cache"

function Resolve-NpmCmd {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($npm) {
        return $npm.Path
    }

    $fallback = "C:\Program Files\nodejs\npm.cmd"
    if (Test-Path $fallback) {
        $env:Path = "C:\Program Files\nodejs;$env:Path"
        return $fallback
    }

    throw "npm.cmd nao encontrado. Instale Node.js ou ajuste o PATH."
}

$npmCmd = Resolve-NpmCmd

function Assert-LastExitCode {
    param(
        [string]$StepName
    )

    if ($LASTEXITCODE -ne 0) {
        throw "$StepName falhou com exit code $LASTEXITCODE."
    }
}

Write-Host "[CI] Frontend path: $frontendDir"
Push-Location $frontendDir
try {
    if (-not $SkipNpmCi) {
        Write-Host "[CI] Running npm ci"
        & $npmCmd ci --cache $npmCacheDir
        Assert-LastExitCode "npm ci"
    }

    Write-Host "[CI] Running frontend tests"
    & $npmCmd run test:run
    Assert-LastExitCode "frontend tests"

    Write-Host "[CI] Running frontend build"
    & $npmCmd run build
    Assert-LastExitCode "frontend build"
}
finally {
    Pop-Location
}

Write-Host "[CI] Running backend tests"
Push-Location $projectRoot
try {
    python -m unittest tests.test_base_collector_resilience tests.test_api_integration tests.test_api_background_tasks -v
    Assert-LastExitCode "backend tests"
}
finally {
    Pop-Location
}

Write-Host "[CI] Pipeline concluido com sucesso."
