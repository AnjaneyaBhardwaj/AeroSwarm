"""Every viewer page links its own CSS, JS and pictures with a hash of the current file (swarm/viz/stamp.py), so a
browser never pairs a freshly deployed page with a stylesheet or script it cached before the deploy."""

import re
from pathlib import Path

from swarm.viz.stamp import ASSET, file_hash, stale, stamp, stamped

VIEWER = Path("viewer")


def test_viewer_stamps_are_current():
    assert stale(VIEWER) == [], "run: uv run python scripts/stamp_assets.py"


def test_every_local_asset_link_is_stamped():
    for page in VIEWER.glob("*.html"):
        html = page.read_text()
        for ref in re.findall(r'(?:href|src)="([\w./-]+\.(?:css|js|png|gif|jpg|svg|webp))[^"]*"', html):
            assert f'{ref}?v={file_hash(VIEWER / ref)}"' in html, (page.name, ref)
    assert ASSET.search('<link rel="stylesheet" href="style.css">')


def test_stamp_rewrites_only_local_files(tmp_path):
    (tmp_path / "a.css").write_text("body { color: red; }")
    page = tmp_path / "index.html"
    page.write_text(
        '<link href="a.css?v=0000000000"><script src="https://cdn.example/x.js"></script>'
        '<img src="missing.png"><a href="replay.html">'
    )
    assert stale(tmp_path) == ["index.html"]
    assert stamp(tmp_path) == ["index.html"] and stale(tmp_path) == []
    h = file_hash(tmp_path / "a.css")
    assert page.read_text() == (
        f'<link href="a.css?v={h}"><script src="https://cdn.example/x.js"></script>'
        '<img src="missing.png"><a href="replay.html">'
    )
    (tmp_path / "a.css").write_text("body { color: blue; }")  # a changed file gets a new address
    assert stamped(page.read_text(), tmp_path) != page.read_text()
