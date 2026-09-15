# Assemble the final knowledge-base markdown from prose parts + ASCII fragments.
$base = "C:\Users\28905\projects\Situated AI"
$D = "$base\tools\docparts"
$F = "$base\tools\frag"
$outdir = "$base\docs\victoria3-modding"
New-Item -ItemType Directory -Force -Path $outdir | Out-Null

# "05-defines" + U+4E0E U+4FEE U+9970 U+7B26 + ".md"  (kept ASCII in this file on purpose)
$name = "05-defines" + [char]0x4E0E + [char]0x4FEE + [char]0x9970 + [char]0x7B26 + ".md"
$out = Join-Path $outdir $name

$seq = @(
    "p:p01.md", "f:A_ns_all.md",
    "p:p02.md", "f:B_block_table.md",
    "p:p03.md", "f:C_ai_block.md",
    "p:p04.md", "f:C_ai_groups.md",
    "p:p05.md", "f:D_ai_params.md",
    "p:p06.md", "f:H_ai_elsewhere.md",
    "p:p07.md", "f:E1_game_rules_table.md",
    "p:p08.md", "f:E2_game_rules_settings.md",
    "p:p09.md", "f:E3_game_rules_flags.md",
    "p:p10.md", "f:F_modtypes_files.md",
    "p:p11.md", "f:F_modtypes_list.md",
    "p:p12.md", "f:G_static_files.md",
    "p:p13.md", "f:G_static_noicon.md",
    "p:p14.md"
)

$missing = @()
foreach ($item in $seq) {
    $kind = $item.Substring(0, 1)
    $fn = $item.Substring(2)
    $src = if ($kind -eq 'p') { Join-Path $D $fn } else { Join-Path $F $fn }
    if (-not (Test-Path -LiteralPath $src)) { $missing += $item; continue }
}
if ($missing.Count -gt 0) { "MISSING: $($missing -join ', ')"; exit 1 }

Remove-Item -LiteralPath $out -ErrorAction SilentlyContinue
$first = $true
foreach ($item in $seq) {
    $kind = $item.Substring(0, 1)
    $fn = $item.Substring(2)
    $src = if ($kind -eq 'p') { Join-Path $D $fn } else { Join-Path $F $fn }
    $txt = Get-Content -LiteralPath $src -Raw -Encoding UTF8
    if ($first) {
        Copy-Item -LiteralPath $src -Destination $out
        $first = $false
    }
    else {
        # ensure a blank line before any part that opens with a horizontal rule
        if ($txt.StartsWith("---")) { $txt = "`r`n" + $txt }
        Add-Content -LiteralPath $out -Value $txt -Encoding UTF8 -NoNewline
    }
}

$fi = Get-Item -LiteralPath $out
"OUT : $($fi.FullName)"
"SIZE: $($fi.Length) bytes"
$lines = (Get-Content -LiteralPath $out -Encoding UTF8).Count
"LINES: $lines"
$bytes = Get-Content -LiteralPath $out -Encoding Byte -TotalCount 4
"FIRST BYTES: " + (($bytes | ForEach-Object { $_.ToString('X2') }) -join ' ')
