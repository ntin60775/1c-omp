---
description: "Платформенные инварианты 1С: приоритет Unica MCP над прямым редактированием, источник по платформе, версия из v8project.local.yaml, запрет полной синтакс-проверки через конфигуратор"
alwaysApply: true
---

⟦⟦START_PLATFORM_TOOLS⟧⟧

Приоритет инструментов:
Unica MCP (`mcp__unica__*`) — ОБЯЗАТЕЛЬНА при любой работе с 1С
→ прямое редактирование XML → shell/платформа (`v8-runner` через bash).
Понижай уровень только когда на текущем нет нужной возможности — и назови
её явно перед fallback (обратная связь для развития инструментария).

Замечания по Unica:
- все операции с рантаймом — `unica.runtime.execute` (`operation`:
  build/dump/make/load/syntax/test/launch) от корня проекта;
- длительные операции — `unica.runtime.job.*` (start/status/wait/logs/cancel);
- точечная работа с метаданными — `unica.cf.*`, `unica.cfe.*`,
  `unica.form.*`, `unica.meta.*` и др.;
- если `mcp__unica__*` недоступны — сначала подключить Unica MCP,
  не начинать работу на fallback.

⟦⟦END_PLATFORM_TOOLS⟧⟧

⟦⟦START_PLATFORM_DOCS⟧⟧

Первичный источник по платформе и объектной модели BSL:
https://kb.1ci.com/1C_Enterprise_Platform/Guides/Developer_Guides/1C_Enterprise_8.3.27_Developer_Guide/?language=en

По возможностям платформы отвечай ТОЛЬКО по документации со ссылкой на раздел.

⟦⟦END_PLATFORM_DOCS⟧⟧

⟦⟦START_PLATFORM_VERSION⟧⟧

Требуемую версию платформы определяй из `v8project.local.yaml`
(только поле версии; учётки в файле не читать и не выводить).

Если на сайте документации нет раздела для этой версии — используй
документацию последней доступной версии и помечай возможные расхождения.

⟦⟦END_PLATFORM_VERSION⟧⟧

⟦⟦START_NO_DESIGNER_SYNTAX_CHECK⟧⟧

НИКОГДА не запускай синтакс-проверку всей конфигурации через конфигуратор
(`1cv8 DESIGNER /CheckConfig`, `v8-runner syntax designer-config`,
`test_syntaxCheck` на полной конфигурации) — это десятки минут.

Вместо этого: точечная диагностика изменённых модулей средствами
Unica (`unica.code.diagnostics`) и проверка фактом загрузки
(`unica.runtime.execute` operation build/load).

⟦⟦END_NO_DESIGNER_SYNTAX_CHECK⟧⟧
