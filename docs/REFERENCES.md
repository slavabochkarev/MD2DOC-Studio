# Технические референсы и компоненты

## Word numbering 0.2.1

- [Microsoft MS-OI29500 2.1.50](https://learn.microsoft.com/en-us/openspecs/office_standards/ms-oi29500/6a8f14ff-df90-4154-9bc9-e0e88ae5e641):
  Word непредсказуемо обрабатывает ilvl внутри numPr определения стиля.
  Это конкретный дефект генерации 0.2.0, устранённый в 0.2.1.
- [ParagraphStyleIdInLevel](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.paragraphstyleidinlevel):
  связь уровня со стилем через lvl/pStyle; стиль хранит numId без ilvl.
- [NumberingProperties](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.numberingproperties):
  прямое numPr абзаца содержит numId и ilvl; правила наследования отличаются от стиля.
- [LevelText](https://learn.microsoft.com/en-us/dotnet/api/documentformat.openxml.wordprocessing.leveltext):
  подстановки %1..%9 в native lvlText и счётчики уровней.
- [Validate a word processing document](https://learn.microsoft.com/en-us/office/open-xml/word/how-to-validate-a-word-processing-document):
  независимая проверка OpenXmlValidator. В QA использован официальный NuGet
  DocumentFormat.OpenXml 2.20.0 (MIT), в режиме Office2013, только для чтения.
  Это необязательный инструмент проверки поставки, а не зависимость конвертера.
  Пакет и DLL находятся в игнорируемом qa/numbering-fix/sdk и не включены в wheel.

Правила входной схемы 0.1 перенесены в config.validation; файлы doc1 не являются
зависимостью движка. Текущий контракт расширения описан в NUMBERING.md.
Ни SDK-проверка схемы, ни собственный инспектор не заменяют ручной просмотр Word.

Исследование выполнено 11 ноября 2026 года до и во время реализации.
Код конвертеров mdocx/md2office не копировался; они не являются зависимостями.
Собственный формат не подгонялся под их схему. Фактический контракт — файлы
FORMAT_SPEC/STYLES_SPEC и оригинальный tools/validate.py в doc1.

## python-docx

- [Официальный репозиторий](https://github.com/python-openxml/python-docx), MIT.
- [Quickstart](https://python-docx.readthedocs.io/en/latest/user/quickstart.html):
  абзацы, runs, headings, таблицы, изображения, размеры и пропорции.
- [Стили](https://python-docx.readthedocs.io/en/latest/user/styles-using.html):
  реальные именованные стили; встроенные имена в OOXML — английские.
- [Секции](https://python-docx.readthedocs.io/en/latest/user/sections.html):
  размеры страниц, ориентация, поля и привязка колонтитулов.
- [Колонтитулы](https://python-docx.readthedocs.io/en/latest/user/hdrftr.html),
  [абзацы](https://python-docx.readthedocs.io/en/latest/user/text.html).

Применён официальный пакет 1.2.0. Публичный API используется для документа,
стилей, runs, таблиц, изображений и секций. Нумерация, закладки, активные ссылки,
поля, свойства таблиц и дополнительные параметры доступны через изолированный
OOXML-слой. Шаблон библиотеки очищается от не объявленных в YAML остатков.

## mdocx

- [Репозиторий и README](https://github.com/jashnimje/mdocx), MIT.
- [md2docx.py](https://github.com/jashnimje/mdocx/blob/main/md2docx.py).
- [Тесты списков](https://github.com/jashnimje/mdocx/blob/main/tests/test_lists.py).

Изучены подходы к нативным структурам Word, независимому перезапуску списков,
вложенности, символьным стилям кода, гиперссылкам и проверке numbering OOXML.
Взята архитектурная идея проверять структуру DOCX, а не только текст или
существование ZIP. Особенности обратной конвертации и сохранения комментариев
в задачу не входят. Перенос правила «первый H1 становится Title» не применён:
тип заголовка в MD2DOC определяет собственный манифест.

## md2office

- [Репозиторий и README](https://github.com/mmaudet/md2office), Apache-2.0.
- [StyleMapper](https://github.com/mmaudet/md2office/blob/main/src/md2office/builder/style_mapper.py).
- [Converter pipeline](https://github.com/mmaudet/md2office/blob/main/src/md2office/core/converter.py).
- [TableBuilder](https://github.com/mmaudet/md2office/blob/main/src/md2office/builder/table_builder.py).

Изучено разделение parser/model/builder, сопоставление семантических элементов
со стилями Word, таблицы с выделением заголовка и чередованием строк,
контейнеры и отделённый слой шаблонов. В v0.1 применено разделение
ответственности; DOCX-template engine и подстановка Jinja не добавлялись,
поскольку не входят в контракт MD2DOC 0.1.

## Установленные прямые зависимости

| Компонент | Версия | Лицензия / назначение |
| --- | --- | --- |
| python-docx | 1.2.0 | MIT, генерация DOCX |
| markdown-it-py | 4.0.0 | MIT, CommonMark AST + tables/strikethrough |
| PyYAML | 6.0.3 | MIT, загрузчик оригинального валидатора |
| Pillow | 12.0.0 | MIT-CMU, изображения и метрики |
| lxml | 6.1.3 | BSD-3-Clause, XML; notices библиотек libxml2/libxslt |
| defusedxml | 0.7.1 | PSF, безопасный SVG XML |
| CairoSVG (extra svg) | 2.8.2 | LGPLv3, локальное преобразование SVG |
| pytest (extra test) | 9.0.2 | MIT, тестирование |
| setuptools (build) | 80.9.0 | MIT, сборка пакета |

Транзитивные версии зафиксированы в requirements.lock. Полный перечень
установленных дистрибутивов с лицензионными метаданными находится в
docs/DEPENDENCIES.json. Проверка `pip check` проходит. Собственный код проекта распространяется по MIT (см. LICENSE).

## SVG и коммерческая упаковка

[CairoSVG documentation](https://cairosvg.org/documentation/) прямо указывает
LGPLv3 и необходимость системной Cairo.
[Текст лицензии CairoSVG](https://github.com/Kozea/CairoSVG/blob/main/LICENSE)
определяет условия Combined Works и shared-library mechanism. Cairo имеет
собственные лицензионные условия; конкретный системный binary должен быть
проверен перед поставкой. В этом проекте CairoSVG оставлен отдельным extra,
а Cairo загружается динамически из уже доступного runtime, без копирования
бинарников. Эта реализация не является готовым планом лицензионного
сопровождения коммерческого Windows EXE.

GPL-инструменты (Pandoc/Poppler-CLI и т. п.) не включены в приложение. Попытка
визуального QA использует отдельный helper среды; ни он, ни LibreOffice не
являются зависимостями конвертера. Изображения не загружаются по сети:
SVG-ресурсы и активное содержимое отклоняются, `unsafe` не включается.
