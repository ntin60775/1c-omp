---
description: "Unica MCP: установка и переустановка, живой сервер (убивается пересозданием кэша плагинов), контрактные пробелы `unica.*` при правке исходников и как их обходить. Применяй при любом падении вызова Unica, при установке/обновлении плагина и перед мутацией исходников."
condition: "**"
interruptMode: never
---

# Unica MCP: жизненный цикл и контрактные пробелы

Без `mcp__unica__*` контур не работает. Здесь — как он устроен, почему умирает
и чего контракт 0.12.3 не умеет при правке исходников.

## Устройство: пути, которые не очевидны

| Что | Где |
|---|---|
| кэш плагина | `~/.omp/plugins/cache/plugins/unica___unica___<ver>` |
| привязка проекта | `.omp/plugins/installed_plugins.json` (не в git) |
| **рантайм (фактически используется)** | `~/.codex/unica/runtimes/<ver>/linux-x64/` |
| маркер готовности | `~/.codex/unica/runtimes/<ver>/linux-x64/.ready.json` |

`.mcp.json` плагина задаёт `UNICA_RUNTIME_CACHE_DIR: ${CLAUDE_PLUGIN_DATA}/runtimes`,
но omp передаёт строку **буквально, не раскрывая переменную** — bootstrap
уходит в fallback хоста Codex и берёт `~/.codex/unica/runtimes`. Поэтому путь к
раннеру версионирован и резолвится динамически:

```bash
V8R=$(ls -d ~/.codex/unica/runtimes/*/linux-x64/bin/linux-x64/v8-runner 2>/dev/null | sort -V | tail -1)
```

## Полная переустановка (project scope)

Из корня проекта. Очистка кэша — обязательный шаг, не опция:

```bash
omp plugin uninstall unica@unica --scope project
omp plugin marketplace remove unica
rm -rf ~/.codex/unica ~/.cache/omp/runtimes ~/.cache/omp/unica-runtimes
find ~/.cache ~/.codex -maxdepth 3 \( -iname "*unica*" -o -iname "*runtimes*" \) 2>/dev/null   # должен быть пуст
omp plugin marketplace add IngvarConsulting/unica-marketplace
omp plugin install unica@unica --scope project
omp plugin list   # unica@unica (<ver>) (project)
```

**После установки/обновления — новая сессия, никогда `--continue`/resume.**
Продолженная сессия упала с `MCP server failed to connect: unica:unica … timed out
after 30000ms`: omp не пересоздаёт уже-failed MCP из marketplace-плагина, а
bootstrap не успевает скачать ~400 МБ рантайма за 30 с. В 0.12.3 в `.mcp.json`
есть `startup_timeout_sec: 900`, но правило новой сессии остаётся: живая сессия
держит **старый** процесс сервера. Первый запуск новой сессии качает рантайм,
дальше старт ~2 с.

## Грабля: `EPIPE` после переустановки

Симптом в НОВОЙ сессии: `Connected: unica:unica. Failed: unica [config:
.omp/mcp.json]: EPIPE: broken pipe, send`.

Причина — устаревшая **ручная** запись `unica` в проектном `.omp/mcp.json` на
захардкоженный версионированный путь (`…/unica___unica___0.12.0/bootstrap/launch.sh`):
после переустановки кэш старой версии удалён, `sh` не может исполнить скрипт,
сервер умирает до рукопожатия. Фикс: удалить проектный `.omp/mcp.json` (или хотя
бы ручную запись) — плагин сам несёт сервер, ручной дубль ломается на каждом
bump версии.

## Грабля: пересоздание кэша плагинов убивает живой сервер

Симптом: **каждый** вызов `mcp__unica__*` падает сразу, независимо от `cwd`:

```
MCP error -32000: failed to read current directory: No such file or directory (os error 2)
stage: json_rpc, retryable: no
```

Причина: `omp plugin install --scope project` (шаг плагинов `init-worktree.sh`,
ручная установка/обновление — любая) **пересоздаёт** каталог кэша плагина, а у
давно живущего stdio-процесса рабочий каталог остался на удалённом иноде:
платформа не может вычислить текущий каталог, и вызов умирает до обработки.
Менять версию или содержимое при этом не нужно — достаточно факта
переустановки того же `unica@<ver>`.

Улики: `ls -l /proc/<PID>/cwd` у процесса показывает `…/unica___unica___<ver> (deleted)`.
Диагностика:

```bash
pgrep -af 'unica-bootstrap|unica --workspace-service'
readlink /proc/<PID>/cwd      # "(deleted)" — инстанс мёртв
```

Восстановление (порядок обязателен: сначала хост, иначе он переподнимет
сервисы в битом виде):

```bash
kill -TERM <PID git unica-bootstrap> <PID unica-сервера>
kill -TERM <PID unica --workspace-service …>   # тот же (deleted) cwd
```

Конкретные PID, не паттерн; `bsl-analyzer` с живым cwd не трогать; чужие
сессии не трогать — их лечит их сеанс/оператор, находку доложить. Дальше
повторить любой MCP-вызов — хост сам поднимает новый инстанс, отдельный рестарт
не нужен. Приёмка: `unica.project.status` с `cwd` дерева → `ready: true`. Вызов
всё ещё падает — открыть **новую сессию**: менеджер MCP этого окна мог не
пережить остановку транспорта.

