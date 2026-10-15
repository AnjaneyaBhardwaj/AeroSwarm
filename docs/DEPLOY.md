# Deploying the run viewer with live runs

The viewer (`viewer/`) is a static page. On its own it replays recorded runs. When it can reach the live
server (`swarm/live.py`), it also offers live runs: the real swarm code, started from the dials, streamed
generation by generation. This guide puts both on your own website.

The server holds your Anthropic API key; the browser never sees it. Visitors can always replay recorded runs
and start mock runs (free, rule-based, labelled "not an LLM"). Starting a real-Claude run needs an access code
that you hand out.

## What runs where

| Piece | What it is | Needs |
|---|---|---|
| Viewer | `viewer/` (HTML, CSS, JS, `runs/*.json`) | any static hosting |
| Live server | FastAPI app, `python -m swarm.live` | a machine or container that can run Python 3.11+, XFoil, and keep a process alive |

Pick one layout:

- **A. One container serves both (simplest).** The server also serves `viewer/`, so the page and the API share
  an origin and nothing needs configuring. Put it behind your site's reverse proxy at a subdomain
  (`https://aeroswarm.example.com`) or a path (`https://example.com/aeroswarm/`; the page uses relative URLs, so
  a path prefix works as long as the proxy strips it).
- **B. Page on your site, server elsewhere.** Copy `viewer/` into your site. In `viewer/index.html` set
  `<meta name="aeroswarm-api" content="https://api.example.com/">`, and on the server set
  `AEROSWARM_LIVE_ORIGINS=https://example.com` so the browser may call it (CORS).

## Build and run the container

```bash
docker build -t aeroswarm .
docker run -d --name aeroswarm --restart unless-stopped -p 8000:8000 \
  -e ANTHROPIC_API_KEY=sk-ant-... \
  -e AEROSWARM_LIVE_ACCESS_CODE='pick-a-long-random-code' \
  -e AEROSWARM_LIVE_DAILY_USD=10 \
  -v aeroswarm-data:/app/runs \
  -v aeroswarm-gallery:/app/viewer/runs/live \
  aeroswarm
```

The image builds XFoil from the Debian/Ubuntu source package (`scripts/install_xfoil.sh`), so the first build
takes a few minutes and needs to reach `deb.debian.org` and `archive.ubuntu.com`. Check the result at
`/api/health`: `"xfoil": true`. Without XFoil no design can be verified, so no run can pass; the page says so.

The two volumes keep finished runs, the daily spend record, and the live gallery across restarts and upgrades.

Hosts that run a Docker image with a persistent disk work: a VPS, Render, Fly.io, Railway. Run **one instance**:
the server keeps the active run in memory and allows one at a time, so two replicas would each start runs.

## Settings

| Variable | Meaning | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` (or `AEROSWARM_ANTHROPIC_API_KEY`) | key for real-Claude runs; without it only the mock runs | none |
| `AEROSWARM_LIVE_ACCESS_CODE` | code a visitor must enter to start a real-Claude run | none |
| `AEROSWARM_LIVE_DAILY_USD` | estimated real-Claude spend allowed per UTC day, all runs together | 10 |
| `AEROSWARM_LIVE_ORIGINS` | comma-separated origins allowed to call the API (layout B only) | none |

Fixed limits per run: at most 40 evaluations, $5 estimated cost (the visitor picks lower; default 15 and $1),
30 minutes, one run at a time.

## Safety rules the server enforces

- It refuses to listen on a public address without `AEROSWARM_LIVE_ACCESS_CODE`. (`--allow-open` overrides
  this; then anyone who finds the page can spend your credit up to the daily cap.)
- A real-Claude run reserves its full cost cap against the daily budget when it starts; the unused part is
  returned when it ends. When the day's budget is used up, real runs are refused until midnight UTC.
- Only whoever started a run can stop it (the start response carries a one-time control token).
- Costs are the run code's own estimates from token counts and `PRICES` in `swarm/llm/client.py`. Set a
  monthly limit on the API key in the Anthropic Console as the final backstop.

## Reverse proxy

Live updates use Server-Sent Events, so the proxy must not buffer responses or time them out early. The server
already sends `X-Accel-Buffering: no`; run it with `--proxy-headers` (the image does) behind a proxy.

nginx:

```nginx
location / {
    proxy_pass http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
    proxy_read_timeout 3600s;
}
```

Caddy (streams by default):

```
aeroswarm.example.com {
    reverse_proxy 127.0.0.1:8000
}
```

## Without Docker

```bash
make install && make xfoil
AEROSWARM_LIVE_ACCESS_CODE=... ANTHROPIC_API_KEY=... uv run python -m swarm.live --host 0.0.0.0 --port 8000 --proxy-headers
```

Keep it alive with systemd or your host's process manager.

## Publishing a live run as a recorded replay

Finished live runs appear in the server's gallery automatically. To ship one with the static page (for
example on GitHub Pages, which only replays), export it into `viewer/runs/` and commit the JSON:

```bash
uv run python scripts/export_run.py runs/live/<run_id> --name <short-name>
```
