#!/usr/bin/env python3
"""
GeoSentinel-NER SimReady preflight wrapper.

Thin, Windows-safe wrapper around NVIDIA omniverse-cad-to-simready
preflight (references/preflight/scripts/preflight.py) for conversion-only
workflows. On hosts without GPU / Docker / Content Agents, this wrapper
runs in --skip-content-agents mode and writes a local manifest so
downstream convert-to-usd / validate-usd-minimum can run without the
full Linux GPU stack.

Usage (matches skill contracts):
  python scripts/simready_preflight.py --skip-content-agents --env-file .simready-env --report preflight.json
  python scripts/simready_preflight.py --check-only --skip-content-agents

For full end-to-end (Material+Physics) on a Linux GPU host, delegate to the
skill's upstream preflight directly:
  python .agents/skills/omniverse-cad-to-simready/references/preflight/scripts/preflight.py \
    --env-file $HOME/.omniverse-cad-to-simready/state/cad-to-simready-preflight.env \
    --report $OUTPUT_ROOT/cad-to-simready-preflight.json

See .agents/skills/omniverse-cad-to-simready/references/preflight/README.md
"""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SKILL_PREFLIGHT = (
    REPO_ROOT / ".agents" / "skills" / "omniverse-cad-to-simready"
    / "references" / "preflight" / "scripts" / "preflight.py"
)


def check(cmd: list[str]) -> bool:
    return shutil.which(cmd[0]) is not None


def try_upstream(args: list[str]) -> int | None:
    """If the skill's upstream preflight exists and Python 3.12 is available, delegate."""
    if not SKILL_PREFLIGHT.exists():
        return None
    # Prefer python3.12 when available, else current interpreter for conversion-only checks
    py = shutil.which("python3.12") or shutil.which("python3") or sys.executable
    try:
        result = subprocess.run([py, str(SKILL_PREFLIGHT), *args], check=False)
        return result.returncode
    except Exception as e:
        print(f"[simready-preflight] upstream delegate failed: {e}", file=sys.stderr)
        return None


def main() -> int:
    p = argparse.ArgumentParser(description="GeoSentinel SimReady preflight (conversion-only default)")
    p.add_argument("--skip-content-agents", action="store_true", help="Skip Content Agents (valid for conversion-only)")
    p.add_argument("--skip-deploy", action="store_true", help="Verify endpoints but do not deploy")
    p.add_argument("--check-only", action="store_true", help="Read-only readiness check")
    p.add_argument("--env-file", type=str, default="", help="POSIX env file to write")
    p.add_argument("--powershell-env-file", type=str, default="", help="PowerShell env file to write")
    p.add_argument("--report", type=str, default="", help="JSON report path")
    p.add_argument("--markdown-report", type=str, default="", help="Markdown report path")
    p.add_argument("--output-root", type=str, default="", help="Workflow output root to verify writable")
    args = p.parse_args()

    # If caller asked for full Content Agents deploy on Linux, delegate to upstream
    if not args.skip_content_agents and platform.system() != "Windows" and SKILL_PREFLIGHT.exists():
        passthrough = []
        if args.skip_deploy:
            passthrough.append("--skip-deploy")
        if args.check_only:
            passthrough.append("--check-only")
        if args.env_file:
            passthrough.extend(["--env-file", args.env_file])
        if args.powershell_env_file:
            passthrough.extend(["--powershell-env-file", args.powershell_env_file])
        if args.report:
            passthrough.extend(["--report", args.report])
        if args.markdown_report:
            passthrough.extend(["--markdown-report", args.markdown_report])
        rc = try_upstream(passthrough)
        if rc is not None:
            return rc

    # Lightweight local preflight (Windows / conversion-only): no GPU/Docker required
    now = datetime.now(timezone.utc).isoformat()
    checks = {
        "python": f"{platform.python_version()} ({sys.executable})",
        "python312": bool(shutil.which("python3.12")),
        "uv": bool(shutil.which("uv")),
        "git": bool(shutil.which("git")),
        "git-lfs": bool(shutil.which("git-lfs")),
        "docker": bool(shutil.which("docker")),
        "nvidia-smi": bool(shutil.which("nvidia-smi")),
        "platform": platform.platform(),
        "skill_preflight_present": SKILL_PREFLIGHT.exists(),
        "mode": "conversion-only (skip-content-agents)" if args.skip_content_agents else "check-only",
    }
    output_writable = True
    if args.output_root:
        try:
            Path(args.output_root).mkdir(parents=True, exist_ok=True)
            test = Path(args.output_root) / ".writetest"
            test.write_text("ok", encoding="utf-8")
            test.unlink()
        except Exception:
            output_writable = False

    manifest = {
        "status": "ready" if output_writable else "blocked",
        "targets": (
            ["conversion", "validation"] if args.skip_content_agents
            else ["conversion", "validation", "content-agents"]
        ),
        "generated_at": now,
        "checks": checks,
        "output_root_writable": output_writable,
        "upstream_version_policy": "pinned-tested-integration (see upstream-versions.lock.json)",
        "note": (
            "Lightweight preflight — for full Content Agents deploy, "
            "use the skill's upstream preflight on a Linux GPU host."
        ),
    }

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"[simready-preflight] report → {args.report}")

    md = f"""# SimReady Preflight — GeoSentinel (conversion-only)
**Status:** `{manifest['status']}` · **Generated:** `{now}`

## Checks
- Python: `{checks['python']}`
- uv: `{checks['uv']}`
- git: `{checks['git']}`
- docker: `{checks['docker']}` (not required for conversion-only)
- nvidia-smi: `{checks['nvidia-smi']}` (not required for conversion-only)
- Output writable: `{output_writable}`

## Next
Source the env file, then run `convert-to-usd` → `validate-usd-minimum`.
For Material/Physics assignment, re-run without `--skip-content-agents` on a Linux GPU host per skill README.
"""
    if args.markdown_report:
        Path(args.markdown_report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.markdown_report).write_text(md, encoding="utf-8")
        print(f"[simready-preflight] markdown → {args.markdown_report}")

    env_content = f"""# GeoSentinel SimReady preflight env — generated {now}
export PHYSICAL_AI_PREFLIGHT_MANIFEST="{args.report or ''}"
export PHYSICAL_AI_REQUIRE_PREFLIGHT=1
export OMNIVERSE_CAD_TO_SIMREADY_HOME="{REPO_ROOT}"
"""
    if args.env_file:
        Path(args.env_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.env_file).write_text(env_content, encoding="utf-8")
        print(f"[simready-preflight] env → {args.env_file}")
    if args.powershell_env_file:
        ps_content = f"""# GeoSentinel SimReady preflight — {now}
$env:PHYSICAL_AI_PREFLIGHT_MANIFEST = "{args.report or ''}"
$env:PHYSICAL_AI_REQUIRE_PREFLIGHT = "1"
$env:OMNIVERSE_CAD_TO_SIMREADY_HOME = "{REPO_ROOT}"
"""
        Path(args.powershell_env_file).parent.mkdir(parents=True, exist_ok=True)
        Path(args.powershell_env_file).write_text(ps_content, encoding="utf-8")
        print(f"[simready-preflight] ps env → {args.powershell_env_file}")

    if args.check_only:
        print(json.dumps(manifest, indent=2))

    if not output_writable:
        print("[simready-preflight] blocked: output_root not writable", file=sys.stderr)
        return 2
    print(f"[simready-preflight] ready — {checks['mode']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
