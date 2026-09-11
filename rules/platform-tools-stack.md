---
description: "Стек инструментов платформы: Unica MCP обязательна при любой работе с 1С; автоприменение UpdateDBCfg при загрузке не верифицировано"
interruptMode: never
---

# Стек инструментов платформы (2026-07-28, обновлено 2026-08-28)

Unica MCP — ОБЯЗАТЕЛЬНА при любой работе с 1С (сборка, загрузка, выгрузка,
метаданные, тесты): `mcp__unica__*`. Приоритет: Unica → прямое редактирование
XML → CLI встроенного в Unica `v8-runner` через bash (понижение уровня —
только с явным называнием причины).

## MUST NOT: прямое редактирование исходников 1С

Файлы в `src/cf/`, `src/cfe/`, `src/epf/`, `src/erf/`, `tests/cfe/`,
`tests/epf/` — **запрещено** редактировать инструментами `edit`, `write`,
`sed -i`, перенаправлениями и любыми другими способами прямой записи.
Хук `unica-gate.ts` блокирует такие вызовы детерминированно.

Единственный путь изменения — соответствующий инструмент Unica MCP
(маршрутизация: `rule://unica-source-gate`). Чтение (`read`, `grep`,
`glob`, `unica.source.read`) — без ограничений.

Основные операции Unica — через `unica.runtime.execute` (`operation`:
build/dump/make/load/syntax/test/launch; `cwd` — корень проекта; мутации —
только с `dryRun: false` по явному запросу пользователя). Длительные
операции — `unica.runtime.job.*` (start/status/wait/logs/cancel). Точечная
работа с метаданными — `unica.cf.*`, `unica.cfe.*`, `unica.form.*`,
`unica.meta.*`, `unica.dcs.*`, `unica.mxl.*`, `unica.role.*`,
`unica.interface.*`, `unica.subsystem.*`, `unica.template.*`; код —
`unica.code.*` (search/grep/patch/diagnostics/outline/definition/graph);
стандарты — `unica.standards.*` (search/explain).

Проверенные требования контура:
- платформа регистрируется для v8find деревом симлинков
  `/opt/1cv8/x86_64/<версия>/1cv8*` → `tools/platform/bin/*` (нужен pkexec);
- `tools/yaxunit.json` — конфиг прогона YAxUnit;
- на тестируемой ИБ не должен быть открыт Конфигуратор — загрузка/дампы требуют
  монопольной блокировки.

НЕ верифицировано (до проверки — не утверждать):
- применяет ли `unica.runtime.execute` (build/load) изменения к конфигурации
  БД автоматически (Unica build делал это всегда по данным предыдущего
  контура). До проверки считать UpdateDBCfg отдельным шагом и следовать
  правилу DB_UPDATE_AND_LAUNCH из `.omp/RULES.md`.
