---
name: 1c-project-bootstrap
description: "Развёртывание контура 1С-разработки в проекте: маркетплейсы и плагины (Unica + 1c), перезапуск сессии, структура каталогов с AGENTS.md, v8project.yaml и локальный overlay, git-гигиена, первый источник правды, тестовый контур. Используй при заведении нового 1С-проекта или подъёме контура в существующем. Не используй для точечного редактирования структуры и для создания объектов метаданных."
argument-hint: [--dir <path>] [--name <slug>] [--kinds cf,cfe,epf,erf] [--extra examples,lib,vendor] [--remote <url>]
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /1c-project-bootstrap — контур 1С-разработки

Разворачивает контур **в два прохода**, и это не формальность: MCP-сервер Unica
и хуки-расширения поднимаются только при старте сессии. До перезапуска
инструментов `unica.*` в сессии не существует, а хуки-гейты не работают.

Детали работы с Unica — навык `unica-project-setup`; тестовый контур —
`unica-test-contour`. Здесь — порядок развёртывания и структура проекта.

## Когда применять

- Новый 1С-проект с нуля (пустой каталог).
- Подъём контура в существующем проекте, где ещё нет плагинов и `v8project.*`.

Не применять: для создания объектов метаданных (`cf-init`, `meta-*`), для
расширений поверх готовой конфигурации (`cfe-init`), для точечной правки
существующей структуры.

## Фаза 1 — плагины (до перезапуска)

Выполняется от корня проекта: установка в project scope пишет в
`<проект>/.omp/plugins/`, поэтому `cwd` обязан быть корнем.

```bash
omp plugin marketplace add IngvarConsulting/unica-marketplace   # один раз на машине
omp plugin marketplace add ntin60775/sot-omp-marketplace        # один раз на машине
omp plugin install --scope project unica@unica
omp plugin install --scope project 1c@sot-omp-marketplace
```

Проверь результат: `omp plugin list`. В `unica` должна быть версия, в `1c` —
запись из каталога.

**Дальше нужен перезапуск сессии** — скажи об этом оператору прямо, не
изображай, что работа продолжается. `/reload-plugins` подхватит навыки, но не
поднимет MCP и хуки.

Отдельно: Unica — плагин третьей стороны из чужого маркетплейса, механизма
зависимостей в каталоге нет, поэтому связка «1c требует unica» держится на этом
навыке. Если `unica@unica` не встал — контур не поднимется, и продолжать
бессмысленно.

## Фаза 2 — после перезапуска

### 1. Проверь, что Unica видит проект

```json
unica.project.status { "cwd": "<корень проекта>" }
```

`ready: true` и список source-set'ов с `sourceFormat: platform_xml` — контур жив.
Вызов **обязательно** с `cwd`: без него workspace резолвится в каталог кэша
плагина и ты получишь `No source sets were discovered`.

Пустой проект даст `ready` без source-set'ов — это нормально, они появятся после
структуры и `v8project.yaml`.

### 2. Структура проекта

Спроси у оператора (один блок, с дефолтами) и запусти скрипт навыка. Каталог
скилла приходит при вызове (`[Skill directory: …]`); путь не хардкодить —
скрипт считает шаблоны от `__file__` и работает из любого расположения.

```bash
SKILL_DIR=<каталог скилла>
python3 "$SKILL_DIR/scripts/bootstrap.py" all \
  --dir <проект> --name <slug> --kinds cf,cfe,epf,erf \
  --extra examples --remote git@github.com:<owner>/<repo>.git
```

Вопросы и флаги:

| # | Вопрос | Дефолт | Флаг |
|---|---|---|---|
| 1 | Имя проекта (slug для `packagedef` и корневого `AGENTS.md`) | имя каталога | `--name` |
| 2 | Типы исходников: cf / cfe / epf / erf | все четыре | `--kinds` |
| 3 | Доп. каталоги: examples / lib / vendor | не создавать | `--extra` |
| 4 | URL remote для origin | не добавлять | `--remote` |

