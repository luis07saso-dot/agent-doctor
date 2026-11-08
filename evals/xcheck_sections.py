"""Cross-check: evals/score.ts readmeSections (TS port) == agent/scorer.py readme_sections_found (Doctor).

Usage (from the repo root): python3 evals/xcheck_sections.py   -> prints "match 10", exit 0
10 READMEs: the 6 task READMEs, Doctor's own README.md, 3 edge cases. Needs node on PATH.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from agent.scorer import readme_sections_found  # noqa: E402

docs = [json.loads(f.read_text())["profile"]["readme"] for f in sorted((ROOT / "evals" / "tasks").glob("*.json"))]
docs.append((ROOT / "README.md").read_text())
docs += [
    # a fenced "# comment" is not a heading; trailing hashes are stripped
    "# Tool\n\n```bash\n# Usage\nrun it\n```\n\n## Limitations ##\n\nNone known.\n",
    # no headings, long intro -> Summary only
    "This agent answers questions about train timetables in plain words and returns the next three departures.\n",
    # 4-space indent is not a heading; "use-case" and "Credits" match their sections
    "# Bot\n\n    ## Usage\n\n## Use-case examples\n\nx\n\n## Credits\n\ny\n",
]

script = (
    "import { readmeSections } from " + json.dumps((ROOT / "evals" / "score.ts").as_uri()) + ";"
    "let s = ''; process.stdin.on('data', (d) => (s += d));"
    "process.stdin.on('end', () => console.log(JSON.stringify(JSON.parse(s).map(readmeSections))));"
)
out = subprocess.run(["node", "--input-type=module", "-e", script], input=json.dumps(docs),
                     capture_output=True, text=True, check=True, cwd=ROOT).stdout
ts = json.loads(out)
py = [readme_sections_found(d) for d in docs]
bad = [i for i, (a, b) in enumerate(zip(ts, py)) if a != b]
if bad or len(ts) != len(py):
    for i in bad:
        print(f"MISMATCH readme {i}: ts={ts[i]} py={py[i]}")
    sys.exit(1)
print(f"match {len(py)}")
