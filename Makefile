.PHONY: install xfoil test lint format demo demo-hard clean-runs

install:
	uv sync

# Builds XFoil 6.99 headless-safe into /usr/local (see scripts/install_xfoil.sh).
xfoil:
	scripts/install_xfoil.sh

test:
	uv run pytest -q

lint:
	uv run ruff check swarm tests
	uv run ruff format --check swarm tests

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

clean-runs:
	rm -rf runs/
