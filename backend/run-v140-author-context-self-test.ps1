$ErrorActionPreference = 'Stop'
$backendRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$demoRoot = Split-Path -Parent $backendRoot
$pythonRuntime = Join-Path $demoRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $pythonRuntime)) {
  throw "Python runtime not found: $pythonRuntime"
}

$env:PUBLIC_APP_MODE = '0'
$env:PUBLIC_BASE_URL = 'http://127.0.0.1:3217'
$env:BACKEND_ORIGIN = 'http://127.0.0.1:8217'
$env:TRUSTED_HOSTS = '127.0.0.1:8217,testserver'
$env:TRUSTED_ORIGINS = 'http://127.0.0.1:3217,http://testserver'

Push-Location $backendRoot
try {
  & $pythonRuntime -m py_compile app/v2_database.py app/main.py app/provider.py app/engine.py
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
  & $pythonRuntime -m unittest tests.test_v140_author_context tests.test_v140_backend_sync tests.test_v130_author_intent tests.test_v130_writing_analysis tests.test_v130_character_alias_change_impact tests.test_v130_story_qa_foreshadow tests.test_v130_revision_plan tests.test_v130_memory_delta_fact_lifecycle tests.test_stage11j_source_changes -q
  exit $LASTEXITCODE
}
finally {
  Pop-Location
}
