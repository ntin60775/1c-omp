#!/usr/bin/env bash
# init-worktree.sh — инициализация воркспейса Unica, тестового окружения и базы
# в git-ворктри. Запускать из основного дерева или из ворктри.
#
# Использование:
#   init-worktree.sh /path/to/worktree
#   init-worktree.sh /path/to/worktree --empty-ib        # файловая база: не копировать, создать пустую
#   init-worktree.sh /path/to/worktree --skip-plugins    # не ставить плагины: живой Unica MCP другой сессии
#                                                        # переживёт только без пересоздания кэша плагинов
#
# Что делает:
#   1. Копирует v8project.local.yaml (креды ИБ, путь к платформе)
#   2. Копирует build/tools/ (YAxUnit.cfe, vanessa-automation-single.epf)
#   3. Собирает tools/VAParams.json и tools/va-env.local.json под ЭТО дерево из
#      tools/VAParams.template.json + v8project.local.yaml (скрипт
#      bootstrap-local-config.py). Готовый VAParams.json из основного дерева
#      копировать нельзя: в нём абсолютный путь к базе основного дерева —
#      тесты уйдут на чужую базу
#   4. Разбирается с базой — см. «База» ниже
#   5. Копирует build/hash-storages/ — только если состояние базы совпадает с
#      основным деревом (иначе инкрементальное состояние невалидно)
#   6. Ставит плагины проекта (project scope): .omp/plugins/ не отслеживается
#      git и в ворктри не попадает. Предупреждает, если живой Unica MCP может
#      от этого сломаться (см. --skip-plugins)
#   7. Проверяет результат
#
# База:
#   File=<относительный путь> — у каждого дерева своя файловая база.
#       Нет базы: без флага — копия из основного дерева (это долго и много
#       места), с --empty-ib — пустая база. Пустая годится для сборки из
#       исходников и тестов без данных; для Vanessa/BDD нужна полная.
#   Srvr=<сервер>;Ref=<база> — база ОДНА на все деревья: отдельную на каждый
#       ворктри не поднять. Изоляции тут нет и быть не может, поэтому
#       одновременно с базой работает одно дерево — это разводит замок хука
#       unica-gate.
#
# ВАЖНО: только реальные копии, НЕ симлинки (distrobox не видит симлинки).

set -euo pipefail

EMPTY_IB=0
SKIP_PLUGINS=0
ARGS=()
for arg in "$@"; do
	case "$arg" in
	--empty-ib) EMPTY_IB=1 ;;
	--skip-plugins) SKIP_PLUGINS=1 ;;
	*) ARGS+=("$arg") ;;
	esac
done
WORKTREE="${ARGS[0]:-.}"
WORKTREE="$(cd "$WORKTREE" && pwd)"

GIT_COMMON_DIR="$(git -C "$WORKTREE" rev-parse --git-common-dir 2>/dev/null || true)"
if [[ -z "$GIT_COMMON_DIR" ]]; then
	echo "✗ не git-репозиторий: $WORKTREE" >&2
	exit 2
fi
GIT_COMMON_DIR="$(cd "$GIT_COMMON_DIR" && pwd)"
MAIN_TREE="$(dirname "$GIT_COMMON_DIR")"

if [[ "$MAIN_TREE" == "$WORKTREE" ]]; then
	echo "✗ это основное дерево, а не ворктри: $WORKTREE" >&2
	exit 2
fi

echo "Основное дерево: $MAIN_TREE"
echo "Ворктри:         $WORKTREE"
echo ""

ERRORS=0

# ── строка подключения к базе: локальный оверлей перекрывает основной файл ──
resolve_connection() {
	python3 - "$1" <<'PY'
import re, sys, pathlib
tree = pathlib.Path(sys.argv[1])
def read(name):
    f = tree / name
    if not f.exists():
        return None
    in_infobase = False
    for line in f.read_text(encoding="utf-8").splitlines():
        if re.match(r"^\S", line):
            in_infobase = bool(re.match(r"^infobase\s*:", line))
            continue
        if not in_infobase:
            continue
        m = re.match(r"^\s+connection\s*:\s*(.+?)\s*$", line)
        if m:
            return m.group(1).strip().strip("'\"")
    return None
print(read("v8project.local.yaml") or read("v8project.yaml") or "")
PY
}

# 1. v8project.local.yaml
if [[ -f "$MAIN_TREE/v8project.local.yaml" ]]; then
	cp -p "$MAIN_TREE/v8project.local.yaml" "$WORKTREE/v8project.local.yaml"
	echo "✓ v8project.local.yaml"
else
	echo "✗ нет $MAIN_TREE/v8project.local.yaml — креды и платформа не перенесены" >&2
	ERRORS=$((ERRORS + 1))
fi

