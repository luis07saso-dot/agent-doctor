// npm run improve [-- --run NN] [-- --coach] [-- --no-commit]
//
// The agent reads what went wrong in a run and rewrites its own instructions and skill.
//   1. Takes the run's failed tasks (never the holdout ones) with the scorer's feedback.
//   2. Opens a TrueForge session with the agent itself (or, with --coach, an inline coach agent on the same model)
//      and asks it for new versions of agent/instructions.md and agent/skills/*/SKILL.md.
//   3. Writes the files and commits them with the trailer "Agent-Session: <session_id>".
// You review the commit (git show) and keep it or drop it (git reset --hard HEAD~1). You don't edit it.

import { existsSync, readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname, join, normalize } from "node:path";
import type { TaskScore } from "../evals/score.ts";
import {
  client,
  die,
  exportSession,
  flag,
  git,
  isClean,
  loadTasks,
  numbered,
  option,
  readAgent,
  ROOT,
  runDir,
  runTurn,
  SUMMARY_CSV,
} from "./lib.ts";
import { writeClean } from "./scrub.ts";

// ---------- which run ----------

const rows = existsSync(SUMMARY_CSV) ? readFileSync(SUMMARY_CSV, "utf8").trim().split("\n").slice(1).filter(Boolean) : [];
if (!rows.length) die("No runs yet. Run npm run run-evals first.");
const run = Number(option("run") ?? rows.length);
const dir = runDir(run);
const nn = String(run).padStart(2, "0");
if (!existsSync(join(dir, "results.json"))) die(`No results for run ${nn} in ${dir}`);
if (!isClean("agent")) die("agent/ has uncommitted changes. Commit or discard them first: the agent's change must be its own.");

type Result = TaskScore & { reply: string };
const results = JSON.parse(readFileSync(join(dir, "results.json"), "utf8")) as Result[];
const tasks = new Map(loadTasks().map((t) => [t.id, t]));
const failed = results.filter((r) => !r.passed && !r.holdout);
if (!failed.length) {
  console.log(`Nothing to learn from run ${nn}: every training task passed. Add harder tasks before run 1 next time.`);
  process.exit(0);
}

// ---------- the prompt ----------

const { agent, instructions, skills } = readAgent();
const currentFiles = [
  { path: "agent/instructions.md", text: instructions },
  ...skills.map((s) => ({ path: `${s.path}/SKILL.md`, text: readFileSync(join(ROOT, s.path, "SKILL.md"), "utf8") })),
];

const feedback = failed
  .map((r) => {
    const t = tasks.get(r.task_id)!;
    const missed = r.missed.map((m) => `  - missed: line ${m.line} (${m.categories.join(" or ")}): ${m.why}`);
    const noise = r.noise.map((n) => `  - not a real problem: line ${n.line} (${n.category})${n.comment ? `: ${n.comment}` : ""}`);
    return [
      `### ${t.filename} — score ${r.score.toFixed(2)}${r.parsed ? "" : " — your reply had no valid ```json block with \"findings\""}`,
      "```" + t.language,
      numbered(t.code),
      "```",
      "Your reply ended with:",
      "```",
      r.reply.slice(-1500) || "(empty reply)",
      "```",
      "The scorer says:",
      ...missed,
      ...noise,
    ].join("\n");
  })
  .join("\n\n");

const prompt = `This message is not a code review. Ignore the Output section of your instructions for this reply.

You are improving your own playbook. Below are your current instruction files, then the reviews you got wrong in your last evaluation run, with what the scorer said.

Rewrite your files so that next time you catch the kinds of problems you missed and stop making the kinds of comments that were not real problems.

Rules:
- Write general rules that would help on code you have never seen. Never mention these files, file names, task names, function names or line numbers.
- Keep what works. Change only what the failures show is wrong or missing. Keep the Output section of instructions.md exactly as it is: the scorer depends on it.
- Short beats long: a checklist item is one line, with what to look for.
- You may edit agent/instructions.md and any agent/skills/<name>/SKILL.md (keep the frontmatter). Leave out files you don't change.

Reply with each changed file in full, in this format, and nothing else:

<<<FILE agent/skills/review-checklist/SKILL.md
(the whole new file)
>>>
<<<LEARNED
(one sentence: what you learned)
>>>

## Your current files

${currentFiles.map((f) => `<<<FILE ${f.path}\n${f.text.trim()}\n>>>`).join("\n\n")}

## What went wrong in run ${nn}

${feedback}
`;

