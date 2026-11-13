# Python Core и CLI

Core 0.2.3 расположен в `src/md2doc`. Studio импортирует этот пакет напрямую;
CLI можно установить независимо от веб-интерфейса. Требуется Python 3.12+.

Из корня клона:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install --no-deps -e .
.\.venv\Scripts\python.exe -m md2doc build .\examples\minimal --strict
.\.venv\Scripts\python.exe -m md2doc build .\examples\minimal --validate-only
```

`--output PATH` переопределяет результат, `--verbose` печатает детали,
`--strict` превращает предупреждения в отказ. Путь результата по умолчанию
берётся из `build.output_dir` и `build.output_name`. Относительный `--output`
отсчитывается от рабочего каталога CLI.

Код завершения: 0 — успех; 1 — ошибка проекта/конвертации/строгой проверки;
2 — ошибка чтения, записи или аргументов. Рядом с результатом размещается
`build-report.json`. При ошибке прежний корректный DOCX сохраняется.
Исходные Markdown и YAML не переписываются.

Центральная проверка поставки:

```powershell
.\.venv\Scripts\python.exe tools/verify_delivery .\examples\minimal --strict
```

`--input-only` проверяет конфигурацию и модель без готового DOCX,
`--output PATH` выбирает существующий результат для проверки,
`--json PATH` сохраняет отчёт. Независимый искусственный документ для ручной
проверки нумерации создаёт `tools/verify_delivery/create_diagnostic.py`.
Microsoft Word, Pandoc и LibreOffice для конвертации не требуются.

Контракты [формата](FORMAT.md), [нумерации](NUMBERING.md),
[архитектуры](ARCHITECTURE.md) и [ограничений](LIMITATIONS.md).
Для SVG отдельно нужна [Cairo](CAIRO_WINDOWS.md); PNG/JPEG работают без неё.
