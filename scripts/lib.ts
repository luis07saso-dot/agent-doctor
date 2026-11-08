// Shared helpers for the starter scripts: config, the TrueForge client, git, the agent files and the eval tasks.
// SDK: @truefoundry/trueforge-sdk (https://trueforge.dev/api/quickstart). The TypeScript SDK uses camelCase
// field names (previousTurnId, iterationLimit); the HTTP API and the docs' JSON use snake_case.

import { execFileSync } from "node:child_process";
import { existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { TrueForge, TrueForgeApi } from "@truefoundry/trueforge-sdk";
import type { Task } from "../evals/score.ts";

export const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const AGENT_DIR = join(ROOT, "agent");
export const TASKS_DIR = join(ROOT, "evals", "tasks");
export const RUNS_DIR = join(ROOT, "runs");
export const SUMMARY_CSV = join(RUNS_DIR, "summary.csv");

// ---------- config ----------

if (existsSync(join(ROOT, ".env"))) process.loadEnvFile(join(ROOT, ".env"));

export const env = {
  baseUrl: process.env.TRUEFORGE_BASE_URL ?? "http://localhost:8790",
  token: process.env.TRUEFORGE_TOKEN || undefined,
  /** Public HTTPS URL of this repo; only needed for skill_mode "git". */
  repoUrl: process.env.SKILL_REPO_URL || undefined,
};

export function client(): TrueForge {
  return new TrueForge({
    baseUrl: env.baseUrl,
    token: env.token, // only when the server has OIDC login on; local npx needs none
    timeoutInSeconds: 600, // turns stream over SSE and can take minutes
  });
}

export function die(msg: string): never {
  console.error(`\n✗ ${msg}\n`);
  process.exit(1);
}

export function flag(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

export function option(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}

// ---------- git ----------

export function git(...args: string[]): string {
  return execFileSync("git", args, { cwd: ROOT, encoding: "utf8" }).trim();
}

export function headSha(): string {
  return git("rev-parse", "HEAD");
}

/** True when these paths have no uncommitted changes (staged, unstaged or untracked). */
export function isClean(...paths: string[]): boolean {
  return git("status", "--porcelain", "--", ...paths) === "";
}

// ---------- the agent's files ----------

export interface AgentFile {
  name: string;
  description: string;
  model: { name: string; params?: Record<string, unknown> };
  /** "inline": skills are pasted into the instructions (no sandbox). "git": real TrueForge skills (needs a sandbox and a public repo). */
  skill_mode?: "inline" | "git";
}

export interface SkillFile {
  name: string;
  description: string;
  body: string;
  /** Path inside the repo, e.g. agent/skills/review-checklist */
  path: string;
}

export function readAgent(): { agent: AgentFile; instructions: string; skills: SkillFile[] } {
  const agent = JSON.parse(readFileSync(join(AGENT_DIR, "agent.json"), "utf8")) as AgentFile;
  if (process.env.TF_AGENT_NAME) agent.name = process.env.TF_AGENT_NAME;
  if (process.env.TF_MODEL) agent.model = { ...agent.model, name: process.env.TF_MODEL };
  // TF_SKILL_MODE=inline|git overrides agent.json (blank = agent.json).
  const mode = process.env.TF_SKILL_MODE;
  if (mode) {
    if (mode !== "inline" && mode !== "git") die(`TF_SKILL_MODE must be inline or git, not "${mode}"`);
    agent.skill_mode = mode;
  }
  // TF_INSTRUCTIONS_FILE=<path> replaces agent/instructions.md (used by try-skills).
  const instructionsFile = process.env.TF_INSTRUCTIONS_FILE ? resolve(ROOT, process.env.TF_INSTRUCTIONS_FILE) : join(AGENT_DIR, "instructions.md");
  const instructions = readFileSync(instructionsFile, "utf8");
  const skillsDir = join(AGENT_DIR, "skills");
  const skills: SkillFile[] = [];
  if (existsSync(skillsDir)) {
    for (const dir of readdirSync(skillsDir).sort()) {
      const file = join(skillsDir, dir, "SKILL.md");
      if (!existsSync(file)) continue;
      const { meta, body } = parseFrontmatter(readFileSync(file, "utf8"));
      skills.push({
        name: meta.name ?? dir,
        description: meta.description ?? "",
        body,
        path: `agent/skills/${dir}`,
      });
    }
  }
  return { agent, instructions, skills };
}

function parseFrontmatter(text: string): { meta: Record<string, string>; body: string } {
  const m = text.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);
  if (!m) return { meta: {}, body: text };
  const meta: Record<string, string> = {};
  for (const line of m[1].split("\n")) {
    const kv = line.match(/^(\w+):\s*(.*)$/);
    if (kv) meta[kv[1]] = kv[2].trim();
  }
  return { meta, body: m[2] };
}

/** The TrueForge agent spec built from agent/. */
export function buildManifest(gitRef?: string): TrueForgeApi.AgentSpec {
  const { agent, instructions, skills } = readAgent();
  const mode = agent.skill_mode ?? "inline";
  const config: TrueForgeApi.RuntimeConfig = {
    askUserQuestions: { enabled: false }, // evals run unattended: never pause for a question
    generativeUi: { enabled: false }, // we want plain text + JSON back
  };
  if (mode === "inline") {
    // Simplest path, no sandbox: the playbook lives in the instructions, and the agent rewrites it.
    const inlined = skills
      .map((s) => `\n\n---\n\n# Skill: ${s.name}\n\n_${s.description}_\n\n${s.body.trim()}`)
      .join("");
    return { model: agent.model, instructions: instructions.trim() + inlined, config };
  }
  // "git" mode: real TrueForge skills, cloned from this repo at the commit that runs (needs a sandbox).
  if (!gitRef) die("skill_mode git needs a git ref");
  return {
    model: agent.model,
    instructions: instructions.trim(),
    skills: skills.map((s) => ({ name: s.name })),
    config: { ...config, sandbox: { enabled: true } }, // skills require the sandbox
  };
}

/**
 * Create or update the TrueForge agent so it matches agent/ at `gitRef`.
 * agents.create / agents.update / agents.list: https://trueforge.dev/create-agent/overview#create-an-agent-via-the-api
 */
export async function syncAgent(tf: TrueForge, gitRef: string): Promise<TrueForgeApi.Agent> {
  const { agent, skills } = readAgent();
  if ((agent.skill_mode ?? "inline") === "git") {
    if (!env.repoUrl) die("skill_mode is \"git\": set SKILL_REPO_URL in .env to your public GitHub repo URL.");
    const { data: caps } = await tf.server.getCapabilities();
    if (!caps.skill.enabled) {
      die(
        `skill_mode is "git" but this TrueForge server can't run skills: ${caps.skill.reason ?? "no sandbox"}\n` +
          `  Local npx: on Linux install bubblewrap, socat and ripgrep, then restart TrueForge (macOS needs no extra packages).\n` +
          `  Or configure Daytona in Settings → Sandbox providers. Or go back to "skill_mode": "inline" (no sandbox needed).`,
      );
    }
    // Register each skill from this repo, pinned to the commit that runs.
    // settings.skills.createOrUpdate: https://trueforge.dev/api-reference/skills/create-or-replace-a-skill
    // TODO(verify): end to end with a pushed public repo; the commit must be pushed before the run.
    for (const s of skills) {
      await tf.settings.skills.createOrUpdate({
        manifest: { type: "git", name: s.name, description: s.description, url: env.repoUrl, path: s.path, ref: gitRef },
      });
    }
  }
  const manifest = buildManifest(gitRef);
  const existing = await findAgent(tf, agent.name);
  if (existing) {
    const { data } = await tf.agents.update(existing.id, { description: agent.description, manifest });
    return data;
  }
  const { data } = await tf.agents.create({ name: agent.name, description: agent.description, manifest });
  return data;
}

export async function findAgent(tf: TrueForge, name: string): Promise<TrueForgeApi.Agent | undefined> {
  const page = await tf.agents.list({ agentName: name }); // substring match, so check the exact name
  for await (const a of page) if (a.name === name) return a;
  return undefined;
}

// ---------- tasks ----------

// Task file schema (evals/tasks/NN-slug.json) lives with the scorer, so `npm run score` needs no SDK.
export type { Task } from "../evals/score.ts";

export function loadTasks(): Task[] {
  return readdirSync(TASKS_DIR)
    .filter((f) => f.endsWith(".json"))
    .sort()
    .map((f) => JSON.parse(readFileSync(join(TASKS_DIR, f), "utf8")) as Task);
}

/** The message the agent gets for one task. Same text every run. */
export function taskPrompt(t: Task): string {
  return [
    "Check this agent listing and fix its text.",
    "",
    `Owner's note on what it does: ${t.job}`,
    "",
    "Profile snapshot:",
    "",
    "```json",
    JSON.stringify(t.profile, null, 2),
    "```",
  ].join("\n");
}

// ---------- turns and sessions ----------

/** Text of a final model message (string or content parts). */
export function messageText(msg: TrueForgeApi.ModelMessageEvent | null | undefined): string {
  const c = msg?.content;
  if (!c) return "";
  if (typeof c === "string") return c;
  return c.map((p) => ("text" in p ? p.text : "")).join("");
}

export interface TurnResult {
  turnId: string;
  status: string;
  text: string;
  error?: string;
}

/**
 * Run one turn and wait for turn.done. `previousTurnId: "none"` makes it a new root turn,
 * so tasks in the same session don't see each other.
 * createTurnStream: https://trueforge.dev/api/use-agent#create-and-stream-a-turn
 */
export async function runTurn(tf: TrueForge, sessionId: string, content: string, root = true): Promise<TurnResult> {
  const stream = await tf.sessions.createTurnStream(
    sessionId,
    { input: [{ type: "user.message", content }], ...(root ? { previousTurnId: "none" } : {}) },
    { maxRetries: 0 }, // a retried POST would start a second turn
  );
  let turnId = "";
  for await (const { data: event } of stream.withMetadata()) {
    if (event.type === "turn.created") turnId = event.turnId;
    if (event.type === "turn.done") {
      const s = event.state;
      if (s.status === "done") return { turnId, status: s.status, text: messageText(s.output) };
      if (s.status === "error") return { turnId, status: s.status, text: "", error: s.message };
      return { turnId, status: s.status, text: "" };
    }
  }
  return { turnId, status: "no-turn-done", text: "" };
}

/**
 * A turn that died because the model provider failed (HTTP 429 or 5xx), not because of the agent.
 * TrueForge 0.184.2 does not retry these itself: its model HTTP client retries only
 * 408/429/503/521-523/530 (+409/502/520/524) and the AI SDK call runs with maxRetries 0, so one
 * asi1 500 ends the whole turn as `[Model Error] Request failed (500): internal server error`.
 * ASI:One's docs say: retry 429, 500 and 502 with backoff, a small number of times
 * (https://docs.asi1.ai/documentation/build-with-asi-one/errors).
 */
export function isTransientModelError(status: string, error?: string): boolean {
  return status === "error" && /^\[Model Error\] Request failed \((429|5\d\d)\)/.test(error ?? "");
}

/** A turn that was thrown away and run again because of a transient model error. */
export interface RetriedTurn {
  turn_id: string;
  error: string;
}

/** Backoff before retry 1 and retry 2 (±25% jitter). Two retries, then the error stands. */
export const MODEL_RETRY_DELAYS_MS = [10_000, 30_000];

/**
 * Run a turn; if it ends in a transient model error, wait and run the same input again as a
 * fresh turn. Any other outcome (done, cut-off reply, unparsed JSON, other errors) is returned
 * as is: only provider failures are retried, never a bad answer.
 */
export async function withModelRetry(
  run: (attempt: number) => Promise<TurnResult>,
  opts: { delaysMs?: number[]; sleep?: (ms: number) => Promise<void>; log?: (msg: string) => void } = {},
): Promise<{ turn: TurnResult; retried: RetriedTurn[] }> {
  const delays = opts.delaysMs ?? MODEL_RETRY_DELAYS_MS;
  const sleep = opts.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));
  const retried: RetriedTurn[] = [];
  for (let attempt = 0; ; attempt++) {
    const turn = await run(attempt);
    // No turn id (stream ended before turn.created) = the gate can't match it to the session: don't retry.
    if (!isTransientModelError(turn.status, turn.error) || !turn.turnId || attempt >= delays.length) return { turn, retried };
    retried.push({ turn_id: turn.turnId, error: turn.error ?? "" });
    const ms = Math.round(delays[attempt] * (0.75 + Math.random() * 0.5));
    opts.log?.(`[${turn.error}; retry ${attempt + 1}/${delays.length} in ${Math.round(ms / 1000)}s] `);
    await sleep(ms);
  }
}

