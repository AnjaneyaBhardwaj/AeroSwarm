"""Stamp the viewer pages' links to their own CSS, JS and pictures with a hash of each file (swarm/viz/stamp.py).

Run after changing any of those files; the tests fail until the stamps match.

    uv run python scripts/stamp_assets.py            # rewrite viewer/*.html
    uv run python scripts/stamp_assets.py --check    # only report (exit 1 if stale)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarm.viz.stamp import stale, stamp  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("viewer_dir", nargs="?", default="viewer")
    ap.add_argument("--check", action="store_true", help="only report stale pages; exit 1 if any")
    a = ap.parse_args()
    if a.check:
        pages = stale(a.viewer_dir)
        for p in pages:
            print(f"stale stamps: {p}")
        return 1 if pages else 0
    for p in stamp(a.viewer_dir):
        print(f"stamped {p}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
