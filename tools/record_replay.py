#!/usr/bin/env python3
"""Record copy/?replay=1 to an MP4 with headless Chrome (Playwright) + ffmpeg.

  python3 tools/record_replay.py                        # local copy of the site, 1280x720, ~40 s
  python3 tools/record_replay.py --url https://0xrenny.github.io/corgi/copy/ --out /workspace/corgi-copy-replay.mp4
"""
import argparse, functools, http.server, shutil, subprocess, sys, tempfile, threading, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", help="page to record (default: serve this repo locally)")
    ap.add_argument("--out", default="/workspace/corgi-copy-replay.mp4")
    ap.add_argument("--seconds", type=int, default=34, help="replay length passed to the page")
    ap.add_argument("--width", type=int, default=1280)
    ap.add_argument("--height", type=int, default=720)
    ap.add_argument("--theme", default="dark", choices=["dark", "light"])
    ap.add_argument("--chrome", default=shutil.which("google-chrome") or shutil.which("chromium"))
    a = ap.parse_args()
    from playwright.sync_api import sync_playwright

    srv = None
    url = a.url
    if not url:
        h = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(ROOT))
        h.log_message = lambda *x: None
        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), h)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        url = f"http://127.0.0.1:{srv.server_address[1]}/copy/"
    url += ("&" if "?" in url else "?") + f"replay=1&seconds={a.seconds}"
    tmp = Path(tempfile.mkdtemp())
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path=a.chrome, args=["--no-sandbox"]) if a.chrome else p.chromium.launch()
        ctx = b.new_context(viewport={"width": a.width, "height": a.height}, record_video_dir=str(tmp),
                            record_video_size={"width": a.width, "height": a.height}, color_scheme=a.theme)
        ctx.add_init_script(f"try{{localStorage.setItem('corgi-copy-theme','{a.theme}')}}catch(e){{}}")
        pg = ctx.new_page()
        t0 = time.time()
        pg.goto(url, wait_until="networkidle")
        pg.wait_for_selector("#finale:not([hidden])", timeout=(a.seconds + 30) * 1000)
        pg.wait_for_timeout(3500)  # hold the finale
        dur = time.time() - t0
        vid = pg.video.path()
        ctx.close(); b.close()
    if srv:
        srv.shutdown()
    # trim the blank first ~0.6 s of page load, encode H.264 for X / phones
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", "0.6", "-i", vid, "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-preset", "medium", "-crf", "20", "-r", "30", "-movflags", "+faststart", a.out], check=True)
    print(f"recorded {dur:.1f}s -> {a.out}")


if __name__ == "__main__":
    main()