/**
 * Everything TrueForge keeps about a session: the session, every turn, and every turn's events.
 * There is no export endpoint, so we page through sessions.get / listTurns / listTurnEvents.
 * https://trueforge.dev/sessions and https://trueforge.dev/api-reference/agent-sessions/list-turn-events
 */
export async function exportSession(tf: TrueForge, sessionId: string) {
  const { data: session } = await tf.sessions.get(sessionId);
  const turns: (TrueForgeApi.Turn & { events: TrueForgeApi.SessionEvent[] })[] = [];
  for await (const turn of await tf.sessions.listTurns(sessionId)) {
    const events: TrueForgeApi.SessionEvent[] = [];
    for await (const e of await tf.sessions.listTurnEvents(sessionId, turn.id, { order: "asc" })) events.push(e);
    turns.push({ ...turn, events });
  }
  turns.sort((a, b) => a.createdAt.localeCompare(b.createdAt));
  return { exported_at: new Date().toISOString(), base_url: env.baseUrl, session, turns };
}

export type SessionExport = Awaited<ReturnType<typeof exportSession>>;

/** Tokens and tool calls for a whole session, from its export. */
export function sessionStats(exp: SessionExport): { tokens: number; toolCalls: number } {
  let tokens = 0;
  let toolCalls = 0;
  for (const t of exp.turns) {
    const metrics = "metrics" in t.state ? t.state.metrics : undefined;
    tokens += metrics?.totalTokens ?? 0;
    for (const e of t.events) if (e.type === "model.message") toolCalls += e.toolCalls?.length ?? 0;
  }
  return { tokens, toolCalls };
}

export function writeJson(path: string, value: unknown): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(value, null, 2) + "\n");
}

export function runDir(n: number): string {
  return join(RUNS_DIR, `run-${String(n).padStart(2, "0")}`);
}
