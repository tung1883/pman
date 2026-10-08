# Dumps `Get-Help -Full` of every command and about_ topic of the running PowerShell into $OutDir (one .txt each).
# Run with both pwsh and powershell.exe:  pwsh -NoProfile -File tools/dump_gethelp.ps1 -OutDir .cache/gethelp/pwsh
param([Parameter(Mandatory)][string]$OutDir)
$ErrorActionPreference = 'SilentlyContinue'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
$skip = '^(prompt|PSConsoleHostReadLine|TabExpansion2|Clear-Host|help|mkdir|more|oss|ImportSystemModules|Pause|cd\.\.|cd\\|[A-Za-z]:)$'
$names = Get-Command -CommandType Cmdlet, Function | Where-Object { $_.Name -notmatch $skip } | Select-Object -ExpandProperty Name -Unique
$n = 0
foreach ($name in $names) {
    $t = Get-Help $name -Full | Out-String -Width 110
    if ($t -and $t.Length -gt 200) {
        [IO.File]::WriteAllText((Join-Path $OutDir "$name.txt"), $t, (New-Object Text.UTF8Encoding $false))
        $n++
    }
}
$about = Get-Help about_* | Select-Object -ExpandProperty Name -Unique
foreach ($name in $about) {
    $t = Get-Help $name -Full | Out-String -Width 110
    if ($t -and $t.Length -gt 200) {
        [IO.File]::WriteAllText((Join-Path $OutDir "$name.txt"), $t, (New-Object Text.UTF8Encoding $false))
        $n++
    }
}
"wrote $n help files to $OutDir"
