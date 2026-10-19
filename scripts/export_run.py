"""Export a run directory to the static viewer: viewer/runs/<name>.json, and refresh viewer/runs/index.json.

    uv run python scripts/export_run.py runs/examples/hard_llm_20261001-201455-faf6a3
    uv run python scripts/export_run.py runs/bench3/llm_s33 runs/bench3/llm_s44 runs/bench3/llm_s55
    uv run python scripts/export_run.py <run_dir> --optuna runs/bench4/optuna_s33   # an existing Optuna run
    uv run python scripts/export_run.py <run_dir> --optuna none                    # no comparison line

The comparison line is an Optuna TPE baseline (swarm.baselines, no LLM) from the same start, spec and
evaluation budget; Optuna's sampler seed is the run's start_seed when it has one, else 0. With
`--optuna auto` (default) it is run once into runs/viewer_baselines/<name>_optuna/ and reused after that.
Numbers come from the ledgers; agent text verbatim from traces.jsonl (swarm/viz/export.py). With FreeCAD installed
(`freecadcmd` on PATH or AEROSWARM_FREECADCMD), the start and final designs are also built as FreeCAD/STEP/.dat
files in viewer/runs/<name>_cad/ and linked from the page (`--cad none` skips them).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swarm.cad.freecad_export import cad_for_viewer
from swarm.viz.export import export_run, optuna_baseline, summarise_baseline, write_index

OUT = Path("viewer/runs")
BASELINES = Path("runs/viewer_baselines")


def optuna_for(run_dir: Path, name: str, choice: str) -> dict | None:
    if choice == "none":
        return None
    if choice != "auto":
        return summarise_baseline(choice)
    out = BASELINES / f"{name}_optuna"
    if not (out / "meta.json").exists():
        print(f"{name}: running Optuna TPE from the same start -> {out}")
    return optuna_baseline(run_dir, out)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("run_dirs", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--name", help="output name (one run only); default: the run directory's name")
    ap.add_argument("--optuna", default="auto", help="auto | none | path to an Optuna baseline run directory")
    ap.add_argument(
        "--cad",
        choices=["auto", "none"],
        default="auto",
        help="auto: build FreeCAD/STEP/.dat files of the start and final designs when FreeCAD is installed",
    )
    a = ap.parse_args(argv)
    if a.name and len(a.run_dirs) > 1:
        ap.error("--name needs exactly one run directory")
    a.out.mkdir(parents=True, exist_ok=True)
    for d in a.run_dirs:
        name = a.name or d.name
        cad = cad_for_viewer(d, a.out, f"{name}_cad", name) if a.cad == "auto" else None
        if a.cad == "auto" and cad is None:
            print(f"{name}: FreeCAD not found (set AEROSWARM_FREECADCMD), no CAD files")
        elif cad and "error" in cad:
            print(f"{name}: CAD export failed: {cad['error']}")
        data = export_run(d, name=name, baseline=optuna_for(d, name, a.optuna), cad=cad)
        path = a.out / f"{name}.json"
        path.write_text(json.dumps(data, separators=(",", ":")))
        o = data["outcome"]
        print(f"{path}: {len(data['generations'])} generations, {data['evals']} evals, {o['result']}")
    index = write_index(a.out)
    print(f"{a.out / 'index.json'}: {len(index['runs'])} runs")


if __name__ == "__main__":
    main()
