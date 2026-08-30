param(
  [Parameter(Mandatory = $true)][ValidateSet("v4impl", "v4pm3")][string]$Profile,
  [Parameter(Mandatory = $true)][string]$SourceRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRoot
)

$ErrorActionPreference = "Stop"
$profiles = @{
  v4impl = @{ Drive = "V:"; Frontend = "http://127.0.0.1:3084"; Backend = "http://127.0.0.1:8084"; Dist = ".next-stage13-v4-impl"; TempPrefix = "story-stage13-v4-impl-" }
  v4pm3 = @{ Drive = "W:"; Frontend = "http://127.0.0.1:3085"; Backend = "http://127.0.0.1:8085"; Dist = ".next-stage13-v4-pm3"; TempPrefix = "story-stage13-v4-pm3-" }
}
$selected = $profiles[$Profile]
$source = (Resolve-Path -LiteralPath $SourceRoot).Path
$artifact = [System.IO.Path]::GetFullPath($ArtifactRoot)
$systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
if (-not $artifact.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase)) { throw "artifact_outside_system_temp" }
if (-not @($artifact.Split([System.IO.Path]::DirectorySeparatorChar) | Where-Object { $_.StartsWith($selected.TempPrefix) }).Count) { throw "artifact_profile_mismatch" }
if (Test-Path -LiteralPath $artifact) { throw "artifact_already_exists" }
if (Get-PSDrive -Name $selected.Drive.TrimEnd(":") -ErrorAction SilentlyContinue) { throw "staging_drive_in_use" }
if (@(Get-ChildItem -LiteralPath $source -Force -File | Where-Object { $_.Name -like ".env*" }).Count) { throw "env_file_present" }
$package = Get-Content -LiteralPath (Join-Path $source "package.json") -Raw | ConvertFrom-Json
if ($package.name -ne "story-continuity-app") { throw "package_name_mismatch" }
$buildIdOutput = @(& node (Join-Path $source "build-id.mjs") $source)
if ($LASTEXITCODE -ne 0 -or $buildIdOutput.Count -ne 1) { throw "source_build_id_failed" }
$buildId = $buildIdOutput[0].Trim()
if ($buildId -notmatch '^s13v4-[a-f0-9]{32}$') { throw "source_build_id_invalid" }

$nextEnvPath = Join-Path $source "next-env.d.ts"
$tsconfigPath = Join-Path $source "tsconfig.json"
$nextEnvBytes = [System.IO.File]::ReadAllBytes($nextEnvPath)
$tsconfigBytes = [System.IO.File]::ReadAllBytes($tsconfigPath)
$distPath = [System.IO.Path]::GetFullPath((Join-Path $source $selected.Dist))
if ((Split-Path -Parent $distPath) -ne $source -or (Split-Path -Leaf $distPath) -ne $selected.Dist) { throw "unsafe_dist_target" }
if (Test-Path -LiteralPath $distPath) { Remove-Item -LiteralPath $distPath -Recurse -Force }
$mapped = $false
try {
  & subst.exe $selected.Drive $source
  if ($LASTEXITCODE -ne 0) { throw "subst_failed" }
  $mapped = $true
  Push-Location ($selected.Drive + "\\")
  try {
    $env:BACKEND_ORIGIN = $selected.Backend
    $env:PUBLIC_APP_MODE = "0"
    $env:PUBLIC_BASE_URL = $selected.Frontend
    $env:NEXT_DIST_DIR = $selected.Dist
    $env:NEXT_BUILD_ID = $buildId
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw "next_build_failed" }
    $mappedDist = Join-Path ($selected.Drive + "\\") $selected.Dist
    $standalone = Join-Path $mappedDist "standalone"
    if (-not (Test-Path -LiteralPath $standalone)) { throw "standalone_missing" }
    New-Item -ItemType Directory -Path $artifact | Out-Null
    Copy-Item -Path (Join-Path $standalone "*") -Destination $artifact -Recurse -Force
    $public = Join-Path ($selected.Drive + "\\") "public"
    if (Test-Path -LiteralPath $public) { Copy-Item -LiteralPath $public -Destination (Join-Path $artifact "public") -Recurse -Force }
    $staticTarget = Join-Path $artifact ($selected.Dist + "\\static")
    New-Item -ItemType Directory -Path $staticTarget -Force | Out-Null
    Copy-Item -Path (Join-Path $mappedDist "static\\*") -Destination $staticTarget -Recurse -Force
  }
  finally { Pop-Location }
}
finally {
  [System.IO.File]::WriteAllBytes($nextEnvPath, $nextEnvBytes)
  [System.IO.File]::WriteAllBytes($tsconfigPath, $tsconfigBytes)
  if ($mapped) { & subst.exe $selected.Drive /D }
}
if (Test-Path -LiteralPath ($selected.Drive + "\\")) { throw "staging_drive_still_available" }
& node (Join-Path $source "scripts\\stage13-v4-policy.mjs") $artifact $Profile $source
if ($LASTEXITCODE -ne 0) { throw "artifact_scan_failed" }