Профилактика: инициализатор ворктри запускать **до** первых `unica.*`-вызовов;
шаг плагинов в чужое рабочее время не запускать. Ложные тревоги, которые здесь
не помогут: `EPIPE` (новая сессия, см. выше) и `timed out after 30000ms` после
`--continue` — это два других габарита.

Симптом не снимается ретраями: `retryable: no`, ломается процесс, а не запрос.

## `mcp__unica__*` нет в сессии

Плагин установлен (`installed_plugins.json`), а инструментов нет — omp не
поднял сервер для этой сессии: перезапустить клиент. Проверить здоровье напрямую
можно JSON-RPC рукопожатием с `bootstrap/launch.sh` (он ответит версией и числом
инструментов).

## Контрактные пробелы 0.12.3 при правке исходников

**Общее правило: аргумент, которого нет в схеме, не отклоняется, а молча
вырезается.** Поэтому после каждой мутации проверять `git diff` и фактическое
содержимое XML, а не код возврата.

| Что не умеет | Обход |
|---|---|
| `unica.form.edit` — только создание (`elements`/`attributes`/`commands`), удаление (`removeElements`), события (`formEvents`/`elementEvents`). Переименование, правка регистра `<xr:ref>` → `<xr:Ref>`, добавление свойства существующему элементу — вне контракта (`FORM_EDIT_UNKNOWN_SECTION`) | точечная правка Form.xml под gate + `unica.form.validate` |
| `unica.code.patch` матчит только **внутри метода**: комментарий вне метода недостижим, `selector.method` предшествующий doc-comment не покрывает | эскалация в `.omp/unica-gate-escalations.txt` (см. `unica-source-gate`); если комментарий — часть правки метода, сначала `replace` метода целиком |
| `replace` **обязан ломать собственный anchor**: если пост-образ содержит anchor дословно — «patch cannot be applied idempotently on the next call» | для вставок — `insert` + `position`; для замен — менять текст anchor |
| `code.patch` создаёт новый модуль с `LF`, а `.gitattributes` требует `eol=crlf` | после применения привести файл к CRLF и повторить бинарную сверку |
| `code.patch` не заменяет модуль целиком (`replace` без селектора не поддерживается) | полная перезапись файла с эскалацией, доказательство — загрузка |
| `unica.dcs.edit rename-parameter` не трогает текст запроса | парой: `patch-query` (`"&Old => &New"`) + `modify-parameter` (`"Имя [Заголовок]"`) |
| `meta.add`/`meta.edit` молча теряют часть свойств (тип константы `Type`, индексация измерения регистра, `Handler` регламентного задания, `kind` параметров сеанса) | правка соответствующего XML под gate |
| `cfe.borrow` пере-сериализует `Configuration.xml` шумом (`&#13;`, пересортировка `ChildObjects`, дифф на сотни строк) | `git checkout -- <ext>/Configuration.xml` + дозапись регистрации через `cf.edit add-childObject` |
| `subsystem.edit` не умеет состав adopted-подсистемы в platform_xml (Writer'а нет) | состав не использовать; регистрацию объекта делать кодом |
| `code.diagnostics` по source-set'у расширения даёт ложные срабатывания (`UnresolvedField`/`QueryToMissingMetadata` на штатных объектах) | доказательство компиляции — загрузка в ИБ (`job build`, exit 0); анализатор — только для основной конфигурации |
| `project.status` на большом дереве: `repositoryReady=false`, `git.inspection_incomplete` (порог 65536 записей) | считать гигиеническим предупреждением, не блокером; гигиену EOL/LFS проверять `git ls-files --eol`, `git lfs ls-files` |
| **полного дампа через MCP нет**: `job.start` отвечает «asynchronous applied full dump is not supported», синхронный `execute` режется 30-с лимитом | прямой запуск раннера (`dump --mode full`) — см. `ib-contour` |

Долгие операции идут через `unica.runtime.job.*` (`job.wait` обрезается 30-с
хостовым лимитом — опрашивать `job.status` с `cwd` воркспейса).

## Сверка документации: `platformVersion`

`unica.documentation.search` автоопределяет версию платформы сканированием
`/opt/1cv8/x86_64/` и берёт первую попавшуюся. Если там несколько версий, либо
стоит минимальная установка (только `1cv8`+`ibcmd`, без синтакс-помощника),
`platform-syntax-help` отдаёт `unavailable`/`version-missing`, и без параметра
работает только `v8std`.

- Передавать версию явно: `{"query": "…", "platformVersion": "8.3.27.1859"}`.
- Диагностика: `{"query": "тест", "limit": 1}` → посмотреть
  `sections[].status` для `platform-syntax-help`.
- Если версий несколько — убрать минимальную/неактуальную установку.

## Как считает хук сверки (`doc-gate`)

- Сверка засчитывается инструментами Unica (`documentation.*`, `standards.*`,
  `*.info`, `code.search/definition/outline/graph/diagnostics`, `source.*`) и
  инструментами `read`/`grep` **по исходникам 1С**.
- **Bash-грепы сверкой не считаются** — путь через `bash` хук не видит.
- Гейт проверяет факт сверки в сессии, а не её **адресность**: «сверка была» ≠
  «проверен тот метод, чьи аргументы меняем». Семантика — на агенте
  (см. `doc-before-write`).
- После мутации **метаданных** флаг сверки сбрасывается: следующее структурное
  решение требует свежего вызова.
