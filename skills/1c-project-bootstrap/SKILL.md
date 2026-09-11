---
name: 1c-project-bootstrap
description: Инициализация структуры нового 1С-проекта с нуля: каталоги по раскладке vanessa-bootstrap (src/cf, src/cfe, src/epf, src/erf, features, fixtures, tests, tasks, tools), AGENTS.md в каждом каталоге, git init с .gitignore/.gitattributes, packagedef (OPM), env.json (профиль запуска vrunner). Используй когда нужно создать новый проект 1С в пустом каталоге. Не используй для точечного редактирования существующей структуры, миграции старого проекта или инициализации отдельных объектов метаданных.
argument-hint: [--dir <path>] [--name <slug>] [--kinds cf,cfe,epf,erf] [--extra examples,lib,vendor] [--remote <url>]
allowed-tools:
  - Bash
  - Read
  - Glob
  - AskUserQuestion
---

# /1c-project-bootstrap — инициализация структуры 1С-проекта

Создаёт стандартную структуру 1С-проекта одной операцией: каталоги + AGENTS.md,
git + служебные файлы, packagedef, env.json, шаблоны-затравки (фичи Vanessa,
конфиги тестов). Взаимодействия со скриптами нет — весь интерактив на уровне
вопросов агента пользователю (см. ниже).

## Когда применять

- Новый проект 1С с нуля (пустой каталог).
- Раскладка существующего проекта по стандартной структуре — только в пустой каталог.
- По запросу пользователя «инициализируй проект/структуру 1С».

Не применять: к проекту с готовой структурой (миграция), для создания объектов
метаданных (см. навыки cf-init, meta-compile), для расширений поверх готовой
конфигурации (см. cfe-init).

## Workflow

1. **Проверь целевой каталог**: существует ли, пуст ли, есть ли уже `.git`,
   `packagedef`, `src/`. Если структура уже есть — скажи об этом и спроси, нужен ли
   повторный запуск (существующие файлы не перезаписываются без `--force`).
2. **Задай пользователю вопросы** (один блок, с дефолтами — таблица ниже).
3. **Запусти скрипт**: `python3 <каталог-скилла>/scripts/bootstrap.py all --dir <путь> ...` — реальное выполнение, `--dry-run` только если пользователь просит показать план. Каталог скилла приходит при его вызове (`[Skill directory: …]`); типовые расположения — `<проект>/.omp/skills/1c-project-bootstrap/` и `~/.omp/agent/skills/1c-project-bootstrap/`. Путь не хардкодить: скрипт сам считает свои шаблоны от `__file__`, поэтому работает из любого из них.
4. **Верифицируй**: дерево каталогов (`read` каталога), наличие `packagedef`, `env.json`, `.gitignore`, `.gitattributes`, `.git/`; при `--remote` — `git remote -v`.
5. **Сообщи следующие шаги** (без выполнения): `opm install` (зависимости из packagedef), настройка ИБ в `env.json`, создание конфигурации через навык `cf-init`, установка OneScript/vanessa-runner.

## Вопросы пользователю

| # | Вопрос | Дефолт | Флаг |
|---|---|---|---|
| 1 | Имя проекта (slug для packagedef и корневого AGENTS.md) | имя целевого каталога | `--name` |
| 2 | Типы исходников (multi): cf / cfe / epf / erf | все четыре | `--kinds cf,cfe,epf,erf` |
| 3 | Доп. каталоги (multi): examples / lib / vendor | не создавать | `--extra examples,lib,vendor` |
| 4 | URL remote для origin (опционально) | не добавлять | `--remote <url>` |

Тестовые фреймворки **фиксированы** (не спрашивать): Vanessa Automation
(`features/` + `tools/VAParams.json`) и YAxUnit (`tests/cfe/` + `tools/yaxunit.json`);
`tests/epf/` — каталог тестовых обработок. `env.json` создаётся всегда
(дефолт `/F./build/ib`, пользователь потом правит). Git identity не настраивается
(только `git init` + файлы).

## Справочник команд

```bash
# Всё одной операцией (рекомендуется)
SKILL_DIR=.omp/skills/1c-project-bootstrap   # либо ~/.omp/agent/skills/1c-project-bootstrap
python3 "$SKILL_DIR/scripts/bootstrap.py" all \
  --dir /path/to/project --name my-project --kinds cf,cfe,epf,erf \
  --extra examples --remote git@github.com:user/repo.git

# Только каталоги + AGENTS.md + затравки
python3 .../bootstrap.py structure --dir /path --name my-project --kinds cf,cfe

# Только git init + .gitignore/.gitattributes (+ remote)
python3 .../bootstrap.py git --dir /path --remote git@github.com:user/repo.git

# Только packagedef (OPM-манифест)
python3 .../bootstrap.py packagedef --dir /path --name my-project

# Только env.json (профиль запуска vrunner)
python3 .../bootstrap.py env --dir /path --ibconnection /F./build/ib

# План без изменений
python3 .../bootstrap.py all --dir /path --dry-run
```

Общие флаги: `--dir` (обязательный), `--name`, `--dry-run`, `--force` (перезапись существующего).

## Итоговая структура

```
project/
├── AGENTS.md            # описание проекта и структуры (только описание, без команд)
├── packagedef           # манифест OPM: add, vanessa-runner, vanessa-automation-single, oneunit
├── env.json             # профиль запуска vrunner (--ibconnection /F./build/ib)
├── .gitignore  .gitattributes
├── docs/AGENTS.md
├── features/AGENTS.md  Шаблон фичи.feature  Шаблон фичи ОФ.feature
├── fixtures/AGENTS.md
├── src/AGENTS.md  cf/  cfe/  epf/  erf/      (по --kinds, в каждом AGENTS.md)
├── tasks/AGENTS.md
├── tests/AGENTS.md  cfe/AGENTS.md  epf/AGENTS.md
└── tools/AGENTS.md  VAParams.json  yaxunit.json  syntax-check-excludes.txt
```

## Инварианты

1. **Идемпотентность**: повторный запуск безопасен; существующие файлы не перезаписываются (`--force` — только по явному запросу).
2. **Git**: только `git init` + `.gitignore`/`.gitattributes` (+ `remote add origin` при указанном URL). `git config` (user.name/email) не трогать.
3. **Не создавать**: `.vscode/`, `build/` (создаётся инструментами сборки, уже в `.gitignore`), корневой README.
4. **AGENTS.md — на русском**, корневой — только описание проекта и структуры.
5. **Тесты фиксированы**: Vanessa + YAxUnit; xUnit-зависимости в packagedef не добавлять.
6. Без `--force` не менять уже созданное; при конфликте с существующей структурой — спросить пользователя.
