# Einrichten und Starten in einem Zug (Windows PowerShell), fuer Teilnehmende:
#   irm https://raw.githubusercontent.com/CHesseling/vfm-dokumenten-pipeline/main/scripts/start.ps1 | iex
# Voraussetzung: Docker Desktop und Ollama sind installiert und laufen.
# Laedt das Projekt nach %USERPROFILE%\vfm-pipeline, holt fehlende Ollama-Modelle,
# zieht das fertige App-Image und startet alles. Mehrfach ausfuehren ist ok (Update).
# Ueberschreibbar per Umgebungsvariable: VFM_ZIEL, VFM_ZIP_URL, VFM_IMAGE, VFM_PORT (Standard 8999).
# Kein "exit" im Skript: bei "irm | iex" wuerde das das PowerShell-Fenster schliessen.

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

    Write-Host "==> Pruefe Voraussetzungen"
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker fehlt. Bitte Docker Desktop installieren: https://www.docker.com/products/docker-desktop/"
    }
    docker info *> $null
    if ($LASTEXITCODE -ne 0) { throw "Docker laeuft nicht. Bitte Docker Desktop starten und den Befehl erneut ausfuehren." }
    docker compose version *> $null
    if ($LASTEXITCODE -ne 0) { throw "'docker compose' fehlt. Bitte Docker Desktop aktualisieren." }
    if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
        throw "Ollama fehlt. Bitte installieren: https://ollama.com/download"
    }
    ollama list *> $null
    if ($LASTEXITCODE -ne 0) { throw "Ollama laeuft nicht. Bitte die Ollama-App starten und den Befehl erneut ausfuehren." }

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
        $EnvZeilen += "APP_IMAGE=$Image"
        $EnvZeilen += "APP_PORT=$Port"
        # UTF-8 ohne BOM, damit docker compose die erste Zeile korrekt liest
        [System.IO.File]::WriteAllLines((Join-Path $Ziel ".env"), $EnvZeilen, (New-Object System.Text.UTF8Encoding $false))

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

        Write-Host "==> Lade Docker-Images (beim ersten Mal mehrere GB)"
        docker compose pull db app
        if ($LASTEXITCODE -ne 0) { throw "docker compose pull fehlgeschlagen." }
        Write-Host "==> Starte"
        docker compose up -d --no-build
        if ($LASTEXITCODE -ne 0) { throw "docker compose up fehlgeschlagen." }
    } finally {
        Pop-Location
    }

    Write-Host "==> Warte auf die Oberflaeche"
    for ($i = 0; $i -lt 90; $i++) {
        try {
            Invoke-WebRequest -Uri "$Gui/gesundheit" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop | Out-Null
            Write-Host ""
            Write-Host "Fertig: $Gui"
            Write-Host "Terminal-Befehle: cd `"$Ziel`"; docker compose exec app vfm check"
            Write-Host "Hinweis: In der Ollama-App die Kontextlaenge auf mindestens 16k stellen, sonst werden lange Dokumente abgeschnitten."
            Start-Process $Gui
            return
        } catch {
            Start-Sleep -Seconds 2
        }
    }
    throw "Die Oberflaeche antwortet nicht. Logs ansehen: cd `"$Ziel`"; docker compose logs app"
}

try {
    Start-VfmPipeline
} catch {
    Write-Host "FEHLER: $($_.Exception.Message)" -ForegroundColor Red
}
