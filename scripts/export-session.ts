// npm run export-session -- <session_id> [out.json]
// Saves a TrueForge session (the session, its turns and every turn's events) as JSON.
// run-evals and improve call this for you; use it by hand for any other session (e.g. one you ran in the UI).

import { client, die, exportSession } from "./lib.ts";
import { assertClean, scrub, writeClean } from "./scrub.ts";

const [sessionId, out] = process.argv.slice(2);
if (!sessionId) die("usage: npm run export-session -- <session_id> [out.json]");

// Scrubbed: home-dir paths become ~ and the output must pass assertClean (scripts/scrub.ts).
const exp = scrub(await exportSession(client(), sessionId));
if (out) {
  writeClean(out, exp);
  console.log(`✓ ${exp.turns.length} turns → ${out}`);
} else {
  const text = JSON.stringify(exp, null, 2);
  assertClean(text, "session export");
  console.log(text);
}
