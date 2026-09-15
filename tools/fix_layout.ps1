# Regenerate the two long listings, one name per line.
# One name per line is deliberate: the longest names are 83 (AI) / 74 (modifier types) chars, so any
# multi-column layout either overflows the column or runs two names together. One per line is also
# the most searchable / copy-pasteable form.
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"
$FRAG = "C:\Users\28905\projects\Situated AI\tools\frag"

function Format-Block {
    param([string[]]$Names)
    $maxLen = 0
    foreach ($n in $Names) { if ($n.Length -gt $maxLen) { $maxLen = $n.Length } }
    $out = @('```text')
    foreach ($n in $Names) { $out += $n }
    $out += '```'
    return @{ Lines = $out; MaxLen = $maxLen }
}

# ---------------- D_ai_params ----------------
$d = Get-Content "$OUT\defines_precise.json" -Raw | ConvertFrom-Json
$ai = @(($d | Where-Object { $_.file -eq '00_ai.txt' }).scalars)
$r = Format-Block -Names $ai
Set-Content -LiteralPath "$FRAG\D_ai_params.md" -Value $r.Lines -Encoding ASCII
"D_ai_params.md  names=$($ai.Count)  maxLen=$($r.MaxLen)  lines=$($r.Lines.Count)"

# ---------------- F_modtypes_list ----------------
$mt = Get-Content "$OUT\modifier_types.json" -Raw | ConvertFrom-Json
$lines = @()
foreach ($g in ($mt | Group-Object file | Sort-Object Name)) {
    $arr = @($g.Group | Sort-Object line)
    $names = @($arr | ForEach-Object { $_.key })
    $rr = Format-Block -Names $names
    $lines += "#### ``$($g.Name)`` -- $($names.Count) keys"
    $lines += ""
    $lines += $rr.Lines
    $lines += ""
    "{0}`t{1}`tmaxLen={2}" -f $g.Name, $names.Count, $rr.MaxLen
}
Set-Content -LiteralPath "$FRAG\F_modtypes_list.md" -Value $lines -Encoding ASCII
"F_modtypes_list.md lines=$($lines.Count)"
"total keys = $(($mt | Measure-Object).Count)"
