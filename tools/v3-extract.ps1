# V3 modding doc extraction helpers. Dot-source style: Invoke-Expression (Get-Content -Raw ...)
# No param block, so it can be loaded with Invoke-Expression inside a live session.

function Get-TopLevelKeys {
  param([string]$Path, [int]$Depth = 0)
  $lines = Get-Content -LiteralPath $Path
  $d = 0
  $out = New-Object System.Collections.ArrayList
  for ($i = 0; $i -lt $lines.Count; $i++) {
    $clean = ($lines[$i] -replace '#.*$','')
    if ($d -eq $Depth -and $clean -match '^\s*([A-Za-z_][A-Za-z0-9_\.]*)\s*=\s*\{') {
      [void]$out.Add([pscustomobject]@{ Key = $Matches[1]; Line = $i + 1 })
    }
    $d += ([regex]::Matches($clean,'\{')).Count - ([regex]::Matches($clean,'\}')).Count
  }
  return $out
}

function Get-FieldKeys {
  param([string]$Dir, [string]$Filter = '*.txt', [int]$TopDepth = 0)
  $fieldCount = @{}
  $files = Get-ChildItem -LiteralPath $Dir -Filter $Filter -File -Recurse | Sort-Object FullName
  foreach ($f in $files) {
    $lines = Get-Content -LiteralPath $f.FullName
    $d = 0
    for ($i = 0; $i -lt $lines.Count; $i++) {
      $clean = ($lines[$i] -replace '#.*$','')
      if ($d -eq ($TopDepth + 1) -and $clean -match '^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=') {
        $k = $Matches[1]
        if (-not $fieldCount.ContainsKey($k)) { $fieldCount[$k] = @() }
        $fieldCount[$k] += "$($f.Name):$($i+1)"
      }
      $d += ([regex]::Matches($clean,'\{')).Count - ([regex]::Matches($clean,'\}')).Count
    }
  }
  $fieldCount.GetEnumerator() | Sort-Object { -$_.Value.Count } | ForEach-Object {
    "{0}`t{1}`t{2}" -f $_.Key, $_.Value.Count, (($_.Value | Select-Object -First 2) -join ' ')
  }
}
