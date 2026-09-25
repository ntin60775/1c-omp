---
name: unica-project-setup
description: "Первичная настройка Unica (MCP + v8-runner) в любом 1С-проекте: подключение без дублей, v8project.yaml/local-overlay, проверка workspace, первая выгрузка/загрузка, git-гигиена исходников. Используй когда подключаешь Unica к новому или чужому 1С-репозиторию, когда unica.project.status не находит source-set'ы, когда в списке инструментов видны двойственные mcp__unica_unica_* префиксы, когда applied-операции отказывают до discovery, или при заводе исходников конфигурации/расширений в git с нуля."
tags: [1c, unica, v8-runner, workspace, bootstrap]
---

# Первичная настройка Unica в 1С-проекте: playbook

Порядок подключения Unica (MCP `unica.*` + встроенный v8-runner) к любому
1С-проекту. Все пути — плейсхолдеры. Тестовый контур (YAxUnit/Vanessa) —
скилл `unica-test-contour`.

## 0. Предусловия

- Плагин Unica установлен (`installed_plugins.json`: `unica@unica`, scope
  user|project). Канонический источник MCP-сервера и skills — ПЛАГИН.
- 1С-платформа установлена; для тестов нужна ПОЛНАЯ (с `1cv8c`), не серверная.
- Есть либо ИБ (тогда выгружаем), либо XML-исходники (тогда грузим).

## 1. Одно MCP-подключение, без дублей

Симптом дубля: в инструментах одновременно `mcp__unica_*` и
`mcp__unica_unica_*`; в `ps` — несколько цепочек
`git -c alias.unica-bootstrap → unica`.

Правило: ручная запись `unica` в `.omp/mcp.json` НЕ нужна — плагин сам несёт
`.mcp.json`. Ручной дубликат удалить, оставить `mcpServers: {}` (или только
другие серверы), перезапустить сессию. Ручная запись допустима лишь когда
плагин не устанавливается, и тогда без plugin-регистрации.

### 1а. Жизненный цикл сервера: три разных отказа подключения

| Симптом | Окно | Причина → действие |
|---|---|---|
| `EPIPE: broken pipe, send` | новая сессия | устаревшая ручная запись на захардкоженный версионированный путь → удалить `.omp/mcp.json` |
| `MCP server failed to connect … timed out after 30000ms` | `--continue`/resume после установки | bootstrap не уложился в 30 с, живая сессия держит старый процесс → **новая сессия**, не продолжение |
| `MCP error -32000: failed to read current directory` | уже живая сессия, все инструменты | пересоздание кэша плагинов при живом сервере (`cwd → (deleted)`) → диагностика/восстановление по `rule://unica-mcp` |

При установке/обновлении — всегда новая сессия. После `init-worktree.sh` шаг
плагинов может сломать уже работающие сессии: запускать инициализатор до первых
`unica.*`-вызовов либо флагом `--skip-plugins`.

## 2. Все MCP-вызовы — с `cwd` корня проекта

Без `cwd` workspace резолвится в каталог кэша плагина →
`No source sets were discovered`, `Workspace is not inside a Git work tree`.
Эталонный вызов проверки:

```json
unica.project.status { "cwd": "<корень проекта>" }
unica.project.map    { "cwd": "<корень проекта>" }
```

`ready: true` + список source-set'ов с `sourceFormat: platform_xml` —
workspace годен. `repositoryReady: false` по причине
`resource classification count exceeds 65536 entries` на гигантских выгрузках
(ERP-класс) — известное ограничение, на работу не влияет.

## 3. `v8project.yaml` — руками, applied `config-init` не полагаться

Applied `config-init`/`init` fail-closed (пишут вне прерываемой транзакции) —
создавать файл руками по схеме
`https://raw.githubusercontent.com/alkoleft/v8-runner-rust/master/docs/schemas/v8project.schema.json`:

