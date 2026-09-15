# Rebuild the game_rules fragments into one combined per-rule table plus a flat settings list.
$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$FRAG = "C:\Users\28905\projects\Situated AI\tools\frag"

function W([string]$name, [string[]]$lines) {
    Set-Content -LiteralPath (Join-Path $FRAG $name) -Value $lines -Encoding ASCII
    "frag $name : $($lines.Count) lines"
}
function Strip-Cmt([string]$Line) {
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ } elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}

$raw = Get-Content -LiteralPath "$GAME\common\game_rules\00_game_rules.txt"
$order = @(); $info = @{}; $depth = 0; $rule = $null; $setting = $null
foreach ($l in $raw) {
    $line = Strip-Cmt $l
    if ($line.Trim().Length -gt 0) {
        $mb = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mk = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$')
        if ($depth -eq 0 -and $mb.Success) {
            $rule = $mb.Groups[1].Value
            $order += $rule
            $info[$rule] = @{ default = ''; settings = @(); flags = @() }
        }
        elseif ($depth -eq 1 -and $mk.Success -and $rule) {
            $k = $mk.Groups[1].Value; $v = $mk.Groups[2].Value.Trim()
            if ($k -eq 'default') { $info[$rule].default = $v }
            elseif ($mb.Success) { $info[$rule].settings += $k }
        }
        elseif ($depth -eq 2 -and $mk.Success -and $rule) {
            $k = $mk.Groups[1].Value; $v = $mk.Groups[2].Value.Trim()
            if ($k -eq 'flag') { $info[$rule].flags += ("{0}:{1}" -f $setting, $v) }
            elseif ($k -eq 'apply_modifier') { $info[$rule].flags += ("{0}:apply_modifier {1}" -f $setting, $v) }
        }
        if ($depth -eq 1 -and $mb.Success -and $rule) { $setting = $mb.Groups[1].Value }
        $depth += ([regex]::Matches($line, '\{')).Count - ([regex]::Matches($line, '\}')).Count
        if ($depth -le 0) { $depth = 0; $rule = $null; $setting = $null }
    }
}

$rows = @("| # | game_rule key | default | settings (non-default) | flag entries |", "|---|---|---|---|---|")
for ($i = 0; $i -lt $order.Count; $i++) {
    $r = $order[$i]; $d = $info[$r]
    $sets = @($d.settings | Where-Object { $_ -ne $d.default })
    $fl = @($d.flags)
    if ($fl.Count -le 6) { $flagCell = (($fl | ForEach-Object { "``$_``" }) -join '<br>') }
    else { $flagCell = ("**{0}** entries (see section 4.7)" -f $fl.Count) }
    if ($flagCell -eq '') { $flagCell = '(none)' }
    $rows += ("| {0} | ``{1}`` | ``{2}`` | {3} | {4} |" -f ($i + 1), $r, $d.default, (($sets | ForEach-Object { "``$_``" }) -join ', '), $flagCell)
}
W "E1_game_rules_table.md" $rows

$flat = @("| # | setting key | game_rule | is default |", "|---|---|---|---|")
$n = 0
foreach ($r in $order) {
    foreach ($s in @($info[$r].settings)) {
        $n++
        $isDef = if ($s -eq $info[$r].default) { 'yes' } else { '' }
        $flat += ("| {0} | ``{1}`` | ``{2}`` | {3} |" -f $n, $s, $r, $isDef)
    }
}
W "E2_game_rules_settings.md" $flat

$flags = @("| game_rule | setting | flag / directive |", "|---|---|---|")
foreach ($r in $order) { foreach ($f in @($info[$r].flags)) { $p = $f -split ':', 2; $flags += ("| ``{0}`` | ``{1}`` | ``{2}`` |" -f $r, $p[0], $p[1]) } }
W "E3_game_rules_flags.md" $flags

$uniq = @()
foreach ($r in $order) { foreach ($f in @($info[$r].flags)) { $p = $f -split ':', 2; if ($p[1] -notlike 'apply_modifier*') { $uniq += $p[1] } } }
$uniq = @($uniq | Sort-Object -Unique)
$fr = @()
for ($i = 0; $i -lt $uniq.Count; $i++) { $fr += ("| {0} | ``{1}`` |" -f ($i + 1), $uniq[$i]) }
W "E4_game_rules_flag_names.md" (@("| # | flag key |","|---|---|") + $fr)
"rules=$($order.Count)  flagNames=$($uniq.Count)"
