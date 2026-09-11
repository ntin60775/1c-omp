/**
 * unica-gate.ts — детерминированный блок прямого редактирования исходников 1С.
 *
 * Перехватывает edit / write / bash на путях src/{cf,cfe,epf,erf} и
 * tests/{cfe,epf}, принуждая использовать Unica MCP. Блокировка fail-closed;
 * единственный обход для edit/write — явный allowlist эскалаций
 * .omp/unica-gate-escalations.txt (одна строка = путь исходника относительно
 * корня; применяется, когда unica.code.patch не выражает изменение, например
 * комментарий вне тела метода). Каждая разрешённая эскалация пишется в журнал.
 *
 * Журнал: ~/.omp/logs/rule-audit.jsonl (rule: "unica-source-gate").
 */
import type { HookAPI } from "@oh-my-pi/pi-coding-agent/extensibility/hooks";
import { homedir } from "node:os";
import { appendFileSync, existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

// ── журнал ───────────────────────────────────────────────────────────────────

const LOG_DIR = join(homedir(), ".omp", "logs");
const AUDIT_LOG = join(LOG_DIR, "rule-audit.jsonl");

function audit(action: string, reason: string, decision = "blocked"): void {
	try {
		mkdirSync(LOG_DIR, { recursive: true });
		const entry = JSON.stringify({
			rule: "unica-source-gate",
			action,
			decision,
			reason,
			timestamp: new Date().toISOString(),
		});
		appendFileSync(AUDIT_LOG, entry + "\n");
	} catch {
		// best-effort
	}
}

// ── маршрутизация ────────────────────────────────────────────────────────────

/** Каталоги исходников 1С, редактируемые только через Unica. */
const SOURCE_PREFIXES = [
	"src/cf/",
	"src/cfe/",
	"src/epf/",
	"src/erf/",
	"tests/cfe/",
	"tests/epf/",
];

/**
 * Нормализует путь к виду "src/cfe/..." (относительно корня дерева) и
 * возвращает [rel, кореньДерева]. Работает и для абсолютных путей git-ворктри,
 * где cwd сессии — основное дерево. null — путь не является исходником 1С.
 */
function normalizeSourcePath(filePath: string, cwd: string): [string, string] | null {
	const abs = isAbsolute(filePath) ? resolve(filePath) : resolve(cwd, filePath);
	if (abs.startsWith(cwd + "/")) {
		const rel = abs.slice(cwd.length + 1);
		if (SOURCE_PREFIXES.some((p) => rel.startsWith(p))) return [rel, cwd];
	}
	for (const p of SOURCE_PREFIXES) {
		const idx = abs.indexOf("/" + p);
		if (idx >= 0) return [abs.slice(idx + 1), abs.slice(0, idx)];
	}
	return null;
}

function isAgentsDoc(rel: string): boolean {
	return rel.endsWith("/AGENTS.md") || rel === "AGENTS.md";
}


// ── эскалации: allowlist прямой правки ───────────────────────────────────────

const ESCALATION_FILE = ".omp/unica-gate-escalations.txt";

/**
 * Строки allowlist'а эскалаций для дерева targetRoot (пустой список, если
 * файла нет). Файл ищется в целевом дереве (ворктри со своей веткой), с
 * откатом на дерево сессии — эскалация не разрешает правку в чужом дереве
 * по записи, заведённой для своего.
 */
function escalationEntries(targetRoot: string, sessionCwd: string): string[] {
	for (const root of [targetRoot, sessionCwd]) {
		const p = join(root, ESCALATION_FILE);
		if (!existsSync(p)) continue;
		try {
			return readFileSync(p, "utf8")
				.split(/\r?\n/)
				.map((l) => l.trim())
				.filter((l) => l && !l.startsWith("#"));
		} catch {
			return [];
		}
	}
	return [];
}

/** Подсказка: какой инструмент Unica использовать для данного файла. */
function suggestUnicaTool(filePath: string): string {
	const lower = filePath.toLowerCase();
	if (lower.endsWith(".bsl")) {
		return "unica.code.patch";
	}
	if (lower.includes("/forms/") && lower.endsWith(".xml")) {
		return "unica.form.edit / unica.form.compile";
	}
	if (lower.endsWith("configuration.xml")) {
		return "unica.cf.edit";
	}
	if (lower.includes("/roles/") && lower.endsWith(".xml")) {
		return "unica.role.edit / unica.role.compile";
	}
	if (lower.includes("/datacompositionschemas/") && lower.endsWith(".xml")) {
		return "unica.dcs.edit / unica.dcs.compile";
	}
	if (lower.includes("/templates/") && lower.endsWith(".xml")) {
		return "unica.mxl.compile / unica.mxl.decompile";
	}
	if (lower.includes("/subsystems/") && lower.endsWith(".xml")) {
		return "unica.subsystem.edit / unica.subsystem.compile";
	}
	if (lower.includes("/commandinterfaces/") && lower.endsWith(".xml")) {
		return "unica.interface.edit";
	}
	if (lower.includes("/xdtopackages/") && lower.endsWith(".xml")) {
		return "unica.xdto.edit";
	}
	return "unica.meta.edit / unica.meta.add (или unica.cfe.borrow для расширений)";
}

function blockMessage(filePath: string, suggestion: string): string {
	return [
		`Прямое редактирование исходников 1С заблокировано (unica-source-gate).`,
		``,
		`Файл: ${filePath}`,
		`Используй: ${suggestion}`,
		``,
		`Маршрутизация:`,
		`  .bsl модуль         -> unica.code.patch`,
		`  Form.xml            -> unica.form.edit / unica.form.compile`,
		`  Configuration.xml   -> unica.cf.edit`,
		`  метаданные (XML)    -> unica.meta.edit / unica.meta.add`,
		`  Role.xml            -> unica.role.edit / unica.role.compile`,
		`  СКД Template.xml    -> unica.dcs.edit / unica.dcs.compile`,
		`  MXL Template.xml    -> unica.mxl.compile`,
		`  Subsystem.xml       -> unica.subsystem.edit`,
		`  CommandInterface    -> unica.interface.edit`,
		`  XDTO                -> unica.xdto.edit`,
		``,
		`Все вызовы Unica требуют cwd корня проекта.`,
	].join("\n");
}

// ── извлечение путей ─────────────────────────────────────────────────────────

function extractPathsFromEdit(input: Record<string, unknown>): string[] {
	const text = String(input.input ?? "");
	const paths: string[] = [];
	const re = /^\[([^\]#]+)#[0-9A-Fa-f]{4}\]/gm;
	let m: RegExpExecArray | null;
	while ((m = re.exec(text)) !== null) {
		paths.push(m[1]);
	}
	return paths;
}

function extractPathsFromWrite(input: Record<string, unknown>): string[] {
	const p = String(input.path ?? "");
	if (p.startsWith("xd://")) {
		// Device/MCP invocation — check ast_edit specially
		if (p === "xd://ast_edit") {
			try {
				const content = JSON.parse(String(input.content ?? "{}"));
				if (Array.isArray(content.paths)) {
					return content.paths.map(String);
				}
			} catch {
				// unparseable — skip
			}
		}
		return [];
	}
	return p ? [p] : [];
}

// ── bash: проверка записи в исходники ────────────────────────────────────────

const SED_INPLACE_RE = /sed\s+(-[a-zA-Z]*i[a-zA-Z]*|--in-place)/;
const REDIRECT_RE = />>?\s*([^\s;|&]+)/g;

function bashWritesToSource(cmd: string, cwd: string): string | null {
	// sed -i на исходниках
	if (SED_INPLACE_RE.test(cmd)) {
		for (const prefix of SOURCE_PREFIXES) {
			if (cmd.includes(prefix)) return prefix;
		}
	}
	// перенаправление вывода в исходники
	let m: RegExpExecArray | null;
	const re = new RegExp(REDIRECT_RE.source, "g");
	while ((m = re.exec(cmd)) !== null) {
		const target = m[1];
		const norm = normalizeSourcePath(target, cwd);
		// AGENTS.md — документация, не исходник 1С (как в edit/write-ветке)
		if (norm && !isAgentsDoc(norm[0])) return target;
	}
	return null;
}

// ── расширения: только полная загрузка ──────────────────────────────────────

/** Кэш разбора v8project.yaml по каталогу проекта. */
const extensionSourceSetsCache = new Map<string, Set<string>>();

/**
 * Source-set'ы типа EXTENSION из v8project.yaml проекта.
 * Читаются из конфига, а не зашиты в код: у каждого проекта свой состав
 * расширений, и хук не должен знать имена чужих объектов.
 */
function extensionSourceSets(cwd: string): Set<string> {
	const cached = extensionSourceSetsCache.get(cwd);
	if (cached) return cached;

	const found = new Set<string>();
	try {
		const raw = readFileSync(join(cwd, "v8project.yaml"), "utf8");
		let inSourceSet = false;
		let current: string | null = null;
		for (const line of raw.split(/\r?\n/)) {
			if (/^\S/.test(line)) {
				// ключ верхнего уровня — определяем, идёт ли блок source-set
				inSourceSet = /^source-set\s*:/.test(line);
				current = null;
				continue;
			}
			if (!inSourceSet) continue;
			const name = /^\s*-\s*name:\s*(.+?)\s*$/.exec(line);
			if (name) {
				current = name[1].replace(/^['"]|['"]$/g, "");
				continue;
			}
			const type = /^\s*type:\s*(.+?)\s*$/.exec(line);
			if (type && current) {
				if (type[1].replace(/^['"]|['"]$/g, "").toUpperCase() === "EXTENSION") found.add(current);
				current = null;
			}
		}
	} catch {
		// конфига нет или он нечитаем — считаем, что расширения не объявлены
	}
	extensionSourceSetsCache.set(cwd, found);
	return found;
}

/** Пути xd://, через которые вызываются build-операции Unica. */
const UNICA_BUILD_XD_PATHS = [
	"xd://mcp__unica_unica_unica_runtime_execute",
	"xd://mcp__unica_unica_unica_runtime_job_start",
	"xd://mcp__unica_unica_unica_build_load",
];

/**
 * Проверяет, является ли вызов Unica сборкой расширения без fullRebuild.
 * Возвращает имя source-set'а или null.
 */
function extensionBuildWithoutFullRebuild(
	xdPath: string,
	content: string,
	cwd: string,
): string | null {
	if (!UNICA_BUILD_XD_PATHS.some((p) => xdPath.startsWith(p))) return null;
	try {
		const args = JSON.parse(content);
		// unica.runtime.execute / job.start: operation === "build"
		// unica.build.load: нет поля operation, но есть sourceSet
		const isBuild =
			args.operation === "build" || xdPath.includes("build_load");
		if (!isBuild) return null;
		const sourceSet = String(args.sourceSet ?? "");
		if (!extensionSourceSets(cwd).has(sourceSet)) return null;
		if (args.fullRebuild === true) return null;
		return sourceSet;
	} catch {
		return null;
	}
}

/**
 * Проверяет, является ли вызов Unica сборкой основной конфигурации
 * с fullRebuild (запрещено — слишком долго).
 * Возвращает имя source-set'а или null.
 */
function mainBuildWithFullRebuild(
	xdPath: string,
	content: string,
): string | null {
	if (!UNICA_BUILD_XD_PATHS.some((p) => xdPath.startsWith(p))) return null;
	try {
		const args = JSON.parse(content);
		const isBuild =
			args.operation === "build" || xdPath.includes("build_load");
		if (!isBuild) return null;
		const sourceSet = String(args.sourceSet ?? "");
		if (sourceSet !== "main") return null;
		if (args.fullRebuild !== true) return null;
		return sourceSet;
	} catch {
		return null;
	}
}

// ── hook ─────────────────────────────────────────────────────────────────────

// ── ворктри: проверка инициализации воркспейса ──────────────────────────────

/**
 * Проверяет, является ли каталог git-ворктри (файл .git вместо директории).
 */
function isWorktree(dir: string): boolean {
	const gitPath = join(dir, ".git");
	if (!existsSync(gitPath)) return false;
	return statSync(gitPath).isFile();
}

/**
 * Проверяет инициализацию воркспейса Unica и тестового окружения в ворктри.
 * Возвращает список отсутствующих элементов или пустой массив.
 */
function missingWorktreeWorkspace(dir: string): string[] {
	const missing: string[] = [];
	if (!existsSync(join(dir, "v8project.local.yaml"))) {
		missing.push("v8project.local.yaml");
	}
	if (!existsSync(join(dir, "build", "tools"))) {
		missing.push("build/tools/ (Vanessa/YAxUnit артефакты)");
	}
	return missing;
}

export default function unicaGate(pi: HookAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		const tool = event.toolName;
		const input = event.input;
		if (typeof input !== "object" || input === null) return;
		const inp = input as Record<string, unknown>;

		// ── write на xd://mcp__unica_*: проверка сборки расширений ──
		if (tool === "write") {
			const xdPath = String(inp.path ?? "");
			if (xdPath.startsWith("xd://mcp__unica_unica_unica_")) {
				const content = String(inp.content ?? "");

				// ── ворктри: проверка инициализации воркспейса ──
				let callCwd = ctx.cwd;
				try {
					const args = JSON.parse(content);
					callCwd = String(args.cwd ?? ctx.cwd);
					if (isWorktree(callCwd)) {
						const missing = missingWorktreeWorkspace(callCwd);
						if (missing.length > 0) {
							audit(
								`unica в ворктри ${callCwd}`,
								`воркспейс не инициализирован: ${missing.join(", ")}`,
							);
							return {
								block: true,
								reason: [
									`Ворктри не инициализирован для Unica (worktree-env).`,
									``,
									`Отсутствует: ${missing.join(", ")}`,
									``,
									`Инициализируй воркспейс одним скриптом:`,
									`  tasks/init-worktree.sh ${callCwd}`,
									``,
									`Скрипт копирует из основного дерева:`,
									`  - v8project.local.yaml (креды ИБ, платформа)`,
									`  - build/tools/ (Vanessa, YAxUnit артефакты)`,
									`  - build/hash-storages/ (инкрементальное состояние)`,
									``,
									`Затем проверь: unica.project.status { "cwd": "${callCwd}" }`,
									`Симлинки НЕ использовать — только реальные копии.`,
								].join("\n"),
							};
						}
					}
				} catch {
					// unparseable content — skip worktree check
				}
				const extName = extensionBuildWithoutFullRebuild(xdPath, content, callCwd);
				if (extName) {
					audit(
						`unica build ${extName}`,
						`сборка расширения без fullRebuild: true`,
					);
					return {
						block: true,
						reason: [
							`Сборка расширения «${extName}» без fullRebuild заблокирована.`,
							``,
							`Частичная/инкрементальная загрузка расширений НЕ работает.`,
							`Добавь "fullRebuild": true в аргументы вызова.`,
						].join("\n"),
					};
				}
				const mainName = mainBuildWithFullRebuild(xdPath, content);
				if (mainName) {
					audit(
						`unica build ${mainName}`,
						`полная пересборка основной конфигурации запрещена`,
					);
					return {
						block: true,
						reason: [
							`Полная пересборка основной конфигурации (main) заблокирована.`,
							``,
							`Основная конфигурация загружается ТОЛЬКО частично (инкрементально).`,
							`Убери "fullRebuild": true из аргументов вызова.`,
						].join("\n"),
					};
				}
			}
		}

		// ── edit / write на исходники ──
		if (tool === "edit" || tool === "write") {
			const paths =
				tool === "edit" ? extractPathsFromEdit(inp) : extractPathsFromWrite(inp);

			for (const filePath of paths) {
				// Изменение самого allowlist'а эскалаций — в журнал: бумажный
				// след появления новой строки обхода.
				const absPath = isAbsolute(filePath) ? resolve(filePath) : resolve(ctx.cwd, filePath);
				if (absPath.endsWith("/" + ESCALATION_FILE)) {
					audit(
						`${tool} ${ESCALATION_FILE}`,
						"изменён allowlist эскалаций — последующие прямые правки исходников будут им разрешены",
						"confirmed",
					);
					continue;
				}
				const norm = normalizeSourcePath(filePath, ctx.cwd);
				if (norm === null) continue;
				const [rel, root] = norm;
				if (isAgentsDoc(rel)) continue;
				if (escalationEntries(root, ctx.cwd).includes(rel)) {
					audit(
						`${tool} ${rel} (дерево ${root})`,
						`эскалация: разрешена прямой правкой (${ESCALATION_FILE})`,
						"confirmed",
					);
					continue;
				}
				const suggestion = suggestUnicaTool(rel);
				audit(`${tool} ${rel}`, `требуется ${suggestion}`);
				return { block: true, reason: blockMessage(rel, suggestion) };
			}
			return;
		}

		// ── bash: sed -i / перенаправления ──
		if (tool === "bash") {
			const cmd = String(inp.command ?? "");
			if (!cmd) return;
			const hit = bashWritesToSource(cmd, ctx.cwd);
			if (hit) {
				audit(`bash -> ${hit}`, `запись в исходники 1С через bash`);
				return {
					block: true,
					reason: [
						`Запись в исходники 1С через bash заблокирована (unica-source-gate).`,
						`Цель: ${hit}`,
						`Используй Unica MCP (см. маршрутизацию в правиле unica-source-gate).`,
					].join("\n"),
				};
			}
		}
	});
}