Тестовые фреймворки фиксированы: Vanessa (`features/` + `tools/VAParams.json`)
и YAxUnit (`tests/cfe/` + `tools/yaxunit.json`). Скрипт создаёт каталоги,
`AGENTS.md` в каждом, `packagedef`, `env.json`, `.gitignore`, `.gitattributes`.

### 3. `v8project.yaml` — руками, не через MCP

Applied `config-init`/`init` в Unica fail-closed, поэтому файл создаётся вручную
по схеме
`https://raw.githubusercontent.com/alkoleft/v8-runner-rust/master/docs/schemas/v8project.schema.json`:

```yaml
workPath: 'build'
execution_timeout: 3600000
format: DESIGNER
builder: DESIGNER
infobase:
  connection: 'File=build/ib'          # или 'Srvr="<сервер>";Ref="<база>";'
source-set:
  - name: main
    type: CONFIGURATION
    path: 'src/cf'
  # каждое расширение — отдельный source-set:
  # - name: <Расширение>
  #   type: EXTENSION
  #   path: 'src/cfe/<Расширение>'
build:
  partialLoadThreshold: 20
```

Каждый source-set — отдельный каталог (`path: .` — ошибка). Тестовые расширения
тоже объявляются здесь как `EXTENSION`, иначе `unica.runtime.execute` не найдёт
их по имени.

### 4. `v8project.local.yaml` — локальное и секретное

Файл в `.gitignore`, значения — только здесь:

```yaml
infobase:
  user: <пользователь ИБ>        # пароль никогда в git, чат и логи
tools:
  platform:
    version: "<8.3.27.xxxx>"
    path: "<каталог установки>"  # плоский каталог с 1cv8, 1cv8c, ibcmd
    strict: true
```

`strict: true` фиксирует версию и все утилиты в одном root; без полной установки
тесты падают на нехватке `1cv8c`. Не добавляй сюда `source-set`, `format`,
`builder`, `execution_timeout` — это контракт команды, он живёт в основном файле.

### 5. Git-гигиена до первой выгрузки

В `.gitignore` проекта:

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

### 6. Первый источник правды

- **ИБ есть, исходников нет** — выгрузка: `unica.runtime.execute` с
  `operation: dump`, `mode: full`, `sourceSet: main`, `dryRun: false`. Перед
  этим проверь `git status --short`, чтобы не смешать чужие изменения.
  Побочный эффект: выгрузка может стереть неконфигурационные файлы в целевом
  каталоге (например `AGENTS.md`) — восстанови из HEAD перед коммитом.
- **Исходники есть, ИБ пустая** — ИБ создаётся штатно (оператором или
  конфигуратором), затем `operation: build` по source-set'ам.

Первую выгрузку коммить атомарно: исходники + `v8project.yaml` + `.gitignore`.

### 7. Тестовый контур

```json
unica.runtime.execute { "cwd": "...", "operation": "tools-download", "tool": "vanessa", "dryRun": false }
unica.runtime.execute { "cwd": "...", "operation": "tools-download", "tool": "yaxunit", "dryRun": false }
```

Артефакты лягут в `build/tools/`. Дальше — `tools/VAParams.json` под свою ИБ и
установка тестового расширения; порядок и грабли — в навыке `unica-test-contour`.

## Инварианты

1. **Два прохода, не один.** Не начинай фазу 2 в той же сессии, что фазу 1.
2. **`cwd` в каждом вызове Unica** — иначе workspace не резолвится.
3. **Основную конфигурацию не пересобирать** — только частичная загрузка;
   расширения, наоборот, только с `fullRebuild: true`.
4. **Секреты только в `v8project.local.yaml`** и только локально.
5. **Идемпотентность скрипта**: повторный запуск безопасен, существующие файлы
   не перезаписываются без `--force`.
6. **Плагины ставятся в project scope** — не в user: 1С-контур принадлежит
   проекту, а не машине.
