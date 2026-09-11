/**
 * retry-gate.ts — дисциплина ретраев: третий идентичный повтор упавшей
 * команды блокируется.
 *
 * Отслеживает команды bash и их результаты. После двух подряд ошибок
 * одной и той же команды третий идентичный вызов блокируется с
 * требованием диагностики (причина C постмортема тикета 09, факап #11:
 * 3–4 идентичных ретрая exit 137 до диагностики).
 *
 * Журнал: ~/.omp/logs/rule-audit.jsonl (rule: "retry-discipline").
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
				rule: "retry-discipline",
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

// ── состояние: команда → подряд идущие ошибки ────────────────────────────────

const failCounts: Record<string, number> = {};

// ── hook ─────────────────────────────────────────────────────────────────────

export default function retryGate(pi: HookAPI): void {
	// считаем подряд идущие ошибки по каждой команде
	pi.on("tool_result", async (event) => {
		if (event.toolName !== "bash") return;
		const cmd = String(
			(event.input as Record<string, unknown> | undefined)?.command ?? "",
		);
		if (!cmd) return;
		if (event.isError) {
			failCounts[cmd] = (failCounts[cmd] ?? 0) + 1;
		} else {
			delete failCounts[cmd];
		}
	});

	// блокируем третий идентичный повтор после двух ошибок подряд
	pi.on("tool_call", async (event) => {
		if (event.toolName !== "bash") return;
		const input = event.input;
		if (typeof input !== "object" || input === null) return;
		const cmd = String((input as Record<string, unknown>).command ?? "");
		if (!cmd) return;
		if ((failCounts[cmd] ?? 0) < 2) return;

		audit(cmd, `третий идентичный повтор после ${failCounts[cmd]} ошибок подряд`);
		return {
			block: true,
			reason: [
				`Третий идентичный повтор упавшей команды заблокирован (retry-discipline).`,
				``,
				`Команда уже падала ${failCounts[cmd]} раза подряд. Повтор без изменения условий запрещён.`,
				``,
				`Дальше — развилка:`,
				`  1. Диагностика: прочитать вывод ошибки целиком, сформулировать гипотезу.`,
				`  2. Смена условий: другое дерево/инструмент/путь, исправить окружение.`,
				`  3. Эскалация: сообщить пользователю с фактами (команда, вывод, что пробовал).`,
				``,
				`См. правило .omp/rules/retry-discipline.md и постмортем тикета 09 (#11).`,
			].join("\n"),
		};
	});
}
