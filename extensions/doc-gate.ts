/**
 * doc-gate.ts — «сверка перед записью» для 1С-исходников.
 *
 * Блокирует мутирующие вызовы Unica (code.patch, form.compile, meta.add,
 * dcs.compile, runtime build/load и др.), если в текущей сессии не было
 * ни одной сверки с источником (documentation.search, meta.info, dcs.info,
 * code.search, source.read, или read/grep по src/).
 *
 * Закрывает корневую причину A постмортема тикета 09: угадывание имён и
 * механизмов «по памяти» вместо сверки с доступным источником. Все три
 * отказа загрузки и оба провала смоука — один паттерн: строгий конфигуратор
 * использовался как валидатор вместо предварительной сверки в один вызов.
 *
 * Журнал: ~/.omp/logs/rule-audit.jsonl (rule: "doc-before-write").
 */
import type { HookAPI } from "@oh-my-pi/pi-coding-agent/extensibility/hooks";
import { homedir } from "node:os";
import { appendFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

// ── журнал ───────────────────────────────────────────────────────────────────

const LOG_DIR = join(homedir(), ".omp", "logs");
const AUDIT_LOG = join(LOG_DIR, "rule-audit.jsonl");

function audit(action: string, reason: string): void {
	try {
		mkdirSync(LOG_DIR, { recursive: true });
		appendFileSync(
			AUDIT_LOG,
			JSON.stringify({
				rule: "doc-before-write",
				action,
				decision: "blocked",
				reason,
				timestamp: new Date().toISOString(),
			}) + "\n",
		);
	} catch {
		// best-effort
	}
}

// ── сверочные инструменты (read-only Unica, засчитываются как «проверил») ───

const VERIFICATION_XD_PREFIXES = [
	"xd://mcp__unica_unica_unica_documentation_search",
	"xd://mcp__unica_unica_unica_documentation_get",
	"xd://mcp__unica_unica_unica_standards_search",
	"xd://mcp__unica_unica_unica_standards_explain",
	"xd://mcp__unica_unica_unica_meta_info",
	"xd://mcp__unica_unica_unica_dcs_info",
	"xd://mcp__unica_unica_unica_form_info",
	"xd://mcp__unica_unica_unica_cf_info",
	"xd://mcp__unica_unica_unica_cfe_diff",
	"xd://mcp__unica_unica_unica_code_search",
	"xd://mcp__unica_unica_unica_code_definition",
	"xd://mcp__unica_unica_unica_code_outline",
	"xd://mcp__unica_unica_unica_code_graph",
	"xd://mcp__unica_unica_unica_code_diagnostics",
	"xd://mcp__unica_unica_unica_source_read",
	"xd://mcp__unica_unica_unica_source_resources",
	"xd://mcp__unica_unica_unica_source_resolve",
	"xd://mcp__unica_unica_unica_source_locate",
	"xd://mcp__unica_unica_unica_source_children",
	"xd://mcp__unica_unica_unica_role_info",
	"xd://mcp__unica_unica_unica_mxl_info",
	"xd://mcp__unica_unica_unica_mxl_decompile",
	"xd://mcp__unica_unica_unica_subsystem_info",
	"xd://mcp__unica_unica_unica_project_status",
	"xd://mcp__unica_unica_unica_project_map",
];

// ── мутирующие инструменты (требуют предварительной сверки) ─────────────────

const MUTATION_XD_PREFIXES = [
	"xd://mcp__unica_unica_unica_code_patch",
	"xd://mcp__unica_unica_unica_form_compile",
	"xd://mcp__unica_unica_unica_form_edit",
	"xd://mcp__unica_unica_unica_form_add",
	"xd://mcp__unica_unica_unica_form_remove",
	"xd://mcp__unica_unica_unica_meta_add",
	"xd://mcp__unica_unica_unica_meta_edit",
	"xd://mcp__unica_unica_unica_meta_remove",
	"xd://mcp__unica_unica_unica_dcs_compile",
	"xd://mcp__unica_unica_unica_dcs_edit",
	"xd://mcp__unica_unica_unica_mxl_compile",
	"xd://mcp__unica_unica_unica_role_compile",
	"xd://mcp__unica_unica_unica_role_edit",
	"xd://mcp__unica_unica_unica_subsystem_compile",
	"xd://mcp__unica_unica_unica_subsystem_edit",
	"xd://mcp__unica_unica_unica_cf_edit",
	"xd://mcp__unica_unica_unica_cfe_borrow",
	"xd://mcp__unica_unica_unica_cfe_patch_method",
	"xd://mcp__unica_unica_unica_interface_edit",
	"xd://mcp__unica_unica_unica_xdto_edit",
	"xd://mcp__unica_unica_unica_template_add",
	"xd://mcp__unica_unica_unica_template_remove",
	"xd://mcp__unica_unica_unica_help_add",
	"xd://mcp__unica_unica_unica_support_edit",
];

// runtime-операции, где дорогая итерация при неверных именах (build/load).
// dump/make/convert не пишут угаданные имена в исходники — не блокируются.
const GATED_RUNTIME_OPS: Record<string, true> = {
	build: true,
	load: true,
};

// ── состояние сессии ─────────────────────────────────────────────────────────

let verified = false;
/** Сверка для Vanessa-фич: доки или существующие фичи/шаблоны. */
let featureVerified = false;

// ── hook ─────────────────────────────────────────────────────────────────────

export default function docGate(pi: HookAPI): void {
	pi.on("tool_call", async (event, ctx) => {
		const tool = event.toolName;
		const input = event.input;
		if (typeof input !== "object" || input === null) return;
		const inp = input as Record<string, unknown>;

		// ── read/grep по исходникам 1С засчитывается как сверка ──
		if (tool === "read" || tool === "grep") {
			const p = String(inp.path ?? "");
			if (
				p.includes("src/cf/") ||
				p.includes("src/cfe/") ||
				p.includes("src/epf/") ||
				p.includes("src/erf/") ||
				p.includes("tests/cfe/") ||
				p.includes("tests/epf/")
			) {
				verified = true;
			}
			// сверка для Vanessa-фич: доки или существующие фичи/шаблоны
			if (
				p.includes("pr-mex.github.io/vanessa-automation") ||
				p.includes("features/")
			) {
				featureVerified = true;
			}
			return;
		}

		// ── write/edit на *.feature: блокируем без сверки с доками/шаблонами ──
		if (tool === "write" || tool === "edit") {
			// write: путь в поле path; edit: в заголовке [path#TAG] внутри input
			const target =
				tool === "write"
					? String(inp.path ?? "")
					: String(inp.input ?? "").match(/^\[([^\]#]+)#[0-9A-Fa-f]{4}\]/m)?.[1] ?? "";
			if (target.endsWith(".feature") && !featureVerified) {
				audit(target, "создание/правка .feature без сверки с доками Vanessa");
				return {
					block: true,
					reason: [
						`Запись .feature без сверки заблокирована (vanessa-tests).`,
						``,
						`В Unica нет доки по Vanessa. Перед написанием шагов:`,
						`  1. Прочитай существующие фичи: read features/*.feature`,
						`     (шаблоны: «Шаблон фичи.feature», «Шаблон фичи ОФ.feature»)`,
						`  2. Для шагов, которых нет в шаблонах — официальная дока:`,
						`     read https://pr-mex.github.io/vanessa-automation/dev/`,
						``,
						`Не пиши шаги «по памяти» (факап #12 тикета 09).`,
					].join("\n"),
				};
			}
		}

		// ── write на xd://mcp__unica_* ──
		if (tool !== "write") return;
		const xdPath = String(inp.path ?? "");
		if (!xdPath.startsWith("xd://mcp__unica_unica_unica_")) return;

		// сверочный вызов → отмечаем и пропускаем
		if (VERIFICATION_XD_PREFIXES.some((p) => xdPath.startsWith(p))) {
			verified = true;
			return;
		}

		// мутирующий вызов → проверяем
		const isMutationTool = MUTATION_XD_PREFIXES.some((p) =>
			xdPath.startsWith(p),
		);
		const isRuntime =
			xdPath.startsWith("xd://mcp__unica_unica_unica_runtime_execute") ||
			xdPath.startsWith("xd://mcp__unica_unica_unica_runtime_job_start");
		if (!isMutationTool && !isRuntime) return;

		// для runtime блокируем только applied build/load, не dryRun-preview
		if (isRuntime) {
			try {
				const args = JSON.parse(String(inp.content ?? "{}"));
				const op = String(args.operation ?? "");
				if (!(op in GATED_RUNTIME_OPS)) return;
				if (args.dryRun !== false) return;
			} catch {
				return;
			}
		}

		if (verified) return;

		audit(xdPath, "мутация 1С-исходников без предварительной сверки");
		return {
			block: true,
			reason: [
				`Мутация 1С-исходников без предварительной сверки заблокирована (doc-before-write).`,
				``,
				`Перед записью имён/механизмов сверься с доступным источником (один вызов):`,
				`  - unica.documentation.search / standards.search — справка, стандарты`,
				`  - unica.meta.info — метаданные: имена реквизитов, ресурсов регистра`,
				`  - unica.dcs.info / unica.form.info — структура СКД / формы (DataPath)`,
				`  - unica.code.search / code.definition — существующий код, паттерны`,
				`  - unica.source.read — содержимое ресурса`,
				`  - read/grep по src/ — референсные исходники и эталонные формы`,
				``,
				`Ни одна из этих проверок не дорога; дорога каждая итерация загрузки.`,
				`См. постмортем: .scratch/ticket-09-failures.md (причина A).`,
			].join("\n"),
		};
	});
}
