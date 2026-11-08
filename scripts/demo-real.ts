// TF_AGENT_NAME=ad-demo npm run demo-real
//
// TQ6 demo, NOT scored and NOT a counted run: the current agent/ checks real Agentverse listings.
// Input: tmp/demo/snapshots/*.json from `python3 scripts/demo_snapshot.py <address> ...`.
// Same prompt and same scorer as the evals (taskPrompt, scoreTask), one TrueForge session.
// Writes tmp/demo/run-<ts>/ only (gitignored): results.json, session.json, <task>.md (readable rewrite).
// Never touches runs/, runs/summary.csv, evals/ or agent/. Needs its own agent name, so the counted
// agent "agent-doctor" is never re-synced by a demo.

import { mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { parseReply, scoreTask, type Task } from "../evals/score.ts";
import { writeClean } from "./scrub.ts";
import { client, die, exportSession, git, isClean, readAgent, ROOT, runTurn, sessionStats, syncAgent, taskPrompt, withModelRetry } from "./lib.ts";

const name = process.env.TF_AGENT_NAME;
if (!name || name === "agent-doctor") die("set TF_AGENT_NAME to a demo name (e.g. ad-demo): the counted agent is never used for demos.");

const snapDir = join(ROOT, "tmp", "demo", "snapshots");
let files: string[] = [];
try {
  files = readdirSync(snapDir).filter((f) => f.endsWith(".json")).sort();
} catch {
  /* handled below */
}
if (!files.length) die("no snapshots: run python3 scripts/demo_snapshot.py <address> ... first.");
const tasks = files.map((f) => JSON.parse(readFileSync(join(snapDir, f), "utf8")) as Task);

// Skills are cloned from the public repo (skill_mode git) at the last commit that changed agent/,
// so the demo runs exactly the latest scored agent even when docs-only commits are unpushed.
const sha = git("rev-list", "-1", "HEAD", "--", "agent");
if (!isClean("agent")) die("agent/ has uncommitted changes: the demo must run a committed agent.");
git("fetch", "-q", "origin");
if (git("branch", "-r", "--contains", sha) === "") die(`push first: ${sha.slice(0, 7)} is on no remote branch, so TrueForge can't clone its skills.`);

const tf = client();
const agent = await syncAgent(tf, sha);
console.log(`Demo: agent "${agent.name}" at ${sha.slice(0, 7)}, ${tasks.length} real listings`);

const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
const dir = join(ROOT, "tmp", "demo", `run-${stamp}`);
mkdirSync(dir, { recursive: true });
const started = Date.now();
const { data: session } = await tf.sessions.create({
  agent: { name: readAgent().agent.name },
  metadata: { purpose: "demo", agent_commit: sha },
});
await tf.sessions.update(session.id, { title: `demo real listings @ ${sha.slice(0, 7)}` });
console.log(`  session ${session.id}`);

const results = [];
for (const task of tasks) {
  process.stdout.write(`  ${task.id.padEnd(40)} `);
  const { turn, retried } = await withModelRetry(() => runTurn(tf, session.id, taskPrompt(task)), {
    log: (m) => process.stdout.write(m),
  });
  const s = scoreTask(task, turn.text);
  results.push({ ...s, title: task.title, turn_id: turn.turnId, status: turn.status, error: turn.error, retried, reply: turn.text });
  console.log(
    `${turn.status === "done" ? "" : `[${turn.status}] `}diag ${s.diagnosis.toFixed(2)} rewrite ${s.rewrite.toFixed(2)}` +
      `  caught [${s.caught.join(", ")}]` +
      (s.missed.length ? `  missed [${s.missed.map((m) => m.rule).join(", ")}]` : "") +
      (s.noise.length ? `  extra [${s.noise.join(", ")}]` : ""),
  );
  const p = parseReply(turn.text);
  if (p) {
    const md = [
      `# ${task.title} — TrueForge Agent Doctor demo`,
      "",
      `Doctor (live scorer) findings: ${task.expected.map((e) => e.rule).join(", ") || "none"}`,
      `Agent findings: ${p.findings.join(", ") || "none"}`,
      "",
      "## New description",
      "",
      p.rewrite.description,
      "",
      "## New keywords",
      "",
      p.rewrite.keywords.join(", "),
      "",
      "## New starter prompts",
      "",
      ...p.rewrite.starter_prompts.map((x) => `- ${x}`),
      "",
      "## New README",
      "",
      p.rewrite.readme,
      "",
    ].join("\n");
    writeFileSync(join(dir, `${task.id}.md`), md);
  }
}
const durationS = Math.round((Date.now() - started) / 1000);
const exp = await exportSession(tf, session.id);
const stats = sessionStats(exp);
writeClean(join(dir, "results.json"), results);
writeClean(join(dir, "session.json"), exp);
console.log(`\nDemo done: ${stats.tokens} tokens, ${stats.toolCalls} tool calls, ${durationS} s → ${dir.replace(ROOT + "/", "")} (not scored, not counted)`);
