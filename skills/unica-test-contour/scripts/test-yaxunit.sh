#!/usr/bin/env bash
# test-yaxunit.sh — прогон YAxUnit с доказательством приёмки.
#
# Зачем обёртка: раннер держит отчёт прогона в своём run-каталоге
# (build/temp/yaxunit/runs/<id>/report.xml) и УДАЛЯЕТ его после успешного
# прогона — артефакты остаются только у упавших. Путь отчёта не
# конфигурируется: у `tests.yaxunit` в схеме v8project.yaml есть только
# `timeouts`, ключа пути нет и в CLI раннера, а файла `tools/yaxunit.json`
# раннер не читает. Поэтому доказательство снимается из JSON-конверта.
#
# Вторая причина — ложно-зелёный: нескомпилировавшийся тестовый модуль молча
# не регистрирует свои тесты, summary остаётся зелёным, и единственный
# признак — строка `ЗагрузкаТестов: Ошибка инициализации модуля` в выводе
# раннера. Обёртка читает её из конверта и сама выносит вердикт.
#
# Артефакты в build/out/yaxunit/:
#   last-run.json — полный JSON-конверт (машиночитаемое доказательство)
#   junit.xml     — JUnit, собранный из конверта
#   log.txt       — сводка, тесты и диагностика (человекочитаемо)
#   result.txt    — код возврата прогона
#
# Код возврата:
#   0 — сводка зелёная, ошибок инициализации модулей нет, тесты есть;
#   1 — прогон упал, есть упавшие/ошибочные тесты, ошибки модулей или ноль тестов;
#   2 — нет окружения (раннер, дисплей).
#
# Использование (из любого каталога проекта):
#   tasks/test-yaxunit.sh                    # все тесты на своём дисплее
#   tasks/test-yaxunit.sh --module <Имя>     # отладка одного набора
#   tasks/test-yaxunit.sh --display :1       # явный дисплей (монитор оператора)
#
# Дисплей: без флага и без рабочего $DISPLAY прогон сам уходит под
# xvfb-run-1c.sh (свой виртуальный дисплей, номер выдаёт Xvfb -displayfd) —
# фиксированный :99 не используется, параллельные прогоны не мешают друг другу.

set -euo pipefail

# Корень проекта: скрипт лежит либо в проекте (tasks/), либо в плагине под
# .omp/plugins/node_modules — git от обоих путей поднимется до корня проекта.
if ROOT="$(git -C "$(dirname "$0")" rev-parse --show-toplevel 2>/dev/null)"; then
	cd "$ROOT"
elif [[ -f "$(dirname "$0")/../v8project.yaml" ]]; then
	cd "$(dirname "$0")/.."
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# xvfb-run-1c.sh ищем рядом с собой, затем в установленном плагине проекта.
find_wrapper() {
	local c
	for c in \
		"${XVFB_RUN_1C:-}" \
		"$SCRIPT_DIR/xvfb-run-1c.sh" \
		".omp/plugins/node_modules/1c-omp/skills/unica-test-contour/scripts/xvfb-run-1c.sh"; do
		[[ -n "$c" && -x "$c" ]] && { echo "$c"; return 0; }
	done
	return 1
}

V8R="$(ls -d "${HOME}"/.codex/unica/runtimes/*/linux-x64/bin/linux-x64/v8-runner 2>/dev/null | sort -V | tail -1)"
if [[ -z "$V8R" ]]; then
	echo "не найден v8-runner: ~/.codex/unica/runtimes/*/linux-x64/bin/linux-x64/v8-runner" >&2
	exit 2
fi

EXPLICIT_DISPLAY=""
MODULE=""
while [[ $# -gt 0 ]]; do
	case "$1" in
	--display)
		EXPLICIT_DISPLAY="${2:?--display требует значение}"
		shift 2
		;;
	--module)
		MODULE="${2:?--module требует значение}"
		shift 2
		;;
	--)
		shift
		break
		;;
	*) break ;;
	esac
done

OUT_DIR=build/out/yaxunit
mkdir -p "$OUT_DIR"

# ── дисплей ──────────────────────────────────────────────────────────────────
if [[ -n "$EXPLICIT_DISPLAY" ]]; then
	export DISPLAY="$EXPLICIT_DISPLAY"
elif [[ -z "${DISPLAY:-}" ]] || ! xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
	WRAPPER="$(find_wrapper || true)"
	if [[ -z "$WRAPPER" ]]; then
		echo "дисплей не задан/недоступен, а xvfb-run-1c.sh не найден" >&2
		echo "подними дисплей: Xvfb <номер> -screen 0 1920x1080x24 -ac" >&2
		exit 2
	fi
	# DISPLAY прокидывается вложенной обёртке сам — рекурсии нет, потому что
	# внутри неё дисплей уже будет рабочим.
	if [[ -z "${DISPLAY_MANAGED:-}" ]]; then
		NESTED=("$0")
		[[ -n "$MODULE" ]] && NESTED+=(--module "$MODULE")
		DISPLAY_MANAGED=1 exec "$WRAPPER" -- "${NESTED[@]}" -- "$@"
	fi
