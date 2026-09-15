# Generic top-level key extractor for PDX script files (brace-depth aware).
$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

function Remove-PdxComment2 {
    param([string]$Line)
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ }
        elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}

# Returns list of top-level `key = { ... }` blocks with their direct child keys.
function Get-TopLevelBlocks {
    param([Parameter(Mandatory=$true)][string]$Path)
    $lines = Get-Content -LiteralPath $Path
    $depth = 0; $cur = $null; $lineno = 0
    $res = New-Object System.Collections.ArrayList
    foreach ($raw in $lines) {
        $lineno++
        $line = Remove-PdxComment2 $raw
        if ($line.Trim().Length -eq 0) { continue }
        $mb = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_\.\-]*)\s*=\s*\{')
        $mk = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_\.\-]*)\s*=')
        if ($depth -eq 0 -and $mb.Success) {
            $cur = [pscustomobject]@{ Key=$mb.Groups[1].Value; Line=$lineno; Children=(New-Object System.Collections.ArrayList); Body=(New-Object System.Collections.ArrayList) }
            [void]$res.Add($cur)
        } elseif ($depth -eq 1 -and $null -ne $cur) {
            if ($mk.Success) { [void]$cur.Children.Add($mk.Groups[1].Value) }
            [void]$cur.Body.Add($line.Trim())
        }
        $depth += ([regex]::Matches($line,'\{')).Count - ([regex]::Matches($line,'\}')).Count
        if ($depth -le 0) { $depth = 0; $cur = $null }
    }
    return $res
}

# game_rules: rule keys = top-level blocks; setting keys = direct children
function Export-GameRules {
    $p = "$GAME\common\game_rules\00_game_rules.txt"
    $blocks = Get-TopLevelBlocks -Path $p
    $out = foreach ($b in $blocks) {
        [pscustomobject]@{
            ruleKey = $b.Key; line = $b.Line
            settings = @($b.Children)
            raw = @($b.Body)
        }
    }
    $out | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$OUT\game_rules.json" -Encoding UTF8
    "game_rules: $($blocks.Count) rules"
    foreach ($b in $blocks) { "  {0} [{1} settings] -> {2}" -f $b.Key, $b.Children.Count, ($b.Children -join ', ') }
}

function Export-ModifierTypes {
    $dir = "$GAME\common\modifier_type_definitions"
    $files = Get-ChildItem -LiteralPath $dir -File -Filter *.txt | Sort-Object Name
    $all = New-Object System.Collections.ArrayList
    foreach ($f in $files) {
        $blocks = Get-TopLevelBlocks -Path $f.FullName
        foreach ($b in $blocks) {
            $color = $null; $percent = $null; $decimals = $null; $boolean = $null
            $translate = $null; $typeSets = @(); $hasGameData = $false
            foreach ($ln in $b.Body) {
                if ($ln -match '^color\s*=\s*(\S+)') { $color = $Matches[1] }
                elseif ($ln -match '^percent\s*=\s*(\S+)') { $percent = $Matches[1] }
                elseif ($ln -match '^decimals\s*=\s*(\S+)') { $decimals = $Matches[1] }
                elseif ($ln -match '^boolean\s*=\s*(\S+)') { $boolean = $Matches[1] }
                elseif ($ln -match '^game_data\s*=\s*\{') { $hasGameData = $true }
                elseif ($ln -match '^translate\s*=\s*"?([A-Za-z0-9_]+)"?') { $translate = $Matches[1] }
                elseif ($ln -match '^type_set\s*=\s*\{(.*)\}') { $typeSets += ($Matches[1].Trim() -split '\s+') }
            }
            [void]$all.Add([pscustomobject]@{
                file=$f.Name; key=$b.Key; line=$b.Line; color=$color; percent=$percent
                decimals=$decimals; boolean=$boolean; translate=$translate
                typeSet=@($typeSets); gameData=$hasGameData
            })
        }
    }
    $all | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$OUT\modifier_types.json" -Encoding UTF8
    "modifier_types: $($all.Count) keys across $($files.Count) files"
    foreach ($f in $files) { "  {0}: {1}" -f $f.Name, (@($all | Where-Object { $_.file -eq $f.Name }).Count) }
}

function Export-StaticModifiers {
    $dir = "$GAME\common\static_modifiers"
    $files = Get-ChildItem -LiteralPath $dir -File -Filter *.txt | Sort-Object Name
    $all = New-Object System.Collections.ArrayList
    foreach ($f in $files) {
        $blocks = Get-TopLevelBlocks -Path $f.FullName
        foreach ($b in $blocks) {
            [void]$all.Add([pscustomobject]@{ file=$f.Name; name=$b.Key; line=$b.Line; childCount=$b.Children.Count; children=@($b.Children) })
        }
    }
    $all | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$OUT\static_modifiers.json" -Encoding UTF8
    "static_modifiers: $($all.Count) entries across $($files.Count) files"
}
