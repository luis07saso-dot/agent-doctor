// TF_AGENT_NAME=ad-c2 npm run try-skills [-- --skip-preflight]
//
// Non-counted proof that the agent's git skills load from the sandbox (B2), from session events,
// not from the model's text. One root turn with test instructions ("read each skill"), then the
// same check as `check-evidence --skills-only`: every skill under agent/skills/ read with exec
// (successful tool.response with its frontmatter) and zero "Sandbox initialization failed".
// Prints "<name>: read ok" per skill. Writes only tmp/ (scrubbed); never runs/.
//
// HEAD must be pushed first: TrueForge clones the skills at that sha (an unpushed sha fails silently).
// --skip-preflight skips that check, only to show the failure at an unpushed sha (expect "not our ref").

import { writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";
import { checkEvidence } from "./check-evidence.ts";
import { client, die, exportSession, flag, git, headSha, readAgent, ROOT, runTurn, syncAgent } from "./lib.ts";
import { scrub, writeClean } from "./scrub.ts";

const SANDBOX_FAIL = "Sandbox initialization failed";

if (!process.env.TF_AGENT_NAME) process.env.TF_AGENT_NAME = "ad-c2";
if (process.env.TF_AGENT_NAME === "agent-doctor") die("try-skills would overwrite the counted agent's instructions: use TF_AGENT_NAME=ad-c2.");

const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+Z$/, "Z");
const dir = join(ROOT, "tmp", `try-skills-${stamp}`);
mkdirSync(dir, { recursive: true });
const instructionsFile = join(ROOT, "tmp", "try-skills-instructions.md");
writeFileSync(instructionsFile, "Read each attached skill's SKILL.md with exec, then reply with each skill's name.\n");
process.env.TF_INSTRUCTIONS_FILE = instructionsFile;

const { agent, skills } = readAgent();
if ((agent.skill_mode ?? "inline") !== "git") die('try-skills needs skill_mode "git" (agent/agent.json, or unset TF_SKILL_MODE).');
if (!skills.length) die("No skills under agent/skills/.");

const sha = headSha();
if (!flag("skip-preflight")) {
  git("fetch", "-q", "origin");
  if (git("branch", "-r", "--contains", sha) === "") die(`push first: ${sha.slice(0, 7)} is on no remote branch, so TrueForge can't clone its skills.`);
}

const tf = client();
await syncAgent(tf, sha);
const { data: session } = await tf.sessions.create({ agent: { name: agent.name }, metadata: { purpose: "try-skills", ref: sha } });
await tf.sessions.update(session.id, { title: `try-skills @ ${sha.slice(0, 7)}` });
console.log(`try-skills: agent "${agent.name}" at ${sha.slice(0, 7)}, skills ${skills.map((s) => s.name).join(", ")} (session ${session.id})`);

const turn = await runTurn(tf, session.id, "Go.");
const exp = await exportSession(tf, session.id);
writeClean(join(dir, "session.json"), exp); // scrubbed (scripts/scrub.ts)

const ev = checkEvidence(exp, { skillsOnly: true, skills: skills.map((s) => s.name) });
console.log(`turn ${turn.status} · ${ev.line}`);
for (const s of skills) console.log(`${s.name}: ${ev.reasons.some((r) => r.endsWith(`skill ${s.name}`)) ? "NOT read" : "read ok"}`);
if (!ev.ok) {
  console.error(ev.reasons.map((r) => `  ✗ ${r}`).join("\n"));
  // Show the sandbox error itself (e.g. "upload-pack: not our ref <sha>" for an unpushed commit).
  const failure = firstString(exp, (v) => v.includes(SANDBOX_FAIL));
  if (failure) console.error(`  ${scrub(failure).slice(0, 400)}`);
  die(`skills not proven (session saved to tmp/${`try-skills-${stamp}`}/session.json)`);
}
console.log("✓ skills ok");

/** First string anywhere in `value` (depth-first) that matches. */
function firstString(value: unknown, match: (s: string) => boolean): string | undefined {
  if (typeof value === "string") return match(value) ? value : undefined;
  if (value && typeof value === "object") {
    for (const v of Object.values(value)) {
      const hit = firstString(v, match);
      if (hit) return hit;
    }
  }
  return undefined;
}
