#!/usr/bin/env python3
"""Машинный guard детерминированных правил стиля `1c-bsl-code-style`.

Check-id:
- tab-rhythm          пустые строки внутри методов держат tab-уровень блока (fix);
- operator-case       операторы только `Не`, `И`, `Или` (fix);
- empty-ctor-parens   пустой конструктор пишется со скобками (fix);
- comma-space         после запятой в списке аргументов стоит пробел (fix);
- struct-ctor-args    `Новый Структура` не более чем с одним значением (report);
- if-nesting          вложенность `Если...Тогда` не глубже двух уровней (report);
- return-expression   нет прямого `Возврат Выражение;`, кроме финального
                      `Возврат ВозвращаемоеЗначение;` (report).
- inline-condition   сложное условие в `Если`/`ИначеЕсли`/`Пока` выносится
                      в переменную с предметным булевым именем (report);
- block-air           в многострочных блоках пустая строка после открывателя,
                      перед закрывателем и перед Возврат/Прервать/Продолжить
                      как границей стадии (report);
- invalid-char        «умная типографика» (— – … NBSP, минус, soft hyphen,
                      BOM) недопустима в .bsl — только ASCII-аналоги (report);
- chained-call        цепочка `)...Метод(` / вызов объекта аргументом вызова —
                      каждый шаг отдельной строкой (report);
- nested-call-arg     вызов/конструктор аргументом другого вызова —
                      вынести аргумент в переменную (report);
- omitted-arg         пропущенный аргумент `Метод(, Текст)` — писать явное
                      `Неопределено` (report);
- named-type-desc     повтор `Новый ОписаниеТипов(...)` в методе inline —
                      именованная переменная или helper (report).

Строковые литералы (включая многострочные с `|`) и комментарии пропускаются.
При `--fix` кодировка, BOM и переводы строк сохраняются.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys

CHECK_IDS = (
    "tab-rhythm",
    "operator-case",
    "empty-ctor-parens",
    "comma-space",
    "struct-ctor-args",
    "if-nesting",
    "return-expression",
    "query-text-format",
    "query-istina",
    "boolean-column",
    "ternary-long",
    "call-args-multi",
    "inline-condition",
    "block-air",
    "invalid-char",
    "chained-call",
    "nested-call-arg",
    "omitted-arg",
    "named-type-desc",
)

FIXABLE = frozenset({"tab-rhythm", "operator-case", "empty-ctor-parens", "comma-space"})

METHOD_START = ("Процедура", "Функция")
METHOD_END = ("КонецПроцедуры", "КонецФункции")
BRANCH_OR_BLOCK_START = (
    "Если ",
    "ИначеЕсли ",
    "Иначе",
    "Для ",
    "Пока ",
    "Попытка",
    "Исключение",
)
CLOSING_OR_BRANCH = (
    "ИначеЕсли ",
    "Иначе",
    "Исключение",
    "КонецЕсли",
    "КонецЦикла",
    "КонецПопытки",
    "КонецПроцедуры",
    "КонецФункции",
)

_WORD = "А-Яа-яЁёA-Za-z0-9_"
_OPERATOR_RE = re.compile(rf"(?<![{_WORD}])(Не|НЕ|не|И|и|Или|ИЛИ|или)(?![{_WORD}])")
_OPERATOR_CANON = {"не": "Не", "и": "И", "или": "Или"}
_CTOR_HEAD_RE = re.compile(rf"(?<![{_WORD}])Новый(\s+)([{_WORD}]+)")
_STRUCT_CTOR_RE = re.compile(r'Новый\s+Структура\s*\(\s*"([^"]*)"')
_COMMA_RE = re.compile(r",(?=[^\s)])")
_RETURN_RE = re.compile(r"Возврат\s+(.+?)\s*;\s*$")
_IF_OPEN_RE = re.compile(r"Если(?:\s|\()")
_IF_CLOSE_RE = re.compile(r"КонецЕсли\b")


@dataclass(frozen=True)
class Violation:
    path: Path
    line_number: int
    check: str
    message: str


# ---------------------------------------------------------------------------
# Базовые лексические помощники
# ---------------------------------------------------------------------------


def _strip_newline(line: str) -> tuple[str, str]:
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n"):
        return line[:-1], "\n"
    if line.endswith("\r"):
        return line[:-1], "\r"
    return line, ""


def _decode(raw: bytes) -> tuple[str, bool]:
    has_bom = raw.startswith(b"\xef\xbb\xbf")
    return raw.decode("utf-8-sig"), has_bom


def _leading_tabs(text: str) -> int:
    return len(text) - len(text.lstrip("\t"))


def _statement_text(text: str) -> str:
    return text.lstrip("\t ")


def _code_spans(lines: list[str]) -> list[list[tuple[int, int]]]:
    """Для каждой строки (с переводом строки) вернуть спаны BSL-кода.

    Спаны (start, end) не включают строковые литералы (в том числе
    многострочные с продолжением `|`) и комментарии `//`.
    """
    spans_per_line: list[list[tuple[int, int]]] = []
    in_string = False
    for raw in lines:
        body, _ = _strip_newline(raw)
        n = len(body)
        spans: list[tuple[int, int]] = []
        i = 0
        span_start: int | None = 0
        if in_string:
            span_start = None
            while i < n and body[i] in " \t":
                i += 1
            if i < n and body[i] == "|":
                i += 1
            while i < n:
                if body[i] == '"':
                    if i + 1 < n and body[i + 1] == '"':
                        i += 2
                        continue
                    i += 1
                    in_string = False
                    span_start = i
                    break
                i += 1
        while i < n:
            if body[i] == "/" and i + 1 < n and body[i + 1] == "/":
                break
            if body[i] == '"':
                if span_start is not None and i > span_start:
                    spans.append((span_start, i))
                span_start = None
                i += 1
                in_string = True
                while i < n:
                    if body[i] == '"':
                        if i + 1 < n and body[i + 1] == '"':
                            i += 2
                            continue
                        i += 1
                        in_string = False
                        break
                    i += 1
                if not in_string:
                    span_start = i
                continue
            i += 1
        if span_start is not None and span_start < i:
            spans.append((span_start, i))
        spans_per_line.append(spans)
    return spans_per_line


def _code_view(lines: list[str], spans: list[list[tuple[int, int]]]) -> list[str]:
    """Строки, где строки-литералы и комментарии заменены пробелами."""
    view: list[str] = []
    for raw, line_spans in zip(lines, spans):
        body, _ = _strip_newline(raw)
        chars = [" "] * len(body)
        for start, end in line_spans:
            chars[start:end] = body[start:end]
        view.append("".join(chars))
    return view


# ---------------------------------------------------------------------------
# tab-rhythm (перенесено из check_bsl_blank_line_tab_rhythm.py)
# ---------------------------------------------------------------------------


def _is_method_start(text: str) -> bool:
    stripped = _statement_text(text)
    return any(stripped.startswith(keyword + " ") or stripped.startswith(keyword + "(") for keyword in METHOD_START)


def _is_method_end(text: str) -> bool:
    stripped = _statement_text(text)
    return any(stripped.startswith(keyword) for keyword in METHOD_END)


def _opens_body(text: str) -> bool:
    stripped = _statement_text(text)
    if _is_method_start(text):
        return True
    if stripped.endswith(" Тогда") or stripped.endswith(" Цикл"):
        return True
    return any(stripped.startswith(keyword) for keyword in BRANCH_OR_BLOCK_START)


def _is_closing_or_branch(text: str) -> bool:
    stripped = _statement_text(text)
    return any(stripped.startswith(keyword) for keyword in CLOSING_OR_BRANCH)


def _previous_nonblank(lines: list[str], start: int, method_start: int) -> int | None:
    for index in range(start - 1, method_start - 1, -1):
        body, _ = _strip_newline(lines[index])
        if body.strip("\t "):
            return index
    return None


def _next_nonblank(lines: list[str], start: int, method_end: int) -> int | None:
    for index in range(start + 1, method_end + 1):
        body, _ = _strip_newline(lines[index])
        if body.strip("\t "):
            return index
    return None


def _expected_tabs(lines: list[str], index: int, method_start: int, method_end: int) -> int:
    prev_index = _previous_nonblank(lines, index, method_start)
    next_index = _next_nonblank(lines, index, method_end)

    prev_text = _strip_newline(lines[prev_index])[0] if prev_index is not None else ""
    next_text = _strip_newline(lines[next_index])[0] if next_index is not None else ""

    if next_index is not None and _is_closing_or_branch(next_text):
        return max(1, _leading_tabs(next_text) + 1)
    if prev_index is not None and _opens_body(prev_text):
        return max(1, _leading_tabs(prev_text) + 1)
    if prev_index is not None and next_index is not None:
        return max(1, min(_leading_tabs(prev_text), _leading_tabs(next_text)))
    if prev_index is not None:
        return max(1, _leading_tabs(prev_text))
    if next_index is not None:
        return max(1, _leading_tabs(next_text))
    return 1


def _blank_line_reason(body: str, actual_tabs: int, expected_tabs: int) -> str:
    if body == "":
        return "пустая строка без табов внутри тела метода"
    if body.strip("\t") != "":
        return "пустая строка содержит пробелы вместо отступа из табов"
    if actual_tabs < expected_tabs:
        return "у пустой строки меньше табов, чем у текущего BSL-блока"
    return "у пустой строки больше табов, чем у текущего BSL-блока"


def _check_tab_rhythm(
    path: Path,
    raw_lines: list[str],
    code_lines: list[str],
) -> list[Violation]:
    violations: list[Violation] = []
    method_start: int | None = None
    for index, code_body in enumerate(code_lines):
        if method_start is None:
            if _is_method_start(code_body):
                method_start = index
            continue

        method_end = index if _is_method_end(code_body) else None
        body, _ = _strip_newline(raw_lines[index])
        if body.strip("\t ") == "":
            end_bound = method_end if method_end is not None else len(code_lines) - 1
            expected_tabs = _expected_tabs(code_lines, index, method_start, end_bound)
            actual_tabs = _leading_tabs(body)
            if body != "\t" * expected_tabs:
                violations.append(
                    Violation(
                        path=path,
                        line_number=index + 1,
                        check="tab-rhythm",
                        message=f"{_blank_line_reason(body, actual_tabs, expected_tabs)}: "
                        f"ожидается {expected_tabs} таб., найдено {actual_tabs}",
                    )
                )

        if method_end is not None:
            method_start = None
    return violations


def _fix_tab_rhythm(raw_lines: list[str], code_lines: list[str]) -> bool:
    changed = False
    method_start: int | None = None
    for index, code_body in enumerate(code_lines):
        if method_start is None:
            if _is_method_start(code_body):
                method_start = index
            continue

        method_end = index if _is_method_end(code_body) else None
        body, newline = _strip_newline(raw_lines[index])
        if body.strip("\t ") == "":
            end_bound = method_end if method_end is not None else len(code_lines) - 1
            expected_tabs = _expected_tabs(code_lines, index, method_start, end_bound)
            expected_body = "\t" * expected_tabs
            if body != expected_body:
                raw_lines[index] = expected_body + newline
                changed = True

        if method_end is not None:
            method_start = None
    return changed


# ---------------------------------------------------------------------------
# Проверки по code-спанам строк
# ---------------------------------------------------------------------------


def _spans_of_line(body: str, line_spans: list[tuple[int, int]]) -> list[str]:
    return [body[start:end] for start, end in line_spans]


def _check_operator_case(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    violations: list[Violation] = []
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        bad: list[str] = []
        for segment in _spans_of_line(body, line_spans):
            for match in _OPERATOR_RE.finditer(segment):
                canon = _OPERATOR_CANON[match.group(1).lower()]
                if match.group(1) != canon:
                    bad.append(f"{match.group(1)}→{canon}")
        if bad:
            violations.append(
                Violation(
                    path=path,
                    line_number=index + 1,
                    check="operator-case",
                    message="неканонический регистр операторов: " + ", ".join(bad),
                )
            )
    return violations


def _fix_operator_case_segment(segment: str) -> str:
    return _OPERATOR_RE.sub(lambda m: _OPERATOR_CANON[m.group(1).lower()], segment)


def _check_empty_ctor_parens(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    violations: list[Violation] = []
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        for segment in _spans_of_line(body, line_spans):
            for match in _CTOR_HEAD_RE.finditer(segment):
                rest = segment[match.end():]
                if not rest.lstrip(" \t").startswith("("):
                    violations.append(
                        Violation(
                            path=path,
                            line_number=index + 1,
                            check="empty-ctor-parens",
                            message=f"пустой конструктор без скобок: `{match.group(0).strip()}`",
                        )
                    )
    return violations


def _fix_empty_ctor_parens_segment(segment: str) -> str:
    def _insert(match: re.Match[str]) -> str:
        rest = segment[match.end():]
        if rest.lstrip(" \t").startswith("("):
            return match.group(0)
        return f"Новый{match.group(1)}{match.group(2)}()"

    return _CTOR_HEAD_RE.sub(_insert, segment)


def _check_comma_space(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    violations: list[Violation] = []
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        for segment in _spans_of_line(body, line_spans):
            if _COMMA_RE.search(segment):
                violations.append(
                    Violation(
                        path=path,
                        line_number=index + 1,
                        check="comma-space",
                        message="после запятой в списке аргументов нет пробела",
                    )
                )
                break
    return violations


def _fix_comma_space_segment(segment: str) -> str:
    return _COMMA_RE.sub(", ", segment)


# ---------------------------------------------------------------------------
# Report-only проверки
# ---------------------------------------------------------------------------


def _check_struct_ctor_args(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    violations: list[Violation] = []
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        for match in _STRUCT_CTOR_RE.finditer(body):
            if not any(start <= match.start() < end for start, end in line_spans):
                continue
            if "," in match.group(1):
                violations.append(
                    Violation(
                        path=path,
                        line_number=index + 1,
                        check="struct-ctor-args",
                        message="`Новый Структура` с более чем одним свойством; "
                        "нужна пустая структура и явные `Вставить(...)`",
                    )
                )
                break
    return violations


def _check_if_nesting(path: Path, code_lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    depth = 0
    in_method = False
    for index, body in enumerate(code_lines):
        statement = _statement_text(body)
        if statement.startswith("#"):
            continue
        if not in_method and _is_method_start(body):
            in_method = True
            depth = 0
            continue
        if not in_method:
            continue
        if _is_method_end(body):
            in_method = False
            depth = 0
            continue
        if _IF_CLOSE_RE.match(statement):
            depth = max(0, depth - 1)
            continue
        if statement.startswith(("ИначеЕсли", "Иначе")):
            continue
        if _IF_OPEN_RE.match(statement):
            depth += 1
            if depth > 2:
                violations.append(
                    Violation(
                        path=path,
                        line_number=index + 1,
                        check="if-nesting",
                        message=f"вложенность `Если...Тогда` — {depth} уровня; допускается не более двух",
                    )
                )
    return violations


def _check_return_expression(path: Path, code_lines: list[str]) -> list[Violation]:
    violations: list[Violation] = []
    for index, body in enumerate(code_lines):
        statement = _statement_text(body).rstrip()
        match = _RETURN_RE.match(statement)
        if match and match.group(1).strip() != "ВозвращаемоеЗначение":
            violations.append(
                Violation(
                    path=path,
                    line_number=index + 1,
                    check="return-expression",
                    message="прямой `Возврат Выражение;`; нужна форма через `ВозвращаемоеЗначение`",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# query-text-format
# ---------------------------------------------------------------------------


def _check_query_text_format(path: Path, lines: list[str]) -> list[Violation]:
    """Query text literal must start with '= "' and end with '|";'."""
    violations: list[Violation] = []

    for index, line in enumerate(lines):
        body, _ = _strip_newline(line)
        stripped = _statement_text(body)

        # Check for query text assignment
        if re.search(r'(Запрос\.Текст|ВозвращаемоеЗначение)\s*=\s*"', stripped):
            # Check if closing is on same line (bad format for multi-line query)
            if stripped.rstrip().endswith('";'):
                # Count remaining | lines
                remaining = 0
                for j in range(index + 1, min(index + 50, len(lines))):
                    rbody, _ = _strip_newline(lines[j])
                    rstripped = _statement_text(rbody)
                    if rstripped.startswith("|"):
                        remaining += 1
                    else:
                        break
                if remaining > 0:
                    violations.append(Violation(path, index + 1, "query-text-format",
                        "query text literal closing quote on same line as assignment; move closing '|\";' to its own line"))

        # Check for closing quote not on | line
        if stripped.rstrip().endswith('";') and not stripped.startswith("|") and not re.search(r'(Запрос\.Текст|ВозвращаемоеЗначение)\s*=\s*"', stripped):
            # Look back for query literal start
            for j in range(index - 1, max(index - 50, -1), -1):
                rbody, _ = _strip_newline(lines[j])
                rstripped = _statement_text(rbody)
                if re.search(r'(Запрос\.Текст|ВозвращаемоеЗначение)\s*=\s*"', rstripped):
                    # Закрытие на той же строке и нет | продолжения - это
                    # одиночный строковый литерал, не текст запроса: стоп без
                    # finding (иначе lookback цепляется за хелперы-строки).
                    if rstripped.rstrip().endswith('";'):
                        nxt = ""
                        if j + 1 < len(lines):
                            nbody, _ = _strip_newline(lines[j + 1])
                            nxt = _statement_text(nbody)
                        if not nxt.startswith("|"):
                            break
                    violations.append(Violation(path, index + 1, "query-text-format",
                        "query text literal closing quote not on '|\";' line"))
                    break
                if rstripped.rstrip().endswith('";') and rstripped.startswith("|"):
                    break

    return violations


# ---------------------------------------------------------------------------
# query-istina
# ---------------------------------------------------------------------------


def _check_query_istina(path: Path, lines: list[str]) -> list[Violation]:
    """Check that first |ГДЕ in a query literal with 2+ conditions starts with |ИСТИНА."""
    violations: list[Violation] = []
    in_literal = False
    gde_checked = False

    for index, line in enumerate(lines):
        body, _ = _strip_newline(line)
        stripped = _statement_text(body)

        if not in_literal:
            if stripped.startswith("|") and any(kw in stripped.upper() for kw in ("ВЫБРАТЬ", "SELECT")):
                in_literal = True
                gde_checked = False
        else:
            if stripped.rstrip().endswith('";') and not stripped.startswith("|"):
                in_literal = False
                continue

            if stripped.startswith("|"):
                # Check for ГДЕ — only first one in literal
                if re.match(r'^\|\s*ГДЕ\s*$', stripped, re.IGNORECASE):
                    if gde_checked:
                        continue  # skip UNION branches

                    gde_checked = True
                    condition_count = 0
                    has_istina = False

                    # Scan following lines for conditions
                    for j in range(index + 1, min(index + 100, len(lines))):
                        rbody, _ = _strip_newline(lines[j])
                        rstripped = _statement_text(rbody)

                        if not rstripped.startswith("|"):
                            break

                        inner = rstripped.lstrip("| ").strip()
                        if not inner:
                            continue
                        if inner.startswith("УПОРЯДОЧИТЬ") or inner.startswith("ORDER"):
                            break
                        if inner == ";" or rstripped.rstrip().endswith('";'):
                            break

                        condition_count += 1
                        if inner == "ИСТИНА":
                            has_istina = True

                    if condition_count >= 2 and not has_istina:
                        violations.append(Violation(path, index + 1, "query-istina",
                            "first WHERE with 2+ conditions should start with |ИСТИНА"))

    return violations


# ---------------------------------------------------------------------------
# boolean-column
# ---------------------------------------------------------------------------


def _check_boolean_column(path: Path, lines: list[str]) -> list[Violation]:
    """Check that multi-line boolean assignments use (Ложь/Истина + column form."""
    violations: list[Violation] = []

    for index, line in enumerate(lines):
        body, _ = _strip_newline(line)
        stripped = _statement_text(body)

        # Check for assignment ending with = on its own line
        if re.search(r'=\s*$', stripped) and index + 1 < len(lines):
            next_body, _ = _strip_newline(lines[index + 1])
            next_stripped = _statement_text(next_body)
            if next_stripped.startswith("Или ") or next_stripped.startswith("И "):
                # Check if the assignment line already has (Ложь or (Истина
                if not re.search(r'=\s*\((?:Ложь|Истина)\s*$', stripped):
                    violations.append(Violation(path, index + 1, "boolean-column",
                        "multi-line boolean assignment should start with (Ложь or (Истина"))

    return violations


# ---------------------------------------------------------------------------
# ternary-long
# ---------------------------------------------------------------------------


def _check_ternary_long(path: Path, lines: list[str]) -> list[Violation]:
    """Check that ternary >140 chars is on multiple lines."""
    violations: list[Violation] = []

    for index, line in enumerate(lines):
        body, _ = _strip_newline(line)
        if len(body) > 140 and "?(" in body and body.count(",") >= 2:
            violations.append(Violation(path, index + 1, "ternary-long",
                f"ternary operator on one line exceeds 140 chars ({len(body)}); use multi-line form"))

    return violations


# ---------------------------------------------------------------------------
# call-args-multi
# ---------------------------------------------------------------------------


def _check_call_args_multi(path: Path, lines: list[str]) -> list[Violation]:
    """Check that function calls with 3+ args are on separate lines."""
    violations: list[Violation] = []

    for index, line in enumerate(lines):
        body, _ = _strip_newline(line)
        stripped = _statement_text(body)

        # Check for assignment with function call
        if "(" not in stripped or "=" not in stripped:
            continue

        # Count commas inside the call
        paren_depth = 0
        arg_count = 0
        in_string = False
        i = 0
        while i < len(stripped):
            ch = stripped[i]
            if ch == '"':
                in_string = not in_string
            elif not in_string:
                if ch == "(":
                    paren_depth += 1
                elif ch == ")":
                    paren_depth -= 1
                elif ch == "," and paren_depth > 0:
                    arg_count += 1
            i += 1

        # 3+ args means 2+ commas
        if arg_count >= 2 and len(stripped) > 140:
            violations.append(Violation(path, index + 1, "call-args-multi",
                f"function call with {arg_count + 1} args on one line ({len(stripped)} chars); use multi-line form"))

    return violations

# ---------------------------------------------------------------------------
# inline-condition
# ---------------------------------------------------------------------------


_AND_OR_RE = re.compile(rf"(?<![{_WORD}])(И|Или)(?![{_WORD}])")
_COMPARISON_RE = re.compile(r"<>|<=|>=|=|<|>")


def _condition_text(statement: str) -> str | None:
    """Условие между ключевым словом и Тогда/Цикл; None, если строка не заголовок."""
    for keyword, closer in (("Если ", " Тогда"), ("ИначеЕсли ", " Тогда"), ("Пока ", " Цикл")):
        if statement.startswith(keyword) and statement.rstrip().endswith(closer):
            return statement[len(keyword) : -len(closer)]
    return None


def _check_inline_condition(path: Path, code_lines: list[str]) -> list[Violation]:
    """Сложные условия `Если`/`ИначеЕсли`/`Пока` выносятся в переменную."""
    violations: list[Violation] = []
    for index, body in enumerate(code_lines):
        statement = _statement_text(body).rstrip()
        condition = _condition_text(statement)
        if condition is None:
            continue
        and_or = len(_AND_OR_RE.findall(condition))
        comparisons = len(_COMPARISON_RE.findall(condition))
        if and_or >= 2 or (and_or >= 1 and comparisons >= 2):
            violations.append(
                Violation(
                    path=path,
                    line_number=index + 1,
                    check="inline-condition",
                    message="сложное условие в `Если`/`Пока` — вынеси в переменную с предметным булевым именем",
                )
            )
    return violations


# ---------------------------------------------------------------------------
# block-air
# ---------------------------------------------------------------------------


_STAGE_RE = re.compile(r"^(Возврат|Прервать|Продолжить)(?:\s|;)")


def _body_first_line(code_lines: list[str], open_index: int, close_index: int) -> int | None:
    """Первая строка тела секции; None, если тело пустое."""
    for index in range(open_index + 1, close_index):
        statement = _statement_text(code_lines[index]).rstrip()
        if statement.startswith(("И ", "Или ")) and statement.endswith("Тогда"):
            continue
        return index
    return None


def _close_block_air_section(
    section: dict,
    close_index: int,
    code_lines: list[str],
    path: Path,
    violations: list[Violation],
) -> None:
    if section["code_count"] < 2:
        return
    first = _body_first_line(code_lines, section["open"], close_index)
    if first is None:
        return
    if _statement_text(code_lines[first]).rstrip() != "":
        violations.append(
            Violation(
                path,
                first + 1,
                "block-air",
                "после открывающей строки многострочного блока нужна пустая строка",
            )
        )
    if _statement_text(code_lines[close_index - 1]).rstrip() != "":
        violations.append(
            Violation(
                path,
                close_index + 1,
                "block-air",
                "перед закрывающей строкой многострочного блока нужна пустая строка",
            )
        )


def _check_block_air(path: Path, code_lines: list[str]) -> list[Violation]:
    """Воздух в многострочных блоках: пустая строка после открывателя,
    перед закрывателем и перед Возврат/Прервать/Продолжить как стадией."""
    violations: list[Violation] = []
    stack: list[dict] = []
    in_method = False
    for index, body in enumerate(code_lines):
        statement = _statement_text(body).rstrip()
        if statement.startswith("#"):
            continue
        if not in_method and _is_method_start(body):
            in_method = True
            stack = []
            continue
        if not in_method:
            continue
        if _is_method_end(body):
            in_method = False
            stack = []
            continue
        if statement.startswith(("КонецЕсли", "КонецЦикла", "КонецПопытки")):
            if stack:
                _close_block_air_section(stack.pop(), index, code_lines, path, violations)
            continue
        if statement.startswith(("ИначеЕсли", "Иначе", "Исключение")):
            if stack:
                _close_block_air_section(stack.pop(), index, code_lines, path, violations)
            stack.append({"open": index, "code_count": 0})
            continue
        if _opens_body(body):
            stack.append({"open": index, "code_count": 0})
            continue
        if statement == "":
            continue
        if _STAGE_RE.match(statement) and stack and index > 0:
            previous = _statement_text(code_lines[index - 1]).rstrip()
            if previous != "" and not _opens_body(code_lines[index - 1]):
                violations.append(
                    Violation(
                        path,
                        index + 1,
                        "block-air",
                        "перед `Возврат`/`Прервать`/`Продолжить` в теле блока нужна пустая строка (граница стадии)",
                    )
                )
        if stack:
            stack[-1]["code_count"] += 1
    return violations


# ---------------------------------------------------------------------------
# invalid-char
# ---------------------------------------------------------------------------


_INVALID_CHARS = {
    0x00A0: "неразрывный пробел (NBSP) -> обычный пробел",
    0x00AD: "мягкий перенос -> убрать",
    0x2010: "дефис -> \"-\"",
    0x2011: "неразрывный дефис -> \"-\"",
    0x2012: "figure dash -> \"-\"",
    0x2013: "короткое тире -> \"-\"",
    0x2014: "длинное тире -> \"-\"",
    0x2015: "horizontal bar -> \"-\"",
    0x2212: "знак минус -> \"-\"",
    0x2024: "одноточечное многоточие -> \"...\"",
    0x2025: "двухточечное многоточие -> \"...\"",
    0x2026: "многоточие -> \"...\"",
    0x2027: "многоточие-разделитель -> \"...\"",
    0xFEFF: "BOM в середине файла -> убрать",
}


def _check_invalid_chars(path: Path, lines: list[str]) -> list[Violation]:
    """«Умная типографика» недопустима в .bsl: bsl-analyzer ругается
    InvalidCharacterInFile (проверено на U+2014, 2026-08-17)."""
    violations: list[Violation] = []
    for index, raw in enumerate(lines):
        body, _ = _strip_newline(raw)
        for ch in body:
            code = ord(ch)
            if code in _INVALID_CHARS:
                violations.append(
                    Violation(
                        path,
                        index + 1,
                        "invalid-char",
                        f"символ U+{code:04X} ({_INVALID_CHARS[code]}) недопустим в .bsl — замени на ASCII",
                    )
                )
    return violations

# ---------------------------------------------------------------------------
# chained-call
# ---------------------------------------------------------------------------

_CHAIN_DOT_RE = re.compile(rf"\)\s*\.\s*[{_WORD}]+\s*\(")
_CHAIN_ARG_RE = re.compile(rf"([{_WORD}]+)\s*\(\s*[^,()]*\.\s*[{_WORD}]+\s*\([^()]*\)\s*\)")
_CONVERT_FUNCS = frozenset({
    "Строка", "Число", "Дата", "Булево", "СокрЛП", "НачалоДня", "КонецДня",
    "Год", "Месяц", "День", "Час", "Минута", "Секунда", "ВРег", "НРег", "СтрДлина",
})


def _check_chained_call(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    """Цепочка `)...Метод(` или вызов объекта аргументом другого вызова.

    Каждый шаг - отдельная строка с именованным промежуточным значением.
    Fluent-API утверждений `ЮТест` исключён явно.
    """
    violations: list[Violation] = []
    in_yutest_chain = False
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        if in_yutest_chain and body.strip().startswith("."):
            # Продолжение цепочки утверждений `ЮТест`: исключение действует на
            # всю цепочку, а не только на строку с её началом.
            continue
        in_yutest_chain = "ЮТест." in body
        if in_yutest_chain:
            continue
        for segment in _spans_of_line(body, line_spans):
            dot_hit = _CHAIN_DOT_RE.search(segment) is not None
            arg_match = _CHAIN_ARG_RE.search(segment)
            arg_hit = bool(arg_match) and arg_match.group(1) not in _CONVERT_FUNCS
            if dot_hit or arg_hit:
                violations.append(
                    Violation(
                        path,
                        index + 1,
                        "chained-call",
                        "цепочка вызовов - разбей на строки с именованными промежуточными значениями",
                    )
                )
                break
    return violations

# ---------------------------------------------------------------------------
# nested-call-arg
# ---------------------------------------------------------------------------

_NCA_HEAD_RE = re.compile(rf"([{_WORD}]+)\s*\(")
_NCA_SKIP_HEADS = frozenset({
    "Если", "ИначеЕсли", "Иначе", "Пока", "Для", "Возврат", "Прервать",
    "Продолжить", "ВызватьИсключение", "Попытка", "Исключение", "КонецЕсли",
    "КонецЦикла", "КонецПопытки", "КонецПроцедуры", "КонецФункции",
    "Процедура", "Функция", "Новый", "Истина", "Ложь", "Неопределено",
    "ЭтотОбъект", "И", "Или", "Не", "Перем", "До", "Из",
})


def _statements_of(code_lines: list[str]) -> list[tuple[int, str]]:
    """Операторы: группы строк от depth 0 до возврата скобок к 0.

    Заголовки процедур, `Если ... Тогда` и директивы формируют отдельные
    группы (скобки сбалансированы в пределах строки). Возвращает
    (строка_начала_1based, склеенный текст кода без литералов).
    """
    statements: list[tuple[int, str]] = []
    parts: list[str] = []
    depth = 0
    start = 0
    for index, line in enumerate(code_lines):
        stripped = line.strip()
        if not stripped:
            continue
        if not parts and statements and stripped.startswith("."):
            # Строка-продолжение fluent-цепочки (`.Метод(...)`): переоткрываем
            # предыдущую инструкцию, чтобы её текст - и маркеры вроде `ЮТест.` -
            # действовал на всю цепочку, а не только на первую строку.
            # В `statements` старт уже 1-based, здесь снова нужен 0-based индекс.
            stored_start, text = statements.pop()
            start = stored_start - 1
            parts = [text, stripped]
        else:
            if not parts:
                start = index
            parts.append(stripped)
        for ch in stripped:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        if depth <= 0:
            depth = 0
            statements.append((start + 1, " ".join(parts)))
            parts = []
    return statements


def _split_top_level_args(text: str) -> list[str]:
    args: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in text:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            args.append("".join(current))
            current = []
            continue
        current.append(ch)
    args.append("".join(current))
    return args


def _arg_span(text: str, open_index: int) -> tuple[int, int] | None:
    """Спан аргументов вызова, открывающейся скобки которой - open_index."""
    depth = 0
    for pos in range(open_index, len(text)):
        if text[pos] == "(":
            depth += 1
        elif text[pos] == ")":
            depth -= 1
            if depth == 0:
                return (open_index + 1, pos)
    return None


def _check_nested_call_arg(path: Path, code_lines: list[str]) -> list[Violation]:
    """Вызов или конструктор аргументом другого вызова в операторе.

    Ловит формы, которые `chained-call` не видит:
    `Метод(Арг, ДругойМетод(...))` и `Метод(Арг, Новый Тип(...))`.
    Конвертеры (`Строка`, `Число`, ...) у внешнего вызова исключены,
    fluent-API утверждений `ЮТест` - тоже.
    """
    violations: list[Violation] = []
    for start_line, statement in _statements_of(code_lines):
        if "ЮТест." in statement:
            continue
        for match in _NCA_HEAD_RE.finditer(statement):
            name = match.group(1)
            if name in _CONVERT_FUNCS or name in _NCA_SKIP_HEADS:
                continue
            open_index = statement.index("(", match.start())
            span = _arg_span(statement, open_index)
            if span is None:
                continue
            nested = False
            for arg in _split_top_level_args(statement[span[0]:span[1]]):
                for inner in _NCA_HEAD_RE.finditer(arg):
                    inner_name = inner.group(1)
                    if inner_name not in _NCA_SKIP_HEADS and inner_name not in _CONVERT_FUNCS:
                        nested = True
                        break
                if nested:
                    break
            if nested:
                violations.append(
                    Violation(
                        path,
                        start_line,
                        "nested-call-arg",
                        "метод инициализируется вложенным методом - вынеси "
                        "аргумент в именованную переменную",
                    )
                )
                break
    return violations


# ---------------------------------------------------------------------------
# omitted-arg
# ---------------------------------------------------------------------------

_OMITTED_HEAD_RE = re.compile(r"\(\s*,")
_OMITTED_TAIL_RE = re.compile(r",\s*\)")


def _check_omitted_arg(path: Path, lines: list[str], spans: list[list[tuple[int, int]]]) -> list[Violation]:
    """Пропущенный аргумент `Метод(, Текст)` / `Метод(Арг, )`.

    `Новый ОписаниеТипов(...)` с пустыми позициями квалификаторов -
    принятая форма, исключена.
    """
    violations: list[Violation] = []
    for index, (raw, line_spans) in enumerate(zip(lines, spans)):
        body, _ = _strip_newline(raw)
        if "ОписаниеТипов" in body:
            continue
        for segment in _spans_of_line(body, line_spans):
            if _OMITTED_HEAD_RE.search(segment) or _OMITTED_TAIL_RE.search(segment):
                violations.append(
                    Violation(
                        path,
                        index + 1,
                        "omitted-arg",
                        "пропущенный аргумент вызова - запиши явно `Неопределено`",
                    )
                )
                break
    return violations


# ---------------------------------------------------------------------------
# named-type-desc
# ---------------------------------------------------------------------------

_TYPE_DESC_HEAD_RE = re.compile(rf"Новый\s+ОписаниеТипов\s*\(")


def _without_comment(body: str) -> str:
    """Строка без хвостового комментария `//` (литералы сохраняются)."""
    in_string = False
    pos = 0
    while pos < len(body):
        char = body[pos]
        if char == '"':
            if in_string and pos + 1 < len(body) and body[pos + 1] == '"':
                pos += 2
                continue
            in_string = not in_string
        elif char == "/" and not in_string and pos + 1 < len(body) and body[pos + 1] == "/":
            return body[:pos]
        pos += 1
    return body


def _type_desc_args(text: str) -> list[str]:
    """Аргументы всех `Новый ОписаниеТипов(...)` в тексте (со вложенными скобками)."""
    results: list[str] = []
    for match in _TYPE_DESC_HEAD_RE.finditer(text):
        depth = 1
        pos = match.end()
        while pos < len(text) and depth:
            char = text[pos]
            if char == "(":
                depth += 1
            elif char == ")":
                depth -= 1
            pos += 1
        if depth == 0:
            results.append(re.sub(r"\s+", "", text[match.end() : pos - 1]))
    return results


def _check_named_type_desc(path: Path, lines: list[str]) -> list[Violation]:
    """Одинаковый `Новый ОписаниеТипов(...)` с квалификаторами повторяется в методе.

    Простые однословные типы (`"Строка"`, `"Булево"`) допустимы inline;
    повтор схемы с квалификаторами получает именованную переменную или helper.
    """
    violations: list[Violation] = []
    seen: dict[str, int] = {}
    for index, raw in enumerate(lines):
        body, _ = _strip_newline(raw)
        statement = _statement_text(body).rstrip()
        if _is_method_start(statement) or _is_method_end(statement):
            seen = {}
        for args in _type_desc_args(_without_comment(body)):
            if "Квалификатор" not in args:
                continue
            if args in seen:
                violations.append(
                    Violation(
                        path,
                        index + 1,
                        "named-type-desc",
                        "повтор `Новый ОписаниеТипов(...)` с квалификаторами в методе - дай имя переменной или helper",
                    )
                )
            else:
                seen[args] = index
    return violations

# ---------------------------------------------------------------------------
# Драйвер
# ---------------------------------------------------------------------------


def analyze_path(path: Path, checks: set[str] | None = None, fix: bool = False) -> list[Violation]:
    selected = set(CHECK_IDS) if checks is None else set(checks)
    raw = path.read_bytes()
    text, has_bom = _decode(raw)
    lines = text.splitlines(keepends=True)
    spans = _code_spans(lines)
    code_lines = _code_view(lines, spans)

    violations: list[Violation] = []
    if "tab-rhythm" in selected:
        violations.extend(_check_tab_rhythm(path, lines, code_lines))
    if "operator-case" in selected:
        violations.extend(_check_operator_case(path, lines, spans))
    if "empty-ctor-parens" in selected:
        violations.extend(_check_empty_ctor_parens(path, lines, spans))
    if "comma-space" in selected:
        violations.extend(_check_comma_space(path, lines, spans))
    if "struct-ctor-args" in selected:
        violations.extend(_check_struct_ctor_args(path, lines, spans))
    if "if-nesting" in selected:
        violations.extend(_check_if_nesting(path, code_lines))
    if "return-expression" in selected:
        violations.extend(_check_return_expression(path, code_lines))
    if "query-text-format" in selected:
        violations.extend(_check_query_text_format(path, lines))
    if "query-istina" in selected:
        violations.extend(_check_query_istina(path, lines))
    if "boolean-column" in selected:
        violations.extend(_check_boolean_column(path, lines))
    if "ternary-long" in selected:
        violations.extend(_check_ternary_long(path, lines))
    if "call-args-multi" in selected:
        violations.extend(_check_call_args_multi(path, lines))
    if "inline-condition" in selected:
        violations.extend(_check_inline_condition(path, code_lines))
    if "block-air" in selected:
        violations.extend(_check_block_air(path, code_lines))
    if "invalid-char" in selected:
        violations.extend(_check_invalid_chars(path, lines))
    if "chained-call" in selected:
        violations.extend(_check_chained_call(path, lines, spans))
    if "nested-call-arg" in selected:
        violations.extend(_check_nested_call_arg(path, code_lines))
    if "omitted-arg" in selected:
        violations.extend(_check_omitted_arg(path, lines, spans))
    if "named-type-desc" in selected:
        violations.extend(_check_named_type_desc(path, lines))

    if fix:
        changed = False
        if "tab-rhythm" in selected:
            changed |= _fix_tab_rhythm(lines, code_lines)
        if selected & {"operator-case", "empty-ctor-parens", "comma-space"}:
            for index, (raw_line, line_spans) in enumerate(zip(lines, spans)):
                body, newline = _strip_newline(raw_line)
                rebuilt: list[str] = []
                pos = 0
                for start, end in line_spans:
                    rebuilt.append(body[pos:start])
                    segment = body[start:end]
                    if "operator-case" in selected:
                        segment = _fix_operator_case_segment(segment)
                    if "empty-ctor-parens" in selected:
                        segment = _fix_empty_ctor_parens_segment(segment)
                    if "comma-space" in selected:
                        segment = _fix_comma_space_segment(segment)
                    rebuilt.append(segment)
                    pos = end
                rebuilt.append(body[pos:])
                fixed_body = "".join(rebuilt)
                if fixed_body != body:
                    lines[index] = fixed_body + newline
                    changed = True
        if changed:
            output = "".join(lines)
            path.write_bytes(("\ufeff" if has_bom else "").encode("utf-8") + output.encode("utf-8"))

    violations.sort(key=lambda v: (v.line_number, v.check))
    return violations


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Проверяет детерминированные правила стиля 1c-bsl-code-style.",
    )
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--checks",
        default=",".join(CHECK_IDS),
        help="Список check-id через запятую; по умолчанию все.",
    )
    parser.add_argument("--fix", action="store_true", help="Исправить автоматически исправимые нарушения.")
    args = parser.parse_args(argv)

    selected = {item.strip() for item in args.checks.split(",") if item.strip()}
    unknown = selected - set(CHECK_IDS)
    if unknown:
        parser.error(f"неизвестные check-id: {', '.join(sorted(unknown))}")

    all_violations: list[Violation] = []
    for path in args.paths:
        all_violations.extend(analyze_path(path, checks=selected, fix=args.fix))
    all_violations.sort(key=lambda v: (str(v.path), v.line_number, v.check))

    for violation in all_violations:
        print(f"{violation.path}:{violation.line_number}: [{violation.check}] {violation.message}")

    if not all_violations:
        print("bsl_style_check_ok")
        return 0

    if args.fix:
        fixed = sum(1 for violation in all_violations if violation.check in FIXABLE)
        print(f"bsl_style_violations={len(all_violations)} fixed={fixed}")
        return 0 if fixed == len(all_violations) else 1

    print(f"bsl_style_violations={len(all_violations)}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
