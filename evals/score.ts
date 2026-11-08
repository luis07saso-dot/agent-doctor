// The scorer. Deterministic: same reply in, same number out. Higher is better.
// Don't change it (or evals/tasks/) after run 1: every run must be scored the same way.
//
//   npm run score -- runs/run-01     re-score a saved run from its results.json
//   npm run score -- --selftest      check the scorer on perfect, empty and noisy answers
//
// Per task:  points = caught - 0.5 * noise   (floored at 0), divided by the number of expected issues → 0..1
//   caught = expected issues the agent found: same category, line within ±1
//   noise  = findings that match no expected issue (including duplicates)
// Run score = 100 × the mean task score → 0..100.
// A task "passes" when every expected issue is caught with zero noise.

import { readdirSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

export const LINE_TOLERANCE = 1;
export const NOISE_PENALTY = 0.5;

export interface Expected {
  line: number;
  categories: string[];
  why: string;
}
export interface ScoredTask {
  id: string;
  title: string;
  holdout?: boolean;
  expected: Expected[];
}
export interface Finding {
  line: number;
  category: string;
  comment?: string;
}
export interface TaskScore {
  task_id: string;
  holdout: boolean;
  score: number; // 0..1
  passed: boolean;
  parsed: boolean;
  caught: Expected[];
  missed: Expected[];
  noise: Finding[];
}

/** The findings from the agent's reply: the last ```json block, or the whole reply if it is bare JSON. */
export function parseFindings(reply: string): Finding[] | null {
  const blocks = [...reply.matchAll(/```json\s*\n([\s\S]*?)```/g)].map((m) => m[1]);
  const candidates = blocks.length ? [blocks[blocks.length - 1]] : [reply];
  for (const c of candidates) {
    try {
      const obj = JSON.parse(c.trim());
      if (!obj || !Array.isArray(obj.findings)) return null;
      return obj.findings
        .filter((f: unknown) => f && typeof f === "object")
        .map((f: Record<string, unknown>) => ({
          line: Number(f.line),
          category: String(f.category ?? "").toLowerCase().trim(),
          comment: typeof f.comment === "string" ? f.comment : undefined,
        }));
    } catch {
      return null;
    }
  }
  return null;
}

export function scoreTask(task: ScoredTask, reply: string): TaskScore {
  const findings = parseFindings(reply);
  const base = { task_id: task.id, holdout: !!task.holdout };
  if (findings === null) {
    return { ...base, score: 0, passed: false, parsed: false, caught: [], missed: [...task.expected], noise: [] };
  }
  const open = [...task.expected];
  const caught: Expected[] = [];
  const noise: Finding[] = [];
  for (const f of findings) {
    const i = open.findIndex(
      (e) => Math.abs(e.line - f.line) <= LINE_TOLERANCE && e.categories.includes(f.category),
    );
    if (i >= 0) caught.push(...open.splice(i, 1));
    else noise.push(f);
  }
  const points = Math.max(0, caught.length - NOISE_PENALTY * noise.length);
  const score = task.expected.length ? points / task.expected.length : noise.length ? 0 : 1;
  return {
    ...base,
    score: round(score, 4),
    passed: open.length === 0 && noise.length === 0,
    parsed: true,
    caught,
    missed: open,
    noise,
  };
}

export function scoreRun(tasks: TaskScore[]): { score: number; tasks_passed: number; tasks_total: number } {
  const mean = tasks.length ? tasks.reduce((s, t) => s + t.score, 0) / tasks.length : 0;
  return { score: round(100 * mean, 2), tasks_passed: tasks.filter((t) => t.passed).length, tasks_total: tasks.length };
}

function round(x: number, d: number): number {
  const k = 10 ** d;
  return Math.round(x * k) / k;
}

// ---------- CLI ----------

const here = dirname(fileURLToPath(import.meta.url));

function loadTasks(): ScoredTask[] {
  const dir = join(here, "tasks");
  return readdirSync(dir)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(dir, f), "utf8")));
}

function reply(findings: Finding[]): string {
  return "Review done.\n\n```json\n" + JSON.stringify({ findings }, null, 2) + "\n```\n";
}

function selftest(): void {
  const tasks = loadTasks();
  const perfect = tasks.map((t) => scoreTask(t, reply(t.expected.map((e) => ({ line: e.line, category: e.categories[0] })))));
  const empty = tasks.map((t) => scoreTask(t, reply([])));
  const garbage = tasks.map((t) => scoreTask(t, "I could not find anything."));
  const noisy = tasks.map((t) =>
    scoreTask(t, reply([...t.expected.map((e) => ({ line: e.line + 1, category: e.categories[0] })), { line: 1, category: "bug" }])),
  );
  const check = (name: string, got: number, want: number) => {
    const ok = got === want;
    console.log(`${ok ? "ok  " : "FAIL"} ${name}: ${got}${ok ? "" : ` (want ${want})`}`);
    if (!ok) process.exitCode = 1;
  };
  check("perfect answers score", scoreRun(perfect).score, 100);
  check("perfect answers pass", scoreRun(perfect).tasks_passed, tasks.length);
  check("empty answers score", scoreRun(empty).score, 0);
  check("unparseable answers score", scoreRun(garbage).score, 0);
  const wantNoisy = round(100 * (tasks.reduce((s, t) => s + (t.expected.length - NOISE_PENALTY) / t.expected.length, 0) / tasks.length), 2);
  check("all caught (line ±1) + one noise", scoreRun(noisy).score, wantNoisy);
}

function rescore(dir: string): void {
  const results = JSON.parse(readFileSync(join(resolve(dir), "results.json"), "utf8")) as { task_id: string; reply: string }[];
  const tasks = new Map(loadTasks().map((t) => [t.id, t]));
  const scored = results.map((r) => {
    const t = tasks.get(r.task_id);
    if (!t) throw new Error(`unknown task ${r.task_id}`);
    return scoreTask(t, r.reply);
  });
  for (const s of scored) console.log(`${s.passed ? "pass" : "    "} ${s.task_id.padEnd(24)} ${s.score.toFixed(2)}  caught ${s.caught.length}, missed ${s.missed.length}, noise ${s.noise.length}`);
  console.log(JSON.stringify(scoreRun(scored)));
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const arg = process.argv[2];
  if (arg === "--selftest") selftest();
  else if (arg) rescore(arg);
  else console.log("usage: npm run score -- runs/run-NN | --selftest");
}
