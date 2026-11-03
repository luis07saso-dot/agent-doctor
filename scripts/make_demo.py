"""Build the S6 demo video from raw ASI:One screen recordings (docs/demo-video.md).

Usage (sandbox off: chrome-headless-shell needs mach ports):
    python3 scripts/make_demo.py            # -> media/demo-v1.mp4 (1080x1080)

Inputs: media/raw/{A-audit,B-fix1,C-prehire}.mov (+ optional D-profile.mov, the Agentverse profile).
All chat footage is real and unedited apart from crop, cut, freeze-frame and
labelled speed-ups. Cards are text only.
"""
from __future__ import annotations

import html
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "media" / "raw"
OUT = ROOT / "media" / "demo-v1.mp4"
CHROME = Path.home() / (
    "Library/Caches/ms-playwright/chromium_headless_shell-1228/"
    "chrome-headless-shell-mac-arm64/chrome-headless-shell"
)
W, BAND = 1080, 170  # square output; caption band on top
VH = W - BAND  # 910: video area under the band
FPS = 30
GREEN = "#4ade80"
BG = "#121212"
FONT = "-apple-system, Helvetica Neue, Helvetica, Arial, sans-serif"  # no quotes: goes inside style='...'

# Crops in source pixels (2274x1676 recordings), all with the 1080:910 aspect.
CROP_PROFILE_TOP = (400, 40, 1620, 1365)
CROP_PROFILE_BOTTOM = (400, 311, 1620, 1365)
CROP_CHAT = (420, 150, 1580, 1331)
CROP_COMPOSER = (420, 345, 1580, 1331)
CROP_PREHIRE = (420, 362, 1560, 1314)  # as low as the source allows: trims most of the link-preview thumbnail
CROP_PROFILE_D = (100, 623, 1250, 1053)  # left column only: header + README (skips owner-only side panel)


def run(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"FAILED: {' '.join(cmd[:6])}...\n{r.stderr[-1500:]}")


def render(html_body: str, size: tuple[int, int], out: Path) -> Path:
    page = out.with_suffix(".html")
    page.write_text(
        f"<html><body style='margin:0;width:{size[0]}px;height:{size[1]}px;"
        f"background:{BG};color:#fff;font-family:{FONT};overflow:hidden'>{html_body}</body></html>"
    )
    run([str(CHROME), "--no-sandbox", "--hide-scrollbars", f"--window-size={size[0]},{size[1]}",
         f"--screenshot={out}", page.as_uri()])
    return out


def caption_png(text: str, note: str, out: Path) -> Path:
    note_html = f"<div style='font-size:26px;color:#9ca3af;margin-top:8px'>{html.escape(note)}</div>" if note else ""
    body = (
        f"<div style='height:{BAND}px;display:flex;flex-direction:column;justify-content:center;"
        f"padding:0 48px;border-bottom:4px solid {GREEN};box-sizing:border-box'>"
        f"<div style='font-size:44px;font-weight:700;line-height:1.15'>{text}</div>{note_html}</div>"
    )
    return render(body, (W, BAND), out)


def card_png(inner: str, out: Path) -> Path:
    body = (
        f"<div style='width:{W}px;height:{W}px;display:flex;flex-direction:column;justify-content:center;"
        f"padding:0 90px;box-sizing:border-box'>{inner}</div>"
    )
    return render(body, (W, W), out)


def enc_args(out: Path) -> list[str]:
    return ["-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-an", str(out)]


def clip(src: Path, start: float, end: float, crop, cap: Path, out: Path, speed: float = 1.0) -> Path:
    x, y, w, h = crop
    vf = (f"[0:v]trim={start}:{end},setpts=(PTS-STARTPTS)/{speed},crop={w}:{h}:{x}:{y},"
          f"scale={W}:{VH}:flags=lanczos,pad={W}:{W}:0:{BAND}:color={BG}[v];[v][1:v]overlay=0:0")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(src), "-i", str(cap),
         "-filter_complex", vf, *enc_args(out)])
    return out


def freeze(src: Path, at: float, secs: float, crop, cap: Path, out: Path) -> Path:
    """Hold one real frame (for reading time)."""
    frame = out.with_suffix(".png")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", str(at), "-i", str(src),
         "-frames:v", "1", str(frame)])
    x, y, w, h = crop
    vf = (f"[0:v]crop={w}:{h}:{x}:{y},scale={W}:{VH}:flags=lanczos,pad={W}:{W}:0:{BAND}:color={BG}[v];"
          f"[v][1:v]overlay=0:0")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-t", str(secs), "-i", str(frame),
         "-i", str(cap), "-filter_complex", vf, *enc_args(out)])
    return out


def still(png: Path, secs: float, out: Path) -> Path:
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-loop", "1", "-t", str(secs),
         "-i", str(png), "-vf", f"scale={W}:{W}", *enc_args(out)])
    return out


