param(
  [Parameter(Mandatory = $true)][ValidateSet("stage14impl", "stage14pm3")][string]$Profile,
  [Parameter(Mandatory = $true)][string]$RepositoryRoot,
  [Parameter(Mandatory = $true)][string]$BundleRoot,
  [Parameter(Mandatory = $true)][string]$PublicBaseUrl
)

$ErrorActionPreference = "Stop"
$repository = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$bundle = [System.IO.Path]::GetFullPath($BundleRoot)
$systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
if (-not $bundle.StartsWith($systemTemp, [System.StringComparison]::OrdinalIgnoreCase) -or -not (Split-Path -Leaf $bundle).StartsWith("story-stage14-bundle-")) { throw "bundle_root_invalid" }
if (Test-Path -LiteralPath $bundle) { throw "bundle_already_exists" }
$frontend = Join-Path $repository "frontend"
$publicUri = $null
if (-not [System.Uri]::TryCreate($PublicBaseUrl, [System.UriKind]::Absolute, [ref]$publicUri) `
  -or $publicUri.Scheme -ne "https" `
  -or [string]::IsNullOrWhiteSpace($publicUri.Host) `
  -or -not $publicUri.IsDefaultPort `
  -or $publicUri.AbsolutePath -ne "/" `
  -or $publicUri.Query `
  -or $publicUri.Fragment `
  -or $publicUri.UserInfo) { throw "public_base_url_invalid" }

New-Item -ItemType Directory -Path $bundle | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "backend") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "backend\app") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "deployment") | Out-Null
New-Item -ItemType Directory -Path (Join-Path $bundle "frontend-source") | Out-Null
Copy-Item -LiteralPath (Join-Path $repository "backend\requirements.txt") -Destination (Join-Path $bundle "backend\requirements.txt")
Get-ChildItem -LiteralPath (Join-Path $repository "backend\app") -File -Filter "*.py" | ForEach-Object {
  Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $bundle "backend\app\$($_.Name)")
}
$frontendFiles = @(
  "build-id.mjs", "build-origin.mjs", "next.config.mjs", "next-env.d.ts",
  "package-lock.json", "package.json", "public-config.mjs", "tsconfig.json"
)
foreach ($name in $frontendFiles) {
  Copy-Item -LiteralPath (Join-Path $frontend $name) -Destination (Join-Path $bundle "frontend-source\$name")
}
Copy-Item -LiteralPath (Join-Path $frontend "app") -Destination (Join-Path $bundle "frontend-source\app") -Recurse
if (Test-Path -LiteralPath (Join-Path $frontend "public")) {
  Copy-Item -LiteralPath (Join-Path $frontend "public") -Destination (Join-Path $bundle "frontend-source\public") -Recurse
}
$deploymentFiles = @(
  ".dockerignore", "Caddyfile", "compose.yaml", "Dockerfile.backend", "Dockerfile.frontend",
  "backend-entrypoint.sh", "deploy.env.example", "secret-dir-check.sh",
  "release.sh", "rollback.sh", "restore.sh", "verify-frontend-image.sh"
)
foreach ($name in $deploymentFiles) {
  $destination = if ($name -eq ".dockerignore") { Join-Path $bundle $name } else { Join-Path $bundle "deployment\$name" }
  Copy-Item -LiteralPath (Join-Path $repository "deployment\$name") -Destination $destination
}
$metadata = [ordered]@{
  profile = $Profile
  publicBaseUrl = $publicUri.AbsoluteUri.TrimEnd('/')
  backendOrigin = "http://backend:8000"
  targetOs = "linux"
  targetArch = "amd64"
  targetLibc = "musl"
  frontendBuild = "docker-multistage-source"
}
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)
[System.IO.File]::WriteAllText(
  (Join-Path $bundle "stage14-platform-metadata.json"),
  (($metadata | ConvertTo-Json -Depth 3) + [Environment]::NewLine),
  $utf8NoBom
)
& node (Join-Path $frontend "scripts\stage14-bundle-scan.mjs") $bundle $Profile $repository $frontend
if ($LASTEXITCODE -ne 0) { throw "stage14_bundle_scan_failed" }