fi

CMD=("$V8R" test yaxunit all --no-build --full --json-message)
if [[ -n "$MODULE" ]]; then
	CMD=("$V8R" test yaxunit module "$MODULE" --no-build --full --json-message)
fi

echo "YAxUnit: $V8R (DISPLAY=${DISPLAY:-<нет>}, сборка не выполняется)" >&2
RC=0
DISPLAY="${DISPLAY:-}" "${CMD[@]}" "$@" >"$OUT_DIR/last-run.json" || RC=$?
echo "$RC" >"$OUT_DIR/result.txt"

VERDICT=0
python3 - "$OUT_DIR" "$RC" <<'PY' || VERDICT=$?
import json
import pathlib
import sys
import xml.etree.ElementTree as ET

out = pathlib.Path(sys.argv[1])
rc = int(sys.argv[2])
raw = (out / "last-run.json").read_text(encoding="utf-8")

try:
    envelope = json.loads(raw)
except json.JSONDecodeError as exc:
    (out / "log.txt").write_text(
        "конверт раннера не разобрался: %s\nпервые 2000 символов:\n%s\n" % (exc, raw[:2000]),
        encoding="utf-8",
    )
    print("ПРИЁМКА НЕ ПРОЙДЕНА: JSON-конверт раннера битый — см. %s/log.txt" % out, file=sys.stderr)
    sys.exit(1)

data = envelope.get("data") or {}
report = data.get("report") or {}
summary = report.get("summary") or {}
suites = report.get("suites") or []
extracted = [str(e) for e in (report.get("extracted_errors") or [])]
diagnostics = [str(d) for d in (data.get("diagnostics") or [])]
runner_error = envelope.get("error") or {}

root = ET.Element(
    "testsuites",
    name="yaxunit",
    tests=str(summary.get("total", 0)),
    failures=str(summary.get("failed", 0)),
    errors=str(summary.get("errors", 0)),
    skipped=str(summary.get("skipped", 0)),
)
for suite in suites:
    cases = suite.get("cases") or []
    suite_el = ET.SubElement(root, "testsuite", name=str(suite.get("name", "")), tests=str(len(cases)), time=f"{int(suite.get('duration_ms') or 0) / 1000:.3f}")
    for case in cases:
        status = str(case.get("status", "")).upper()
        case_el = ET.SubElement(
            suite_el,
            "testcase",
            name=str(case.get("name", "")),
            classname=str(case.get("class_name", "")),
            time=f"{int(case.get('duration_ms') or 0) / 1000:.3f}",
        )
        if status in ("FAILED", "ERROR"):
            ET.SubElement(case_el, "failure" if status == "FAILED" else "error", message=str(case.get("failure_message", ""))).text = str(case.get("stack_trace", ""))
        elif status == "SKIPPED":
            ET.SubElement(case_el, "skipped")
ET.indent(root)
ET.ElementTree(root).write(out / "junit.xml", encoding="utf-8", xml_declaration=True)

lines = [
    "summary: total=%s, passed=%s, failed=%s, skipped=%s, errors=%s"
    % (summary.get("total", 0), summary.get("passed", 0), summary.get("failed", 0), summary.get("skipped", 0), summary.get("errors", 0))
]
for suite in suites:
    lines.append("suite: %s" % suite.get("name", ""))
    for case in suite.get("cases") or []:
        lines.append("  %s %s — %s" % (case.get("status", ""), case.get("class_name", ""), case.get("name", "")))
if extracted:
    lines += ["", "ошибки из лога YAxUnit:"]
    for error in extracted:
        lines += ["  " + line for line in error.splitlines()] or ["  (пустая строка)"]
if runner_error:
    lines += [
        "",
        "ошибка раннера: %s (%s)" % (runner_error.get("message", ""), runner_error.get("code", "")),
    ]
elif envelope.get("ok") is False:
    lines += ["", "раннер вернул ok=false: %s" % data.get("message", "")]
if diagnostics:
    lines += ["", "диагностика платформы:"]
    for entry in diagnostics:
        lines += ["  " + line for line in entry.strip().splitlines()]
(out / "log.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines))

failed = int(summary.get("failed", 0)) + int(summary.get("errors", 0))
total = int(summary.get("total", 0))
# Ноль тестов при непустом наборе — это не «всё зелёное», а несовпавший
# фильтр/имя расширения либо незапущенный прогон: приёмкой такой прогон не считается.
if total == 0:
    if runner_error:
        print("приёмка: раннер не дошёл до тестов: %s" % runner_error.get("message", ""), file=sys.stderr)
    else:
        print("приёмка: 0 зарегистрированных тестов — набор не загрузился (имя расширения/фильтр)", file=sys.stderr)
sys.exit(1 if (rc != 0 or failed or extracted or total == 0) else 0)
PY

if [[ $VERDICT -eq 0 ]]; then
	echo "приёмка: прогон зелёный, артефакты — $OUT_DIR/"
else
	echo "приёмка: НЕ пройдена (код прогона $RC, разбор — $OUT_DIR/log.txt)" >&2
fi
exit "$VERDICT"