```yaml
workPath: 'build'
execution_timeout: 3600000
format: DESIGNER
builder: DESIGNER
infobase:
  connection: 'File=build/ib'          # или 'Srvr="srv";Ref="db";'
source-set:
  - name: main
    type: CONFIGURATION
    path: 'src/cf'
  - name: <Расш1>
    type: EXTENSION
    path: 'src/cfe/<Расш1>'
build:
  partialLoadThreshold: 20
```

- `format/builder: DESIGNER` — файловая ИБ; для серверной IBCMD нужен
  `infobase.dbms`. Legacy top-level `connection` не использовать.
- Каждый source-set — отдельный strict-child каталог (`path: .` — ошибка).
- Тестовые расширения — тоже EXTENSION source-set'ы (обычно `tests/cfe/<...>`).

## 4. `v8project.local.yaml` — локальное и секретное (gitignored)

```yaml
infobase:
  user: <пользователь ИБ>        # пароль — только сюда, никогда в git/чат/лог
tools:
  platform:
    version: "<8.3.27.xxxx>"
    path: "<каталог установки>"  # плоский каталог с 1cv8, 1cv8c, ibcmd
    strict: true
```

- Не добавлять в local-overlay: `source-set`, `format`, `builder`,
  `execution_timeout` (это контракт команды, живёт в основном конфиге).
- Не передавать local-overlay как `config` в MCP.
- `strict: true` фиксирует версию и все утилиты в одном root; без полной
  установки тесты падают на нехватке `1cv8c`.
- Требуемую версию платформы определять из этого файла (поле версии).

## 5. Git-гигиена до первой выгрузки

В `.gitignore` (проектный корень):

```gitignore
build/
out/
ConfigDumpInfo.xml
src/cf/ConfigDumpInfo.xml
src/cf/lastUploadedCommit.txt
src/cf/lastUploadedConfigDumpInfo.xml
v8project.local.yaml
DumpFilesIndex.txt
src/.unica-dump-guard-*/
.env
```

- `ConfigDumpInfo.xml` с корнем `<ConfigDumpInfo>` — platform-generated CDFI
  sidecar конкретной ИБ, не исходник, не коммитится (исключение: легитимный
  metadata-файл объекта с таким именем).
- `.unica-dump-guard-*` — транзакционная страховка applied-dump, чистится сама.
- CRLF/LF предупреждения git при `git add` выгрузки — штатная нормализация
  `text=auto`, содержимое не портит.

## 6. Первый источник правды: ИБ или git

- **ИБ первична, исходников нет** → applied full `dump` по source-set'у
  (на Linux — transactional publication с private staging и rollback, риск
  `runtime_risk_publication_without_bounded_recovery` в ответе назван):

```json
unica.runtime.execute { "cwd": "...", "operation": "dump", "mode": "full",
                        "sourceSet": "main", "dryRun": false }
```

  **Если полной выгрузки через MCP нет** (проверяется на самом проекте!):
  `unica.runtime.job.start` отвечает «asynchronous applied full dump is not
  supported», а синхронный `execute` режется 30-с лимитом — процесс отрабатывает,
  но публикация оборвана: `src/cf` не меняется, staged-дерево
  `src/.unica-dump-guard-*/` выбрасывается. Тогда выгрузку запускает встроенный
  раннер напрямую (обход допустим — названной возможности в контракте нет):

  ```bash
  "$V8R" dump --config v8project.yaml --mode full --source-set main
  ```

  Для расширения добавить `"extension": "<Имя>"`. Перед dump проверить
  `git status --short` — не смешивать чужие изменения.
  Побочный эффект: выгрузка может стереть неконфигурационные файлы в целевом
  каталоге (например `AGENTS.md`) — восстановить из HEAD перед коммитом.
  Перед ПЕРВОЙ загрузкой убедиться, что `src/cf` не старше конфигурации базы
  (`v8-runner dump --mode full`): иначе загрузка откатит базу на состояние
  исходников.
- **git первичен, ИБ пустая/нет** → `init`/первая `build` требуют ИБ; applied
  `init` fail-closed — создать ИБ (конфигуратор/`1cv8 DESIGNER /CreateInfoBase`
  или штатно оператором), затем `build` по source-set'ам.
