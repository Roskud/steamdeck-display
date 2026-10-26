# ==============================================================================
# DeckDisplay - Automated Plug & Play Watchdog & Hardware Streamer for Windows
# Automatically detects Steam Deck USB-C connection, configures network adapter,
# selects optimal GPU hardware encoder (NVENC / AMF / QSV), and launches stream.
# ==============================================================================

[CmdletBinding()]
param(
    [string]$DeckIP = "10.77.77.2",
    [int]$Port = 5000,
    [int]$OutputIdx = 1,              # 0 = основной дисплей, 1 = виртуальный монитор IddCx
    [int]$Framerate = 90,             # 90 для Steam Deck OLED, 60 для LCD
    [string]$Encoder = "auto",        # auto, h264_nvenc, h264_amf, h264_qsv, libx264
    [string]$Bitrate = "45M"          # 45 Mbps битрейт передачи
)

# Проверка и запрос прав Администратора
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[DeckDisplay] Запрос привилегий Администратора для настройки сети..." -ForegroundColor Yellow
    $arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    if ($PSBoundParameters.Count -gt 0) {
        foreach ($param in $PSBoundParameters.GetEnumerator()) {
            $arguments += " -$($param.Key) $($param.Value)"
        }
    }
    Start-Process powershell -Verb RunAs -ArgumentList $arguments
    exit
}

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "    DeckDisplay Windows Host - Автоматический Plug & Play Вотчдог   " -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "[DeckDisplay] Параметры: Экран #$OutputIdx | $Framerate FPS | Битрейт $Bitrate | Порт $Port" -ForegroundColor DarkCyan

# 1. Автоопределение установленной видеокарты при режиме "auto"
if ($Encoder -eq "auto") {
    $gpuList = Get-CimInstance Win32_VideoController -ErrorAction SilentlyContinue
    $gpuName = ($gpuList | Select-Object -ExpandProperty Name) -join " "
    Write-Host "[DeckDisplay] Обнаружен видеоадаптер: $gpuName" -ForegroundColor Gray

    if ($gpuName -match "NVIDIA|GeForce|RTX|GTX|Quadro") {
        $Encoder = "h264_nvenc"
    } elseif ($gpuName -match "AMD|Radeon|Advanced Micro Devices") {
        $Encoder = "h264_amf"
    } elseif ($gpuName -match "Intel|Arc|Iris|UHD") {
        $Encoder = "h264_qsv"
    } else {
        $Encoder = "libx264"
    }
    Write-Host "[DeckDisplay] Автоматически выбран аппаратный энкодер: $Encoder" -ForegroundColor Green
}

# 2. Проверка наличия FFmpeg в системе (при отсутствии скомпилированного сервера)
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
$serverExe = Join-Path $scriptDir "deckdisplay_server.exe"

if (-not (Test-Path $serverExe)) {
    $ffmpegCmd = Get-Command ffmpeg -ErrorAction SilentlyContinue
    if (-not $ffmpegCmd) {
        Write-Host "[ВНИМАНИЕ] Утилита ffmpeg.exe не найдена в PATH!" -ForegroundColor Red
        Write-Host "[DeckDisplay] Рекомендуется установить FFmpeg через winget:" -ForegroundColor Yellow
        Write-Host "    winget install Gyan.FFmpeg" -ForegroundColor White
        Write-Host "Или запустите вспомогательный скрипт install-ffmpeg.ps1" -ForegroundColor Yellow
        Write-Host ""
    }
}

Write-Host "[DeckDisplay] Ожидание подключения Steam Deck по кабелю USB Type-C ($DeckIP)..." -ForegroundColor Cyan

# 3. Главный цикл Plug & Play
while ($true) {
    # Поиск виртуального сетевого адаптера USB CDC-NCM / Remote NDIS
    $usbNet = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object {
        ($_.InterfaceDescription -match "UsbNcm|Remote NDIS|CDC|Steam Deck" -or $_.Name -match "UsbNcm|Ethernet") -and
        $_.Status -eq "Up"
    }

    if ($usbNet) {
        foreach ($adapter in $usbNet) {
            $ipObj = Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue
            $hasCorrectIP = ($ipObj | Where-Object { $_.IPAddress -eq "10.77.77.1" })

            if (-not $hasCorrectIP) {
                Write-Host "[DeckDisplay] Настройка статического IP 10.77.77.1/30 на интерфейсе $($adapter.Name)..." -ForegroundColor Yellow
                New-NetIPAddress -InterfaceIndex $adapter.ifIndex -IPAddress "10.77.77.1" -PrefixLength 30 -ErrorAction SilentlyContinue | Out-Null
            }
        }
    }

    # Проверка доступности Steam Deck по сети
    $pingOk = Test-Connection -ComputerName $DeckIP -Count 1 -Quiet -ErrorAction SilentlyContinue
    if ($pingOk) {
        Write-Host "[DeckDisplay] Steam Deck обнаружен в сети ($DeckIP)! Запуск видеопотока..." -ForegroundColor Green

        if (Test-Path $serverExe) {
            # Вариант А: Запуск скомпилированного C++ DXGI сервера
            Write-Host "[DeckDisplay] Запуск нативного C++ Zero-Copy сервера ($serverExe)..." -ForegroundColor Cyan
            & $serverExe $DeckIP $Port $OutputIdx $Framerate
        } else {
            # Вариант Б: Zero-Build режим через аппаратный конвейер FFmpeg (ddagrab)
            Write-Host "[DeckDisplay] Запуск Zero-Build конвейера через FFmpeg ddagrab..." -ForegroundColor Cyan

            $encArgs = switch ($Encoder) {
                "h264_nvenc" { "-c:v h264_nvenc -preset p1 -tune ull -zerolatency 1 -forced-idr 1 -repeat-headers 1 -bf 0" }
                "h264_amf"   { "-c:v h264_amf -usage ultralowlatency -quality speed -header_insertion_mode idr -bf 0" }
                "h264_qsv"   { "-c:v h264_qsv -preset veryfast -low_delay_brc 1 -forced-idr 1 -bf 0" }
                default      { "-c:v libx264 -preset ultrafast -tune zerolatency -bf 0" }
            }

            # Фильтр ddagrab производит аппаратный захват VRAM и преобразует текстуру в NV12 для энкодера
            $cmd = "ffmpeg -hide_banner -loglevel warning " +
                   "-init_hw_device d3d11va=gpu:0 -filter_hw_device gpu " +
                   "-f lavfi -i `"ddagrab=output_idx=$($OutputIdx):framerate=$($Framerate):draw_mouse=1,hwdownload,format=bgra,format=nv12`" " +
                   "$encArgs -b:v $Bitrate -maxrate $Bitrate -bufsize 500k -g $Framerate " +
                   "-f h264 `"udp://$($DeckIP):$($Port)?pkt_size=1400`""

            Write-Host "[DeckDisplay] Команда: $cmd" -ForegroundColor DarkGray
            Invoke-Expression $cmd
        }

        Write-Host "[DeckDisplay] Соединение прервано или кабель отключен. Ожидание повторного подключения..." -ForegroundColor Yellow
    }

    Start-Sleep -Seconds 1
}
