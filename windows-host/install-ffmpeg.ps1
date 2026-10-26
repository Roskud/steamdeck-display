# ==============================================================================
# DeckDisplay - Helper script to install FFmpeg on Windows via winget
# ==============================================================================

Write-Host "[DeckDisplay] Проверка наличия FFmpeg..." -ForegroundColor Cyan

$ffmpeg = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ffmpeg) {
    Write-Host "[DeckDisplay] FFmpeg уже установлен: $($ffmpeg.Source)" -ForegroundColor Green
    exit 0
}

Write-Host "[DeckDisplay] Установка FFmpeg (Gyan.FFmpeg) через Windows Package Manager (winget)..." -ForegroundColor Yellow
winget install Gyan.FFmpeg --accept-package-agreements --accept-source-agreements

Write-Host "[DeckDisplay] Установка завершена. Перезапустите терминал для обновления переменной PATH." -ForegroundColor Green
