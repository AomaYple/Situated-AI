# Build ASCII-only markdown fragments. ConstrainedLanguage-safe (cmdlets only, no .NET statics).
$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"
$FRAG = "C:\Users\28905\projects\Situated AI\tools\frag"
New-Item -ItemType Directory -Force -Path $FRAG | Out-Null

function W([string]$name, [string[]]$lines) {
    $p = Join-Path $FRAG $name
    Set-Content -LiteralPath $p -Value $lines -Encoding ASCII
    "frag $name : $($lines.Count) lines"
}

$d  = Get-Content "$OUT\defines_precise.json" -Raw | ConvertFrom-Json
$mt = Get-Content "$OUT\modifier_types.json" -Raw | ConvertFrom-Json
$sm = Get-Content "$OUT\static_modifiers.json" -Raw | ConvertFrom-Json

# ---------------------------------------------------------------- A: ns_all
$rows = @()
foreach ($g in ($d | Group-Object ns | Sort-Object Name)) {
    $files = ($g.Group | ForEach-Object { $_.file } | Sort-Object -Unique) -join ', '
    $tot = ($g.Group | Measure-Object total -Sum).Sum
    $rows += ("| ``{0}`` | {1} | {2} | {3} |" -f $g.Name, $g.Count, $tot, $files)
}
W "A_ns_all.md" (@("| Namespace | Blocks | Params | File(s) |","|---|---|---|---|") + $rows)

# ------------------------------------------------------------- B: block_table
$rows = @()
foreach ($b in ($d | Sort-Object file, line)) {
    $rows += ("| ``{0}`` | ``{1}`` | {2} | {3} | {4} | {5} | {6} |" -f $b.file, $b.ns, $b.line, $b.scalarCount, $b.inlineListCount, $b.nestedCount, $b.total)
}
W "B_block_table.md" (@("| File | Namespace block | Line | Scalar | Inline list | Nested | Total |","|---|---|---|---|---|---|---|") + $rows)

# --------------------------------------------------------------- C: ai_groups
$ai = $d | Where-Object { $_.file -eq '00_ai.txt' }
$params = @($ai.scalars)
$grp = @($params | ForEach-Object { ($_ -split '_')[0] } | Group-Object | Sort-Object Count -Descending)
$rows = @()
foreach ($g in $grp) { $rows += ("| ``{0}_*`` | {1} |" -f $g.Name, $g.Count) }
W "C_ai_groups.md" (@("| Leading prefix | Param count |","|---|---|") + $rows)
W "C_ai_block.md" (@("| Namespace block | Start line | Scalar params | Inline-list params | Nested blocks | Total params |","|---|---|---|---|---|---|","| ``$($ai.ns)`` | $($ai.line) | $($ai.scalarCount) | $($ai.inlineListCount) | $($ai.nestedCount) | **$($ai.total)** |"))

# --------------------------------------------------------------- D: ai_params
$lines = @()
$lines += '```text'
for ($i = 0; $i -lt $params.Count; $i += 4) {
    $buf = ""
    for ($j = 0; $j -lt 4 -and ($i + $j) -lt $params.Count; $j++) { $buf += ("{0,-52}" -f $params[$i + $j]) }
    $lines += $buf.TrimEnd()
}
$lines += '```'
W "D_ai_params.md" $lines

# ------------------------------------------------------------ E: game_rules
function Strip-Cmt([string]$Line) {
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ } elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}
$raw = Get-Content -LiteralPath "$GAME\common\game_rules\00_game_rules.txt"
$names = @(); $rows = @(); $depth = 0; $rule = $null
foreach ($l in $raw) {
    $line = Strip-Cmt $l
    if ($line.Trim().Length -gt 0) {
        $mb = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mk = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
        if ($depth -eq 0 -and $mb.Success) { $rule = $mb.Groups[1].Value; $names += $rule }
        elseif ($depth -eq 1 -and $mk.Success -and $rule) {
            $k = $mk.Groups[1].Value; $v = $mk.Groups[2].Value.Trim()
            if ($k -in @('default', 'flag', 'apply_modifier')) { $rows += ("| ``{0}`` | ``{1}`` | ``{2}`` |" -f $rule, $k, $v) }
        }
        $depth += ([regex]::Matches($line, '\{')).Count - ([regex]::Matches($line, '\}')).Count
        if ($depth -le 0) { $depth = 0; $rule = $null }
    }
}
W "E_game_rules_rows.md" (@("| game_rule | Field | Value |","|---|---|---|") + $rows)
$r2 = @()
for ($i = 0; $i -lt $names.Count; $i++) { $r2 += ("| {0} | ``{1}`` | ``rule_{1}`` |" -f ($i + 1), $names[$i]) }
W "E_game_rules_names.md" (@("| # | game_rule key | Localisation key |","|---|---|---|") + $r2)

# -------------------------------------------------------------- F: modtypes
$rows = @()
foreach ($g in ($mt | Group-Object file | Sort-Object Name)) { $rows += ("| ``{0}`` | {1} |" -f $g.Name, $g.Count) }
W "F_modtypes_files.md" (@("| File | Modifier type keys |","|---|---|") + $rows)

$lines = @()
foreach ($g in ($mt | Group-Object file | Sort-Object Name)) {
    $lines += "#### ``$($g.Name)`` -- $($g.Count) keys"
    $lines += ""
    $lines += '```text'
    $arr = @($g.Group | Sort-Object line)
    for ($i = 0; $i -lt $arr.Count; $i += 3) {
        $buf = ""
        for ($j = 0; $j -lt 3 -and ($i + $j) -lt $arr.Count; $j++) { $buf += ("{0,-48}" -f $arr[$i + $j].key) }
        $lines += $buf.TrimEnd()
    }
    $lines += '```'
    $lines += ""
}
W "F_modtypes_list.md" $lines

# --------------------------------------------------------------- G: static
$rows = @()
foreach ($g in ($sm | Group-Object file | Sort-Object Name)) {
    $mx = ($g.Group | Measure-Object childCount -Maximum).Maximum
    $rows += ("| ``{0}`` | {1} | {2} |" -f $g.Name, $g.Count, $mx)
}
W "G_static_files.md" (@("| File | Entries | Max entries in one modifier |","|---|---|---|") + $rows)

$rows = @()
foreach ($e in ($sm | Where-Object { $_.children -notcontains 'icon' } | Sort-Object file, name)) { $rows += ("| ``{0}`` | ``{1}`` |" -f $e.file, $e.name) }
W "G_static_noicon.md" (@("| File | Static modifier without ``icon`` |","|---|---|") + $rows)
