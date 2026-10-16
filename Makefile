.PHONY: install xfoil test lint format demo demo-hard viewer viewer-export live clean-runs

install:
	uv sync

# Builds XFoil 6.99 headless-safe into /usr/local (see scripts/install_xfoil.sh).
xfoil:
	scripts/install_xfoil.sh

test:
	uv run pytest -q

lint:
	uv run ruff check swarm tests scripts
	uv run ruff format --check swarm tests scripts

format:
	uv run ruff format swarm tests
	uv run ruff check --fix swarm tests

# Full optimization: real LLM when AEROSWARM_ANTHROPIC_API_KEY (or ANTHROPIC_API_KEY) is set, labelled mock otherwise.
demo:
	uv run python -m swarm.run

# Smoke test above; this one targets 85% of attached Cl,max at Re 3e5. With the mock the
# NeuralFoil screen blocks every near-target candidate (no stall margin), so nothing is
# promoted to XFoil and it does not reach target_met.
# Needs the xfoil binary (make xfoil). Pinned to the mock so the path is reproducible.
demo-hard:
	uv run python -m swarm.run --preset hard --llm mock

# Static run viewer (viewer/): export the example run, then serve on http://localhost:8000
viewer-export:
	uv run python scripts/export_run.py runs/examples/hard_llm_20261001-201455-faf6a3 --name example_hard_llm

viewer:
	python3 -m http.server 8000 -d viewer

# Viewer + live runs (local only): http://127.0.0.1:8000. Real-LLM runs need AEROSWARM_ANTHROPIC_API_KEY
# (or ANTHROPIC_API_KEY); every run is capped (default 15 evaluations, $1). Without a key only the mock runs.
live:
	uv run python -m swarm.live

clean-runs:
	rm -rf runs/
