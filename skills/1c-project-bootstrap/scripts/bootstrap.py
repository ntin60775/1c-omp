#!/usr/bin/env python3
"""1C Project Bootstrap — scaffold стандартной структуры 1С-проекта.

Операции (subcommands):
  structure   — каталоги + AGENTS.md + шаблоны-затравки (фичи, конфиги тестов)
  git         — git init + .gitignore/.gitattributes (+ remote origin)
  packagedef  — манифест OPM (имя проекта, зависимости тестовых фреймворков)
  env         — env.json (профиль запуска vrunner, дефолт /F./build/ib)
  all         — всё вышеперечисленное одним вызовом

Все операции идемпотентны: существующие файлы не перезаписываются
(кроме явного --force), git init пропускается, если репозиторий уже есть.

Взаимодействие с пользователем отсутствует: все параметры — аргументы CLI.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(SKILL_ROOT, "templates")

# Каталоги, создаваемые всегда.
DEFAULT_DIRS = [
    "docs",
    "features",
    "fixtures",
    "tasks",
    "tools",
    "tests",
    "tests/cfe",
    "tests/epf",
]

# Каталоги исходников по типам артефактов (--kinds).
KIND_DIRS = {
    "cf": "src/cf",
    "cfe": "src/cfe",
    "epf": "src/epf",
    "erf": "src/erf",
}

# Дополнительные каталоги (--extra), по явному запросу пользователя.
EXTRA_DIRS = ["examples", "lib", "vendor"]

# Затравки-шаблоны: относительный путь в проекте -> файл в templates/.
SEED_FILES = {
    "features/Шаблон фичи.feature": "features/Шаблон фичи.feature",
    "features/Шаблон фичи ОФ.feature": "features/Шаблон фичи ОФ.feature",
    "tools/VAParams.json": "tools/VAParams.json",
    "tools/yaxunit.json": "tools/yaxunit.json",
    "tools/syntax-check-excludes.txt": "tools/syntax-check-excludes.txt",
}

# Имя шаблона AGENTS.md для каждого каталога ("" — корень проекта).
AGENTS_FOR_DIR = {
    "": "root",
    "docs": "docs",
    "features": "features",
    "fixtures": "fixtures",
    "src": "src",
    "src/cf": "src_cf",
    "src/cfe": "src_cfe",
    "src/epf": "src_epf",
    "src/erf": "src_erf",
    "tasks": "tasks",
    "tests": "tests",
    "tests/cfe": "tests_cfe",
    "tests/epf": "tests_epf",
    "tools": "tools",
    "examples": "examples",
    "lib": "lib",
    "vendor": "vendor",
}

# Зависимости packagedef: фиксированный набор (Vanessa + YAxUnit).
PACKAGEDEF_DEPS = [
    ("add", None),
    ("vanessa-automation-single", None),
    ("vanessa-runner", "2.6.1"),
    ("oneunit", None),  # YAxUnit
]


def log(message: str) -> None:
    print(message)


def make_dirs(paths: list[str], dry_run: bool) -> tuple[int, int]:
    created = skipped = 0
    for rel in paths:
        dst = os.path.join(TARGET_DIR, rel)
        if os.path.isdir(dst):
            skipped += 1
            continue
        log(f"  mkdir   {rel}")
        if not dry_run:
            os.makedirs(dst, exist_ok=True)
        created += 1
    return created, skipped


def copy_template(template_rel: str, dst_rel: str, dry_run: bool, force: bool) -> str:
    """Копирует шаблон в проект. Возвращает статус: created | exists | overwritten."""
    src = os.path.join(TEMPLATES, template_rel)
    dst = os.path.join(TARGET_DIR, dst_rel)
    if os.path.exists(dst) and not force:
        log(f"  skip    {dst_rel} (already exists)")
        return "exists"
    action = "overwrite" if os.path.exists(dst) else "create"
    log(f"  {action:<8} {dst_rel}")
    if not dry_run:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
    return action


def write_agents(dirs: list[str], project_name: str, dry_run: bool, force: bool) -> tuple[int, int]:
    """Пишет AGENTS.md в перечисленные каталоги (включая корень через "")."""
    written = skipped = 0
    for rel in dirs:
        dst = os.path.join(TARGET_DIR, rel, "AGENTS.md")
        if os.path.exists(dst) and not force:
            skipped += 1
            log(f"  skip    {os.path.join(rel, 'AGENTS.md') if rel else 'AGENTS.md'} (already exists)")
            continue
        template_rel = os.path.join("agents", AGENTS_FOR_DIR[rel] + ".md")
        with open(os.path.join(TEMPLATES, template_rel), encoding="utf-8") as f:
            content = f.read()
        content = content.replace("{project_name}", project_name)
        log(f"  create  {os.path.join(rel, 'AGENTS.md') if rel else 'AGENTS.md'}")
        if not dry_run:
            with open(dst, "w", encoding="utf-8") as f:
                f.write(content)
        written += 1
    return written, skipped


def cmd_structure(args: argparse.Namespace) -> int:
    kinds = [k.strip() for k in args.kinds.split(",") if k.strip()]
    extra = [k.strip() for k in args.extra.split(",") if k.strip()]
    dirs = list(DEFAULT_DIRS)
    if kinds:
        dirs.append("src")
        dirs.extend(KIND_DIRS[k] for k in kinds if k in KIND_DIRS)
    dirs.extend(e for e in extra if e in EXTRA_DIRS)
    log(f"Каталоги: {len(dirs)}")
    created, skipped = make_dirs(dirs, args.dry_run)
    log(f"AGENTS.md:")
    written, ag_skipped = write_agents(dirs + [""], args.project_name, args.dry_run, args.force)
    log(f"Затравки-шаблоны:")
    seeds = 0
    for dst_rel, tpl_rel in SEED_FILES.items():
        status = copy_template(tpl_rel, dst_rel, args.dry_run, args.force)
        if status != "exists":
            seeds += 1
    log(f"structure: каталогов создано/пропущено {created}/{skipped}, "
        f"AGENTS.md {written}/{ag_skipped}, шаблонов {seeds}")
    return 0


def cmd_git(args: argparse.Namespace) -> int:
    git_dir = os.path.join(TARGET_DIR, ".git")
    if os.path.isdir(git_dir):
        log("git: репозиторий уже существует, git init пропущен")
    else:
        log("git: git init")
        if not args.dry_run:
            subprocess.run(["git", "init"], cwd=TARGET_DIR, check=True)
    copy_template("gitignore.template", ".gitignore", args.dry_run, args.force)
    copy_template("gitattributes.template", ".gitattributes", args.dry_run, args.force)
    if args.remote:
        if os.path.isdir(os.path.join(TARGET_DIR, ".git")):
            existing = subprocess.run(
                ["git", "remote", "get-url", "origin"],
                cwd=TARGET_DIR, capture_output=True, text=True,
            )
            if existing.returncode == 0:
                log(f"git: remote origin уже задан ({existing.stdout.strip()}), пропуск")
            else:
                log(f"git: git remote add origin {args.remote}")
                if not args.dry_run:
                    subprocess.run(["git", "remote", "add", "origin", args.remote], cwd=TARGET_DIR, check=True)
        else:
            log(f"git: remote origin не добавлен (нет репозитория, dry-run или git init отложен)")
    log("git: готово")
    return 0


def cmd_packagedef(args: argparse.Namespace) -> int:
    dst = os.path.join(TARGET_DIR, "packagedef")
    if os.path.exists(dst) and not args.force:
        log("packagedef: уже существует, пропуск")
        return 0
    lines = [f'Описание.Имя("{args.project_name}")', '    .Версия("1.0.0")', '    .ВерсияСреды("2.0.0")']
    for dep, version in PACKAGEDEF_DEPS:
        if version:
            lines.append(f'    .ЗависитОт("{dep}", "{version}")')
        else:
            lines.append(f'    .ЗависитОт("{dep}")')
    lines += ["", ";", ""]
    content = "\n".join(lines)
    log(f"create  packagedef (проект {args.project_name}, зависимостей {len(PACKAGEDEF_DEPS)})")
    if not args.dry_run:
        with open(dst, "w", encoding="utf-8") as f:
            f.write(content)
    return 0


def cmd_env(args: argparse.Namespace) -> int:
    dst = os.path.join(TARGET_DIR, "env.json")
    if os.path.exists(dst) and not args.force:
        log("env.json: уже существует, пропуск")
        return 0
    log(f"create  env.json (--ibconnection {args.ibconnection})")
    if not args.dry_run:
        with open(dst, "w", encoding="utf-8") as f:
            f.write('{\n    "default": {\n        "--ibconnection": "%s"\n    }\n}\n' % args.ibconnection)
    return 0


def cmd_all(args: argparse.Namespace) -> int:
    for cmd in (cmd_structure, cmd_git, cmd_packagedef, cmd_env):
        print(f"== {cmd.__name__[4:]} ==")
        cmd(args)
    log("all: готово. Дальше: opm install (зависимости), настройка ИБ и env.json.")
    return 0


def make_common_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dir", required=True, help="целевой каталог проекта (создаётся при необходимости)")
    common.add_argument("--name", dest="project_name", help="имя проекта (slug); по умолчанию — имя каталога")
    common.add_argument("--dry-run", action="store_true", help="показать план без изменений")
    common.add_argument("--force", action="store_true", help="перезаписывать существующие файлы/шаблоны")
    return common


def main(argv: list[str] | None = None) -> int:
    global TARGET_DIR
    common = make_common_parser()
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Scaffold стандартной структуры 1С-проекта (vanessa-bootstrap layout).",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_structure = sub.add_parser("structure", help="каталоги + AGENTS.md + затравки", parents=[common])
    p_structure.add_argument("--kinds", default="cf,cfe,epf,erf", help="типы исходников (csv): cf,cfe,epf,erf")
    p_structure.add_argument("--extra", default="", help="доп. каталоги (csv): examples,lib,vendor")
    p_structure.set_defaults(func=cmd_structure)

    p_git = sub.add_parser("git", help="git init + .gitignore/.gitattributes + remote", parents=[common])
    p_git.add_argument("--remote", help="URL remote origin (опционально)")
    p_git.set_defaults(func=cmd_git)

    p_packagedef = sub.add_parser("packagedef", help="манифест OPM", parents=[common])
    p_packagedef.set_defaults(func=cmd_packagedef)

    p_env = sub.add_parser("env", help="env.json (профиль запуска vrunner)", parents=[common])
    p_env.add_argument("--ibconnection", default="/F./build/ib", help="строка подключения к ИБ")
    p_env.set_defaults(func=cmd_env)

    p_all = sub.add_parser("all", help="structure + git + packagedef + env", parents=[common])
    p_all.add_argument("--kinds", default="cf,cfe,epf,erf", help="типы исходников (csv): cf,cfe,epf,erf")
    p_all.add_argument("--extra", default="", help="доп. каталоги (csv): examples,lib,vendor")
    p_all.add_argument("--remote", help="URL remote origin (опционально)")
    p_all.add_argument("--ibconnection", default="/F./build/ib", help="строка подключения к ИБ")
    p_all.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    TARGET_DIR = os.path.abspath(args.dir)
    if not args.project_name:
        args.project_name = os.path.basename(TARGET_DIR.rstrip(os.sep)) or "project"
    if args.dry_run:
        log(f"DRY-RUN: изменений не вносится. Цель: {TARGET_DIR}")
    else:
        log(f"Цель: {TARGET_DIR}")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
