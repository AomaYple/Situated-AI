param(
    [Parameter(Mandatory)] [string] $SdkIncludeDir,
    [Parameter(Mandatory)] [string] $GameRoot,
    [string] $OutputDir = (Join-Path $PSScriptRoot '..\out\steam-workshop-helper')
)

$ErrorActionPreference = 'Stop'
$compiler = Get-Command cl.exe -CommandType Application
if ($env:VSCMD_ARG_TGT_ARCH -ne 'x64') {
    throw 'Run this script from an x64 Developer PowerShell for Visual Studio.'
}
$includeDir = (Resolve-Path -LiteralPath $SdkIncludeDir).Path
$gameBinaries = Join-Path (Resolve-Path -LiteralPath $GameRoot).Path 'binaries'
$steamDll = Join-Path $gameBinaries 'steam_api64.dll'
$steamLib = Join-Path $gameBinaries 'steam_api64.lib'
$signature = Get-AuthenticodeSignature -LiteralPath $steamDll
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '^CN=Valve Corp\.,') {
    throw 'The installed Victoria 3 steam_api64.dll must have a valid Valve signature.'
}
$header = Get-Content -Raw -LiteralPath (Join-Path $includeDir 'isteamugc.h')
if ($header -notmatch '(?m)^#define STEAMUGC_INTERFACE_VERSION "STEAMUGC_INTERFACE_VERSION016"') {
    throw 'The helper requires Steamworks SDK 1.53a headers (ISteamUGC v016).'
}

$outputPath = (New-Item -ItemType Directory -Force -Path $OutputDir).FullName
$sourcePath = Join-Path $PSScriptRoot 'workshop.cpp'
$executable = Join-Path $outputPath 'situated-ai-steam-workshop.exe'
$object = Join-Path $outputPath 'workshop.obj'
& $compiler.Source /nologo /std:c++17 /EHsc /W4 /WX /O2 /MT /source-charset:.1252 /execution-charset:utf-8 "/I$includeDir" `
    "/Fo$object" "/Fe$executable" $sourcePath /link $steamLib
if ($LASTEXITCODE -ne 0) {
    throw "Steam Workshop helper build failed ($LASTEXITCODE)."
}
Copy-Item -LiteralPath $steamDll -Destination (Join-Path $outputPath 'steam_api64.dll')
Remove-Item -LiteralPath $object
& $executable version
if ($LASTEXITCODE -ne 0) {
    throw "Steam Workshop helper failed its startup check ($LASTEXITCODE)."
}
Write-Output $executable