# 2. build/tools/
mkdir -p "$WORKTREE/build"
if [[ -d "$MAIN_TREE/build/tools" ]]; then
	cp -r "$MAIN_TREE/build/tools" "$WORKTREE/build/tools"
	echo "✓ build/tools/"
else
	echo "✗ нет $MAIN_TREE/build/tools — в основном дереве выполни tools-download" >&2
	ERRORS=$((ERRORS + 1))
fi

# 3. tools/VAParams.json (+ tools/va-env.local.json)
# Шаблон в ворктри копируется, рабочий файл СОБИРАЕТСЯ под это дерево:
# в копии из основного дерева лежит абсолютный ПутьКИнфобазе, и тест-клиент
# тихо тестирует базу основного дерева (см. rule://worktree-env).
mkdir -p "$WORKTREE/tools"
TEMPLATE_FOUND=0
if [[ -f "$MAIN_TREE/tools/VAParams.template.json" ]]; then
	cp -p "$MAIN_TREE/tools/VAParams.template.json" "$WORKTREE/tools/VAParams.template.json"
	TEMPLATE_FOUND=1
	echo "✓ tools/VAParams.template.json"
fi
GENERATOR=""
for g in "$(cd "$(dirname "$0")" && pwd)/bootstrap-local-config.py" \
	"$MAIN_TREE/.omp/plugins/node_modules/1c-omp/skills/1c-project-bootstrap/scripts/bootstrap-local-config.py" \
	"$WORKTREE/.omp/plugins/node_modules/1c-omp/skills/1c-project-bootstrap/scripts/bootstrap-local-config.py"; do
	[[ -f "$g" ]] && { GENERATOR="$g"; break; }
done
if [[ $TEMPLATE_FOUND -eq 1 && -f "$WORKTREE/v8project.local.yaml" ]]; then
	if [[ -n "$GENERATOR" ]]; then
		# Значения не печатаются: скрипт пишет только имена заполненных ключей.
		if python3 "$GENERATOR" --tree "$WORKTREE"; then
			echo "✓ tools/VAParams.json + tools/va-env.local.json (собраны под ворктри)"
		else
			echo "✗ сборка профиля Vanessa не удалась" >&2
			ERRORS=$((ERRORS + 1))
		fi
	else
		echo "⚠ нет bootstrap-local-config.py — профиль не собран" >&2
		ERRORS=$((ERRORS + 1))
	fi
elif [[ -f "$MAIN_TREE/tools/VAParams.json" ]]; then
	# Старый канон без шаблона: копия с предупреждением о чужом пути.
	cp -p "$MAIN_TREE/tools/VAParams.json" "$WORKTREE/tools/VAParams.json"
	echo "⚠ tools/VAParams.json скопирован как есть — проверь ПутьКИнфобазе:"
	echo "  в нём может быть путь базы ОСНОВНОГО дерева (см. rule://worktree-env)"
else
	echo "✗ нет ни VAParams.template.json, ни VAParams.json в основном дереве —" >&2
	echo "  v8-runner не пройдёт валидацию конфига" >&2
	ERRORS=$((ERRORS + 1))
fi
# Креды тест-клиента для шагов Vanessa, подключающих клиент сами: канон раньше
# их не копировал, и фичи падали на чтении файла в ворктри. Генератор уже
# создаёт их под ворктри (см. выше), поэтому здесь — только путь без шаблона.
if [[ ! -f "$WORKTREE/tools/va-env.local.json" && -f "$MAIN_TREE/tools/va-env.local.json" ]]; then
	cp -p "$MAIN_TREE/tools/va-env.local.json" "$WORKTREE/tools/va-env.local.json"
	chmod 600 "$WORKTREE/tools/va-env.local.json" 2>/dev/null || true
	echo "✓ tools/va-env.local.json"
fi

# 4. База
CONNECTION="$(resolve_connection "$WORKTREE")"
COPY_HASHES=1
echo ""
if [[ -z "$CONNECTION" ]]; then
	echo "⚠ база не объявлена ни в v8project.yaml, ни в оверлее"
	COPY_HASHES=0
elif [[ "$CONNECTION" == File=* ]]; then
	REL="${CONNECTION#File=}"
	IB="$WORKTREE/$REL"
	MAIN_IB="$MAIN_TREE/$REL"
	if [[ -d "$IB" ]]; then
		echo "✓ файловая база на месте: $REL"
	elif [[ $EMPTY_IB -eq 1 ]]; then
		mkdir -p "$IB"
		echo "• файловая база создана пустой: $REL (данных нет)"
		COPY_HASHES=0
	elif [[ -d "$MAIN_IB" ]]; then
		echo "• копирую файловую базу из основного дерева: $REL ($(du -sh "$MAIN_IB" 2>/dev/null | cut -f1))…"
		cp -a "$MAIN_IB" "$IB"
		echo "✓ база скопирована"
	else
		echo "✗ файловой базы нет ни в ворктри, ни в основном дереве: $REL" >&2
		echo "  подними пустую: $0 $WORKTREE --empty-ib" >&2
		ERRORS=$((ERRORS + 1))
		COPY_HASHES=0
	fi