// ---------- ask the agent ----------

const tf = client();
const coach = flag("coach");
const { data: session } = await tf.sessions.create({
  // The agent itself (by name), or a coach: an inline TrueForge agent on the same model.
  agent: coach
    ? { spec: { model: agent.model, instructions: "You coach a code-review agent: you rewrite its instruction files from its failed runs.", config: { askUserQuestions: { enabled: false }, generativeUi: { enabled: false } } } }
    : { name: agent.name },
  metadata: { purpose: "improve", learned_from_run: nn },
});
await tf.sessions.update(session.id, { title: `improve from run ${nn}` });
console.log(`Asking ${coach ? "the coach" : `"${agent.name}"`} to rewrite its playbook from ${failed.length} failed tasks (session ${session.id})…`);

const turn = await runTurn(tf, session.id, prompt, false);
if (turn.status !== "done") die(`The turn ended with status ${turn.status}${turn.error ? `: ${turn.error}` : ""}`);

// ---------- parse and check the change ----------

const files = [...turn.text.matchAll(/<<<FILE ([^\n]+)\n([\s\S]*?)\n>>>/g)].map((m) => ({ path: normalize(m[1].trim()), text: m[2].trimEnd() + "\n" }));
const learned = turn.text.match(/<<<LEARNED\n([\s\S]*?)\n>>>/)?.[1].trim() ?? "";
if (!files.length) die(`The agent proposed no files. Its reply:\n\n${turn.text}`);

const allowed = /^agent\/(instructions\.md|skills\/[a-z0-9][a-z0-9-]*\/SKILL\.md)$/;
for (const f of files) {
  if (!allowed.test(f.path)) die(`The agent tried to write ${f.path}. Only agent/instructions.md and agent/skills/<name>/SKILL.md are allowed.`);
}

// Overfitting guard: the new playbook must not quote the eval tasks.
const leaks: string[] = [];
for (const t of loadTasks()) {
  const quotes = [t.id, t.filename, ...t.expected.map((e) => t.code[e.line - 1].trim()).filter((l) => l.length >= 16)];
  for (const f of files) for (const q of quotes) if (f.text.includes(q)) leaks.push(`${f.path} quotes "${q}"`);
}
if (leaks.length && !flag("allow-leaks")) die(`The change quotes the eval tasks, so it would overfit:\n  ${leaks.join("\n  ")}\nRun improve again (or pass --allow-leaks to keep it anyway).`);

for (const f of files.filter((f) => f.path.endsWith("/SKILL.md"))) {
  if (!/^---\n[\s\S]*?\bname:[\s\S]*?\bdescription:[\s\S]*?\n---\n/.test(f.text) || f.text.split("\n").length < 6) {
    die(`${f.path} lost its frontmatter (name, description) or its body. Run improve again.`);
  }
}
const newInstructions = files.find((f) => f.path === "agent/instructions.md");
if (newInstructions && !newInstructions.text.includes('"findings"')) {
  die("The new instructions.md dropped the JSON output format the scorer needs. Run improve again.");
}

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

const message = `agent: learn from run ${nn}\n\n${learned || "(no summary given)"}\n\nAgent-Session: ${session.id}`;
if (flag("no-commit")) {
  console.log(`\nFiles written, not committed. To commit:\n  git add agent runs && git commit -F- <<'EOF'\n${message}\nEOF`);
} else {
  git("add", "agent", join(dir, "improve-session.json"));
  git("commit", "-q", "-m", message);
  console.log(`\n✓ Committed the agent's change (Agent-Session: ${session.id}).`);
  console.log("  Review it: git show    Drop it: git reset --hard HEAD~1    Then: npm run run-evals");
}
