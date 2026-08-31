param(
  [Parameter(Mandatory = $true)][ValidateSet("stage14impl", "stage14pm3")][string]$Profile,
  [Parameter(Mandatory = $true)][string]$SourceRoot,
  [Parameter(Mandatory = $true)][string]$ArtifactRoot,
  [Parameter(Mandatory = $true)][string]$PublicBaseUrl
)

$ErrorActionPreference = "Stop"
$profiles = @{
  stage14impl = @{ Drive = "V:"; Dist = ".next-stage14-impl"; TempPrefix = "story-stage14-impl-" }
  stage14pm3 = @{ Drive = "W:"; Dist = ".next-stage14-pm3"; TempPrefix = "story-stage14-pm3-" }
}
$selected = $profiles[$Profile]
$backendOrigin = "http://backend:8000"
try { $publicUri = [System.Uri]$PublicBaseUrl } catch { throw "public_base_url_invalid" }
if ($publicUri.Scheme -ne "https" -or $publicUri.UserInfo -or $publicUri.PathAndQuery -ne "/" -or $publicUri.Fragment -or $publicUri.AbsoluteUri.TrimEnd("/") -ne $PublicBaseUrl) { throw "public_base_url_invalid" }

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
    $env:BACKEND_ORIGIN = $backendOrigin
    $env:PUBLIC_APP_MODE = "1"
    $env:PUBLIC_BASE_URL = $PublicBaseUrl
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
    $metadata = [ordered]@{ profile = $Profile; publicBaseUrl = $PublicBaseUrl; backendOrigin = $backendOrigin; buildId = $buildId }
    $metadataJson = $metadata | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText(
        (Join-Path $artifact "stage14-build-metadata.json"),
        $metadataJson,
        [System.Text.UTF8Encoding]::new($false)
    )
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
