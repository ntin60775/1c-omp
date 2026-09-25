/**
 * Тест скрипта xvfb-run-1c.sh: дисплей под прогон назначается динамически.
 *
 * Проверяем главное требование контура: фиксированного `:99` нет, параллельные
 * прогоны получают РАЗНЫЕ дисплеи, дисплей снимается после прогона (чужие
 * Xvfb, живущие на машине, в счётчик не берём — у них нет -displayfd).
 *
 * Запуск: bun run tests/xvfb-run-1c.test.ts
 */
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, readFileSync, rmSync } from "node:fs";
import { join } from "node:path";

const SCRIPT = join(import.meta.dir, "..", "skills", "unica-test-contour", "scripts", "xvfb-run-1c.sh");

let failed = 0;
function check(name: string, actual: unknown, expected: unknown): void {
	if (actual === expected) {
		console.log(`  OK  ${name}`);
	} else {
		console.log(`  FAIL ${name}: got='${actual}' want='${expected}'`);
		failed++;
	}
}

/** Наши Xvfb — только что поднятые обёрткой (ищем -displayfd, не имя дисплея). */
function ownXvfb(): string {
	const res = spawnSync("pgrep", ["-af", "Xvfb"], { encoding: "utf8" });
	return res.stdout
		.split("\n")
		.filter((line) => line.includes("-displayfd"))
		.join("\n");
}

check("скрипт существует и исполняемый", existsSync(SCRIPT), true);

const outDir = `/tmp/xvfb-test-${process.pid}`;
rmSync(outDir, { recursive: true, force: true });
mkdirSync(outDir, { recursive: true });

console.log("=== 1. одиночный прогон ===");
const displayFile = join(outDir, "display.txt");
const single = spawnSync(SCRIPT, ["--display-file", displayFile, "--", "sh", "-c", "echo DISPLAY=$DISPLAY"], {
	encoding: "utf8",
});
check("код возврата 0", single.status, 0);
const display = existsSync(displayFile) ? readFileSync(displayFile, "utf8").trim() : "";
check("display-file записан", /^:[0-9]+$/.test(display), true);
check("команда увидела тот же дисплей", single.stdout.includes(`DISPLAY=${display}`), true);
check("своих Xvfb после прогона не осталось", ownXvfb(), "");

console.log("=== 2. два параллельных прогона ===");
const runOnce = () => {
	const { promise, resolve } = Promise.withResolvers<{ status: number | null; display: string }>();
	const child = spawn(SCRIPT, ["--", "sh", "-c", "echo DISPLAY=$DISPLAY; sleep 1"], {
		stdio: ["ignore", "pipe", "ignore"],
	});
	let stdout = "";
	child.stdout.on("data", (chunk) => (stdout += String(chunk)));
	// завершение процесса — это событие, а не выдержка времени
	child.on("close", (status) =>
		resolve({ status, display: (stdout.match(/DISPLAY=(:[0-9]+)/) ?? [])[1] ?? "" }),
	);
	return promise;
};
const runs = await Promise.all([runOnce(), runOnce()]);
check("оба прогона вышли с 0", runs.every((r) => r.status === 0), true);
check("оба получили дисплей", runs.every((r) => /^:[0-9]+$/.test(r.display)), true);
check("дисплеи разные (параллельные прогоны не мешают)", runs[0].display !== runs[1].display, true);
check("своих Xvfb после прогона не осталось", ownXvfb(), "");

console.log("=== 3. код возврата команды пробрасывается ===");
check("false -> 1", spawnSync(SCRIPT, ["--", "false"], { encoding: "utf8" }).status, 1);
check("exit 7 -> 7", spawnSync(SCRIPT, ["--", "sh", "-c", "exit 7"], { encoding: "utf8" }).status, 7);

console.log("=== 4. отказы окружения ===");
const noHelp = spawnSync(SCRIPT, ["--help"], { encoding: "utf8" });
check("--help -> 0", noHelp.status, 0);
const noCommand = spawnSync(SCRIPT, [], { encoding: "utf8" });
check("без команды -> 2", noCommand.status, 2);
// PATH подменяем целиком — она же отдаёт интерпретатор shebang, поэтому
// скрипт зовём явным bash, как это делает оболочка при `bash <script>`.
const bashBin = spawnSync("command", ["-v", "bash"], { encoding: "utf8", shell: true }).stdout.trim() || "/bin/bash";
const noXvfb = spawnSync(bashBin, [SCRIPT, "--", "true"], {
	encoding: "utf8",
	env: { ...process.env, PATH: "/nonexistent" },
});
check("нет Xvfb в PATH -> 2", noXvfb.status, 2);

console.log("=== 5. контрольный кадр ===");
const shotDir = join(outDir, "frames");
const shot = spawnSync(SCRIPT, ["--screenshot-at", "1", "--screenshot-dir", shotDir, "--", "sh", "-c", "sleep 2"], {
	encoding: "utf8",
	timeout: 30000,
});
check("прогон с кадром -> 0", shot.status, 0);
check("файл кадра создан", existsSync(join(shotDir, "frame-1s.png")), true);
check("своих Xvfb после прогона не осталось", ownXvfb(), "");

console.log("=== 6. обрыв сессии (SIGHUP) не оставляет ни дисплей, ни клиента ===");
// Сценарий из поля: сессия-родитель закрывается, пока идёт прогон. Без
// ловушки HUP bash выходит, минуя EXIT-трюк, и Xvfb утекает; плюс сам прогон
// (и его тест-клиент — внук раннера) гасится поддеревом процессов.
// Ждём событий, а не выдержек: строка на stderr — признак того, что Xvfb уже
// поднят, close — признак того, что обёртка доработала.
const GHOST = "137"; // нестандартная длительность = уникальная метка нашего внучка
const hung = spawn(SCRIPT, ["--", "sh", "-c", `sleep ${GHOST}`], {
	stdio: ["ignore", "pipe", "pipe"],
});
const { promise: readyPromise, resolve: markReady } = Promise.withResolvers<void>();
let hungStderr = "";
hung.stderr!.on("data", (chunk: Buffer) => {
	hungStderr += String(chunk);
	if (hungStderr.includes("[xvfb] DISPLAY=")) markReady();
});
await readyPromise;
check("Xvfb поднят во время прогона", ownXvfb().includes("-displayfd"), true);
const childAliveBefore = spawnSync("pgrep", ["-af", `sleep ${GHOST}`], { encoding: "utf8" }).stdout.trim();
check("прогон (и его внук) запущены", childAliveBefore.includes(`sleep ${GHOST}`), true);
const { promise: closedPromise, resolve: markClosed } = Promise.withResolvers<number | null>();
hung.on("close", (code) => markClosed(code));
hung.kill("SIGHUP");
await closedPromise;
check("после SIGHUP своих Xvfb нет", ownXvfb(), "");
check("процессы прогона не остались сиротами", spawnSync("pgrep", ["-af", `sleep ${GHOST}`], { encoding: "utf8" }).stdout.trim(), "");

rmSync(outDir, { recursive: true, force: true });
console.log(failed === 0 ? "\nвсе проверки прошли" : `\nпровалено: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
