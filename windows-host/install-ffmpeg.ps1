# ==============================================================================
# DeckDisplay - Helper script to install FFmpeg on Windows via winget
# ==============================================================================

Write-Host "[DeckDisplay] Проверка наличия совместимого FFmpeg..." -ForegroundColor Cyan

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
$hasDdagrab = $false

if ($ffmpeg) {
    try {
        $filterList = & $ffmpeg.Source -filters 2>&1
        if ($filterList -match "ddagrab") {
            $hasDdagrab = $true
        }
    } catch {
        $hasDdagrab = $false
    }
}

if ($hasDdagrab) {
    Write-Host "[DeckDisplay] Современный FFmpeg с поддержкой ddagrab уже установлен: $($ffmpeg.Source)" -ForegroundColor Green
    exit 0
}

if ($ffmpeg -and -not $hasDdagrab) {
    Write-Host "[ВНИМАНИЕ] Обнаружен устаревший FFmpeg: $($ffmpeg.Source)" -ForegroundColor Yellow
    Write-Host "[DeckDisplay] В установленной версии отсутствует фильтр ddagrab (требуется для Zero-Build режима)." -ForegroundColor Yellow
}

Write-Host "[DeckDisplay] Установка актуальной сборки FFmpeg (Gyan.FFmpeg) через winget..." -ForegroundColor Yellow
winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements

Write-Host "[DeckDisplay] Установка завершена. Перезапустите терминал для обновления переменной PATH." -ForegroundColor Green
