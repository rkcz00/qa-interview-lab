"""One manual entry point: locked npm ci, then the existing isolated full QA runner."""

import os
from pathlib import Path
import shutil
import subprocess
import sys

from check_practice_backend import CheckFailed, ROOT, file_hashes, run_check


def main():
    npm = shutil.which("npm.cmd" if os.name == "nt" else "npm")
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not npm or not python.is_file():
        raise CheckFailed("PREREQUISITES=BLOCKED project Python and npm are required")
    if not (ROOT / "docs/PRACTICE_SPEC.md").is_file() or Path(__file__).resolve().parent != ROOT / "tools":
        raise CheckFailed("PROJECT=BLOCKED unexpected project path")
    before = file_hashes()
    frontend_env = {key: value for key, value in os.environ.items() if not key.startswith(("POSTGRES_", "DJANGO_", "VITE_"))}
    frontend_env["CI"] = "true"
    try:
        run_check("NPM_CI", [npm, "ci", "--no-audit", "--no-fund", "--cache", ".cache/npm"],
                  frontend_env, cwd=ROOT / "frontend", timeout=240)
    finally:
        if file_hashes() != before:
            raise CheckFailed("FILES=FAIL source or protected files changed during npm ci")
    # Keep the full runner's safe live status and cleanup output visible to the user.
    child = subprocess.Popen([str(python), "-B", str(ROOT / "tools/check_practice_backend.py")], cwd=ROOT)
    try:
        status = child.wait()
    except KeyboardInterrupt:
        try:
            status = child.wait(timeout=45)
        except subprocess.TimeoutExpired:
            print("CLEANUP=PENDING child still running; cleanup not confirmed", flush=True)
            status = 130
    raise SystemExit(status)


if __name__ == "__main__":
    try:
        main()
    except CheckFailed as error:
        print(str(error), flush=True)
        print("RESULT=FAIL", flush=True)
        raise SystemExit(1)
    except Exception as error:
        print("CHECK=FAIL exception=" + type(error).__name__ + "; private details suppressed", flush=True)
        print("RESULT=FAIL", flush=True)
        raise SystemExit(1)