def main() -> None:
    a, b, c = (RAW / f"{n}.mov" for n in ("A-audit", "B-fix1", "C-prehire"))
    for f in (a, b, c):
        if not f.is_file():
            sys.exit(f"missing {f}")
    tmp = Path(tempfile.mkdtemp(prefix="demo-"))
    g = f"style='color:{GREEN}'"

    title = card_png(
        "<div style='font-size:84px;font-weight:800;line-height:1.1'>"
        "Why is nobody finding my agent on Agentverse?</div>"
        f"<div style='font-size:44px;margin-top:40px;color:#d1d5db'>Ask <span {g}>Agent Doctor</span>.</div>",
        tmp / "title.png")
    r11 = card_png(
        "<div style='font-size:40px;color:#9ca3af'>Does it work?</div>"
        "<div style='font-size:64px;font-weight:800;margin-top:20px;line-height:1.15'>"
        f"Our own test agent followed the fixes: <span {g}>12 → 72/100</span></div>"
        "<div style='font-size:30px;color:#9ca3af;margin-top:36px'>Before/after audits: docs/r11 in our repo</div>",
        tmp / "r11.png")
    end = card_png(
        f"<div style='font-size:96px;font-weight:800'><span {g}>Agent Doctor</span></div>"
        "<div style='font-size:46px;margin-top:24px'>Free on ASI:One. Type:</div>"
        "<div style='font-size:38px;margin-top:20px;font-family:Menlo,monospace;background:#1f2937;"
        "padding:18px 26px;border-radius:12px'>@agent-doctor audit my-agent-name</div>"
        "<div style='font-size:30px;color:#9ca3af;margin-top:44px'>Score · top 3 fixes · step-by-step help · Pre-Hire Check<br>"
        "Built at Stranger Builds on Fetch.ai Agentverse</div>",
        tmp / "end.png")

    cap = {k: caption_png(t, n, tmp / f"cap_{k}.png") for k, (t, n) in {
        "p2": ("Agent Doctor audits any Agentverse agent", "Live on ASI:One. Real chat, no mockups"),
        "a": (f"Score <span {g}>77/100</span> + the top 3 fixes", "agent-listing-generator, with the points each fix adds"),
        "b1": ("Ask how to fix #1", "Waiting sped up 2×"),
        "b2": (f"<span {g}>Step-by-step</span> + a copy-paste example", ""),
        "c1": ("Hiring an agent? Check it first", "Doctor sends it one test message. Waiting sped up 4×"),
        "c2": (f"Agentverse says “unresponsive”. Doctor: <span {g}>LIVE</span>", "ticketlens-agent answered the test message: ack 0.9 s, answer 5.0 s"),
        "d1": (f"Listed on Agentverse: <span {g}>Active</span>, ASI Available", "Agent Doctor's profile"),
        "d2": ("A full README: what search reads first", "Summary · Key features · Usage · Use cases · Limitations"),
    }.items()}

    parts = [
        still(title, 3.0, tmp / "00.mp4"),
        clip(a, 3.0, 5.8, CROP_PROFILE_BOTTOM, cap["p2"], tmp / "02.mp4"),
        freeze(a, 17.0, 6.0, CROP_CHAT, cap["a"], tmp / "03.mp4"),
        clip(b, 3.8, 7.0, CROP_COMPOSER, cap["b1"], tmp / "04.mp4"),
        clip(b, 7.0, 11.0, CROP_CHAT, cap["b1"], tmp / "05.mp4", speed=2.0),
        freeze(b, 17.5, 4.0, CROP_CHAT, cap["b2"], tmp / "06.mp4"),
        clip(b, 19.0, 21.0, CROP_CHAT, cap["b2"], tmp / "07.mp4"),
        clip(c, 1.5, 3.3, CROP_COMPOSER, cap["c1"], tmp / "08.mp4"),
        clip(c, 3.3, 13.0, CROP_PREHIRE, cap["c1"], tmp / "09.mp4", speed=4.0),
        freeze(c, 16.0, 6.0, CROP_PREHIRE, cap["c2"], tmp / "10.mp4"),
    ]
    d = RAW / "D-profile.mov"
    if d.is_file():
        parts += [
            freeze(d, 1.0, 3.0, CROP_PROFILE_D, cap["d1"], tmp / "11a.mp4"),
            clip(d, 9.5, 13.5, CROP_PROFILE_D, cap["d2"], tmp / "11b.mp4"),
        ]
    parts.append(still(r11, 3.5, tmp / "11.mp4"))
    parts.append(still(end, 5.0, tmp / "12.mp4"))

    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    OUT.parent.mkdir(exist_ok=True)
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest", "-c:v", "copy",
         "-c:a", "aac", "-b:a", "64k", "-movflags", "+faststart", str(OUT)])
    print(OUT, f"(tmp {tmp})")


if __name__ == "__main__":
    main()
