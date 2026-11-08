// node --test scripts/improve.test.ts — improve's guards and feedback, no TrueForge server needed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { scoreTask } from "../evals/score.ts";
import { instructionsMissing, overfitLeaks, skillFileOk, taskFeedback, trainingFailures, type AgentFileText } from "./improve.ts";
import { loadTasks, type Task } from "./lib.ts";

const tasks = loadTasks();
const byId = new Map(tasks.map((t) => [t.id, t]));
const blank = byId.get("01-blank-template")!;
const current: AgentFileText[] = [
  { path: "agent/instructions.md", text: "# Agent Doctor\n\nCheck one Agentverse listing.\n" },
  { path: "agent/skills/listing-rewrite/SKILL.md", text: "---\nname: listing-rewrite\ndescription: d\n---\n\n# Listing rewrite\n" },
];
const skill = (body: string): AgentFileText => ({
  path: "agent/skills/listing-rewrite/SKILL.md",
  text: `---\nname: listing-rewrite\ndescription: How to rewrite a listing.\n---\n\n# Listing rewrite\n\n${body}\n`,
});

test("guard rejects a SKILL.md quoting a task's job sentence", () => {
  const leaks = overfitLeaks([skill(`Example: ${blank.job}`)], current, tasks);
  assert.ok(leaks.some((l) => l.includes(blank.job)), leaks.join("\n"));
});

test('guard accepts a SKILL.md containing "cup measures" (must_keep phrases are not quotes)', () => {
  assert.deepEqual(overfitLeaks([skill("Keep the owner's own terms, e.g. units like cup measures.")], current, tasks), []);
});

test("guard rejects a task's README line, title or handle", () => {
  const line = "Invoice Helper reads invoice text and returns the supplier, total amount and due date as a short table, so small teams can log bills fast.";
  assert.equal(overfitLeaks([skill(line)], current, tasks).length > 0, true);
  assert.equal(overfitLeaks([skill("Like Blank template listing.")], current, tasks).length > 0, true);
  assert.equal(overfitLeaks([skill("Handle flightdelays is fine.")], current, tasks).length > 0, true);
});

test('guard ignores quotes already in the current files (task named "Agent") and empty handles', () => {
  assert.ok(blank.profile.name === "Agent" && tasks.some((t) => t.profile.handle === ""));
  const unchanged = { path: "agent/instructions.md", text: current[0].text + "\nAgent names and Agentverse handles matter.\n" };
  assert.deepEqual(overfitLeaks([unchanged], current, tasks), []);
});

test("guard rejects an instructions.md without create_sub_agent", () => {
  const text = '# Agent Doctor\nUse profile-rubric and listing-rewrite.\n```json\n{"findings": [], "rewrite": {}}\n```\n';
  assert.deepEqual(instructionsMissing(text), ["create_sub_agent"]);
  assert.deepEqual(instructionsMissing(text + "Call create_sub_agent twice.\n"), []);
});

test("SKILL.md frontmatter + body check", () => {
  assert.equal(skillFileOk(skill("1. one rule").text), true);
  assert.equal(skillFileOk("# no frontmatter\n\n1\n2\n3\n4\n"), false);
});

test("holdout tasks never reach the improve prompt", () => {
  const results = tasks.map((t) => ({ ...scoreTask(t, "no json"), reply: "no json" }));
  const failed = trainingFailures(results, byId);
  assert.deepEqual(failed.map((r) => r.task_id), tasks.filter((t: Task) => !t.holdout).map((t) => t.id));
  // A result that lost its holdout flag is still dropped by the task file's flag.
  const lying = results.map((r) => ({ ...r, holdout: false }));
  assert.equal(trainingFailures(lying, byId).some((r) => byId.get(r.task_id)!.holdout), false);
});

test("feedback lists missed rules, noise and failed rewrite checks, never must_keep phrases", () => {
  const reply = 'x\n```json\n{"findings":[{"rule":"website","fix":"a"}],"rewrite":{"description":"","readme":"","keywords":[],"starter_prompts":[]}}\n```';
  const fb = taskFeedback(blank, { ...scoreTask(blank, reply), reply });
  assert.match(fb, /^### Blank template listing — score /);
  assert.match(fb, /  - missed: readme_sections: /);
  assert.match(fb, /  - not a finding here: website/);
  assert.match(fb, /  - rewrite check failed: README drops terms from the owner's note/);
  // must_keep phrases appear only inside the owner's note (the job sentence), not in the scorer's lines.
  const said = fb.slice(fb.indexOf("The scorer says:"));
  for (const k of blank.must_keep) assert.equal(said.includes(k), false, k);
});