else
	echo "⚠ база серверная и общая для всех деревьев: $CONNECTION"
	echo "  изоляции здесь нет и быть не может — отдельную серверную базу на"
	echo "  каждый ворктри не поднять. Одновременные операции разводит замок"
	echo "  хука unica-gate: пока одно дерево грузит, другое получит отказ."
fi

# 5. build/hash-storages/ — инкрементальное состояние сборки
if [[ $COPY_HASHES -eq 1 && -d "$MAIN_TREE/build/hash-storages" ]]; then
	cp -r "$MAIN_TREE/build/hash-storages" "$WORKTREE/build/hash-storages"
	echo "✓ build/hash-storages/"
elif [[ $COPY_HASHES -eq 0 ]]; then
	echo "• build/hash-storages/ не копирую: база не совпадает с основным деревом"
fi

# 6. Плагины проекта (project scope)
#
# ВАЖНО: `omp plugin install` ПЕРЕСОЗДАЁТ каталог кэша плагина, а у живого
# stdio-сервера Unica MCP рабочий каталог остался на удалённом иноде — все его
# вызовы после этого падают с «failed to read current directory». Симптом,
# диагностика и восстановление — rule://unica-mcp. Если в других окнах сейчас
# работает Unica, либо пропусти шаг флагом --skip-plugins (плагины поставит
# следующая сессия), либо выполни восстановление для зависших окон сразу.
PLUGINS_JSON="$MAIN_TREE/.omp/plugins/installed_plugins.json"
if [[ $SKIP_PLUGINS -eq 1 ]]; then
	echo "• шаг плагинов пропущен (--skip-plugins): плагины в ворктри не ставились"
	echo "  поставь их в свободное время либо оставь на следующую сессию"
elif [[ -f "$PLUGINS_JSON" ]]; then
	LIVE_UNICA="$(pgrep -af 'linux-x64/unica|unica-bootstrap' 2>/dev/null || true)"
	if [[ -n "$LIVE_UNICA" ]]; then
		echo "⚠ живые процессы Unica MCP — шаг плагинов может сломать их:"
		printf '%s\n' "$LIVE_UNICA" | sed 's/^/    /'
		echo "  при симптоме «failed to read current directory» — rule://unica-mcp,"
		echo "  раздел «пересоздание кэша плагинов убивает живой сервер»"
	fi
	if command -v omp >/dev/null 2>&1; then
		while IFS= read -r spec; do
			[[ -n "$spec" ]] || continue
			if (cd "$WORKTREE" && omp plugin install --scope project "$spec" >/dev/null 2>&1); then
				echo "✓ плагин $spec"
			else
				echo "✗ плагин $spec не установился" >&2
				ERRORS=$((ERRORS + 1))
			fi
		done < <(grep -oE '"[^"]+@[^"]+":' "$PLUGINS_JSON" | tr -d '":')
	else
		echo "✗ omp не найден в PATH — плагины проекта не установлены" >&2
		ERRORS=$((ERRORS + 1))
	fi
else
	echo "⚠ .omp/plugins/installed_plugins.json нет — плагины проекта не ставились"
fi

# 7. Проверка
echo ""
echo "=== Проверка воркспейса ==="
MISSING=0
REQUIRED=(v8project.local.yaml v8project.yaml tools/VAParams.json)
[[ -f "$PLUGINS_JSON" ]] && REQUIRED+=(.omp/plugins/installed_plugins.json)
for f in "${REQUIRED[@]}"; do
	if [[ -f "$WORKTREE/$f" ]]; then
		echo "✓ $f"
	else
		echo "✗ $f" >&2
		MISSING=$((MISSING + 1))
	fi
done
for d in build/tools; do
	if [[ -d "$WORKTREE/$d" ]]; then
		echo "✓ $d/"
	else
		echo "✗ $d/" >&2
		MISSING=$((MISSING + 1))
	fi
done

if [[ $MISSING -gt 0 || $ERRORS -gt 0 ]]; then
	echo ""
	echo "Не хватает: $MISSING, ошибок: $ERRORS" >&2
	exit 1
fi

echo ""
echo "Воркспейс готов. Проверь: unica.project.status { \"cwd\": \"$WORKTREE\" }"
if [[ "$CONNECTION" == Srvr=* ]]; then
	echo "База общая: перед операциями убедись, что в основном дереве никто не грузит."
fi