- Коммит первой выгрузки — атомарно: исходники + `v8project.yaml` + `.gitignore`.
- **Код обычных форм недоступен поиску** (лежит в `Ext/Form.bin`) — см.
  `rule://doc-before-write`, «Что не видит поиск».

## 7. Загрузка изменений (штатный цикл)

- Только по source-set'у: `operation: build`, `sourceSet: <имя>` — каждое
  изменённое расширение отдельно. Основную конфигурацию без явного запроса НЕ
  пересобирать (десятки минут).
- Durable-вариант длинной сборки: `unica.runtime.job.start` (build сам ретраит
  один раз full-rebuild при доказанном partial-отказе; `job.wait` обрезается
  хостовым 30-с лимитом — опрашивать `job.status` с `cwd`).
- Partial load падает XDTO-ошибкой на формах → при изменённых формах
  `--full-rebuild` (или MCP `fullRebuild: true`).
- `operation: extensions` (синхронизация свойств/снятие safe mode) — только по
  объявленным source-set'ам; `unknown extension source-set` = не объявлено.

## 8. Инструменты

```json
unica.runtime.execute { "cwd": "...", "operation": "tools-download",
                        "tool": "vanessa", "dryRun": false }
unica.runtime.execute { "cwd": "...", "operation": "tools-download",
                        "tool": "yaxunit", "dryRun": false }
```

Артефакты в `build/tools/` (EPF/CFE). `sources: true` для yaxunit кладёт
дерево в `<workspace>/tests` — конфликтует с проектным `tests/`, артефактного
режима это не касается. GitHub 403 на tools-download — анонимный лимит API,
не ошибка проекта.

## 9. Прямые вызовы платформы (обходной путь, когда MCP не умеет)

Допустим по явной команде оператора или при названном gap контракта; для
файловой ИБ:

```bash
<платформа>/1cv8 DESIGNER /F"<путь ИБ>" /N"<пользователь>" \
  <ключ операции> /DisableStartupDialogs /DisableStartupMessages /Out build/<log>.log
```

- Пустой пароль: НЕ передавать `/P""` → «Пользователь ИБ не идентифицирован»;
  просто опустить `/P`.
- Конфигуратор держит монопольную блокировку ИБ: перед сборкой/load проверять
  `ps aux | grep '[1]cv8'`.

## 10. Типовые отказы первичной настройки

| Симптом | Причина → действие |
|---|---|
| Два набора `unica_*` инструментов / двойные bootstrap-процессы | плагин + ручная запись в `.omp/mcp.json` → удалить ручную, перезапуск |
| `No source sets were discovered` при живом проекте | MCP-вызов без `cwd` → добавить |
| `EPIPE: broken pipe, send` в новой сессии | устаревшая ручная запись в `.omp/mcp.json` на версионированный путь → удалить файл (§1а) |
| `MCP server failed to connect … timed out after 30000ms` | сессия продолжена после установки → новая сессия, не `--continue` (§1а) |
| `MCP error -32000: failed to read current directory` (все инструменты) | пересоздан кэш плагина при живом сервере → `rule://unica-mcp` (§1а) |
| `Workspace is not inside a Git work tree` | то же: нет `cwd` |
| полная выгрузка через MCP «не идёт» (мало исходников, staged-дерево выброшено) | `job.start` не умеет полного dump, синхронный `execute` обрезан 30-с лимитом → прямой `v8-runner dump --mode full` (§6) |
| applied `config-init`/`init` отказывает | fail-closed контракт → конфиг руками (§3), ИБ — штатно |
| applied `dump`/`load` отказывает до spawn | неклассифицированная операция контракта → preview `dryRun: true`, applied через `job.start` где разрешено |
| `git.inspection_incomplete` (>65536 entries) | гигантская выгрузка → принять, не чинить |
| после dump пропал `AGENTS.md`/файл в целевом каталоге | выгрузка перезаписала дерево → `git restore <файл>` |
| `Не найдено расширение` на load .cfe | расширение не в ИБ → первичная установка DESIGNER /LoadCfg (§9) |
