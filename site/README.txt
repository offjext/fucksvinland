# Сайт

1. После сборки: `dist\ddjj.exe` → `site\releases\app.exe`
2. Версия в `site\releases\meta.json` (`version`, `sha256`)
3. Запуск: `run_site.bat` → http://127.0.0.1:8080
4. У клиента в `config.json`: `"update_url": "http://ТВОЙ_IP:8080"`

Скачивание с сайта: каждый раз своё имя файла и размер (pad).
Автообнова тянет чистый `app.exe` без pad.
