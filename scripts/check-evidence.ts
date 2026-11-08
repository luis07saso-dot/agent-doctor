// npm run check-evidence -- [--skills-only] [--run <dir>] <session.json>
//
// Proof from a saved TrueForge session (not from the model's text) that the agent really used
// TrueForge skills (B2) and dynamic subagents (B1). Exits non-zero unless:
//   - "Sandbox initialization failed" appears nowhere (an unpushed skill sha fails silently otherwise)
//   - every root turn (one per task) has ≥ 1 successful exec read of skills/<name>/SKILL.md
//     for each skill under agent/skills/
//   - unless --skills-only: every root turn has ≥ 1 create_sub_agent call
//   - with --run <dir> (counted-run gate): root turns = tasks in evals/tasks/, every turn "done",
//     every <dir>/results.json entry parsed: true
// Root turns that died on a model provider error (429/5xx, see lib.ts isTransientModelError) and
// were re-run are skipped in every check above; with --run they must match results.json `retried`
// exactly (no unlisted dead turn, no listed turn that isn't one).
// Prints: turns N · create_sub_agent X · threads Y · skill reads {a: n, b: m} · sandbox failures 0 · model-error retries R

import { existsSync, readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { flag, isTransientModelError, loadTasks, option, readAgent, type SessionExport } from "./lib.ts";

const SANDBOX_FAIL = "Sandbox initialization failed";

export interface EvidenceOptions {
  skillsOnly?: boolean;
  /** Counted-run gate: the run dir whose results.json must be all parsed. */
  runDir?: string;
  /** Skill names to require; default = every skill under agent/skills/. */
  skills?: string[];
}

export interface Evidence {
  ok: boolean;
  reasons: string[];
  line: string;
}

type Ev = { type: string; threadId?: string | null; [k: string]: any };

function skillRead(content: string, name: string): boolean {
  try {
    const r = JSON.parse(content);
    return r?.success === true && typeof r?.response?.result === "string" && r.response.result.includes(`name: ${name}`);
  } catch {
    return false;
  }
}

export function checkEvidence(exp: SessionExport, opts: EvidenceOptions = {}): Evidence {
  const skills = opts.skills ?? readAgent().skills.map((s) => s.name);
  const reasons: string[] = [];
  const failures = JSON.stringify(exp).split(SANDBOX_FAIL).length - 1;
  if (failures) reasons.push(`${failures} × "${SANDBOX_FAIL}"`);
  if (!skills.length) reasons.push("no skills under agent/skills/");

  const allRoots = exp.turns.filter((t) => t.previousTurnId == null);
  const deadTurn = (t: (typeof allRoots)[number]) => {
    const st = t.state as { status?: string; message?: string } | undefined;
    return isTransientModelError(st?.status ?? "", st?.message);
  };
  const dead = allRoots.filter(deadTurn);
  const roots = allRoots.filter((t) => !deadTurn(t));

  let results: { task_id: string; parsed: boolean; retried?: { turn_id: string }[] }[] | undefined;
  const resultsFile = opts.runDir ? join(opts.runDir, "results.json") : "";
  if (opts.runDir) {
    if (!existsSync(resultsFile)) reasons.push(`missing ${resultsFile}`);
    else results = JSON.parse(readFileSync(resultsFile, "utf8"));
  }
  if (results) {
    const listed = new Set(results.flatMap((r) => (r.retried ?? []).map((x) => x.turn_id)));
    const deadIds = new Set(dead.map((t) => t.id));
    for (const id of deadIds) if (!listed.has(id)) reasons.push(`turn ${id}: model error, not listed as retried in results.json`);
    for (const id of listed) if (!deadIds.has(id)) reasons.push(`turn ${id}: listed as retried but is not a model-error root turn`);
  }
  let subCalls = 0;
  let threads = 0;
  const reads: Record<string, number> = Object.fromEntries(skills.map((s) => [s, 0]));

  roots.forEach((turn, i) => {
    const events = turn.events as unknown as Ev[];
    const calls = new Map<string, string>(); // tool call id → exec command
    let turnSub = 0;
    const turnReads: Record<string, number> = Object.fromEntries(skills.map((s) => [s, 0]));
    for (const e of events) {
      if (e.type === "model.message") {
        for (const c of e.toolCalls ?? []) {
          const name = c.function?.name;
          if (name === "create_sub_agent" && e.threadId === "main") turnSub++;
          if (name === "exec") {
            let cmd = "";
            try { cmd = String(JSON.parse(c.function.arguments ?? "{}").command ?? ""); } catch { cmd = String(c.function?.arguments ?? ""); }
            calls.set(c.id, cmd);
          }
        }
      }
      if (e.type === "thread.created" && e.agentInfo?.type === "dynamic") threads++;
      if (e.type === "tool.response") {
        const cmd = calls.get(e.toolCallId) ?? "";
        for (const s of skills) if (cmd.includes(`skills/${s}/SKILL.md`) && skillRead(String(e.content ?? ""), s)) turnReads[s]++;
      }
    }
    subCalls += turnSub;
    for (const s of skills) {
      reads[s] += turnReads[s];
      if (!turnReads[s]) reasons.push(`turn ${i + 1}: no successful read of skill ${s}`);
    }
    if (!opts.skillsOnly && !turnSub) reasons.push(`turn ${i + 1}: no create_sub_agent call`);
    if (opts.runDir && turn.state?.status !== "done") reasons.push(`turn ${i + 1}: status ${turn.state?.status}`);
  });

  if (!roots.length) reasons.push("no root turns");
  if (opts.runDir) {
    const tasks = loadTasks().length;
    if (roots.length !== tasks) reasons.push(`root turns ${roots.length} ≠ tasks ${tasks}`);
    if (results) {
      if (results.length !== tasks) reasons.push(`results ${results.length} ≠ tasks ${tasks}`);
      for (const r of results) if (r.parsed !== true) reasons.push(`task ${r.task_id}: reply not parsed`);
    }
  }

  const line =
    `turns ${roots.length} · create_sub_agent ${subCalls} · threads ${threads} · skill reads {` +
    skills.map((s) => `${s}: ${reads[s]}`).join(", ") +
    `} · sandbox failures ${failures} · model-error retries ${dead.length}`;
  return { ok: reasons.length === 0, reasons, line };
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const runDir = option("run");
  const file = process.argv.slice(2).filter((a, i, all) => !a.startsWith("--") && all[i - 1] !== "--run").pop();
  if (!file) {
    console.error("usage: npm run check-evidence -- [--skills-only] [--run <dir>] <session.json>");
    process.exit(2);
  }
  const exp = JSON.parse(readFileSync(resolve(file), "utf8")) as SessionExport;
  const ev = checkEvidence(exp, { skillsOnly: flag("skills-only"), runDir: runDir && resolve(runDir) });
  console.log(ev.line);
  if (!ev.ok) {
    console.error(ev.reasons.map((r) => `  ✗ ${r}`).join("\n"));
    process.exit(1);
  }
  console.log("✓ evidence ok");
}
