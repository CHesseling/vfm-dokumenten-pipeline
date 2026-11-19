# Spielt das Offline-Paket (USB-Stick) auf diesem Rechner ein.
# Aufruf (im Stick-Ordner): powershell -ExecutionPolicy Bypass -File .\einspielen.ps1 [-Ziel C:\vfm]
param(
    [string]$Ziel = (Join-Path $env:USERPROFILE "vfm-pipeline")
)
$ErrorActionPreference = "Stop"

$Stick = Split-Path -Parent $MyInvocation.MyCommand.Path

# Ziel absolut machen und nicht auf dem Stick zulassen
New-Item -ItemType Directory -Force -Path $Ziel | Out-Null
$Ziel = (Resolve-Path $Ziel).Path.TrimEnd('\')
$StickPfad = (Resolve-Path $Stick).Path.TrimEnd('\')
if (($Ziel + '\').StartsWith($StickPfad + '\', [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "Das Ziel liegt auf dem Stick ($Ziel). Bitte ein Verzeichnis auf dem Rechner waehlen."
}

# 32-Bit-PowerShell auf 64-Bit-Windows meldet PROCESSOR_ARCHITECTURE=x86
$ProzArch = $env:PROCESSOR_ARCHITEW6432
if (-not $ProzArch) { $ProzArch = $env:PROCESSOR_ARCHITECTURE }
switch ($ProzArch) {
    "AMD64" { $Arch = "amd64" }
    "ARM64" { $Arch = "arm64" }
    default { throw "Unbekannte Architektur: $ProzArch" }
}
Write-Host "Architektur: $Arch"

function Get-ContainerEngine {
    # Docker oder Podman, je nachdem was laeuft (VFM_ENGINE=docker|podman erzwingt eine)
    $Alt = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $Kandidaten = if ($env:VFM_ENGINE) { @($env:VFM_ENGINE) } else { @("docker", "podman") }
        foreach ($E in $Kandidaten) {
            if (Get-Command $E -ErrorAction SilentlyContinue) {
                & $E info 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { return $E }
            }
        }
        return $null
    } finally {
        $ErrorActionPreference = $Alt
    }
}

# Unter PS 5.1 kann stderr eines nativen Befehls mit "Stop" zum Abbruch fuehren
$CE = Get-ContainerEngine
if (-not $CE) {
    throw "Weder Docker noch Podman laeuft - bitte Docker Desktop bzw. 'podman machine start' starten und das Skript erneut ausfuehren."
}
Write-Host "Container-Engine: $CE"

function Lade-Image([string]$Name) {
    $Datei = Join-Path $Stick "images\$Name"
    if (-not (Test-Path $Datei)) {
        Write-Host "  uebersprungen (nicht auf dem Stick): $Name"
        return
    }
    Write-Host "  lade $Name ..."
    # docker/podman load liest .tar.gz direkt
    $Alt = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & $CE load -i $Datei
    $Ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $Alt
    if (-not $Ok) { throw "$CE load fehlgeschlagen: $Name" }
}

Write-Host "==> Container-Images laden"
if (-not (Test-Path (Join-Path $Stick "images\vfm-pipeline-$Arch.tar.gz"))) {
    throw "App-Image fuer $Arch fehlt auf dem Stick"
}
Lade-Image "vfm-pipeline-$Arch.tar.gz"
$Alt = $ErrorActionPreference
$ErrorActionPreference = "Continue"
& $CE tag "vfm-pipeline:latest-$Arch" "vfm-pipeline:latest"
$Ok = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $Alt
if (-not $Ok) { throw "$CE tag fehlgeschlagen" }
Lade-Image "pgvector-pg16-$Arch.tar.gz"

$Antwort = Read-Host "Ollama-Image (fuer Ollama im Container) auch laden? [j/N]"
if ($Antwort -match '^(j|y)$') { Lade-Image "ollama-$Arch.tar.gz" }

$ModelleQuelle = Join-Path $Stick "ollama-modelle"
if (Test-Path $ModelleQuelle) {
    $ModelleZiel = Join-Path $env:USERPROFILE ".ollama\models"
    $Antwort = Read-Host "Ollama-Modelle nach $ModelleZiel kopieren (vorhandene Dateien bleiben erhalten)? [j/N]"
    if ($Antwort -match '^(j|y)$') {
        New-Item -ItemType Directory -Force -Path $ModelleZiel | Out-Null
        # ohne -Force: vorhandene Dateien werden nicht ueberschrieben
        Get-ChildItem -Path $ModelleQuelle -Recurse -File | ForEach-Object {
            $Rel = $_.FullName.Substring($ModelleQuelle.Length).TrimStart('\')
            $Ziel2 = Join-Path $ModelleZiel $Rel
            if (-not (Test-Path $Ziel2)) {
                New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Ziel2) | Out-Null
                Copy-Item $_.FullName $Ziel2
            }
        }
        Write-Host "  Modelle kopiert (vorhandene Dateien wurden nicht ueberschrieben)."
    } else {
        Write-Host "  Modelle uebersprungen."
    }
} else {
    Write-Host "Keine Ollama-Modelle auf dem Stick."
}

Write-Host "==> Projekt entpacken nach $Ziel"
$Entpacken = $true
if (Get-ChildItem -Force -Path $Ziel | Select-Object -First 1) {
    $Antwort = Read-Host "$Ziel ist nicht leer. Vorhandene Projektdateien ueberschreiben? [j/N]"
    if ($Antwort -notmatch '^(j|y)$') {
        $Entpacken = $false
        Write-Host "  Entpacken uebersprungen."
    }
}
if ($Entpacken) {
    # tar ist seit Windows 10 (1803) enthalten
    $Alt = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    tar -xzf (Join-Path $Stick "vfm-pipeline-repo.tar.gz") -C $Ziel --strip-components=1
    $Ok = ($LASTEXITCODE -eq 0)
    $ErrorActionPreference = $Alt
    if (-not $Ok) { throw "Entpacken fehlgeschlagen" }
}
$EnvDatei = Join-Path $Ziel ".env"
if (-not (Test-Path $EnvDatei)) {
    Copy-Item (Join-Path $Ziel ".env.example") $EnvDatei
    Write-Host "  .env aus .env.example angelegt."
} else {
    Write-Host "  .env existiert bereits, unveraendert. Bitte mit .env.example auf neue Schluessel vergleichen."
}

Write-Host ""
Write-Host "Fertig. Weiter mit:"
Write-Host "  cd `"$Ziel`"; $CE compose up -d; $CE compose exec app vfm check"
