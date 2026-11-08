// Scrub: keep local paths, emails, keys and private hosts out of everything this repo publishes.
//
//   scrub(value)        deep copy with home-dir paths (macOS Users, Linux home) replaced by ~
//   assertClean(text)   throws if text still holds a home path, an email, a key, a private host or a session link
//   writeClean(p, v)    scrub → JSON → assertClean → write. Used for every file under runs/run-NN/ and tmp/.
//
//   npm run scan        checks every file changed since tag tf-base (plus staged/untracked files)
//                       and every commit message since tf-base. Prints "clean" or the hits.
//
// Every pattern is built from string pieces, so this file never trips its own scan.
// SCAN_DENY (git-ignored .env, comma-separated) adds private literals that must never be published.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { git, ROOT } from "./lib.ts";

const SL = "/";
const HOME_DIRS = ["Us" + "ers", "ho" + "me"];
const homePath = new RegExp(HOME_DIRS.map((d) => SL + d + SL + "[^/\"\\s]+").join("|"), "g");
const homeBare = new RegExp(HOME_DIRS.map((d) => SL + d + SL).join("|"));

const AT = "@";
const email = new RegExp("[\\w.+-]+" + AT + "[\\w-]+\\.[\\w.]+", "g");
const emailOk = [
  (e: string) => e === "noreply" + AT + "anthropic.com",
  (e: string) => e.endsWith(AT + "users.noreply.github.com"),
  (e: string) => e.endsWith(AT + "example.com"),
  (e: string) => e.endsWith(".invalid"),
];

const fixed: { name: string; re: RegExp }[] = [
  { name: "api key", re: new RegExp("\\b" + "s" + "k-[A-Za-z0-9_-]{20,}") },
  { name: "bearer token", re: new RegExp("Bea" + "rer [A-Za-z0-9._~+/-]{20,}") },
  { name: "session link", re: new RegExp("claude" + "\\.ai/code/" + "session") },
];

function denyList(): string[] {
  return (process.env.SCAN_DENY ?? "")
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Deep copy of `value` with every home-dir path in every string replaced by ~. */
export function scrub<T>(value: T): T {
  if (typeof value === "string") return value.replace(homePath, "~") as T;
  if (Array.isArray(value)) return value.map((v) => scrub(v)) as T;
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(value)) out[k] = scrub(v);
    return out as T;
  }
  return value;
}

/** Names of the problems found in `text` (never the matched values). */
export function findLeaks(text: string): string[] {
  const hits: string[] = [];
  if (homeBare.test(text)) hits.push("home-dir path");
  for (const m of text.matchAll(email)) {
    const e = m[0].replace(/\.+$/, ""); // sentence punctuation after an address
    if (!emailOk.some((ok) => ok(e))) { hits.push("email"); break; }
  }
  for (const f of fixed) if (f.re.test(text)) hits.push(f.name);
  if (denyList().some((d) => text.includes(d))) hits.push("SCAN_DENY literal");
  return hits;
}

/** Throws if `text` holds anything that must never be published. */
export function assertClean(text: string, where = "text"): void {
  const hits = findLeaks(text);
  if (hits.length) throw new Error(`${where} is not clean: ${hits.join(", ")}`);
}

/** Scrub, serialise, check, write. */
export function writeClean(path: string, value: unknown): void {
  const text = JSON.stringify(scrub(value), null, 2) + "\n";
  assertClean(text, path.replace(ROOT + SL, ""));
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text);
}

// ---------- npm run scan ----------

function lines(s: string): string[] {
  return s.split("\n").map((l) => l.trim()).filter(Boolean);
}

function scan(): void {
  try {
    git("rev-parse", "-q", "--verify", "refs/tags/tf-base");
  } catch {
    console.error("✗ tag tf-base not found (git fetch --tags)");
    process.exit(1);
  }
  const files = new Set([
    ...lines(git("diff", "--name-only", "--diff-filter=d", "tf-base")),
    ...lines(git("diff", "--name-only", "--diff-filter=d", "--cached")),
    ...lines(git("ls-files", "--others", "--exclude-standard")),
  ]);
  const problems: string[] = [];
  for (const f of [...files].sort()) {
    const p = join(ROOT, f);
    if (!existsSync(p)) continue;
    const buf = readFileSync(p);
    if (buf.includes(0)) continue; // binary
    const hits = findLeaks(buf.toString("utf8"));
    if (hits.length) problems.push(`${f}: ${hits.join(", ")}`);
  }
  const msgs = git("log", "--format=%H%n%B%n%an <%ae>%n%cn <%ce>", "tf-base..HEAD");
  for (const block of msgs.split(/\n(?=[0-9a-f]{40}\n)/)) {
    const sha = block.slice(0, 40);
    if (!sha.trim()) continue;
    const hits = findLeaks(block.slice(41));
    if (hits.length) problems.push(`commit ${sha.slice(0, 7)}: ${hits.join(", ")}`);
  }
  if (!denyList().length) console.warn("! SCAN_DENY is empty (.env): private literals are not checked");
  if (problems.length) {
    console.error(problems.join("\n"));
    console.error(`✗ not clean (${problems.length})`);
    process.exit(1);
  }
  console.log(`clean (${files.size} files, ${lines(git("rev-list", "tf-base..HEAD")).length} commits since tf-base)`);
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  if (process.argv.includes("--scan")) scan();
  else console.log("usage: npm run scan");
}
