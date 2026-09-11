/**
 * Замок на информационную базу.
 *
 * Серверная база одна на все деревья проекта: отдельную на каждый ворктри не
 * поднять (размер, кластер). Изоляции там быть не может, поэтому единственный
 * достижимый инвариант — «в один момент с базой работает одно дерево».
 *
 * Файловая база изолируется сама: `File=build/ib` — путь относительный, у
 * каждого дерева свой, ключи замка разные, и замок не мешает вообще.
 */
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { isAbsolute, join, resolve } from "node:path";

const STATE_DIR = join(homedir(), ".omp", "state", "1c-ib-locks");
const DEFAULT_TTL_MS = 20 * 60 * 1000;

export interface BaseLock {
	connection: string;
	tree: string;
	pid: number;
	operation: string;
	startedAt: string;
	expiresAt: string;
}

/** Достаёт `infobase.connection` из файла проекта; null, если его там нет. */
function connectionFromFile(file: string): string | null {
	if (!existsSync(file)) return null;
	let inInfobase = false;
	for (const line of readFileSync(file, "utf8").split(/\r?\n/)) {
		if (/^\S/.test(line)) {
			inInfobase = /^infobase\s*:/.test(line);
			continue;
		}
		if (!inInfobase) continue;
		const m = /^\s+connection\s*:\s*(.+?)\s*$/.exec(line);
		if (m) return m[1].replace(/^['"]|['"]$/g, "");
	}
	return null;
}

/**
 * Строка подключения к базе проекта: локальный оверлей перекрывает основной
 * файл, потому что адрес и креды живут именно в нём.
 */
export function resolveInfobaseConnection(tree: string): string | null {
	return (
		connectionFromFile(join(tree, "v8project.local.yaml")) ??
		connectionFromFile(join(tree, "v8project.yaml"))
	);
}

/**
 * Ключ замка. Для файловой базы относительный путь разворачивается от корня
 * дерева — поэтому у каждого дерева свой ключ, а значит и своя база.
 */
export function lockKey(connection: string, tree: string): string {
	let norm = connection.toLowerCase().replace(/\s+/g, "");
	const file = /^file=(.+)$/.exec(norm);
	if (file) {
		norm = `file=${isAbsolute(file[1]) ? file[1] : resolve(tree, file[1])}`;
	}
	return createHash("sha1").update(norm).digest("hex");
}

function lockPath(connection: string, tree: string): string {
	return join(STATE_DIR, `${lockKey(connection, tree)}.json`);
}

function pidAlive(pid: number): boolean {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

/** Замок мёртв: державший процесс умер или истёк срок. */
function isStale(lock: BaseLock): boolean {
	if (!pidAlive(lock.pid)) return true;
	return Date.parse(lock.expiresAt) <= Date.now();
}

function readLock(path: string): BaseLock | null {
	try {
		return JSON.parse(readFileSync(path, "utf8")) as BaseLock;
	} catch {
		return null;
	}
}

/**
 * Берёт замок на базу. Возвращает держателя, если база занята другим живым
 * деревом; свой замок просто продлевается.
 */
export function acquireBaseLock(opts: {
	tree: string;
	connection: string;
	operation: string;
	ttlMs?: number;
}): { ok: true } | { ok: false; holder: BaseLock } {
	const path = lockPath(opts.connection, opts.tree);
	const now = Date.now();
	const existing = readLock(path);
	if (existing && !isStale(existing) && existing.tree !== opts.tree) {
		return { ok: false, holder: existing };
	}
	const lock: BaseLock = {
		connection: opts.connection,
		tree: opts.tree,
		pid: process.pid,
		operation: opts.operation,
		startedAt: existing?.tree === opts.tree ? existing.startedAt : new Date(now).toISOString(),
		expiresAt: new Date(now + (opts.ttlMs ?? DEFAULT_TTL_MS)).toISOString(),
	};
	try {
		mkdirSync(STATE_DIR, { recursive: true });
		writeFileSync(path, JSON.stringify(lock, null, 2));
	} catch {
		// нет доступа к каталогу состояния — из-за этого работу не блокируем
	}
	return { ok: true };
}

/** Отпускает замок, если он наш. */
export function releaseBaseLock(tree: string, connection: string): void {
	const path = lockPath(connection, tree);
	const lock = readLock(path);
	if (lock?.tree === tree && lock.pid === process.pid) {
		try {
			rmSync(path, { force: true });
		} catch {
			// истечёт по TTL
		}
	}
}

/** Отпускает все замки процесса — вызывается на остановке сессии. */
export function releaseLocksForPid(pid: number): void {
	if (!existsSync(STATE_DIR)) return;
	for (const name of readdirSync(STATE_DIR)) {
		if (!name.endsWith(".json")) continue;
		const path = join(STATE_DIR, name);
		if (readLock(path)?.pid === pid) {
			try {
				rmSync(path, { force: true });
			} catch {
				// истечёт по TTL
			}
		}
	}
}

/** Описание держателя для сообщения о блокировке. */
export function describeHolder(lock: BaseLock): string {
	const held = Math.max(0, Math.round((Date.now() - Date.parse(lock.startedAt)) / 60000));
	return `${lock.tree} — операция ${lock.operation}, держит ${held} мин, pid ${lock.pid}`;
}
