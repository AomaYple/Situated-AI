# Precise defines extractor v3.
# Handles PDX style "NAME =" + "{" on the next line, while preserving PHYSICAL line numbers.
$GAME = "C:\Program Files (x86)\Steam\steamapps\common\Victoria 3\game"
$OUT  = "C:\Users\28905\projects\Situated AI\tools\out"
New-Item -ItemType Directory -Force -Path $OUT | Out-Null

function Strip-Cmt {
    param([string]$Line)
    $inQ = $false
    for ($i = 0; $i -lt $Line.Length; $i++) {
        $c = $Line[$i]
        if ($c -eq '"') { $inQ = -not $inQ }
        elseif ($c -eq '#' -and -not $inQ) { return $Line.Substring(0, $i) }
    }
    return $Line
}

# Returns array of "<physicalLineNumber>`t<text>" with "NAME =" + "{" merged.
function Get-LogicalLines {
    param([Parameter(Mandatory=$true)][string]$Path)
    $raw = Get-Content -LiteralPath $Path
    $out = @()
    $i = 0
    while ($i -lt $raw.Count) {
        $phys = $i + 1
        $line = Strip-Cmt $raw[$i]
        $t = $line.Trim()
        if ($t.Length -gt 0 -and $t.EndsWith('=')) {
            $j = $i + 1
            $nt = ''
            while ($j -lt $raw.Count) {
                $nt = (Strip-Cmt $raw[$j]).Trim()
                if ($nt.Length -gt 0) { break }
                $j++
            }
            if ($j -lt $raw.Count -and $nt.StartsWith('{')) {
                $out += ("{0}`t{1} {{" -f $phys, $line)
                $i = $j + 1
                continue
            }
        }
        $out += ("{0}`t{1}" -f $phys, $line)
        $i++
    }
    return $out
}

function Get-DefinesPrecise {
    param([Parameter(Mandatory=$true)][string]$Path)
    $lines = Get-LogicalLines -Path $Path
    $depth = 0; $cur = $null
    $blocks = @()
    foreach ($entry in $lines) {
        $tab = $entry.IndexOf("`t")
        $phys = [int]$entry.Substring(0, $tab)
        $line = $entry.Substring($tab + 1)
        if ($line.Trim().Length -eq 0) { continue }
        $opens  = ([regex]::Matches($line, '\{')).Count
        $closes = ([regex]::Matches($line, '\}')).Count
        $mBlock = [regex]::Match($line, '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*\{')
        $mAny   = [regex]::Match($line, '^\s*([A-Za-z_@][A-Za-z0-9_]*)\s*=\s*(.*)$')

        if ($depth -eq 0 -and $mBlock.Success) {
            $cur = @{ Name = $mBlock.Groups[1].Value; Line = $phys
                      Scalar = @(); InlineList = @(); Nested = @(); Vars = @() }
            $blocks += $cur
        }
        elseif ($depth -eq 1 -and $null -ne $cur -and $mAny.Success) {
            $nm = $mAny.Groups[1].Value
            if ($nm.StartsWith('@')) { $cur.Vars += $nm.Substring(1) }
            elseif ($mBlock.Success) {
                if ($opens -eq $closes) { $cur.InlineList += $nm } else { $cur.Nested += $nm }
            }
            else { $cur.Scalar += $nm }
        }
        $depth += ($opens - $closes)
        if ($depth -le 0) { $depth = 0; $cur = $null }
    }
    return $blocks
}

function Export-DefinesPrecise {
    $root = "$GAME\common\defines"
    $files = Get-ChildItem -LiteralPath $root -Recurse -File -Filter *.txt | Sort-Object FullName
    $all = @()
    foreach ($f in $files) {
        $rel = $f.FullName.Substring("$root\".Length) -replace '\\', '/'
        foreach ($b in (Get-DefinesPrecise -Path $f.FullName)) {
            $all += New-Object -TypeName PSObject -Property @{
                file = $rel; ns = $b.Name; line = $b.Line
                scalarCount = $b.Scalar.Count; inlineListCount = $b.InlineList.Count; nestedCount = $b.Nested.Count
                total = $b.Scalar.Count + $b.InlineList.Count + $b.Nested.Count
                scalars = @($b.Scalar); inlineLists = @($b.InlineList); nested = @($b.Nested); localVars = @($b.Vars)
            }
        }
    }
    $all | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath "$OUT\defines_precise.json" -Encoding UTF8
    "WROTE defines_precise.json with $($all.Count) namespace blocks"
    foreach ($g in ($all | Group-Object file | Sort-Object Name)) {
        $sc = ($g.Group | Measure-Object scalarCount -Sum).Sum
        $il = ($g.Group | Measure-Object inlineListCount -Sum).Sum
        $ne = ($g.Group | Measure-Object nestedCount -Sum).Sum
        "  {0}`tblocks={1}`tscalar={2}`tinline={3}`tnested={4}`tTOTAL={5}" -f $g.Name, $g.Count, $sc, $il, $ne, ($sc + $il + $ne)
    }
    $sc = ($all | Measure-Object scalarCount -Sum).Sum
    $il = ($all | Measure-Object inlineListCount -Sum).Sum
    $ne = ($all | Measure-Object nestedCount -Sum).Sum
    "GRAND TOTAL entries = $($sc + $il + $ne)  (scalar $sc + inline $il + nested $ne)"
    "blocks = $($all.Count) ; distinct namespaces = $(($all | Group-Object ns).Count)"
    $names = @()
    foreach ($b in $all) { $names += @($b.scalars) + @($b.inlineLists) + @($b.nested) }
    "param entries = $($names.Count) ; distinct names = $(($names | Sort-Object -Unique).Count)"
    $bad = @($names | Where-Object { $_ -cne $_.ToUpper() } | Sort-Object -Unique)
    "non-uppercase names = $($bad.Count) : $($bad -join ', ')"
}
