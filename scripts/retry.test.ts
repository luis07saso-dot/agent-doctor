// node --test scripts/retry.test.ts — model-error retry (lib.ts) + evidence gate skipping retried turns. No server needed.
import assert from "node:assert/strict";
import { mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { checkEvidence } from "./check-evidence.ts";
import { isTransientModelError, loadTasks, withModelRetry, type SessionExport, type TurnResult } from "./lib.ts";

const E500 = "[Model Error] Request failed (500): internal server error";
const noSleep = { sleep: async () => {} };

test("isTransientModelError: only provider 429/5xx on an error turn", () => {
  assert.equal(isTransientModelError("error", E500), true);
  assert.equal(isTransientModelError("error", "[Model Error] Request failed (502): bad gateway"), true);
  assert.equal(isTransientModelError("error", "[Model Error] Request failed (429): rate limited"), true);
  assert.equal(isTransientModelError("error", "[Model Error] Request failed (400): bad request"), false);
  assert.equal(isTransientModelError("error", "Sandbox initialization failed"), false);
  assert.equal(isTransientModelError("error", undefined), false);
  assert.equal(isTransientModelError("done", E500), false);
});

function scripted(outcomes: TurnResult[]) {
  const calls: number[] = [];
  return { calls, run: async (attempt: number) => (calls.push(attempt), outcomes[Math.min(attempt, outcomes.length - 1)]) };
}
const done = (id: string, text = "ok"): TurnResult => ({ turnId: id, status: "done", text });
const dead = (id: string, error = E500): TurnResult => ({ turnId: id, status: "error", text: "", error });

test("withModelRetry: 500 then done → one retry, dead turn listed", async () => {
  const s = scripted([dead("t1"), done("t2")]);
  const { turn, retried } = await withModelRetry(s.run, noSleep);
  assert.deepEqual(s.calls, [0, 1]);
  assert.equal(turn.turnId, "t2");
  assert.deepEqual(retried, [{ turn_id: "t1", error: E500 }]);
});

test("withModelRetry: gives up after 2 retries, last error stands", async () => {
  const s = scripted([dead("a"), dead("b"), dead("c"), done("d")]);
  const { turn, retried } = await withModelRetry(s.run, noSleep);
  assert.deepEqual(s.calls, [0, 1, 2]);
  assert.equal(turn.status, "error");
  assert.equal(turn.turnId, "c");
  assert.deepEqual(retried.map((r) => r.turn_id), ["a", "b"]);
});

test("withModelRetry: never retries a bad answer or a non-transient error", async () => {
  for (const first of [done("x", "prose, no JSON"), done("x", ""), dead("x", "[Model Error] Request failed (400): bad"), { turnId: "x", status: "cancelled", text: "" }]) {
    const s = scripted([first, done("y")]);
    const { turn, retried } = await withModelRetry(s.run, noSleep);
    assert.deepEqual(s.calls, [0]);
    assert.equal(turn, first);
    assert.deepEqual(retried, []);
  }
});

test("withModelRetry: backoff uses the delays with jitter", async () => {
  const waits: number[] = [];
  const s = scripted([dead("a"), dead("b"), done("c")]);
  await withModelRetry(s.run, { delaysMs: [1000, 3000], sleep: async (ms) => void waits.push(ms) });
  assert.equal(waits.length, 2);
  assert.ok(waits[0] >= 750 && waits[0] <= 1250, `wait 1 ${waits[0]}`);
  assert.ok(waits[1] >= 2250 && waits[1] <= 3750, `wait 2 ${waits[1]}`);
});

test("withModelRetry: a dead turn with no turn id is not retried (gate couldn't audit it)", async () => {
  const s = scripted([dead(""), done("y")]);
  const { turn, retried } = await withModelRetry(s.run, noSleep);
  assert.deepEqual(s.calls, [0]);
  assert.equal(turn.status, "error");
  assert.deepEqual(retried, []);
});

// ---------- evidence gate ----------

const SKILLS = ["profile-rubric", "listing-rewrite"];
let n = 0;
function goodTurn(id: string) {
  const events = SKILLS.flatMap((s) => {
    const cid = `c${n++}`;
    return [
      { type: "model.message", threadId: "main", toolCalls: [{ id: cid, function: { name: "exec", arguments: JSON.stringify({ command: `cat skills/${s}/SKILL.md` }) } }] },
      { type: "tool.response", threadId: "main", toolCallId: cid, content: JSON.stringify({ success: true, response: { result: `---\nname: ${s}\n---` } }) },
    ];
  });
  events.push({ type: "model.message", threadId: "main", toolCalls: [{ id: `s${n++}`, function: { name: "create_sub_agent", arguments: "{}" } }] } as any);
  return { id, previousTurnId: null, createdAt: id, state: { status: "done" }, events };
}
function deadTurn(id: string, message = E500) {
  return { id, previousTurnId: null, createdAt: id, state: { status: "error", message }, events: [] };
}
const exp = (turns: unknown[]) => ({ exported_at: "", base_url: "", session: {}, turns }) as unknown as SessionExport;
const taskIds = loadTasks().map((t) => t.id);
function runDirWith(retried: Record<number, string[]>) {
  const dir = mkdtempSync(join(tmpdir(), "retry-test-"));
  const results = taskIds.map((task_id, i) => ({ task_id, parsed: true, retried: (retried[i] ?? []).map((turn_id) => ({ turn_id, error: E500 })) }));
  writeFileSync(join(dir, "results.json"), JSON.stringify(results));
  return dir;
}
const good = () => taskIds.map((_, i) => goodTurn(`t${i}`));

test("gate: clean run passes, line shows 0 retries", () => {
  const ev = checkEvidence(exp(good()), { skills: SKILLS, runDir: runDirWith({}) });
  assert.deepEqual(ev.reasons, []);
  assert.match(ev.line, /model-error retries 0$/);
});

test("gate: dead turn listed in results.json is skipped", () => {
  const turns = good();
  turns.splice(1, 0, deadTurn("d1") as any);
  const ev = checkEvidence(exp(turns), { skills: SKILLS, runDir: runDirWith({ 1: ["d1"] }) });
  assert.deepEqual(ev.reasons, []);
  assert.match(ev.line, /^turns 6 .* model-error retries 1$/);
});

test("gate: unlisted dead turn fails (old harness / hidden retry)", () => {
  const turns = [...good(), deadTurn("d1")];
  const ev = checkEvidence(exp(turns), { skills: SKILLS, runDir: runDirWith({}) });
  assert.ok(ev.reasons.some((r) => r.includes("d1") && r.includes("not listed")), ev.reasons.join("; "));
});

test("gate: a listed turn that is not a model-error turn fails", () => {
  const ev = checkEvidence(exp(good()), { skills: SKILLS, runDir: runDirWith({ 0: ["t0"] }) });
  assert.ok(ev.reasons.some((r) => r.includes("t0") && r.includes("not a model-error")), ev.reasons.join("; "));
});

test("gate: a non-transient error turn is never skipped", () => {
  const turns = good();
  turns[2] = deadTurn("t2", "[Model Error] Request failed (400): bad") as any;
  const ev = checkEvidence(exp(turns), { skills: SKILLS, runDir: runDirWith({}) });
  assert.ok(ev.reasons.some((r) => r.includes("status error")), ev.reasons.join("; "));
});

test("gate: without --run, dead turns are skipped for skill/subagent checks", () => {
  const ev = checkEvidence(exp([...good(), deadTurn("d1")]), { skills: SKILLS });
  assert.deepEqual(ev.reasons, []);
  assert.match(ev.line, /model-error retries 1$/);
});

test("gate: old results.json without `retried` key = no retries (runs 01/02 format)", () => {
  const dir = mkdtempSync(join(tmpdir(), "retry-test-"));
  writeFileSync(join(dir, "results.json"), JSON.stringify(taskIds.map((task_id) => ({ task_id, parsed: true }))));
  assert.deepEqual(checkEvidence(exp(good()), { skills: SKILLS, runDir: dir }).reasons, []);
  const withDead = checkEvidence(exp([...good(), deadTurn("d1")]), { skills: SKILLS, runDir: dir });
  assert.ok(withDead.reasons.some((r) => r.includes("not listed")), withDead.reasons.join("; "));
});
