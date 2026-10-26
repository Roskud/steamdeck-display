# ==============================================================================
# DeckDisplay - Setup Script for Virtual Display Driver (IddCx)
# Copies Steam Deck native resolution profile (1280x800 @ 60/90Hz) to
# C:\IddSampleDriver\option.txt and assists with driver deployment.
# ==============================================================================

# Проверка прав администратора
$currentPrincipal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $currentPrincipal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "[DeckDisplay] Требуются права Администратора для настройки драйвера..." -ForegroundColor Yellow
    Start-Process powershell -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`""
    exit
}

$targetDir = "C:\IddSampleDriver"
$targetFile = Join-Path $targetDir "option.txt"
$sourceFile = Join-Path $PSScriptRoot "option.txt"

Write-Host "====================================================================" -ForegroundColor Cyan
Write-Host "   DeckDisplay - Настройка виртуального монитора (IddCx Driver)     " -ForegroundColor Cyan
Write-Host "====================================================================" -ForegroundColor Cyan

# 1. Создание каталога и копирование профиля разрешения
if (-not (Test-Path $targetDir)) {
    Write-Host "[DeckDisplay] Создание каталога $targetDir..." -ForegroundColor Yellow
    New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
}

if (Test-Path $sourceFile) {
    Copy-Item -Path $sourceFile -Destination $targetFile -Force
    Write-Host "[DeckDisplay] Профиль Steam Deck (1280x800 @ 60/90Hz) скопирован в $targetFile" -ForegroundColor Green
} else {
    # Создание option.txt напрямую
    Set-Content -Path $targetFile -Value @("1", "1280, 800, 60", "1280, 800, 90") -Encoding Ascii
    Write-Host "[DeckDisplay] Файл $targetFile успешно создан с параметрами 1280x800 60/90Hz." -ForegroundColor Green
}

# 2. Проверка наличия установленного устройства IddSampleDriver
$iddDevice = Get-PnpDevice -FriendlyName "*Virtual Display*" -ErrorAction SilentlyContinue
if ($iddDevice) {
    Write-Host "[DeckDisplay] Виртуальный дисплей обнаружен в системе: $($iddDevice.FriendlyName) ($($iddDevice.Status))" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Host "[Инструкция по установке драйвера IddSampleDriver / MTT]:" -ForegroundColor Yellow
    Write-Host "1. Скачайте последнюю версию драйвера с GitHub:" -ForegroundColor White
    Write-Host "   https://github.com/itsmikethetech/Virtual-Display-Driver/releases" -ForegroundColor Cyan
    Write-Host "2. Распакуйте архив в $targetDir" -ForegroundColor White
    Write-Host "3. Запустите 'Install.bat' от имени Администратора" -ForegroundColor White
    Write-Host "   или установите через Диспетчер устройств -> Действие -> Установить старое устройство." -ForegroundColor White
    Write-Host ""

    $choice = Read-Host "Открыть страницу загрузки драйвера в браузере? (Y/N)"
    if ($choice -match "^[yYдД]") {
        Start-Process "https://github.com/itsmikethetech/Virtual-Display-Driver/releases"
    }
}

Write-Host ""
Write-Host "[DeckDisplay] Готово! Теперь Windows создаст виртуальный экран 1280x800 с частотой до 90 Гц." -ForegroundColor Green
