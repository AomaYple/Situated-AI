# Dump structured extraction results to JSON/text files in the workspace tools dir.
# Usage: Invoke-Expression (Get-Content -LiteralPath <this> -Raw); then call functions.

$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"

function Get-DefineParamsDetailed {
    param([Parameter(Mandatory = $true)][string]$Path)
    $lines = Get-Content -LiteralPath $Path
    $depth = 0; $current = $null; $lineno = 0
    $blocks = New-Object System.Collections.ArrayList
    foreach ($raw in $lines) {
        $lineno++
        $line = $raw
        $inQ = $false; $cut = -1
        for ($i = 0; $i -lt $line.Length; $i++) {
            $c = $line[$i]
            if ($c -eq '"') { $inQ = -not $inQ } elseif ($c -eq '#' -and -not $inQ) { $cut = $i; break }
        }
        if ($cut -ge 0) { $line = $line.Substring(0, $cut) }
        if ($line.Trim().Length -eq 0) { continue }
        $mBlock = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mParam = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
        if ($depth -eq 0 -and $mBlock.Success) {
            $current = [pscustomobject]@{ Name = $mBlock.Groups[1].Value; Line = $lineno
                Params = (New-Object System.Collections.ArrayList); SubBlocks = (New-Object System.Collections.ArrayList) }
            [void]$blocks.Add($current)
        } elseif ($depth -eq 1 -and $null -ne $current -and $mParam.Success) {
            $nm = $mParam.Groups[1].Value
            $val = $mParam.Groups[2].Value.Trim()
            if ($mBlock.Success) { [void]$current.SubBlocks.Add([pscustomobject]@{Name=$nm;Line=$lineno}) }
            else { [void]$current.Params.Add([pscustomobject]@{Name=$nm;Line=$lineno;Value=$val}) }
        }
        $depth += ([regex]::Matches($line, '\{')).Count - ([regex]::Matches($line, '\}')).Count
        if ($depth -le 0) { $depth = 0; $current = $null }
    }
    return $blocks
}

function Export-DefinesDir {
    New-Item -ItemType Directory -Force -Path $OUT | Out-Null
    $files = Get-ChildItem -LiteralPath "$GAME\common\defines" -Recurse -File -Filter *.txt
    $all = New-Object System.Collections.ArrayList
    foreach ($f in $files) {
        $rel = $f.FullName.Substring("$GAME\common\defines\".Length)
        foreach ($b in (Get-DefineParamsDetailed -Path $f.FullName)) {
            [void]$all.Add([pscustomobject]@{
                file = $rel; ns = $b.Name; line = $b.Line
                paramCount = $b.Params.Count
                params = @($b.Params | ForEach-Object { $_.Name })
                subBlockCount = $b.SubBlocks.Count
                subBlocks = @($b.SubBlocks | ForEach-Object { $_.Name })
            })
        }
    }
    $all | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$OUT\defines_all.json" -Encoding UTF8
    "WROTE defines_all.json : $($all.Count) blocks"
}
