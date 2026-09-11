#!/usr/bin/env bash
# init-worktree.sh — инициализация воркспейса Unica, тестового окружения и базы
# в git-ворктри. Запускать из основного дерева или из ворктри.
#
# Использование:
#   tasks/init-worktree.sh /path/to/worktree
#   tasks/init-worktree.sh /path/to/worktree --empty-ib   # файловая база: не копировать, создать пустую
#
# Что делает:
#   1. Копирует v8project.local.yaml (креды ИБ, путь к платформе)
#   2. Копирует build/tools/ (YAxUnit.cfe, vanessa-automation-single.epf)
#   3. Копирует tools/VAParams.json (профиль Vanessa; без него v8-runner падает
#      на валидации конфига при ЛЮБОЙ операции)
#   4. Разбирается с базой — см. «База» ниже
#   5. Копирует build/hash-storages/ — только если состояние базы совпадает с
#      основным деревом (иначе инкрементальное состояние невалидно)
#   6. Ставит плагины проекта (project scope): .omp/plugins/ не отслеживается
#      git и в ворктри не попадает
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
ARGS=()
for arg in "$@"; do
	case "$arg" in
	--empty-ib) EMPTY_IB=1 ;;
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

# 3. tools/VAParams.json
mkdir -p "$WORKTREE/tools"
if [[ -f "$MAIN_TREE/tools/VAParams.json" ]]; then
	cp -p "$MAIN_TREE/tools/VAParams.json" "$WORKTREE/tools/VAParams.json"
	echo "✓ tools/VAParams.json"
else
	echo "✗ нет $MAIN_TREE/tools/VAParams.json — v8-runner не пройдёт валидацию" >&2
	ERRORS=$((ERRORS + 1))
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
PLUGINS_JSON="$MAIN_TREE/.omp/plugins/installed_plugins.json"
if [[ -f "$PLUGINS_JSON" ]]; then
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
