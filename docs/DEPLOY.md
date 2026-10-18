# Deploying the run viewer

The viewer (`viewer/`) is a static page. On its own it replays recorded runs. When it can reach the live
server (`swarm/live.py`), it also offers live runs: the real swarm code, started from the dials, streamed
generation by generation. This guide puts both on your own website.

The server holds your Anthropic API key; the browser never sees it. Visitors can always replay recorded runs
and start mock runs (free, rule-based, labelled "not an LLM"). Starting a real-Claude run needs an access code
that you hand out.

## GitHub Pages: replays only, no server (the current setup)

`.github/workflows/pages.yml` publishes `viewer/` to GitHub Pages on every push to `main` that touches it.
Visitors get the guided replay of every run in `viewer/runs/`; the Live run panel stays hidden because no server
answers. Nothing runs on a server and no API key is involved. Live runs stay on your own machine (`make live`).

One-time setup for `https://aeroswarm.anjaneyabhardwaj.com`:

1. **Turn Pages on.** GitHub → the repository → Settings → Pages → Build and deployment → Source:
   **GitHub Actions**.
2. **Publish once.** Merge the viewer into `main` (or run the "Pages" workflow by hand from the Actions tab).
   The site then appears at `https://anjaneyabhardwaj.github.io/AeroSwarm/`.
3. **DNS.** At the provider that manages `anjaneyabhardwaj.com`, add one record:
   `CNAME`, name `aeroswarm`, value `anjaneyabhardwaj.github.io`. It does not affect the rest of the domain.
4. **Custom domain.** Settings → Pages → Custom domain: `aeroswarm.anjaneyabhardwaj.com` → Save. When the DNS
   check passes (minutes to a few hours), tick **Enforce HTTPS**.
5. **Recommended:** verify `anjaneyabhardwaj.com` under your GitHub account (Settings → Pages → Verified
   domains) so no other repository can claim a subdomain of it.

To add a run to the public site: export it into `viewer/runs/` (`scripts/export_run.py`), commit, push to `main`.

The sections below are for putting **live runs** on a public address as well. They need a machine that stays on.

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

## Live runs on a subdomain (needs a server)

This is layout A at `https://aeroswarm.<your-domain>`, using `deploy/`: the app container behind
[Caddy](https://caddyserver.com), a web server that obtains and renews the HTTPS certificate for the subdomain by
itself and forwards visitors to the app.

1. **A server.** Any small Linux VPS (Ubuntu 24.04 or Debian 12) with about 2 GB RAM and 10 GB disk (the image
   is about 2.5 GB). Install Docker with its Compose plugin (`curl -fsSL https://get.docker.com | sh`). Open ports
   80 and 443 in its firewall; Caddy needs both (80 for the certificate check, 443 for the site).
2. **DNS.** At your domain's DNS provider, add an `A` record: name `aeroswarm`, value the server's IP address.
   Wait until `ping aeroswarm.<your-domain>` answers from that IP.
3. **Code and settings.**
   ```bash
   git clone https://github.com/AnjaneyaBhardwaj/AeroSwarm.git && cd AeroSwarm
   cp deploy/.env.example deploy/.env
   nano deploy/.env   # DOMAIN, ANTHROPIC_API_KEY, AEROSWARM_LIVE_ACCESS_CODE, AEROSWARM_LIVE_DAILY_USD
   ```
4. **Start.**
   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```
   The first build takes several minutes (it compiles XFoil). Caddy waits until the app reports healthy (about
   20 s after it starts), then requests the certificate.
5. **Check.** Open `https://aeroswarm.<your-domain>`: the replay plays and the Live run panel appears.
   `https://aeroswarm.<your-domain>/api/health` should show `"xfoil": true` and `"access_code_required": true`.

Updating later: `git pull && docker compose -f deploy/docker-compose.yml up -d --build`. Finished runs, the daily
spend record and certificates live in Docker volumes and survive updates. Logs:
`docker compose -f deploy/docker-compose.yml logs -f aeroswarm`.

`deploy/.env` holds your API key: it is git-ignored, keep it that way.

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
