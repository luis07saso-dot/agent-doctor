// npm run improve [-- --run NN] [-- --coach] [-- --no-commit]
// npm run improve -- --from tmp/dry-<ts> --no-commit      (non-counted: learn from a dry run's results)
//
// The agent reads what went wrong in a run and rewrites its own instructions and skills.
//   1. Takes the run's failed tasks (never the holdout ones) with the scorer's feedback.
//   2. Opens a TrueForge session with the agent itself (or, with --coach, an inline coach agent on the same model)
//      and asks it for new versions of agent/instructions.md and agent/skills/*/SKILL.md.
//   3. Writes the files and commits them with the trailer "Agent-Session: <session_id>".
// You review the commit (git show) and keep it or drop it (git reset --hard HEAD~1). You don't edit it.
//
// --from <dir>: read <dir>/results.json and write <dir>/improve-session.json instead of runs/run-NN/.
// It never touches runs/ and needs --no-commit (a dry run is not a counted run to learn from).
// Exception: tmp/failed-<ts> (a counted run that failed the evidence gate, same agent sha) may be
// committed: only agent/ is staged; the commit names the attempt and keeps the Agent-Session line.

import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { basename, dirname, join, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { TaskScore } from "../evals/score.ts";
import {
  client,
  die,
  exportSession,
  flag,
  git,
  isClean,
  loadTasks,
  option,
  readAgent,
  ROOT,
  runDir,
  runTurn,
  SUMMARY_CSV,
  type Task,
  withModelRetry,
} from "./lib.ts";
import { writeClean } from "./scrub.ts";

export interface AgentFileText {
  path: string;
  text: string;
}

/** Literals the scorer and the evidence gate depend on (spec §4.7). A new instructions.md must keep them all. */
export const REQUIRED_IN_INSTRUCTIONS = ['"findings"', '"rewrite"', "create_sub_agent", "profile-rubric", "listing-rewrite"];

/** Exact strings from a task that a general playbook has no reason to contain. Empty strings never count. */
export function taskQuotes(t: Task): string[] {
  const lines = [t.profile.readme, t.profile.description]
    .flatMap((text) => text.split(/\r?\n/))
    .map((l) => l.trim())
    .filter((l) => l.length >= 16);
  return [t.id, t.title, t.profile.name, t.profile.handle, t.job, ...lines].filter((q) => q.trim().length > 0);
}

/**
 * Overfitting guard: a new file must not quote the eval tasks (exact, case-sensitive substring).
 * A quote already present in one of the current agent files is not a leak (e.g. a task named "Agent"
 * vs the playbook's "# Agent Doctor"): only quotes the change introduces count. (👤 2026-11-08, spec §12.)
 */
export function overfitLeaks(files: AgentFileText[], current: AgentFileText[], tasks: Task[]): string[] {
  const before = current.map((f) => f.text).join("\n");
  const leaks: string[] = [];
  for (const t of tasks) {
    for (const q of taskQuotes(t)) {
      if (before.includes(q)) continue;
      for (const f of files) if (f.text.includes(q)) leaks.push(`${f.path} quotes "${q}"`);
    }
  }
  return leaks;
}

/** Missing required literals in a new instructions.md (empty = ok). */
export function instructionsMissing(text: string): string[] {
  return REQUIRED_IN_INSTRUCTIONS.filter((s) => !text.includes(s));
}

/** True when a SKILL.md keeps its frontmatter (name, description) and a body. */
export function skillFileOk(text: string): boolean {
  return /^---\n[\s\S]*?\bname:[\s\S]*?\bdescription:[\s\S]*?\n---\n/.test(text) && text.split("\n").length >= 6;
}

type Result = TaskScore & { reply: string };

/** Failed training tasks only. Holdout tasks never reach the prompt: checked on the result and the task file. */
export function trainingFailures(results: Result[], tasks: Map<string, Task>): Result[] {
  return results.filter((r) => !r.passed && !r.holdout && !tasks.get(r.task_id)?.holdout);
}

/** The scorer's feedback on one failed training task. */
export function taskFeedback(t: Task, r: Result): string {
  const said = [
    ...r.missed.map((m) => `  - missed: ${m.rule}: ${m.why}`),
    ...r.noise.map((n) => `  - not a finding here: ${n}`),
    ...r.checks.filter((c) => c.score < 1).map((c) => `  - rewrite check failed: ${c.detail}`),
  ];
  return [
    `### ${t.title} — score ${r.score.toFixed(2)}${r.parsed ? "" : ' — your reply had no valid ```json block with "findings" and "rewrite"'}`,
    "Profile snapshot:",
    "```json",
    JSON.stringify(t.profile, null, 2),
    "```",
    `Owner's note on what it does: ${t.job}`,
    "Your reply ended with:",
    "```",
    r.reply.slice(-1500) || "(empty reply)",
    "```",
    "The scorer says:",
    ...said,
  ].join("\n");
}

export function improvePrompt(currentFiles: AgentFileText[], feedback: string, label: string): string {
  return `This message is not a listing check. Ignore the How to work and Output sections of your instructions for this reply. You are improving your own playbook. Below are your current instruction files, then the listings you got wrong in your last evaluation run, with what the scorer said.

Rewrite your files so that next time you report the rule failures you missed, stop reporting rules that did not fail, and write listing text that passes the rewrite checks.

Rules:
- Write general rules that would help on listings you have never seen. Never mention these listings, agent names, handles, owner's notes or lines from their READMEs.
- Keep what works. Change only what the failures show is wrong or missing. Keep the Output section of instructions.md exactly as it is: the scorer depends on it.
- Keep delegating with create_sub_agent and keep both skills, profile-rubric and listing-rewrite.
- Short beats long: a checklist item is one line, with what to look for.
- You may edit agent/instructions.md and any agent/skills/<name>/SKILL.md (keep the frontmatter). Leave out files you don't change.

Reply with each changed file in full, in this format, and nothing else:

<<<FILE agent/skills/profile-rubric/SKILL.md
(the whole new file)
>>>
<<<LEARNED
(one sentence: what you learned)
>>>

## Your current files

${currentFiles.map((f) => `<<<FILE ${f.path}\n${f.text.trim()}\n>>>`).join("\n\n")}

## What went wrong in ${label}

${feedback}
`;
}

async function main(): Promise<void> {
  // ---------- which run ----------

  const from = option("from");
  if (flag("from") && (!from || from.startsWith("--"))) die("--from needs a directory, e.g. --from tmp/dry-<ts>");
  let dir: string;
  let label: string;
  let nn = "";
  if (from) {
    dir = resolve(process.cwd(), from);
    const gated = /^failed-\d{8}T\d{6}Z$/.test(basename(dir)) && dirname(dir) === join(ROOT, "tmp");
    if (!gated && !flag("no-commit")) die("--from learns from a non-counted run: add --no-commit.");
    label = gated ? `attempt ${basename(dir)}` : `dry run ${basename(dir)}`;
    if (gated && !flag("no-commit")) {
      const sc = JSON.parse(readFileSync(join(dir, "score.json"), "utf8")) as { agent_commit?: string };
      const same = sc.agent_commit && git("rev-parse", `${sc.agent_commit}:agent`) === git("rev-parse", "HEAD:agent");
      if (!same) die(`${basename(dir)} ran at ${sc.agent_commit}, whose agent/ differs from HEAD: learn only from an attempt at the current agent.`);
    }
  } else {
    const rows = existsSync(SUMMARY_CSV) ? readFileSync(SUMMARY_CSV, "utf8").trim().split("\n").slice(1).filter(Boolean) : [];
    if (!rows.length) die("No runs yet. Run npm run run-evals first.");
    const run = Number(option("run") ?? rows.length);
    dir = runDir(run);
    nn = String(run).padStart(2, "0");
    label = `run ${nn}`;
  }
  if (!existsSync(join(dir, "results.json"))) die(`No results.json in ${dir}`);
  if (!isClean("agent")) die("agent/ has uncommitted changes. Commit or discard them first: the agent's change must be its own.");

  const results = JSON.parse(readFileSync(join(dir, "results.json"), "utf8")) as Result[];
  const allTasks = loadTasks();
  const tasks = new Map(allTasks.map((t) => [t.id, t]));
  for (const r of results) if (!tasks.has(r.task_id)) die(`results.json has task ${r.task_id}, which is not in evals/tasks/.`);
  const failed = trainingFailures(results, tasks);
  if (!failed.length) {
    console.log(`Nothing to learn from ${label}: every training task passed. Add harder tasks before run 1 next time.`);
    process.exit(0);
  }

  // ---------- the prompt ----------

  const { agent, instructions, skills } = readAgent();
  const currentFiles: AgentFileText[] = [
    { path: "agent/instructions.md", text: instructions },
    ...skills.map((s) => ({ path: `${s.path}/SKILL.md`, text: readFileSync(join(ROOT, s.path, "SKILL.md"), "utf8") })),
  ];
  const feedback = failed.map((r) => taskFeedback(tasks.get(r.task_id)!, r)).join("\n\n");
  const prompt = improvePrompt(currentFiles, feedback, label);

  // ---------- ask the agent ----------

  const tf = client();
  const coach = flag("coach");
  const { data: session } = await tf.sessions.create({
    // The agent itself (by name), or a coach: an inline TrueForge agent on the same model.
    agent: coach
      ? { spec: { model: agent.model, instructions: "You coach an agent-listing checker: you rewrite its instruction files from its failed runs.", config: { askUserQuestions: { enabled: false }, generativeUi: { enabled: false } } } }
      : { name: agent.name },
    metadata: { purpose: "improve", learned_from: from ? basename(dir) : nn },
  });
  await tf.sessions.update(session.id, { title: `improve from ${label}` });
  console.log(`Asking ${coach ? "the coach" : `"${agent.name}"`} to rewrite its playbook from ${failed.length} failed tasks (session ${session.id})…`);

  // Model provider error (asi1 429/5xx): retry as a new root turn, so it doesn't chain on the dead one.
  const { turn } = await withModelRetry((attempt) => runTurn(tf, session.id, prompt, attempt > 0), {
    log: (m) => console.log(m.trim()),
  });
  if (turn.status !== "done") die(`The turn ended with status ${turn.status}${turn.error ? `: ${turn.error}` : ""}`);

  // ---------- parse and check the change ----------

  const files = [...turn.text.matchAll(/<<<FILE ([^\n]+)\n([\s\S]*?)\n>>>/g)].map((m) => ({ path: normalize(m[1].trim()), text: m[2].trimEnd() + "\n" }));
  const learned = turn.text.match(/<<<LEARNED\n([\s\S]*?)\n>>>/)?.[1].trim() ?? "";
  if (!files.length) die(`The agent proposed no files. Its reply:\n\n${turn.text}`);

  const allowed = /^agent\/(instructions\.md|skills\/[a-z0-9][a-z0-9-]*\/SKILL\.md)$/;
  for (const f of files) {
    if (!allowed.test(f.path)) die(`The agent tried to write ${f.path}. Only agent/instructions.md and agent/skills/<name>/SKILL.md are allowed.`);
  }

  const leaks = overfitLeaks(files, currentFiles, allTasks);
  if (leaks.length && !flag("allow-leaks")) die(`The change quotes the eval tasks, so it would overfit:\n  ${leaks.join("\n  ")}\nRun improve again (or pass --allow-leaks to keep it anyway).`);

  for (const f of files.filter((f) => f.path.endsWith("/SKILL.md"))) {
    if (!skillFileOk(f.text)) die(`${f.path} lost its frontmatter (name, description) or its body. Run improve again.`);
  }
  const newInstructions = files.find((f) => f.path === "agent/instructions.md");
  const missing = newInstructions ? instructionsMissing(newInstructions.text) : [];
  if (missing.length) die(`The new instructions.md dropped ${missing.join(", ")} (output format, delegation or skill names). Run improve again.`);

  // ---------- write and commit ----------

  for (const f of files) {
    mkdirSync(dirname(join(ROOT, f.path)), { recursive: true });
    writeFileSync(join(ROOT, f.path), f.text);
  }
  writeClean(join(dir, "improve-session.json"), await exportSession(tf, session.id)); // scrubbed (scripts/scrub.ts)

  if (isClean("agent")) {
    console.log("The agent sent back its files unchanged. Nothing to commit.");
    process.exit(0);
  }
  console.log(git("diff", "--stat", "--", "agent"));

  const message = `agent: learn from ${label}\n\n${learned || "(no summary given)"}\n\nAgent-Session: ${session.id}`;
  if (from && !flag("no-commit")) {
    git("add", "agent");
    git("commit", "-q", "-m", message);
    console.log(`\n✓ Committed the agent's change (Agent-Session: ${session.id}), learned from ${label}.`);
    console.log("  Review it: git show    Drop it: git reset --hard HEAD~1    Then: npm run run-evals");
  } else if (from) {
    console.log("\nFiles written, not committed (non-counted). Discard with: git checkout -- agent/instructions.md agent/skills");
  } else if (flag("no-commit")) {
    console.log(`\nFiles written, not committed. To commit:\n  git add agent runs && git commit -F- <<'EOF'\n${message}\nEOF`);
  } else {
    git("add", "agent", join(dir, "improve-session.json"));
    git("commit", "-q", "-m", message);
    console.log(`\n✓ Committed the agent's change (Agent-Session: ${session.id}).`);
    console.log("  Review it: git show    Drop it: git reset --hard HEAD~1    Then: npm run run-evals");
  }
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) await main();
