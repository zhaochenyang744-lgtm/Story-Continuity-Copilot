param(
  [Parameter(Mandatory = $true)][string]$RepositoryRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRoot,
  [Parameter(Mandatory = $true)][string]$TestRoot
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$frontend = Join-Path $repository "frontend"
$backend = Join-Path $repository "backend"
$artifact = (Resolve-Path -LiteralPath $ArtifactRoot).Path
$test = [System.IO.Path]::GetFullPath($TestRoot)
$systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
if (-not $artifact.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -or -not $artifact.Split([System.IO.Path]::DirectorySeparatorChar).Where({ $_.StartsWith("story-stage13-v4-impl-build2-") }).Count) { throw "artifact_profile_invalid" }
if (-not $test.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $test).StartsWith("story-stage13-v4-impl-e2e-")) { throw "test_root_invalid" }
if (Test-Path -LiteralPath $test) { throw "test_root_exists" }
if (Get-PSDrive -Name V -ErrorAction SilentlyContinue) { throw "staging_drive_in_use" }
foreach ($port in 3084, 8084) {
  if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) { throw "isolated_port_in_use" }
}

$stamp = (Split-Path -Leaf $test).Substring("story-stage13-v4-impl-e2e-".Length)
$relocated = Join-Path $systemTemp ("story-stage13-v4-impl-relocated-" + $stamp)
if (Test-Path -LiteralPath $relocated) { throw "relocated_root_exists" }
$evidence = Join-Path $test "evidence"
$logs = Join-Path $test "logs"
New-Item -ItemType Directory -Path $test, $evidence, $logs | Out-Null
Copy-Item -LiteralPath $artifact -Destination $relocated -Recurse

$env:STAGE13_HARNESS_PROFILE = "v4impl"
$env:E2E_BASE_URL = "http://127.0.0.1:3084"
$env:E2E_BACKEND_ORIGIN = "http://127.0.0.1:8084"
$env:BACKEND_ORIGIN = "http://127.0.0.1:8084"
$env:PUBLIC_APP_MODE = "0"
$env:PUBLIC_BASE_URL = "http://127.0.0.1:3084"
$env:NEXT_DIST_DIR = ".next-stage13-v4-impl"
$env:E2E_ACCOUNT_PREFIX = "stage13v4impl" + $stamp.Substring(0, 8)
$env:E2E_TEST_ROOT = $test
$env:E2E_OUTPUT_DIR = $evidence

$python = Join-Path $repository ".venv\\Scripts\\python.exe"
$backendOut = Join-Path $logs "backend.stdout.log"
$backendErr = Join-Path $logs "backend.stderr.log"
$frontendOut = Join-Path $logs "frontend.stdout.log"
$frontendErr = Join-Path $logs "frontend.stderr.log"
$backendProcess = $null
$frontendProcess = $null
$playwrightExit = 1
try {
  $backendProcess = Start-Process -FilePath $python -ArgumentList @("-m", "uvicorn", "tests.stage13_app:app", "--host", "127.0.0.1", "--port", "8084", "--workers", "1", "--no-access-log") -WorkingDirectory $backend -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -WindowStyle Hidden -PassThru
  $frontendProcess = Start-Process -FilePath (Get-Command node).Source -ArgumentList @("scripts/start-stage13-v4-artifact.mjs", $relocated, "v4impl", $frontend) -WorkingDirectory $frontend -RedirectStandardOutput $frontendOut -RedirectStandardError $frontendErr -WindowStyle Hidden -PassThru
  $ready = $false
  for ($attempt = 0; $attempt -lt 60; $attempt++) {
    try {
      $backendResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:8084/health" -TimeoutSec 2
      $frontendResponse = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:3084/" -TimeoutSec 2
      if ($backendResponse.StatusCode -eq 200 -and $frontendResponse.StatusCode -eq 200) { $ready = $true; break }
    } catch {}
    Start-Sleep -Milliseconds 500
  }
  if (-not $ready) { throw "isolated_services_not_ready" }
  Push-Location $frontend
  try {
    & ".\\node_modules\\.bin\\playwright.cmd" test --config playwright.stage13.config.ts
    $playwrightExit = $LASTEXITCODE
  } finally { Pop-Location }
}
finally {
  foreach ($process in @($frontendProcess, $backendProcess)) {
    if ($process -and -not $process.HasExited) {
      $observed = Get-CimInstance Win32_Process -Filter "ProcessId=$($process.Id)" -ErrorAction SilentlyContinue
      if ($observed -and ($observed.CommandLine -like "*start-stage13-v4-artifact.mjs*" -or $observed.CommandLine -like "*tests.stage13_app:app*")) {
        Stop-Process -Id $process.Id -Force
      }
    }
  }
  Start-Sleep -Milliseconds 500
}

Copy-Item -LiteralPath $backendOut, $backendErr, $frontendOut, $frontendErr -Destination $evidence
Push-Location $frontend
try {
  & node ".\\scripts\\stage13-v4-runtime-scan.mjs" $evidence v4impl $repository $frontend
  $scanExit = $LASTEXITCODE
} finally { Pop-Location }
$listeners = @(Get-NetTCPConnection -State Listen -LocalPort 3084, 8084 -ErrorAction SilentlyContinue).Count
$result = [ordered]@{
  playwright_exit = $playwrightExit
  runtime_scan_exit = $scanExit
  listeners_after = $listeners
  staging_drive_available = [bool](Get-PSDrive -Name V -ErrorAction SilentlyContinue)
  evidence_root = $evidence
}
$result | ConvertTo-Json -Compress
if ($playwrightExit -ne 0 -or $scanExit -ne 0 -or $listeners -ne 0) { exit 1 }
