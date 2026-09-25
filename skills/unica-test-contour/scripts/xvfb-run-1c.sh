#!/usr/bin/env bash
# xvfb-run-1c.sh — прогон 1С на СВОЁМ виртуальном дисплее.
#
# Зачем: фиксированный `:99` — общий ресурс. Параллельные агенты мешают друг
# другу на одном дисплее, а `Xvfb :99 &` из одноразовой команды умирает вместе
# с ней (прогон падает с «Unable to initialize GTK+ or connect to the windowing
# system»). Здесь Xvfb живёт ровно столько, сколько команда, а номер дисплея
# выбирает сам сервер.
#
# Выбор номера — не сканированием /tmp/.X*-lock (там гонка), а `Xvfb
# -displayfd`: сервер занимает свободный дисплей и пишет его номер в
# переданный fd. Проверено: три одновременных запуска получают :2, :3, :4.
#
# Использование:
#   xvfb-run-1c.sh -- "$V8R" test yaxunit all --no-build
#   xvfb-run-1c.sh --screenshot-at 75 --screenshot-dir build/out/frames -- \
#       "$V8R" test va --no-build
#   xvfb-run-1c.sh --display-file build/out/display -- <команда>
#
# Опции:
#   --screen <WxHxD>        размер экрана (по умолчанию 1920x1080x24)
#   --screenshot-at <сек>   снять кадр корневого окна через N секунд после старта
#   --screenshot-dir <dir>  каталог для кадра (без него --screenshot-at бесполезен)
#   --display-file <path>   записать номер дисплея в файл (для ручных скриншотов)
#   --                      конец опций, дальше — команда
#
# Код возврата — код команды; 2 — сам дисплей поднять не удалось.
# Xvfb гасится по выходу (в т. ч. по Ctrl-C и по ошибке команды): висящий
# дисплей не достаётся следующему прогону наполовину живым.

set -euo pipefail

SCREEN="1920x1080x24"
SCREENSHOT_AT=""
SCREENSHOT_DIR=""
DISPLAY_FILE=""

usage() {
	sed -n '3,30p' "$0" | sed 's/^#\{1,2\} \{0,1\}//'
}

while [[ $# -gt 0 ]]; do
	case "$1" in
	--screen)
		SCREEN="${2:?--screen требует значение}"
		shift 2
		;;
	--screenshot-at)
		SCREENSHOT_AT="${2:?--screenshot-at требует значение}"
		shift 2
		;;
	--screenshot-dir)
		SCREENSHOT_DIR="${2:?--screenshot-dir требует значение}"
		shift 2
		;;
	--display-file)
		DISPLAY_FILE="${2:?--display-file требует значение}"
		shift 2
		;;
	--)
		shift
		break
		;;
	-h | --help)
		usage
		exit 0
		;;
	*) break ;;
	esac
done

if [[ $# -eq 0 ]]; then
	echo "не передана команда (см. --help)" >&2
	exit 2
fi

if ! command -v Xvfb >/dev/null 2>&1; then
	echo "нет Xvfb в PATH — виртуальный дисплей поднять нечем" >&2
	exit 2
fi

RUN_DIR="$(mktemp -d "${TMPDIR:-/tmp}/1c-xvfb.XXXXXX")"
XVFB_PID=""
SHOT_PID=""
CMD_PID=""

# Гасим всё дерево процессов прогона: раннер порождает тест-клиента внука, и
# одного ребёнка мало — без этого клиент переживает раннер и висит на экране
# (стоп-протокол из правила test-contour). Обход — ровно поддерево этого
# прогона, начиная с его PID: ни шаблонов, ни чужих веток.
stop_tree() {
	local pid="$1" child
	for child in $(cat "/proc/$pid/task/$pid/children" 2>/dev/null); do
		stop_tree "$child"
	done
	kill -TERM "$pid" 2>/dev/null || true
}

cleanup() {
	if [[ -n "$SHOT_PID" ]]; then
		kill "$SHOT_PID" 2>/dev/null || true
	fi
	if [[ -n "$CMD_PID" ]] && kill -0 "$CMD_PID" 2>/dev/null; then
		stop_tree "$CMD_PID"
		wait "$CMD_PID" 2>/dev/null || true
	fi
	if [[ -n "$XVFB_PID" ]]; then
		kill "$XVFB_PID" 2>/dev/null || true
		wait "$XVFB_PID" 2>/dev/null || true
	fi
	rm -rf "$RUN_DIR"
}
# EXIT покрывает нормальный и ошибочный выход; HUP/INT/TERM/QUIT переводим в
# exit, иначе bash выйдет по сигналу, минуя EXIT-ловушку, и Xvfb утечёт
# (сигнал приходит, когда сессия-родитель закрывается).
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'exit 131' QUIT

# fd 3 — канал, в который Xvfb пишет выбранный номер дисплея.
Xvfb -displayfd 3 -screen 0 "$SCREEN" -ac 3>"$RUN_DIR/display" 2>"$RUN_DIR/xvfb.log" &
XVFB_PID=$!

for _ in $(seq 1 100); do
	[[ -s "$RUN_DIR/display" ]] && break
	kill -0 "$XVFB_PID" 2>/dev/null || break
	sleep 0.1
done

NUM="$(tr -dc '0-9' <"$RUN_DIR/display" 2>/dev/null || true)"
if [[ -z "$NUM" ]]; then
	echo "Xvfb не отдал номер дисплея, он не стартовал" >&2
	sed 's/^/  Xvfb: /' "$RUN_DIR/xvfb.log" >&2 || true
	XVFB_PID=""
	exit 2
fi

export DISPLAY=":$NUM"

if command -v xdpyinfo >/dev/null 2>&1; then
	READY=0
	for _ in $(seq 1 50); do
		if xdpyinfo -display "$DISPLAY" >/dev/null 2>&1; then
			READY=1
			break
		fi
		sleep 0.1
	done
	if [[ $READY -eq 0 ]]; then
		echo "дисплей $DISPLAY создан, но не отвечает (xdpyinfo)" >&2
		exit 2
	fi
fi

[[ -n "$DISPLAY_FILE" ]] && {
	mkdir -p "$(dirname "$DISPLAY_FILE")"
	printf '%s\n' "$DISPLAY" >"$DISPLAY_FILE"
}
echo "[xvfb] DISPLAY=$DISPLAY (Xvfb pid $XVFB_PID, screen $SCREEN)" >&2

if [[ -n "$SCREENSHOT_AT" && -n "$SCREENSHOT_DIR" ]]; then
	if command -v import >/dev/null 2>&1; then
		mkdir -p "$SCREENSHOT_DIR"
		(
			sleep "$SCREENSHOT_AT"
			import -window root "$SCREENSHOT_DIR/frame-${SCREENSHOT_AT}s.png" 2>/dev/null || true
		) &
		SHOT_PID=$!
	else
		echo "⚠ import (ImageMagick) нет в PATH — контрольный кадр не сниму" >&2
	fi
fi

RC=0
"$@" &
CMD_PID=$!
wait "$CMD_PID" || RC=$?
CMD_PID=""

echo "[xvfb] команда завершилась с кодом $RC; дисплей $DISPLAY снимается" >&2
exit "$RC"
