/**
 * Тест хука unica-gate: обработчики вызываются напрямую с поддельным событием,
 * без сессии и без обращения к базе.
 *
 * Запуск: bun run tests/unica-gate.test.ts
 *
 * Фикстуры — временные деревья со своим v8project.yaml: тест не зависит ни от
 * одного реального проекта.
 */
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import unicaGate from "../extensions/unica-gate.ts";
import { releaseLocksForPid } from "../lib/ib-lock.ts";

type Handler = (event: unknown, ctx: unknown) => Promise<unknown>;
const handlers = new Map<string, Handler>();
unicaGate({ on: (event: string, handler: Handler) => handlers.set(event, handler) } as never);

const XD = "xd://mcp__unica_unica_unica_runtime_execute";
const SERVER = `Srvr="srv";Ref="base";`;
const EXT = "Расширение";

/** Дерево-фикстура: конфигурация main плюс одно расширение. */
function tree(name: string): string {
	const dir = join(mkdtempSync(join(tmpdir(), "unica-gate-")), name);
	mkdirSync(dir, { recursive: true });
	writeFileSync(
		join(dir, "v8project.yaml"),
		[
			"infobase:",
			`  connection: '${SERVER}'`,
			"source-set:",
			"  - name: main",
			"    type: CONFIGURATION",
			"    path: 'src/cf'",
			`  - name: ${EXT}`,
			"    type: EXTENSION",
			`    path: 'src/cfe/${EXT}'`,
			"",
		].join("\n"),
	);
	return dir;
}

const MAIN = tree("main");
const SECOND = tree("second");

let failed = 0;
function check(name: string, actual: unknown, expected: unknown): void {
	const ok = JSON.stringify(actual) === JSON.stringify(expected);
	if (!ok) failed++;
	console.log(`${ok ? "✓" : "✗"} ${name}${ok ? "" : `\n    получено: ${JSON.stringify(actual)}`}`);
}

/**
 * Прогоняет write в xd://mcp__unica_*. Дерево задаётся и в аргументах, и в
 * каталоге сессии — как в жизни: хук доверяет `args.cwd`.
 */
async function callUnica(args: Record<string, unknown>, at = MAIN): Promise<Record<string, unknown> | undefined> {
	const handler = handlers.get("tool_call");
	if (!handler) throw new Error("хук не зарегистрировал tool_call");
	return (await handler(
		{ toolName: "write", input: { path: XD, content: JSON.stringify({ cwd: at, ...args }) } },
		{ cwd: at },
	)) as Record<string, unknown> | undefined;
}

const reason = (res: Record<string, unknown> | undefined): string => (res?.block ? String(res.reason) : "");

check("хук зарегистрировал tool_call", typeof handlers.get("tool_call"), "function");
check("хук зарегистрировал tool_result", typeof handlers.get("tool_result"), "function");
check("хук зарегистрировал session_shutdown", typeof handlers.get("session_shutdown"), "function");

// 1. Сборка расширения без fullRebuild — блок
const extBlock = await callUnica({ operation: "build", sourceSet: EXT, fullRebuild: false });
check("сборка расширения без fullRebuild заблокирована", extBlock?.block, true);
check("в причине названо расширение", reason(extBlock).includes(EXT), true);

// 2. Полная пересборка основной конфигурации — блок
check(
	"полная пересборка main заблокирована",
	(await callUnica({ operation: "build", sourceSet: "main", fullRebuild: true }))?.block,
	true,
);

// 3. Замок на базу: первое дерево работает, второе получает отказ
releaseLocksForPid(process.pid);
check("первое дерево пропущено (замок взят)", await callUnica({ operation: "load", sourceSet: "main" }), undefined);
const second = await callUnica({ operation: "load", sourceSet: "main" }, SECOND);
check("второе дерево заблокировано на той же базе", second?.block, true);
check("в причине назван держатель", reason(second).includes(MAIN), true);

// 4. Освобождение по tool_result открывает базу второму дереву
await handlers.get("tool_result")!(
	{ toolName: "write", input: { path: XD, content: JSON.stringify({ cwd: MAIN, operation: "load" }) } },
	{ cwd: MAIN },
);
check(
	"после освобождения второе дерево пропущено",
	await callUnica({ operation: "load", sourceSet: "main" }, SECOND),
	undefined,
);

// 5. Чтение базы замок не берёт
releaseLocksForPid(process.pid);
check("dump пропущен", await callUnica({ operation: "dump", sourceSet: "main" }), undefined);

releaseLocksForPid(process.pid);
rmSync(MAIN, { recursive: true, force: true });
rmSync(SECOND, { recursive: true, force: true });
console.log(failed === 0 ? "\nвсе проверки прошли" : `\nпровалено: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
