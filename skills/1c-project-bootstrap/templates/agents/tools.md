# Каталог tools — инструменты и конфигурации

Конфигурации инструментов разработки и тестирования (JSON), вспомогательные утилиты.

## Правила
- `VAParams.template.json` — шаблон параметров Vanessa Automation (в git, с плейсхолдерами); рабочий `VAParams.json` собирается из него скриптом `scripts/bootstrap-local-config.py` и в git не попадает.
- `syntax-check-excludes.txt` — исключения синтаксического контроля.
- `yaxunit.json` не заводить: v8-runner его не читает (`tests.yaxunit` в схеме `v8project.yaml` знает только `timeouts`), доказательство приёмки — JSON-конверт прогона (см. навык `unica-test-contour`).
- Секреты и пароли сюда не класть: `VAParams.json` и `va-env.local.json` — только из локального оверлея, в git их быть не должно.
