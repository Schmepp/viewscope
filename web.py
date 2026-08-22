"""Launch the ViewScope web interface.

The desktop viewer is one command because Python owns the whole stack. The
web build has three moving parts -- npm packages, the exported data bundle,
and a dev server -- so this script does what a developer would otherwise do
by hand, and skips whichever steps are already done.

    uv run web.py                 dev server with hot reload, opens a browser
    uv run web.py --build         production build into web/dist
    uv run web.py --preview       serve the production build
    uv run web.py --deploy        build, then publish to Cloudflare Pages
    uv run web.py --refresh-data  re-export data/kiri before starting

Requires Node.js. Everything else it installs itself on the first run.
"""

from __future__ import annotations

import argparse
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
EXPORT_SCRIPT = ROOT / "scripts/export_web_bundle.py"
MANIFEST = WEB / "public/data/manifest.json"

DEFAULT_PORT = 5173


def fail(message: str, hint: str | None = None) -> None:
    print(f"\nerror: {message}", file=sys.stderr)
    if hint:
        print(f"       {hint}", file=sys.stderr)
    raise SystemExit(1)


def npm() -> str:
    """Locate npm, with a useful message rather than a traceback."""
    found = shutil.which("npm")
    if found is None:
        fail(
            "npm was not found on PATH",
            "Install Node.js 20 or newer: https://nodejs.org (or `brew install node`)",
        )
    return found  # type: ignore[return-value]


def run(command: list[str], cwd: Path) -> None:
    """Run a command to completion, failing the script if it fails."""
    print(f"$ {' '.join(command)}")
    result = subprocess.run(command, cwd=cwd)
    if result.returncode != 0:
        fail(f"`{' '.join(command)}` exited with {result.returncode}")


def ensure_packages() -> None:
    if (WEB / "node_modules").is_dir():
        return
    print("installing npm packages (first run only)...")
    run([npm(), "install"], cwd=WEB)


def ensure_data(refresh: bool) -> None:
    """Export data/kiri into web/public/data if it is not already there.

    The browser cannot parse .obj or .npz quickly, so the bundle is converted
    once by viewscope_core and served as flat typed-array blobs.
    """
    if MANIFEST.exists() and not refresh:
        return
    if not (ROOT / "data/kiri").is_dir():
        fail(
            "data/kiri is missing, so there is nothing to export",
            "The web interface needs the dataset that the desktop viewer reads.",
        )
    print("exporting the data bundle (this takes a few seconds)...")
    # sys.executable is the project environment uv resolved for us, which is
    # where numpy, trimesh and viewscope_core live.
    run([sys.executable, str(EXPORT_SCRIPT)], cwd=ROOT)


def port_is_open(port: int) -> bool:
    """True if anything is listening on localhost:port.

    Every address localhost resolves to has to be tried. Node binds ::1 in
    preference to 127.0.0.1, so probing IPv4 alone reports a running Vite
    server as absent.
    """
    try:
        candidates = socket.getaddrinfo("localhost", port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False

    for family, kind, proto, _canonical, address in candidates:
        with socket.socket(family, kind, proto) as probe:
            probe.settimeout(0.25)
            if probe.connect_ex(address) == 0:
                return True
    return False


def open_when_ready(url: str, port: int, timeout: float = 60.0) -> None:
    """Open a browser once the dev server is actually accepting connections.

    Vite prints its banner before the port is bound, so opening immediately
    races the server and lands on a connection-refused page.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if port_is_open(port):
            print(f"\nViewScope is running at {url}\n")
            webbrowser.open(url)
            return
        time.sleep(0.25)
    print(f"\nserver did not come up within {timeout:.0f}s; open {url} yourself\n")


def serve(script: str, port: int, should_open: bool) -> int:
    """Run a long-lived npm script, opening a browser alongside it."""
    if port_is_open(port):
        fail(
            f"port {port} is already in use",
            f"Something is already listening there. Try --port {port + 1}.",
        )

    url = f"http://localhost:{port}"
    if should_open:
        threading.Thread(target=open_when_ready, args=(url, port), daemon=True).start()

    command = [npm(), "run", script, "--", "--port", str(port), "--strictPort"]
    print(f"$ {' '.join(command)}")
    process = subprocess.Popen(command, cwd=WEB)
    try:
        return process.wait()
    except KeyboardInterrupt:
        # Ctrl-C reaches the child too; give it a moment to exit on its own
        # before insisting, so Vite can release the port cleanly.
        print("\nstopping...")
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Launch the ViewScope web interface.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--build", action="store_true", help="production build only")
    mode.add_argument(
        "--preview", action="store_true", help="serve the production build"
    )
    mode.add_argument(
        "--deploy", action="store_true", help="build and publish to Cloudflare Pages"
    )
    parser.add_argument(
        "--refresh-data", action="store_true", help="re-export data/kiri first"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help="port to serve on"
    )
    parser.add_argument("--no-open", action="store_true", help="do not open a browser")
    args = parser.parse_args()

    if not WEB.is_dir():
        fail(f"{WEB} is missing", "Expected the web/ directory next to this script.")

    ensure_packages()
    ensure_data(args.refresh_data)

    if args.build:
        run([npm(), "run", "build"], cwd=WEB)
        print(f"\nbuilt into {WEB / 'dist'}\n")
        return 0

    if args.deploy:
        # Publishes to a public URL, so make it obvious what is about to
        # happen rather than doing it silently on a mistyped flag.
        print("\nThis publishes the site publicly to Cloudflare Pages.")
        if input("Continue? [y/N] ").strip().lower() not in ("y", "yes"):
            print("cancelled")
            return 1
        run([npm(), "run", "deploy"], cwd=WEB)
        return 0

    if args.preview:
        return serve("preview", args.port, not args.no_open)

    return serve("dev", args.port, not args.no_open)


if __name__ == "__main__":
    raise SystemExit(main())
