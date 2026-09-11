---
description: "Исходники 1С редактируются только через Unica MCP; прямое редактирование заблокировано хуком"
condition: "src/**; tests/**"
interruptMode: never
---

# Unica source gate

Исходники конфигурации, расширений, внешних обработок и отчётов
(`src/cf/`, `src/cfe/`, `src/epf/`, `src/erf/`, `tests/cfe/`, `tests/epf/`)
редактируются **только** через Unica MCP. Прямое редактирование
(`edit`, `write`, `sed -i`, перенаправления) заблокировано хуком
`unica-gate.ts`.

## Маршрутизация: файл → инструмент

| Файл / тип | Инструмент Unica |
|---|---|
| `*.bsl` (модуль) | `unica.code.patch` |
| `Form.xml` | `unica.form.edit` / `unica.form.compile` |
| `Configuration.xml` | `unica.cf.edit` |
| XML метаданных (справочник, документ, регистр…) | `unica.meta.edit` / `unica.meta.add` |
| `Role.xml` / `Rights.xml` | `unica.role.edit` / `unica.role.compile` |
| СКД `Template.xml` | `unica.dcs.edit` / `unica.dcs.compile` |
| MXL `Template.xml` | `unica.mxl.compile` / `unica.mxl.decompile` |
| `Subsystem.xml` | `unica.subsystem.edit` / `unica.subsystem.compile` |
| `CommandInterface.xml` | `unica.interface.edit` |
| XDTO `*.xsd` | `unica.xdto.edit` |
| Заимствование в расширение | `unica.cfe.borrow` |
| Перехват метода (CFE) | `unica.cfe.patch_method` |

## Правила вызова

- Все вызовы Unica **обязаны** нести `cwd` корня проекта.
- Мутации — только с `dryRun: false` по явному запросу пользователя.
- Длительные операции — `unica.runtime.job.*`.
- Чтение/инспекция (`unica.source.read`, `unica.meta.info`,
  `unica.form.info`, `unica.code.outline`) — без ограничений.

## Расширения: только полная загрузка

Частичная/инкрементальная загрузка расширений **не работает**.
Для любого расширения, объявленного в `v8project.yaml` (source-set с
`type: EXTENSION`), сборка — только с `"fullRebuild": true`:

```json
{
  "operation": "build",
  "sourceSet": "<ИмяРасширения>",
  "fullRebuild": true,
  "dryRun": false
}
```

Хук `unica-gate.ts` блокирует сборку расширения без `fullRebuild: true`.

## Основная конфигурация (main): только частичная загрузка

Полная пересборка основной конфигурации (`sourceSet: "main"`) занимает
десятки минут и **запрещена**. Загрузка — только инкрементальная
(без `fullRebuild`):

```json
{
  "operation": "build",
  "sourceSet": "main",
  "dryRun": false
}
```

Хук `unica-gate.ts` блокирует сборку `main` с `"fullRebuild": true`.

## Исключения (не блокируются)

- Чтение файлов (`read`, `grep`, `glob`) — разрешено.
- Файлы вне `src/` и `tests/` (документация, скрипты, конфиги
  инструментов) — редактируются обычными инструментами.
- `AGENTS.md` внутри `src/` — это документация, не исходник.

## Эскалация: allowlist прямой правки

Когда `unica.code.patch` (или иной инструмент Unica) **в принципе не выражает**
изменение — например, комментарий вне тела BSL-метода (грабель G3,
`docs/reference/unica-tooling-gotchas.md`) — путь исходника вписывается в
`.omp/unica-gate-escalations.txt` (одна строка = путь относительно корня,
причина — комментарием `#`). Хук разрешает `edit`/`write` перечисленных путей
и пишет каждое разрешение в `~/.omp/logs/rule-audit.jsonl`
(`decision: confirmed`). Файл правится до правки исходника, запись удаляется
после завершения правки. Обычная правка кода по-прежнему только через Unica;
на `bash`-запись в исходники allowlist НЕ распространяется.
