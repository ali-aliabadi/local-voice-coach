#!/usr/bin/env python3
"""Fail if a source file outgrows its line budget.

Every line in this repo is context an agent has to read before it can help. A file that
stays under the budget stays cheap to reason about and cheap to change. When one crosses
the line, split it along a real seam - a mode, a concern - rather than cutting it in half.

    python scripts/check_lines.py          # report, exit 1 if anything is over
    python scripts/check_lines.py --quiet  # only complain
"""

import sys
from pathlib import Path

LIMIT = 300  # hard cap: over this, the build fails
WARN = 240  # 80% of the cap: time to think about the seam

ROOT = Path(__file__).resolve().parent.parent
SEARCH = ["main.py", "src", "tests", "scripts"]
SKIP = {".venv", "__pycache__", ".git", "build", "dist"}


def sources() -> list[Path]:
    found = []
    for entry in SEARCH:
        target = ROOT / entry
        if target.is_file():
            found.append(target)
        elif target.is_dir():
            found += [
                path
                for path in target.rglob("*.py")
                if not SKIP & set(path.relative_to(ROOT).parts)
            ]
    return sorted(found)


def main(quiet: bool = False) -> int:
    counts = [
        (len(path.read_text(encoding="utf-8").splitlines()), path.relative_to(ROOT))
        for path in sources()
    ]
    counts.sort(reverse=True)
    over = [(n, p) for n, p in counts if n > LIMIT]

    if not quiet:
        width = max((len(str(p)) for _, p in counts), default=0)
        for lines, path in counts:
            flag = "OVER" if lines > LIMIT else "warn" if lines >= WARN else ""
            bar = "█" * round(lines / LIMIT * 24)
            print(f"  {str(path):<{width}}  {lines:>4}  {bar:<24} {flag}")
        total = sum(n for n, _ in counts)
        print(
            f"\n  {len(counts)} files, {total} lines, "
            f"largest {counts[0][0] if counts else 0}/{LIMIT}"
        )

    for lines, path in over:
        print(f"\n✗ {path} is {lines} lines, over the {LIMIT} line budget.")
        print("  Split it along a real seam, or raise LIMIT in scripts/check_lines.py and say why.")
    return 1 if over else 0


if __name__ == "__main__":
    sys.exit(main(quiet="--quiet" in sys.argv))
