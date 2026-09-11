---
description: "При создании ворктри — обязательная инициализация воркспейса Unica и тестового окружения: v8project.local.yaml, build/tools (Vanessa/YAxUnit), tools/VAParams.json, hash-storages; только реальные копии"
condition: "**"
interruptMode: never
---

# Ворктри: инициализация воркспейса и тестового окружения

При создании ворктри агент НЕ инициализирует воркспейс Unica и не
копирует тестовое окружение. В ворктри после `git worktree add` есть
только то, что в git: `v8project.yaml`, `tools/yaxunit.json`. Всё остальное
(креды, профиль Vanessa, инструменты тестов, инкрементальное состояние) —
в gitignore и отсутствует.

## Что отсутствует в свежем ворктри

| Что | Зачем нужно |
|---|---|
| `v8project.local.yaml` | креды ИБ, путь и версия платформы |
| `tools/VAParams.json` | профиль Vanessa-прогона; без него `v8-runner` падает на валидации конфига при ЛЮБОЙ операции |
| `build/tools/` | `YAxUnit-*.cfe`, `vanessa-automation-single.epf` — артефакты тестов |
| `build/hash-storages/` | инкрементальное состояние сборки (без него первая сборка полная) |

## Правило: один скрипт

После `git worktree add` — ОБЯЗАТЕЛЬНО запустить инициализатор:

```bash
tasks/init-worktree.sh /path/to/worktree
```

Скрипт копирует из основного дерева:
1. `v8project.local.yaml`
2. `build/tools/` (Vanessa, YAxUnit)
3. `tools/VAParams.json`
4. `build/hash-storages/`

и проверяет результат. Только реальные копии, НЕ симлинки.

## Проверка после инициализации

```json
unica.project.status { "cwd": "<корень ворктри>" }
```

Ожидание: `ready: true` + список source-set'ов. Все последующие вызовы
Unica — с `cwd` корня ворктри (перенаправление воркспейса на адрес
ворктри), не основного дерева.

## Если артефактов нет в основном дереве

`build/tools/` отсутствует → в основном дереве:

```json
unica.runtime.execute { "cwd": "<main>", "operation": "tools-download",
                        "tool": "vanessa", "dryRun": false }
unica.runtime.execute { "cwd": "<main>", "operation": "tools-download",
                        "tool": "yaxunit", "dryRun": false }
```

Затем повторить `tasks/init-worktree.sh`.

## MUST NOT

- Создавать ворктри без запуска `tasks/init-worktree.sh`.
- Использовать симлинки на `build/tools`, `VAParams.json` в ворктри
  контейнера — только реальные копии (distrobox не видит симлинки).
- Вызывать Unica с `cwd` основного дерева, работая в ворктри — воркспейс
  должен указывать на адрес ворктри.
- Запускать сборку/тесты в ворктри без проверки `unica.project.status`.
- Повторять идентичные упавшие прогоны (3+ раза) без диагностики
  (память, симлинки, окружение).

## Детерминированный слой

Хук `unica-gate.ts` блокирует вызовы Unica из ворктри, если в нём
отсутствует `v8project.local.yaml` или `build/tools/`.
