<#
.SYNOPSIS
  Install repograph on Windows.

.DESCRIPTION
  Copies repograph.exe into %LOCALAPPDATA%\Programs\repograph, adds that folder to
  your user PATH, and creates a Start Menu shortcut that opens the UI.

.EXAMPLE
  .\install.ps1 -Binary .\repograph.exe
  .\install.ps1                      # from a git clone, installs with pip
#>
[CmdletBinding()]
param(
  [string]$Binary = "",
  [switch]$NoShortcut
)

$ErrorActionPreference = "Stop"
$target = Join-Path $env:LOCALAPPDATA "Programs\repograph"
New-Item -ItemType Directory -Force -Path $target | Out-Null

if ($Binary) {
  Copy-Item -Force $Binary (Join-Path $target "repograph.exe")
  $exe = Join-Path $target "repograph.exe"
  Write-Host "  installed $exe"
} else {
  $root = Split-Path -Parent $PSScriptRoot
  Write-Host "  installing from source with pip"
  & python -m pip install --user --upgrade $root
  $exe = (Get-Command repograph -ErrorAction SilentlyContinue).Source
  if (-not $exe) { $exe = Join-Path $target "repograph.exe" }
}

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$target*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$target", "User")
  Write-Host "  added $target to your user PATH (restart your terminal to pick it up)"
}

if (-not $NoShortcut) {
  $shell = New-Object -ComObject WScript.Shell
  $startMenu = $shell.SpecialFolders("Programs")
  $link = $shell.CreateShortcut((Join-Path $startMenu "repograph.lnk"))
  $link.TargetPath = $exe
  $link.Description = "Scan a repository and produce architecture diagrams and reports"
  $link.WorkingDirectory = $shell.SpecialFolders("MyDocuments")
  $link.Save()
  Write-Host "  created a Start Menu shortcut"
}

Write-Host ""
Write-Host "  done. Try:"
Write-Host "    repograph scan C:\path\to\repo     scan from the terminal"
Write-Host "    repograph ui                       open the desktop UI"
