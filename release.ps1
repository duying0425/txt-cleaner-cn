[CmdletBinding()]
param(
    [string]$Version
)

$ErrorActionPreference = "Stop"

# Check git status
$gitStatus = git status --porcelain
if ($gitStatus) {
    Write-Warning "Working tree has uncommitted changes. Stashing or commit first is recommended."
}

# Determine Version tag
if (-not $Version) {
    $currentTag = git describe --tags --abbrev=0 2>$null
    if (-not $currentTag) {
        $currentTag = "v0.1.0"
    }
    Write-Host "Current tag: $currentTag" -ForegroundColor Cyan
    $newVer = Read-Host "Enter new version tag (e.g. v0.1.0 or press Enter to auto-increment patch)"
    if (-not $newVer) {
        if ($currentTag -match '^v?(\d+)\.(\d+)\.(\d+)$') {
            $major = [int]$matches[1]
            $minor = [int]$matches[2]
            $patch = [int]$matches[3] + 1
            $Version = "v$major.$minor.$patch"
        } else {
            $Version = "v0.1.0"
        }
    } else {
        $Version = if ($newVer.StartsWith("v")) { $newVer } else { "v$newVer" }
    }
}

Write-Host "Target Release Version: $Version" -ForegroundColor Green

# Optional: git commit changes
$commitMsg = "chore(release): bump version to $Version"
git add .
git commit -m $commitMsg --allow-empty

# Create Git Tag
Write-Host "Creating tag $Version..." -ForegroundColor Yellow
git tag -a $Version -m "Release $Version"

# Push to GitHub
Write-Host "Pushing commit and tags to remote GitHub..." -ForegroundColor Cyan
git push origin HEAD --tags

Write-Host "Done! GitHub Actions workflow has been triggered to build and publish $Version." -ForegroundColor Green

