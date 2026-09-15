# Fix A: rebuild D_ai_params.md with a safe column width.
# Fix B: rebuild game-rule fragments capturing depth-2 flag / apply_modifier entries.
$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"
$FRAG = "C:\Users\28905\projects\Situated AI\tools\frag"

function W([string]$name, [string[]]$lines) {
    Set-Content -LiteralPath (Join-Path $FRAG $name) -Value $lines -Encoding ASCII
    "frag $name : $($lines.Count) lines"
}

$d  = Get-Content "$OUT\defines_precise.json" -Raw | ConvertFrom-Json
$ai = $d | Where-Object { $_.file -eq '00_ai.txt' }
$params = @($ai.scalars)
$maxLen = 0
foreach ($p in $params) { if ($p.Length -gt $maxLen) { $maxLen = $p.Length } }
"max NAI param name length = $maxLen"
$w = $maxLen + 3
$perLine = 3
$lines = @('```text')
$col = ""
for ($i = 0; $i -lt $params.Count; $i++) {
    $col += $params[$i].PadRight($w)
    if ((($i + 1) % $perLine) -eq 0) { $lines += $col.TrimEnd(); $col = "" }
}
if ($col.Trim().Length -gt 0) { $lines += $col.TrimEnd() }
$lines += '```'
W "D_ai_params.md" $lines

# ------------------------------------------------------------- game rules
function Strip-Cmt([string]$Line) {
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ } elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}
$raw = Get-Content -LiteralPath "$GAME\common\game_rules\00_game_rules.txt"
$ruleNames = @(); $setNames = @(); $rows = @(); $flagRows = @()
$depth = 0; $rule = $null; $setting = $null
foreach ($l in $raw) {
    $line = Strip-Cmt $l
    if ($line.Trim().Length -gt 0) {
        $mb = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mk = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
        if ($depth -eq 0 -and $mb.Success) {
            $rule = $mb.Groups[1].Value; $ruleNames += $rule
        }
        elseif ($depth -eq 1 -and $mk.Success) {
            $k = $mk.Groups[1].Value; $v = $mk.Groups[2].Value.Trim()
            if ($k -eq 'default') { $rows += ("| ``{0}`` | ``default`` | ``{1}`` |" -f $rule, $v) }
            elseif ($mb.Success) {
                $setting = $k
                $setNames += ("{0}.{1}" -f $rule, $k)
                $rows += ("| ``{0}`` | setting block | ``{1}`` |" -f $rule, $k)
            }
        }
        elseif ($depth -eq 2 -and $mk.Success -and $rule) {
            $k = $mk.Groups[1].Value; $v = $mk.Groups[2].Value.Trim()
            if ($k -eq 'flag' -or $k -eq 'apply_modifier') {
                $flagRows += ("| ``{0}`` | ``{1}`` | ``{2}`` | ``{3}`` |" -f $rule, $setting, $k, $v)
            }
        }
        $depth += ([regex]::Matches($line, '\{')).Count - ([regex]::Matches($line, '\}')).Count
        if ($depth -le 0) { $depth = 0; $rule = $null; $setting = $null }
    }
}
W "E_game_rules_rows.md" (@("| game_rule | Field | Value |","|---|---|---|") + $rows)
$r2 = @()
for ($i = 0; $i -lt $ruleNames.Count; $i++) { $r2 += ("| {0} | ``{1}`` | ``rule_{1}`` |" -f ($i + 1), $ruleNames[$i]) }
W "E_game_rules_names.md" (@("| # | game_rule key | Localisation key |","|---|---|---|") + $r2)
W "E_game_rules_flags.md" (@("| game_rule | setting | Field | Value |","|---|---|---|---|") + $flagRows)
"rules=$($ruleNames.Count) settings=$($setNames.Count) flagEntries=$($flagRows.Count)"
$flagVals = @($flagRows | ForEach-Object { ($_ -split '\|')[4].Trim() } | Sort-Object -Unique)
"distinct flag values = $($flagVals.Count)"
$sr = @()
for ($i = 0; $i -lt $setNames.Count; $i++) { $sr += ("| {0} | ``{1}`` |" -f ($i + 1), $setNames[$i]) }
W "E_game_rules_settings.md" (@("| # | game_rule.setting |","|---|---|") + $sr)
