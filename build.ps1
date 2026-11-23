<#
.SYNOPSIS
    Builds AutoClicker Visual and its per-user Windows installer.

.DESCRIPTION
    1. Finds Python 3.11+            4. Bundles the app with PyInstaller (dist\AutoClickerVisual\)
    2. Creates/updates .venv          5. Compiles the Inno Setup 6 installer
    3. Runs the tests                 6. Prints where the installer is

.EXAMPLE
    .\build.ps1
.EXAMPLE
    .\build.ps1 -Version 1.1.0 -Clean
.EXAMPLE
    .\build.ps1 -InstallHooks      # only installs the local git hooks
#>
[CmdletBinding()]
param(
    [string]$Version,          # sets the app version (src\acv\__init__.py) before building
    [switch]$SkipTests,
    [switch]$Clean,            # deletes build\ and dist\ first
    [string]$IsccPath,         # path to ISCC.exe if it is not found automatically
    [switch]$InstallHooks
)

$ErrorActionPreference = 'Stop'
Set-Location -Path $PSScriptRoot

function Write-Step([string]$Message) { Write-Host "==> $Message" -ForegroundColor Cyan }
function Stop-Build([string]$Message) {
    Write-Host ""
    Write-Host "ERROR: $Message" -ForegroundColor Red
    exit 1
}
function Assert-LastExit([string]$What) {
    if ($LASTEXITCODE -ne 0) { Stop-Build "$What failed (exit code $LASTEXITCODE)." }
}

# --- Git hooks only -------------------------------------------------------
if ($InstallHooks) {
    if (-not (Test-Path '.git')) { Stop-Build 'This folder is not a git repository.' }
    Copy-Item -Path 'tools\git-hooks\pre-commit', 'tools\git-hooks\commit-msg' -Destination '.git\hooks\' -Force
    Write-Host 'Git hooks installed (pre-commit, commit-msg).' -ForegroundColor Green
    if (-not (Test-Path '.private\forbidden_words.txt')) {
        Write-Host 'Note: create .private\forbidden_words.txt (one word per line) for the hooks to check anything.' -ForegroundColor Yellow
    }
    exit 0
}

$initFile = 'src\acv\__init__.py'
$versionPattern = '__version__ = "([^"]+)"'
if ($Version) {
    if ($Version -notmatch '^\d+\.\d+\.\d+$') { Stop-Build "Version must look like 1.2.3 (got '$Version')." }
    $content = Get-Content -Path $initFile -Raw
    $content = [regex]::Replace($content, $versionPattern, "__version__ = `"$Version`"")
    [IO.File]::WriteAllText((Resolve-Path $initFile), $content)
} else {
    $Version = ([regex]::Match((Get-Content -Path $initFile -Raw), $versionPattern)).Groups[1].Value
}
Write-Host "AutoClicker Visual $Version" -ForegroundColor White

# --- 1. Python ------------------------------------------------------------
Write-Step 'Looking for Python 3.11+'
$candidates = @(
    @{ Exe = 'py'; Args = @('-3.12') },
    @{ Exe = 'py'; Args = @('-3.13') },
    @{ Exe = 'py'; Args = @('-3.11') },
    @{ Exe = 'python'; Args = @() }
)
$python = $null
foreach ($c in $candidates) {
    try {
        $pyArgs = $c.Args
        $ok = & $c.Exe @pyArgs -c 'import sys; print(sys.version_info >= (3, 11))' 2>$null
        if ($LASTEXITCODE -eq 0 -and $ok -eq 'True') { $python = $c; break }
    } catch { }
}
if (-not $python) {
    Stop-Build ('Python 3.11 or newer was not found. Install Python 3.12 from https://www.python.org/downloads/windows/ ' +
                '(tick "Add python.exe to PATH") and run this script again.')
}
Write-Host "    using: $($python.Exe) $($python.Args -join ' ')"

# --- 2. Virtual environment ---------------------------------------------
if ($Clean) {
    Write-Step 'Cleaning build\ and dist\'
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue 'build', 'dist'
}
$venvPython = '.venv\Scripts\python.exe'
if (-not (Test-Path $venvPython)) {
    Write-Step 'Creating virtual environment (.venv)'
    $pyArgs = $python.Args
    & $python.Exe @pyArgs -m venv .venv
    Assert-LastExit 'Creating the virtual environment'
}
Write-Step 'Installing dependencies'
& $venvPython -m pip install --disable-pip-version-check -q --upgrade pip
Assert-LastExit 'Upgrading pip'
& $venvPython -m pip install --disable-pip-version-check -q -r requirements.txt -r requirements-dev.txt
Assert-LastExit 'Installing dependencies'

# --- 3. Tests -------------------------------------------------------------
if ($SkipTests) {
    Write-Step 'Skipping tests (-SkipTests)'
} else {
    Write-Step 'Running tests'
    $env:QT_QPA_PLATFORM = 'offscreen'
    & $venvPython -m pytest -q
    $testExit = $LASTEXITCODE
    Remove-Item Env:\QT_QPA_PLATFORM
    if ($testExit -ne 0) { Stop-Build 'Tests failed. Fix them or use -SkipTests.' }
}

# --- 4. PyInstaller -------------------------------------------------------
Write-Step 'Bundling the app (PyInstaller, one-folder)'
& $venvPython -m PyInstaller acv.spec --noconfirm --log-level WARN
Assert-LastExit 'PyInstaller'
if (-not (Test-Path 'dist\AutoClickerVisual\AutoClickerVisual.exe')) { Stop-Build 'PyInstaller did not produce AutoClickerVisual.exe.' }

# --- 5. Inno Setup --------------------------------------------------------
Write-Step 'Looking for Inno Setup 6 (ISCC.exe)'
$isccCandidates = @(
    $IsccPath,
    (Get-Command 'ISCC.exe' -ErrorAction SilentlyContinue | Select-Object -First 1 -ExpandProperty Source),
    (Join-Path ${env:ProgramFiles(x86)} 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:ProgramFiles 'Inno Setup 6\ISCC.exe'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Inno Setup 6\ISCC.exe')
)
$iscc = $isccCandidates | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) {
    Stop-Build ('Inno Setup 6 was not found. Install it from https://jrsoftware.org/isdl.php ' +
                '(or: winget install JRSoftware.InnoSetup), or pass -IsccPath "C:\path\to\ISCC.exe". ' +
                'The app itself is already built in dist\AutoClickerVisual\.')
}
Write-Host "    using: $iscc"

Write-Step 'Compiling the installer'
& $iscc /Qp "/DMyAppVersion=$Version" 'installer\installer.iss'
Assert-LastExit 'Inno Setup'

# --- 6. Summary -----------------------------------------------------------
$setup = Get-Item "dist\installer\AutoClickerVisual-Setup-$Version.exe"
$sizeMb = [math]::Round($setup.Length / 1MB, 1)
Write-Host ""
Write-Host 'Build complete.' -ForegroundColor Green
Write-Host "    Installer: $($setup.FullName) ($sizeMb MB)"
Write-Host '    Share this file: it installs for the current user only, without administrator rights.'
