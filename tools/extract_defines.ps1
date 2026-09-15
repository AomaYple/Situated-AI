# Extract top-level namespace blocks + member parameter names from PDX defines files.
# Dot-source via: Invoke-Expression (Get-Content -LiteralPath <this> -Raw)
# Then call: Get-DefineBlocks -Path <file>

function Remove-PdxComment {
    param([string]$Line)
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ }
        elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}

function Get-DefineBlocks {
    param([Parameter(Mandatory = $true)][string]$Path)

    $lines = Get-Content -LiteralPath $Path
    $depth = 0
    $current = $null
    $blocks = New-Object System.Collections.ArrayList
    $lineno = 0

    foreach ($raw in $lines) {
        $lineno++
        $line = Remove-PdxComment $raw
        if ($line.Trim().Length -eq 0) { continue }

        $mBlock = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mParam = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=')

        if ($depth -eq 0 -and $mBlock.Success) {
            $current = [pscustomobject]@{
                Name      = $mBlock.Groups[1].Value
                Line      = $lineno
                Params    = (New-Object System.Collections.ArrayList)
                SubBlocks = (New-Object System.Collections.ArrayList)
            }
            [void]$blocks.Add($current)
        }
        elseif ($depth -eq 1 -and $null -ne $current -and $mParam.Success) {
            $name = $mParam.Groups[1].Value
            if ($mBlock.Success) { [void]$current.SubBlocks.Add($name) }
            else { [void]$current.Params.Add($name) }
        }

        $opens = ([regex]::Matches($line, '\{')).Count
        $closes = ([regex]::Matches($line, '\}')).Count
        $depth += ($opens - $closes)
        if ($depth -le 0) { $depth = 0; $current = $null }
    }
    return $blocks
}

function Show-DefineSummary {
    param([Parameter(Mandatory = $true)][string]$Path)
    $blocks = Get-DefineBlocks -Path $Path
    $total = 0
    foreach ($b in $blocks) {
        $total += $b.Params.Count
        "{0}`tline={1}`tparams={2}`tsubblocks={3}" -f $b.Name, $b.Line, $b.Params.Count, $b.SubBlocks.Count
    }
    "--- TOTAL_BLOCKS=$($blocks.Count)  TOTAL_PARAMS=$total"
}
