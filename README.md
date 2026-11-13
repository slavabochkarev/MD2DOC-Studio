# MD2DOC Studio

Локальное Windows-приложение для преобразования Markdown-проекта в редактируемый DOCX.
**Studio MVP 0.1.0 · MD2DOC Core 0.2.3 · MIT.**

Веб-интерфейс SvelteKit/Svelte и FastAPI находятся в `studio/`, независимый
Python Core — в `src/md2doc`. Studio предоставляет дерево проекта,
редакторы Markdown/YAML с защитой от внешних изменений, HTML-preview,
визуальные настройки страницы, H1–H6 и колонтитулов, конвертацию и диагностику.
Сборка DOCX не требует Word, Pandoc или LibreOffice. Приложение работает через localhost.

## Установка из чистого клона: Windows 11

Нужны **Git, Python 3.12+ (проверено на 3.12 x64), Node.js 22.12+ с npm/npx**
и интернет для загрузки зависимостей. Все команды PowerShell выполняются из корня клона.
Путь клона можно выбрать любой.

```powershell
git clone https://github.com/slavabochkarev/MD2DOC-Studio.git
cd MD2DOC-Studio
powershell -ExecutionPolicy Bypass -File .\studio\Setup-Studio.ps1
powershell -ExecutionPolicy Bypass -File .\studio\Start-Studio.ps1
```

Setup создаёт `studio/.venv`, устанавливает Python-зависимости из lock-файла,
затем собирает frontend. Если pnpm 11.25.0 не установлен, используется
`npx.cmd --yes pnpm@11.25.0`; отдельная установка pnpm не нужна.
Для выбора Python: `-PythonExe (py -3.12 -c "import sys; print(sys.executable)")`.

Откройте **http://127.0.0.1:8731**. Скопируйте `examples/minimal` в свою папку,
откройте её кнопкой «Открыть проект» и сформируйте DOCX. Пример содержит только
искусственные данные. Результат появится в `output/example.docx`.
Studio открывает существующие проекты; отдельного мастера создания проекта нет.

Frontend build, node_modules и venv в Git не хранятся. Точные команды ручной сборки:

```powershell
cd studio\frontend
npx.cmd --yes pnpm@11.25.0 install --frozen-lockfile
npx.cmd --yes pnpm@11.25.0 check
npx.cmd --yes pnpm@11.25.0 build
cd ..\..
```

Node.js нужен при сборке frontend, а не при каждом запуске. Для другого порта
используйте `Start-Studio.ps1 -Port 8732`. Остановка — Ctrl+C в окне сервера.
Для SVG отдельно установите [Cairo](docs/CAIRO_WINDOWS.md). Без неё PNG/JPEG,
интерфейс и пример без SVG работают. DLL и зависимости не привязаны к Codex/runtime
или к исходному пути разработки.

## Исходники и документация

- `src/md2doc/` — CLI, схемы 0.1/0.2, Markdown, модель, DOCX и OOXML-нумерация.
- `studio/backend/md2doc_web/` — FastAPI, сохранение/резервные копии, preview и сборка.
- `studio/frontend/src/` — единственная рабочая реализация интерфейса.
- `tests/`, `studio/tests/`, `tests/fixtures/` — тесты ядра и Studio.
- `tools/verify_delivery/` — проверки готового документа и диагностический пример.
- [Использование Studio](studio/README.md), [обновление](studio/UPDATE.md),
  [CLI](docs/CLI.md), [архитектура](docs/ARCHITECTURE.md),
  [формат 0.1/0.2](docs/FORMAT.md), [нумерация](docs/NUMBERING.md),
  [колонтитулы](studio/HEADER_SUPPORT.md), [ограничения](docs/LIMITATIONS.md).

Схемы встроены в Python-пакет; внешний исторический валидатор не требуется.
Ранние HTML-прототипы, дизайн-архивы, личные проекты и QA-артефакты исключены
из публикации. Приложение не зависит от `design/ui/`.

## Проверки

После Setup и сборки frontend:

```powershell
.\studio\.venv\Scripts\python.exe -m pytest tests -q
.\studio\.venv\Scripts\python.exe -m pytest studio/tests -q
```

Проверки работают с искусственными проектами и временными копиями.
Необязательные локальные эталоны можно задать переменными
`MD2DOC_DOC1_PROJECT`, `MD2DOC_ECOBURO_PROJECT`, `MD2DOC_STUDIO_TEST_PROJECT`.
Они не требуются для работы клона; соответствующие дополнительные проверки
без эталонов пропускаются. Результаты Word проверяются структурно; тесты не
подтверждают визуальное отображение во всех версиях Word и не запускают его.

Собственный код распространяется по [MIT LICENSE](LICENSE).
Лицензии зависимостей перечислены в [REFERENCES](docs/REFERENCES.md).
