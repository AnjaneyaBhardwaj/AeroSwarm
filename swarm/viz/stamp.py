"""Version stamps for the viewer's own files: `style.css?v=<hash>`.

GitHub Pages lets browsers keep a file for 10 minutes, so right after a deploy a visitor could get the new page with
the old stylesheet or script. Each link to a local stylesheet, script or picture carries a short hash of the file it
points to; a changed file gets a new address and is fetched fresh. `scripts/stamp_assets.py` rewrites the stamps and
the tests fail while any is stale.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

ASSET = re.compile(r'((?:href|src)=")([\w./-]+\.(?:css|js|png|gif|jpg|svg|webp))(?:\?v=[0-9a-f]*)?(")')


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:10]


def stamped(html: str, base: Path) -> str:
    """`html` with every local asset link stamped with its file's current hash (paths relative to `base`)."""

    def sub(m: re.Match) -> str:
        target = base / m.group(2)
        if not target.is_file():  # leave it alone; the link tests report missing files
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}?v={file_hash(target)}{m.group(3)}"

    return ASSET.sub(sub, html)


def stale(viewer_dir: str | Path = "viewer") -> list[str]:
    """Pages in `viewer_dir` whose stamps do not match their files."""
    viewer_dir = Path(viewer_dir)
    return [p.name for p in sorted(viewer_dir.glob("*.html")) if stamped(p.read_text(), viewer_dir) != p.read_text()]


def stamp(viewer_dir: str | Path = "viewer") -> list[str]:
    """Rewrite the stamps in place; returns the pages that changed."""
    viewer_dir = Path(viewer_dir)
    changed = []
    for p in sorted(viewer_dir.glob("*.html")):
        old = p.read_text()
        new = stamped(old, viewer_dir)
        if new != old:
            p.write_text(new)
            changed.append(p.name)
    return changed
