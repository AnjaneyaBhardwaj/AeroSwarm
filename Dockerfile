# Aeroptimize live server: the run viewer (viewer/) plus live swarm runs (swarm/live.py). See docs/DEPLOY.md.
#
#   docker build -t aeroswarm .
#   docker run -p 8000:8000 -e ANTHROPIC_API_KEY=... -e AEROSWARM_LIVE_ACCESS_CODE=... \
#     -v aeroswarm-data:/app/runs -v aeroswarm-gallery:/app/viewer/runs/live aeroswarm

# ---- XFoil, built headless-safe (scripts/install_xfoil.sh explains why not the apt package)
FROM python:3.12-slim-bookworm AS xfoil
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends gfortran libx11-dev make patch curl ca-certificates xz-utils \
 && rm -rf /var/lib/apt/lists/*
COPY scripts/install_xfoil.sh /tmp/install_xfoil.sh
RUN bash /tmp/install_xfoil.sh /usr/local

# ---- FreeCAD (headless), for the CAD files of each finished run (swarm/cad/freecad_export.py).
# Pinned stable release from conda-forge; adds about 3.6 GB. Build with --build-arg WITH_FREECAD=0 to leave it out
# (runs then finish without CAD files, and the page says so).
FROM mambaorg/micromamba:2.3.2 AS freecad
ARG WITH_FREECAD=1
USER root
RUN if [ "$WITH_FREECAD" = "1" ]; then \
      micromamba create -y -q -p /opt/freecad -c conda-forge --override-channels "freecad=1.1.3" \
      && micromamba clean -a -y -q; \
    else mkdir -p /opt/freecad; fi

# ---- runtime
FROM python:3.12-slim-bookworm
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends libgfortran5 libx11-6 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv==0.11.32
COPY --from=xfoil /usr/local/bin/xfoil /usr/local/bin/xfoil
COPY --from=xfoil /usr/local/share/aeroswarm /usr/local/share/aeroswarm
COPY --from=freecad /opt/freecad /opt/freecad

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy MPLBACKEND=Agg PYTHONUNBUFFERED=1 \
    AEROSWARM_FREECADCMD=/opt/freecad/bin/freecadcmd
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY swarm ./swarm
COPY viewer ./viewer
COPY runs/examples ./runs/examples
RUN uv sync --frozen --no-dev \
 && useradd --create-home --uid 10001 aeroswarm \
 && mkdir -p /app/runs/live /app/runs/viewer_baselines /app/viewer/runs/live \
 && chown -R aeroswarm /app/runs /app/viewer/runs
USER aeroswarm

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4)"
# Listens on all interfaces: the server refuses to start without AEROSWARM_LIVE_ACCESS_CODE unless --allow-open.
CMD ["/app/.venv/bin/python", "-m", "swarm.live", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
