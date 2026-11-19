# Einrichten und Starten in einem Zug (Windows PowerShell), fuer Teilnehmende:
#   irm https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.ps1 | iex
# Voraussetzung: Docker Desktop (oder Podman Desktop) laeuft. Ollama fuer die lokalen
# Modelle; ohne Ollama geht es mit Cortecs (PROVIDER=cortecs in der .env, siehe README).
# Laedt das Projekt nach %USERPROFILE%\vfm-pipeline, holt fehlende Ollama-Modelle,
# zieht das fertige App-Image und startet alles. Mehrfach ausfuehren ist ok (Update).
# Ueberschreibbar per Umgebungsvariable: VFM_ZIEL, VFM_ZIP_URL, VFM_IMAGE, VFM_PORT (Standard 8999),
# VFM_ENGINE (docker|podman), VFM_BUILD=1 (App-Image lokal bauen statt ziehen).
# Kein "exit" im Skript: bei "irm | iex" wuerde das das PowerShell-Fenster schliessen.

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

function Start-VfmPipeline {
    # "Continue": in Windows PowerShell 5.1 wuerden stderr-Ausgaben von docker/ollama
    # (Fortschrittsanzeigen) sonst als Fehler abbrechen. Native Befehle pruefen $LASTEXITCODE.
    $ErrorActionPreference = "Continue"
    $ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest sonst sehr langsam

    $Ziel = if ($env:VFM_ZIEL) { $env:VFM_ZIEL } else { Join-Path $env:USERPROFILE "vfm-pipeline" }
    $ZipUrl = if ($env:VFM_ZIP_URL) { $env:VFM_ZIP_URL } else { "https://github.com/CHesseling/vfm-dokumenten-pipeline/archive/refs/heads/main.zip" }
    $Image = if ($env:VFM_IMAGE) { $env:VFM_IMAGE } else { "ghcr.io/chesseling/vfm-pipeline:latest" }
    $Port = if ($env:VFM_PORT) { $env:VFM_PORT } else { "8999" }
    $Gui = "http://localhost:$Port"
    $Bauen = ($env:VFM_BUILD -eq "1")

    Write-Host "==> Pruefe Voraussetzungen"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue) -and -not (Get-Command podman -ErrorAction SilentlyContinue)) {
        throw "Docker fehlt. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/ (oder Podman Desktop)"
    }
    $CE = Get-ContainerEngine
    if (-not $CE) { throw "Docker/Podman laeuft nicht. Bitte Docker Desktop bzw. 'podman machine start' starten und den Befehl erneut ausfuehren." }
    Write-Host "  Container-Engine: $CE"
    & $CE compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw "'$CE compose' fehlt. Docker Desktop aktualisieren bzw. fuer Podman docker-compose installieren." }
    # Ollama ist optional: ohne lokale Modelle geht es mit Cortecs (README "Ohne lokale Modelle")
    $OllamaOk = $false
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        Write-Host "  Ollama fehlt (https://ollama.com/download) - ohne lokale Modelle siehe README."
    } else {
        ollama list *> $null
        if ($LASTEXITCODE -eq 0) { $OllamaOk = $true } else { Write-Host "  Ollama laeuft nicht (Ollama-App starten) - ohne lokale Modelle siehe README." }
    }

    Write-Host "==> Lade Projekt nach $Ziel"
    $Tmp = Join-Path ([System.IO.Path]::GetTempPath()) ("vfm-" + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $Tmp | Out-Null
    try {
        $Zip = Join-Path $Tmp "repo.zip"
        Invoke-WebRequest -Uri $ZipUrl -OutFile $Zip -UseBasicParsing -ErrorAction Stop
        Expand-Archive -Path $Zip -DestinationPath (Join-Path $Tmp "x") -ErrorAction Stop
        $Quelle = Get-ChildItem (Join-Path $Tmp "x") -Directory | Select-Object -First 1
        if (-not (Test-Path (Join-Path $Quelle.FullName "docker-compose.yml"))) { throw "Unerwarteter Inhalt im Download." }
        New-Item -ItemType Directory -Force -Path $Ziel | Out-Null
        # .env und material\ der Teilnehmenden bleiben erhalten
        Copy-Item -Path (Join-Path $Quelle.FullName "*") -Destination $Ziel -Recurse -Force -ErrorAction Stop
        Get-ChildItem $Quelle.FullName -Force -Filter ".*" | Copy-Item -Destination $Ziel -Recurse -Force
    } finally {
        Remove-Item -Recurse -Force $Tmp -ErrorAction SilentlyContinue
    }
    New-Item -ItemType Directory -Force -Path (Join-Path $Ziel "material") | Out-Null

    Push-Location $Ziel
    try {
        if (-not (Test-Path ".env")) {
            Copy-Item ".env.example" ".env"
            Write-Host "  .env aus .env.example angelegt."
        }
        $EnvZeilen = @(Get-Content ".env" | Where-Object { $_ -notmatch '^(APP_IMAGE|APP_PORT)=' })
        # leer bei VFM_BUILD=1: compose nimmt das lokal gebaute vfm-pipeline:latest
        $EnvZeilen += if ($Bauen) { "APP_IMAGE=" } else { "APP_IMAGE=$Image" }
        $EnvZeilen += "APP_PORT=$Port"
        # UTF-8 ohne BOM, damit docker compose die erste Zeile korrekt liest
        [System.IO.File]::WriteAllLines((Join-Path $Ziel ".env"), $EnvZeilen, (New-Object System.Text.UTF8Encoding $false))

        if (Select-String -Path ".env" -Pattern '^PROVIDER=cortecs' -Quiet) {
            Write-Host "==> PROVIDER=cortecs in der .env: Ollama-Modelle werden nicht gebraucht"
        } elseif (-not $OllamaOk) {
            Write-Host "==> HINWEIS: Ohne Ollama melden chat, vision und embed in 'vfm check' Fehler."
            Write-Host "    Entweder Ollama installieren/starten und den Befehl erneut ausfuehren,"
            Write-Host "    oder in $Ziel\.env PROVIDER=cortecs und CORTECS_API_KEY eintragen (README)."
        } else {
            Write-Host "==> Pruefe Ollama-Modelle"
            $Vorhanden = @(ollama list | Select-Object -Skip 1 | ForEach-Object { ($_ -split '\s+')[0] })
            $Modelle = Get-Content "profile\ollama.env" |
                Where-Object { $_ -match '^(CHAT|VISION|EMBED)_MODEL=' } |
                ForEach-Object { ($_ -split '=', 2)[1].Trim() } | Sort-Object -Unique
            foreach ($Modell in $Modelle) {
                if ($Vorhanden -contains $Modell -or $Vorhanden -contains "${Modell}:latest") {
                    Write-Host "  $Modell vorhanden"
                } else {
                    Write-Host "  lade $Modell (mehrere GB, dauert) ..."
                    ollama pull $Modell
                    if ($LASTEXITCODE -ne 0) { throw "ollama pull $Modell fehlgeschlagen." }
                }
            }
        }

        if ($Bauen) {
            Write-Host "==> Lade Datenbank-Image"
            & $CE compose pull db
            if ($LASTEXITCODE -ne 0) { throw "$CE compose pull fehlgeschlagen." }
            Write-Host "==> Baue App-Image und starte (beim ersten Mal 10-20 Minuten)"
            & $CE compose up -d --build
        } else {
            Write-Host "==> Lade Container-Images (beim ersten Mal mehrere GB)"
            & $CE compose pull db app
            if ($LASTEXITCODE -ne 0) { throw "$CE compose pull fehlgeschlagen." }
            Write-Host "==> Starte"
            & $CE compose up -d --no-build
        }
        if ($LASTEXITCODE -ne 0) { throw "$CE compose up fehlgeschlagen." }
    } finally {
        Pop-Location
    }

    Write-Host "==> Warte auf die Oberflaeche"
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri "$Gui/gesundheit" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
            Write-Host ""
            Write-Host "Fertig: $Gui"
            Write-Host "Terminal-Befehle: cd `"$Ziel`"; $CE compose exec app vfm check"
            Write-Host "Terminal im Browser: http://localhost:7681 (Link `"Terminal`" in der Oberflaeche)"
            Write-Host "Hinweis: In der Ollama-App die Kontextlaenge auf mindestens 16k stellen, sonst werden lange Dokumente abgeschnitten."
            Start-Process $Gui
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Die Oberflaeche antwortet nicht. Logs ansehen: cd `"$Ziel`"; $CE compose logs app"
}

try {
    Start-VfmPipeline
} catch {
    Write-Host "FEHLER: $($_.Exception.Message)" -ForegroundColor Red
}
