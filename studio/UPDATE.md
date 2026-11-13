# Пересборка frontend и перезапуск backend

Инструкция для MD2DOC Studio на Windows 11.

Команды выполняются из корня клона MD2DOC-Studio; расположение каталога произвольное.
Адрес в браузере: `http://127.0.0.1:8731`.

## Когда что нужно делать

| Что изменилось | Что выполнить |
|---|---|
| Интерфейс: `.svelte`, `.js`, `.css` в `studio/frontend/src` | Пересобрать frontend и обновить страницу |
| Зависимости frontend: `package.json`, `pnpm-lock.yaml` | Установить зависимости, пересобрать frontend и обновить страницу |
| Backend: Python-файлы в `studio/backend` или `studio/start.py` | Перезапустить сервер |
| И интерфейс, и backend | Выполнить все шаги ниже |

Перед обновлением сохраните черновики Markdown, YAML и визуальных настроек. Дождитесь завершения конвертации. После перезапуска backend проект нужно открыть заново.

## 1. Остановить работающий backend

Перейдите в окно PowerShell, в котором работает сервер Studio, и нажмите **Ctrl+C**. Дождитесь возвращения приглашения PowerShell.

Если такого окна нет, используйте раздел «Сервер работает в фоне» ниже.

Закрытие вкладки браузера само по себе не останавливает backend. Повторный запуск `Start-Studio.ps1` при работающем сервере открывает существующий экземпляр, а не перезапускает его.

## 2. Пересобрать frontend

В PowerShell перейдите в папку интерфейса:

```powershell
cd studio\frontend
```

Установите зависимости:

```powershell
npx.cmd --yes pnpm@11.25.0 install --frozen-lockfile
```

После успешного завершения выполните сборку:

```powershell
npx.cmd --yes pnpm@11.25.0 build
```

Дождитесь сообщения вида:

```text
Wrote site to "build"
```

Собранный интерфейс появится в `studio/frontend/build`.

Эти команды работают без отдельной установки `pnpm`: `npx.cmd` загружает нужную версию. Для загрузки пакетов требуется интернет. На компьютере должен быть установлен Node.js 22.12 или новее.

Если команда установки или сборки завершилась ошибкой, сначала устраните её. Сообщения об ошибках не означают, что новый интерфейс успешно собран.

## 3. Запустить backend заново

В PowerShell выполните:

```powershell
cd ..\..
powershell -ExecutionPolicy Bypass -File .\studio\Start-Studio.ps1
```

При новом запуске в консоли появится сообщение вида:

```text
Uvicorn running on http://127.0.0.1:8731
```

Оставьте это окно PowerShell открытым: в нём работает backend.

Если вместо этого написано `MD2DOC Studio is already running`, старый сервер ещё работает. Вернитесь к шагу остановки; изменения Python ещё не загружены этим экземпляром.

## 4. Обновить браузер

Откройте [MD2DOC Studio](http://127.0.0.1:8731) и нажмите **Ctrl+F5**. Затем откройте нужный проект.

Пересборка интерфейса и конвертация Markdown в DOCX — разные операции. Для обновления приложения нажимать «Конвертировать в DOCX» не требуется.

## Сервер работает в фоне

Этот способ нужен, если сервер запущен, но окна PowerShell с ним нет. Сначала сохраните черновики в приложении и дождитесь завершения конвертации.

Вставьте блок целиком в PowerShell. Он проверяет, что на порту 8731 работает именно Studio, и останавливает её Python-процесс:

```powershell
$StudioListener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort 8731 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1

if ($null -eq $StudioListener) {
    Write-Host 'На порту 8731 нет работающего сервера.'
} else {
    $StudioHealth = Invoke-RestMethod -Uri 'http://127.0.0.1:8731/api/health' -TimeoutSec 3
    $StudioServerProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$($StudioListener.OwningProcess)"

    if ($StudioHealth.application -ne 'md2doc-studio' -or $StudioServerProcess.CommandLine -notmatch 'studio[\\/]start\.py(?:\s|"|$)') {
        throw 'Процесс не распознан как MD2DOC Studio. Остановка отменена.'
    }

    Stop-Process -Id $StudioServerProcess.ProcessId -ErrorAction Stop
    Write-Host 'Backend Studio остановлен.'
}
```

После остановки продолжите с пересборки frontend или с запуска backend — в зависимости от внесённых изменений.

## Частые сообщения

| Сообщение или симптом | Действие |
|---|---|
| `pnpm.cmd` не распознано | Используйте приведённые выше команды через `npx.cmd --yes pnpm@11.25.0` |
| `npx.cmd` не распознано | Установите Node.js и откройте новое окно PowerShell |
| Ошибка несовпадения lockfile | Сохраните текст ошибки; не удаляйте `pnpm-lock.yaml` наугад |
| `Port 8731 is occupied` | Убедитесь, какой процесс занимает порт; для Studio используйте описанную остановку |
| Интерфейс выглядит по-старому | Убедитесь в успешной сборке и нажмите Ctrl+F5 |
| Новая кнопка получает ошибку API | Убедитесь, что backend действительно остановлен и запущен заново |

Эта инструкция не запускает тесты. Сборка frontend также не запускает конвертацию проектов в DOCX.
