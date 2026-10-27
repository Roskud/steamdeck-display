# DeckDisplay 🎮🖥️

**DeckDisplay** — это высокопроизводительное решение с открытым исходным кодом, превращающее **Steam Deck (LCD и OLED)** в сверхбыстрый проводной второй монитор для ПК по кабелю **USB Type-C**.

---

## 🚀 Установка

### 1. Для Steam Deck (Плагин Decky)
Самый простой способ установки — через Decky Loader.

1. Установите [Decky Loader](https://github.com/SteamDeckHomebrew/decky-loader).
2. Нажмите кнопку `...` (Quick Access Menu) → иконка **Decky Loader** (шестеренка).
3. Перейдите в раздел **Developer** и вставьте ссылку на этот репозиторий:
   `https://github.com/Roskud/steamdeck-display`
4. Нажмите **Install**. Плагин появится в меню.

### 2. Для ПК (Windows)
1. Перейдите в раздел [Releases](https://github.com/Roskud/steamdeck-display/releases) (или скачайте готовый `DeckDisplay.exe` из папки `/releases` в этом репозитории).
2. Запустите `DeckDisplay.exe`.
3. Подключите Steam Deck кабелем Type-C.

---

## 📁 Файлы для установки
Вы можете скачать готовые файлы прямо из этого репозитория:
- [DeckDisplay.exe](releases/DeckDisplay.exe) — готовое приложение для Windows.
- [DeckDisplay_Plugin.zip](releases/DeckDisplay_Plugin.zip) — архив для ручной установки плагина (если не работает установка через ссылку).

---

## ⚙️ Технические особенности
- **Zero-Copy**: Аппаратный захват (NVENC/AMF/QSV) и декодирование (VA-API).
- **Plug & Play**: Автоматическая настройка сети и тачскрина при подключении.
- **Поддержка**: 60/90 Гц, сенсорный ввод.

---

## 🛠️ Сборка из исходников
Если вы разработчик, инструкции по сборке C++ сервера и C-клиента находятся в папках `windows-host` и `steamos-client`.
