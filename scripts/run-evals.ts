// npm run run-evals [-- --dry] [-- --no-commit] [-- --allow-dirty]
//
// One run = one TrueForge session. Each task in evals/tasks/ is one root turn in that session
// (so tasks don't see each other). Then:
//   runs/run-NN/results.json   the agent's reply and score for each task
//   runs/run-NN/score.json     the run score and per-task details
//   runs/run-NN/session.json   the whole session, exported from TrueForge
//   runs/summary.csv           one new row
// and a commit "run NN: score X" (skip with --no-commit).
//
// --dry: non-counted run. Writes tmp/dry-<ts>/ only: no runs/ dir, no summary row, no commit.
// Skill mode git: HEAD must be pushed first (TrueForge clones skills at that sha; an unpushed sha
// fails silently). Counted runs need HEAD on origin/main; dry runs need HEAD on any remote branch.
// Every file written is scrubbed (scripts/scrub.ts). A counted run must also pass the evidence gate
// (scripts/check-evidence.ts --run); if it fails, files go to tmp/failed-<ts>/ and nothing is committed.
// A task whose turn dies on a model provider error (429/5xx) is re-run up to 2× (results.json `retried`).

import { appendFileSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { scoreRun, scoreTask } from "../evals/score.ts";
import { checkEvidence } from "./check-evidence.ts";
import { writeClean } from "./scrub.ts";
import {
  client,
  die,
  exportSession,
  flag,
  git,
  headSha,
  isClean,
  loadTasks,
  readAgent,
  ROOT,
  runDir,
  runTurn,
  sessionStats,
  SUMMARY_CSV,
  syncAgent,
  taskPrompt,
  withModelRetry,
} from "./lib.ts";

const HEADER = "run,session_id,agent_commit,score,date_utc,tasks_passed,tasks_total,tokens,tool_calls,duration_s";

const DRY = flag("dry");

// 1. The agent and the eval must be committed, so agent_commit says exactly what ran.
if (!isClean("agent", "evals") && !flag("allow-dirty") && !DRY) {
  die("agent/ or evals/ has uncommitted changes. Commit them first, so agent_commit points at what ran.");
}
const agentCommit = headSha() + (isClean("agent", "evals") ? "" : "-dirty");

// 1b. Push preflight (skill mode git): TrueForge clones the skills at HEAD from the public repo.
if ((readAgent().agent.skill_mode ?? "inline") === "git") {
  const sha = headSha();
  if (DRY) {
    git("fetch", "-q", "origin");
    if (git("branch", "-r", "--contains", sha) === "") die(`push first: ${sha.slice(0, 7)} is on no remote branch, so TrueForge can't clone its skills.`);
  } else {
    git("fetch", "-q", "origin", "main");
    try {
      git("merge-base", "--is-ancestor", sha, "origin/main");
    } catch {
      die(`push first: ${sha.slice(0, 7)} is not on origin/main. Counted runs need agent_commit and skill refs on public main.`);
    }
  }
}

const summaryText = existsSync(SUMMARY_CSV) ? readFileSync(SUMMARY_CSV, "utf8") : "";
const rows = summaryText.trim().split("\n").slice(1).filter(Boolean);
const run = rows.length + 1;
const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
// Counted runs write to a staging dir first; it becomes runs/run-NN only after the evidence gate.
const dir = join(ROOT, "tmp", `${DRY ? "dry" : "stage"}-${stamp}`);
const nn = String(run).padStart(2, "0");

// 2. Make the TrueForge agent match agent/ at this commit.
const tf = client();
const agent = await syncAgent(tf, headSha());
const tasks = loadTasks();
console.log(`Run ${nn}: agent "${agent.name}" at ${agentCommit.slice(0, 7)}, ${tasks.length} tasks`);

// 3. One session for the whole run. https://trueforge.dev/api/overview#session
const started = Date.now();
const { data: session } = await tf.sessions.create({
  agent: { name: readAgent().agent.name },
  metadata: { purpose: "eval", run: nn, agent_commit: agentCommit },
});
await tf.sessions.update(session.id, { title: `eval run ${nn} @ ${agentCommit.slice(0, 7)}` });
console.log(`  session ${session.id}`);

// 4. Each task is one root turn; score the reply.
const results = [];
for (const task of tasks) {
  process.stdout.write(`  ${task.id.padEnd(24)} `);
  // A turn killed by a model provider error (asi1 429/5xx) is run again as a fresh root turn,
  // at most twice (lib.ts withModelRetry). The dead turn stays in session.json and is listed in
  // `retried`; check-evidence skips only turns listed there. Bad or unparsed answers are never retried.
  // Dead turns' tokens/tool calls still count in score.json + summary.csv (real cost); duration includes the waits.
  const { turn, retried } = await withModelRetry(() => runTurn(tf, session.id, taskPrompt(task)), {
    log: (m) => process.stdout.write(m),
  });
  const scored = scoreTask(task, turn.text);
  results.push({ ...scored, turn_id: turn.turnId, status: turn.status, error: turn.error, retried, reply: turn.text });
  console.log(`${turn.status === "done" ? "" : `[${turn.status}${turn.error ? `: ${turn.error}` : ""}] `}${scored.score.toFixed(2)}${scored.passed ? "  pass" : ""}`);
}
const durationS = Math.round((Date.now() - started) / 1000);
const total = scoreRun(results);

// 5. Save the run (scrubbed: no local paths, emails or keys).
const exp = await exportSession(tf, session.id);
const stats = sessionStats(exp);
try {
  writeClean(join(dir, "results.json"), results);
  writeClean(join(dir, "score.json"), { run, session_id: session.id, agent_commit: agentCommit, ...total, ...stats, duration_s: durationS });
  writeClean(join(dir, "session.json"), exp);
} catch (e) {
  const failed = join(ROOT, "tmp", `failed-${stamp}`);
  if (existsSync(dir)) renameSync(dir, failed);
  die(`scrub check failed (${(e as Error).message}); nothing saved to runs/, nothing committed. Session ${session.id}`);
}

console.log(`\nRun ${nn} score: ${total.score} (${total.tasks_passed}/${total.tasks_total} tasks passed, ${stats.tokens} tokens)`);

if (DRY) {
  console.log(`(dry run: ${dir.replace(ROOT + "/", "")}; runs/ untouched)`);
  process.exit(0);
}

// 5b. Counted-run gate: B1 + B2 events, every task done + parsed, no sandbox failure.
const ev = checkEvidence(exp, { runDir: dir });
console.log(ev.line);
if (!ev.ok) {
  const failed = join(ROOT, "tmp", `failed-${stamp}`);
  renameSync(dir, failed);
  die(`evidence gate failed; nothing saved to runs/, nothing committed. Files: ${failed.replace(ROOT + "/", "")}\n  ${ev.reasons.join("\n  ")}\n  Re-run the same sha (no agent/ change).`);
}

const final = runDir(run);
if (existsSync(final)) die(`${final} already exists`);
mkdirSync(dirname(final), { recursive: true });
renameSync(dir, final);
if (summaryText.trim() === "") writeFileSync(SUMMARY_CSV, HEADER + "\n");
const date = new Date().toISOString().replace(/\.\d+Z$/, "Z");
appendFileSync(
  SUMMARY_CSV,
  [run, session.id, agentCommit, total.score, date, total.tasks_passed, total.tasks_total, stats.tokens, stats.toolCalls, durationS].join(",") + "\n",
);
const dirLabel = final.replace(/.*\/runs\//, "runs/");
console.log(`✓ Saved ${dirLabel}`);

// 6. Commit the run, so git history reads: run 1 → agent change → run N.
if (!flag("no-commit")) {
  git("add", "runs");
  git("commit", "-q", "-m", `run ${nn}: score ${total.score}`, "-m", `TrueForge session: ${session.id}\nagent_commit: ${agentCommit}`);
  console.log(`✓ Committed ${dirLabel}. Next: npm run improve`);
}
