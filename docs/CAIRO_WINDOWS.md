# SVG и Cairo на Windows

Для PNG/JPEG библиотека Cairo не нужна. Для SVG используются зафиксированные
CairoSVG/cairocffi из Python lock-файла и **отдельная системная Cairo x64**.
Studio не скачивает нативные DLL и не поставляет их в Git.

Если Cairo уже установлена, укажите каталог, содержащий `cairo.dll` **вместе
с зависимыми DLL**, в текущем PowerShell перед запуском Studio:

```powershell
$env:MD2DOC_CAIRO_DLL_DIR = 'C:\Libraries\Cairo\bin'
powershell -ExecutionPolicy Bypass -File .\studio\Start-Studio.ps1
```

Это пример выбранного вами каталога, не требование к пути клона. Разрядность
Python и DLL должна совпадать. Не копируйте один cairo.dll без зависимостей.

Один из вариантов установки — отдельный префикс conda-forge через
[Miniforge](https://github.com/conda-forge/miniforge). После установки Miniforge
выполните в его консоли:

```powershell
conda create --prefix "$env:LOCALAPPDATA\md2doc-cairo" --override-channels --channel conda-forge cairo
```

Затем в PowerShell, из корня клона:

```powershell
$env:MD2DOC_CAIRO_DLL_DIR = Join-Path $env:LOCALAPPDATA 'md2doc-cairo\Library\bin'
if (-not (Test-Path (Join-Path $env:MD2DOC_CAIRO_DLL_DIR 'cairo.dll'))) { throw 'Проверьте установленный Cairo runtime и путь к DLL.' }
powershell -ExecutionPolicy Bypass -File .\studio\Start-Studio.ps1
```

[Пакет Cairo для Windows x64](https://anaconda.org/conda-forge/cairo),
[документация CairoSVG](https://cairosvg.org/documentation/).
Miniforge здесь нужен для нативных библиотек; приложение продолжает работать
в своей `studio/.venv`. Установку системного runtime пользователь выполняет
отдельно. У Cairo/CairoSVG собственные лицензии; MIT проекта их не заменяет.

Без Cairo приложение запускается и конвертирует документы без SVG.
Попытка включить SVG завершится диагностикой `E_IMAGE`, не скрытым пропуском.
