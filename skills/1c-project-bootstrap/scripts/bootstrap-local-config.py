#!/usr/bin/env python3
"""bootstrap-local-config.py — сборка локальных конфигов тестового контура.

Создаёт два файла, которые обязаны быть в дереве, но не должны попадать в git:

  tools/VAParams.json      — параметры Vanessa Automation (из
                             tools/VAParams.template.json)
  tools/va-env.local.json  — креды тест-клиента для шагов Vanessa, которые
                             подключают клиент сами (шаг „я подключаю TestClient
                             логин … пароль …“)

Единственный источник значений — v8project.local.yaml (он и так вне git).
Значения не печатаются: наружу идут только имена заполненных ключей.

Зачем генерация, а не готовый файл в git:

  * ПутьКИнфобазе абсолютен, поэтому готовый VAParams.json в ворктри ведёт
    тест-клиент в базу ОСНОВНОГО дерева — прогоны зелёные, но на старом
    состоянии (грабля проекта, проверена 2026-09-20).
  * Пустой пароль вместо отсутствующего /P даёт «Пользователь ИБ не
    идентифицирован»; пароль в вообще отслеживаемом файле — утечка.
  * Таймаут запуска 1С по умолчанию (25 с) не доживает до холодного старта:
    «Не получилось подключить TestClient, PID=0».

Использование:
  python3 bootstrap-local-config.py            # создать отсутствующие
  python3 bootstrap-local-config.py --force    # пересобрать поверх
  python3 bootstrap-local-config.py --tree <dir>

Коды возврата: 0 — готово, 1 — что-то уже есть без --force, 2 — окружения нет.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys

try:
    import yaml
except ImportError:  # сюда не ходят секреты — только текст ошибки
    print("нет модуля pyyaml: python3 -m pip install pyyaml", file=sys.stderr)
    sys.exit(2)

MIN_STARTUP_TIMEOUT = 300  # холодный старта тяжёлой конфигурации не укладывается в 25 с
PLACEHOLDER_USER = "<ПОЛЬЗОВАТЕЛЬ>"
PLACEHOLDER_PASS = "<ПАРОЛЬ>"
PLACEHOLDER_ROOT = "<абсолютный путь к дереву>"


def read_yaml(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data if isinstance(data, dict) else {}


def resolve_connection(connection: str, tree: pathlib.Path) -> str:
    """Строка подключения в формате Vanessa: абсолютный File= либо Srvr= как есть."""
    connection = connection.strip()
    if connection.startswith("File="):
        db_path = connection[len("File="):].strip().strip('"').rstrip(";")
        if not os.path.isabs(db_path):
            db_path = str((tree / db_path).resolve())
        return f'File="{db_path}";'
    return connection


def substitute(value, subs: dict[str, str]):
    if isinstance(value, str):
        for placeholder, replacement in subs.items():
            value = value.replace(placeholder, replacement)
        return value
    if isinstance(value, list):
        return [substitute(item, subs) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, subs) for key, item in value.items()}
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="перезаписать уже существующие файлы")
    parser.add_argument("--tree", default=None, help="дерево проекта (по умолчанию — текущий каталог)")
    args = parser.parse_args()

    root = pathlib.Path(args.tree or pathlib.Path.cwd()).resolve()
    local_config = root / "v8project.local.yaml"
    base_config = root / "v8project.yaml"
    template = root / "tools" / "VAParams.template.json"

    if not local_config.exists() and not base_config.exists():
        print(f"нет ни {local_config.name}, ни {base_config.name} — брать неоткуда", file=sys.stderr)
        return 2

    overlay = read_yaml(local_config)
    base = read_yaml(base_config)
    infobase = overlay.get("infobase") or base.get("infobase") or {}
    # Значения принудительно в строку: YAML сам по себе даст int для
    # незакавыченного числового пароля и лист для потока в квадратных скобках —
    # и замена плейсхолдеров упадёт на типе.
    user = str(infobase.get("user") or "")
    password = str(infobase.get("password") or "")
    connection = str(infobase.get("connection") or "")

    if not connection:
        print("в конфиге нет infobase.connection — куда подключаться тест-клиенту неизвестно", file=sys.stderr)
        return 2

    if not template.exists():
        print(
            f"нет {template} — без шаблона VAParams.json не собрать.\n"
            f"  положи его в git (шаблон с плейсхолдерами {PLACEHOLDER_USER}/"
            f"{PLACEHOLDER_PASS}/{PLACEHOLDER_ROOT}) либо восстанови "
            f"tools/VAParams.json вручную из основного дерева.",
            file=sys.stderr,
        )
        return 2

    params = json.loads(template.read_text(encoding="utf-8"))
    params = substitute(
        params,
        {
            PLACEHOLDER_USER: user,
            PLACEHOLDER_PASS: password,
            PLACEHOLDER_ROOT: str(root),
        },
    )

    client = params.setdefault("КлиентТестирования", {})
    # Холодный старт тяжёлой конфигурации не укладывается в дефолтные 25 с.
    try:
        if int(client.get("ТаймаутЗапуска1С", 0)) < MIN_STARTUP_TIMEOUT:
            client["ТаймаутЗапуска1С"] = MIN_STARTUP_TIMEOUT
    except (TypeError, ValueError):
        client["ТаймаутЗапуска1С"] = MIN_STARTUP_TIMEOUT

    # Точечные ключи клиентов. Другие имена («ПутьКИнформационнойБазе»,
    # «Порт», «ИмяПользователя») Vanessa не распознаёт — «Параметр не загружен».
    clients = client.get("ДанныеКлиентовТестирования")
    if not isinstance(clients, list) or not clients:
        clients = [{}]
        client["ДанныеКлиентовТестирования"] = clients
    entry = clients[0] if isinstance(clients[0], dict) else {}
    clients[0] = entry
    entry.setdefault("Имя", "Этот клиент")
    entry["ПутьКИнфобазе"] = resolve_connection(connection, root)
    entry.setdefault("ПортЗапускаТестКлиента", 48000)
    entry.setdefault("ТипКлиента", "Тонкий")
    entry.setdefault("ИмяКомпьютера", "localhost")
    # /P добавляем ТОЛЬКО при непустом пароле: пустой пароль-флаг даёт
    # «Пользователь ИБ не идентифицирован». Ключи — ровно эти, без замен.
    if user:
        args_part = f'/N"{user}"' + (f' /P"{password}"' if password else "")
        entry["ДопПараметры"] = args_part

    targets = {
        root / "tools" / "VAParams.json": json.dumps(params, ensure_ascii=False, indent=2) + "\n",
        root / "tools" / "va-env.local.json": json.dumps({"Логин": user, "Пароль": password}, ensure_ascii=False, indent=2) + "\n",
    }

    exit_code = 0
    for path, content in targets.items():
        if path.exists() and not args.force:
            print(f"пропуск (есть, нужен --force): {path.relative_to(root)}")
            exit_code = 1
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        print(f"записан (0600): {path.relative_to(root)}")

    # Страховка: отслеживаемый VAParams.json = креды в git.
    tracked = []
    import subprocess

    for path in targets:
        try:
            subprocess.run(
                ["git", "-C", str(root), "ls-files", "--error-unmatch", str(path.relative_to(root))],
                capture_output=True,
                check=True,
            )
            tracked.append(str(path.relative_to(root)))
        except (subprocess.CalledProcessError, OSError):
            continue
    if tracked:
        print(
            "⚠ в git отслеживаются файлы с кредами: "
            + ", ".join(tracked)
            + " — сними индексирования (git rm --cached) и пересобери --force",
            file=sys.stderr,
        )
        exit_code = max(exit_code, 1)

    print("ключи заполнены: infobase.user, infobase.connection, КлиентТестирования.* (значения не печатаю)")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
