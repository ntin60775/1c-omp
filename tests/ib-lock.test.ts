/**
 * Самотест замка на инфобазу. Запуск: bun run tests/ib-lock.test.ts
 *
 * Проверяет то, что ломается молча: на серверной базе ключ замка должен
 * совпадать у двух деревьев (база общая), на файловой — различаться (у каждого
 * дерева своя), а мёртвый или истёкший замок не должен блокировать работу.
 *
 * Фикстуры создаются в временном каталоге: тест не зависит ни от одного
 * реального проекта.
 */
import { existsSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join } from "node:path";
import {
	acquireBaseLock,
	describeHolder,
	lockKey,
	releaseBaseLock,
	releaseLocksForPid,
	resolveInfobaseConnection,
} from "../lib/ib-lock.ts";

const ROOT = mkdtempSync(join(tmpdir(), "ib-lock-"));
const SERVER = `Srvr="srv";Ref="base";`;
const FILE_CONN = "File=build/ib";

/** Дерево-фикстура: файл проекта с заданной строкой подключения. */
function tree(name: string, connection: string, overlay?: string): string {
	const dir = join(ROOT, name);
	mkdirSync(dir, { recursive: true });
	writeFileSync(join(dir, "v8project.yaml"), `infobase:\n  connection: '${connection}'\n`);
	if (overlay !== undefined) {
		writeFileSync(join(dir, "v8project.local.yaml"), `infobase:\n  connection: '${overlay}'\n`);
	}
	return dir;
}

let failed = 0;
function check(name: string, actual: unknown, expected: unknown): void {
	const ok = JSON.stringify(actual) === JSON.stringify(expected);
	if (!ok) failed++;
	console.log(
		`${ok ? "✓" : "✗"} ${name}${ok ? "" : `\n    получено: ${JSON.stringify(actual)}\n    ожидалось: ${JSON.stringify(expected)}`}`,
	);
}

const srvA = tree("srv-a", SERVER);
const srvB = tree("srv-b", SERVER);
const fileA = tree("file-a", FILE_CONN);
const fileB = tree("file-b", FILE_CONN);
const overlayWins = tree("overlay", "Srvr=\"main\";Ref=\"main\";", SERVER);

// 1. Разбор строки подключения
check("строка читается из файла проекта", resolveInfobaseConnection(srvA), SERVER);
check("локальный оверлей перекрывает основной файл", resolveInfobaseConnection(overlayWins), SERVER);

// 2. Ключ: серверная база одна на все деревья
check("серверная база → один ключ на два дерева", lockKey(SERVER, srvA) === lockKey(SERVER, srvB), true);

// 3. Ключ: файловая база у каждого дерева своя
check("файловая база → разные ключи у деревьев", lockKey(FILE_CONN, fileA) === lockKey(FILE_CONN, fileB), false);

// 4. Замок: первое дерево берёт, второе получает отказ с держателем
check("дерево A берёт замок", acquireBaseLock({ tree: srvA, connection: SERVER, operation: "build" }).ok, true);
const second = acquireBaseLock({ tree: srvB, connection: SERVER, operation: "load" });
check("дерево B заблокировано", second.ok, false);
check("держатель описан", second.ok === false && describeHolder(second.holder).includes(srvA), true);
check("дерево A продлевает свой замок", acquireBaseLock({ tree: srvA, connection: SERVER, operation: "load" }).ok, true);

// 5. Освобождение открывает базу второму дереву
releaseBaseLock(srvA, SERVER);
check("после освобождения дерево B берёт замок", acquireBaseLock({ tree: srvB, connection: SERVER, operation: "load" }).ok, true);

// 6. Мёртвый и истёкший замок не блокируют
const path = join(homedir(), ".omp", "state", "1c-ib-locks", `${lockKey(SERVER, srvA)}.json`);
releaseLocksForPid(process.pid);
const stamp = (pid: number, expiresMs: number) =>
	JSON.stringify({
		connection: SERVER,
		tree: srvA,
		pid,
		operation: "load",
		startedAt: new Date().toISOString(),
		expiresAt: new Date(Date.now() + expiresMs).toISOString(),
	});
writeFileSync(path, stamp(999999, 60_000));
check("мёртвый держатель не блокирует", acquireBaseLock({ tree: srvB, connection: SERVER, operation: "build" }).ok, true);
writeFileSync(path, stamp(process.pid, -1000));
check("истёкший замок не блокирует", acquireBaseLock({ tree: srvB, connection: SERVER, operation: "build" }).ok, true);

releaseLocksForPid(process.pid);
check("замки процесса убраны", existsSync(path), false);
rmSync(ROOT, { recursive: true, force: true });

console.log(failed === 0 ? "\nвсе проверки прошли" : `\nпровалено: ${failed}`);
process.exit(failed === 0 ? 0 : 1);
