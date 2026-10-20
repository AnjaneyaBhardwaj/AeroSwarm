"""Replay GIF for the top of the README, from a viewer export: a light and a dark variant.

    uv run python scripts/replay_gif.py viewer/runs/example_hard_llm.json   # -> viewer/media/replay-{light,dark}.gif
    make readme-gif

The README shows the variant that matches the reader's GitHub theme (<picture>). Every number on a frame comes
from the export (the run ledger); the drawing is swarm/viz/replay_gif.py.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from swarm.viz.replay_gif import THEMES, load, write_gif


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("export", help="viewer/runs/<name>.json")
    ap.add_argument("--out-dir", default="viewer/media")
    ap.add_argument("--name", default="replay", help="file stem: <name>-light.gif, <name>-dark.gif")
    ap.add_argument("--themes", nargs="+", choices=sorted(THEMES), default=["light", "dark"])
    ap.add_argument("--dpi", type=int, default=100, help="100 gives 960 x 410 px")
    a = ap.parse_args(argv)
    export = load(a.export)
    for theme in a.themes:
        path = write_gif(export, Path(a.out_dir) / f"{a.name}-{theme}.gif", theme=theme, dpi=a.dpi)
        print(f"{path} ({path.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()
