# PowerShell wrapper for loop.sh. loop.sh is bash and will not run in PowerShell or cmd,
# so this locates Git Bash and hands the arguments straight through.
#
#   .\loop.ps1 -m plan -n 3
#   .\loop.ps1 -m build
#
# All flags are passed to loop.sh unchanged; see loop.sh for the list.

$ErrorActionPreference = 'Stop'

# Git Bash paths come first on purpose: a bare "bash.exe" on PATH is often WSL's
# (C:\Windows\System32\bash.exe), which cannot see Windows paths the way we pass them.
$candidates = @(
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe",
    "$env:LOCALAPPDATA\Programs\Git\bin\bash.exe",
    (Get-Command bash.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.Source -notlike "$env:WINDIR\*" } |
        Select-Object -First 1 -ExpandProperty Source)
)

$bash = $null
foreach ($c in $candidates) {
    if ($c -and (Test-Path $c)) { $bash = $c; break }
}

if (-not $bash) {
    Write-Error "Git Bash not found. Install Git for Windows (https://git-scm.com/download/win), then re-run."
}

# Forward slashes: PowerShell 5.1 strips backslashes when passing args to a native exe.
$script = ($PSScriptRoot -replace '\\', '/') + '/loop.sh'

& $bash $script @args
exit $LASTEXITCODE
