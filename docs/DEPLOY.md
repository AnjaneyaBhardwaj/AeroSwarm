# Deploying the run viewer

The viewer (`viewer/`) is a static page. On its own it replays recorded runs. When it can reach the live
server (`swarm/live.py`), it also offers live runs: the real swarm code, started from the dials, streamed
generation by generation. This guide puts both on your own website.

The server holds your Anthropic API key; the browser never sees it. Visitors can always replay recorded runs
and start mock runs (free, rule-based, labelled "not an LLM"). Starting a real-Claude run needs an access code
that you hand out.

## Public replay site on GitHub Pages (the chosen setup)

`.github/workflows/pages.yml` publishes `viewer/` to GitHub Pages whenever a push to `main` changes it. Visitors get
the guided replay of every run in `viewer/runs/` and its CAD downloads; the Live run panel stays hidden because no
server answers. Nothing runs on a server and no API key is online. Live runs happen on your Mac (next section).

One-time setup:

1. **Turn Pages on.** GitHub → the repository → Settings → Pages → Build and deployment → Source:
   **GitHub Actions**. (Pages on a free account needs a public repository.)
2. **Publish once.** Run the "Pages" workflow by hand from the Actions tab (or push a change under `viewer/`).
   The site appears at `https://<github-user>.github.io/Aeroptimize/`.
3. **DNS.** At the provider that manages your domain, add one record: `CNAME`, name `aeroswarm`, value
   `<github-user>.github.io`. It does not affect the rest of the domain.
4. **Custom domain.** Settings → Pages → Custom domain: `aeroswarm.<your-domain>` → Save. When the DNS check passes
   (minutes to a few hours), tick **Enforce HTTPS**.
5. **Recommended:** verify your domain under your GitHub account (Settings → Pages → Verified domains), so no other
   repository can claim a subdomain of it.

To add a run to the site: export it into `viewer/runs/` (`make local-export`), commit, and merge into `main`.

The server sections further down are for always-on live runs, if you want them later. A DNS name points at one
place: moving the subdomain to a server means replacing the CNAME with the server's `A` record.

## On your Mac: live runs on your own computer

The simplest way to run live: the same Docker image as the server, on your Mac, reachable only from that Mac at
`http://localhost:8000`. No domain, HTTPS, access code or cloud bill. Works on Apple Silicon (built natively for
ARM) and Intel Macs.

1. **Install** [Docker Desktop](https://www.docker.com/products/docker-desktop/) (free for personal use) and start
   it. In its Settings → Resources, give it at least 4 GB of memory; the image needs about 15 GB of disk.
   `make` comes with Apple's command-line tools (`xcode-select --install` if `make` is missing).
2. **Get the code:** `git clone https://github.com/AnjaneyaBhardwaj/Aeroptimize.git && cd Aeroptimize`
3. **Start it:**
   ```bash
   export ANTHROPIC_API_KEY=sk-ant-...   # optional: without it only the free mock runs
   make local-live
   ```
   The first build takes a while (it compiles XFoil and downloads FreeCAD, about 4 GB); later starts are quick.
   When the log shows the server running, open `http://localhost:8000`.
4. **Run live** from the Live run panel (dials → "Run live from the dials"). The default cap is $1 per run.
5. **Keep a good run:** the page ends with "Saved as live_<id>". In a second Terminal window, in the same folder:
   ```bash
   make local-export RUN=live_<id> NAME=<short-name>
   ```
   This writes `viewer/runs/<short-name>.json` and its CAD files into your checkout. Commit them to add the run to
   the public replay site.

Stop it with Ctrl-C in the first window. Runs are kept in `runs/live/` in your checkout.

## What runs where

| Piece | What it is | Needs |
|---|---|---|
| Viewer | `viewer/` (HTML, CSS, JS, `runs/*.json`) | any static hosting |
| Live server | FastAPI app, `python -m swarm.live` | a machine or container that can run Python 3.11+, XFoil, FreeCAD (optional, for CAD files), and keep a process alive |

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

1. **A server.** Any small Linux VPS or cloud VM (Ubuntu 24.04 or Debian 12; on Azure, a B-series Ubuntu VM) with
   about 4 GB RAM and 30 GB disk: the image is about 7.5 GB, most of it FreeCAD. Install Docker with its Compose plugin (`curl -fsSL https://get.docker.com | sh`). Open ports
   80 and 443 in its firewall; Caddy needs both (80 for the certificate check, 443 for the site).
2. **DNS.** At your domain's DNS provider, add an `A` record: name `aeroswarm`, value the server's IP address.
   Wait until `ping aeroswarm.<your-domain>` answers from that IP.
3. **Code and settings.**
   ```bash
   git clone https://github.com/AnjaneyaBhardwaj/Aeroptimize.git && cd Aeroptimize
   cp deploy/.env.example deploy/.env
   nano deploy/.env   # DOMAIN, ANTHROPIC_API_KEY, AEROSWARM_LIVE_ACCESS_CODE, AEROSWARM_LIVE_DAILY_USD
   ```
4. **Start.**
   ```bash
   docker compose -f deploy/docker-compose.yml up -d --build
   ```
   The first build takes a while (it compiles XFoil and downloads FreeCAD, about 4 GB). Caddy waits until the app reports healthy (about
   20 s after it starts), then requests the certificate.
5. **Check.** Open `https://aeroswarm.<your-domain>`: the replay plays and the Live run panel appears.
   `https://aeroswarm.<your-domain>/api/health` should show `"xfoil": true`, `"freecad": true` and
   `"access_code_required": true`. At the end of a run the page offers its CAD files (FreeCAD model, STEP,
   coordinates).

Updating later: `git pull && docker compose -f deploy/docker-compose.yml up -d --build`. Finished runs, the daily
spend record and certificates live in Docker volumes and survive updates. Logs:
`docker compose -f deploy/docker-compose.yml logs -f aeroswarm`.

`deploy/.env` holds your API key: it is git-ignored, keep it that way.

## On an Azure VM

The same setup as above on Azure, with the [Azure CLI](https://learn.microsoft.com/cli/azure/install-azure-cli)
(`az login` first). Names and the region are examples; pick a region near your visitors.

**1. Create the VM** (Ubuntu 24.04, 2 vCPU / 4 GB RAM, 64 GB disk, SSH key login, static public IP):

```bash
az group create --name aeroswarm-rg --location westeurope
az vm create --resource-group aeroswarm-rg --name aeroswarm-vm \
  --image Ubuntu2404 --size Standard_B2s --os-disk-size-gb 64 \
  --admin-username azureuser --generate-ssh-keys --public-ip-sku Standard
```

A Standard-SKU public IP is static, so the DNS record below never needs changing. `Standard_B2s` is the smallest
size that fits comfortably (FreeCAD and the build need the 4 GB). Check its monthly price for your region in the
Azure pricing calculator.

**2. Open the web ports** (Caddy needs 80 for the certificate check and 443 for the site; SSH on 22 is already open):

```bash
az vm open-port --resource-group aeroswarm-rg --name aeroswarm-vm --port 80 --priority 1010
az vm open-port --resource-group aeroswarm-rg --name aeroswarm-vm --port 443 --priority 1020
az vm show -d --resource-group aeroswarm-rg --name aeroswarm-vm --query publicIps -o tsv   # the VM's IP
```

**3. DNS.** At the provider that manages your domain: an `A` record, name `aeroswarm`, value that IP.

**4. Install Docker and start the app** (on the VM: `ssh azureuser@<IP>`):

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && exit        # log out and back in so the group applies
ssh azureuser@<IP>
git clone https://github.com/AnjaneyaBhardwaj/Aeroptimize.git && cd Aeroptimize
cp deploy/.env.example deploy/.env && nano deploy/.env   # DOMAIN=aeroswarm.<your-domain>, API key, access code
docker compose -f deploy/docker-compose.yml up -d --build
```

The first build downloads FreeCAD (about 4 GB) and compiles XFoil; expect it to take a while on this size. Then
check `https://aeroswarm.<your-domain>/api/health` (`"xfoil": true`, `"freecad": true`) as in step 5 above.
If the repository is private, clone with a GitHub personal access token or an SSH deploy key.

**Costs and safety on Azure:**
- The VM bills while it runs; `az vm deallocate --resource-group aeroswarm-rg --name aeroswarm-vm` stops the compute
  charge (the disk and the static IP still cost a little) and `az vm start` brings it back with the same IP.
- Set a budget alert in Azure Cost Management, and a monthly limit on the Anthropic key, as backstops to the app's
  own daily cap.
- Keep the server patched: `sudo apt update && sudo apt upgrade` now and then, or enable Ubuntu's
  `unattended-upgrades` (on by default on Azure's Ubuntu images).

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

The image also installs FreeCAD 1.1.3 (headless, from conda-forge; it needs to reach `conda.anaconda.org`), which
builds the CAD files of every finished run: a FreeCAD document with the start and final sections and a
spreadsheet of their results, a STEP file, and the final section's coordinates. Each file is checked before it is
offered (FreeCAD's face area against the section's own, and the STEP file read back). To leave FreeCAD out and save
about 3.6 GB: `docker build --build-arg WITH_FREECAD=0 -t aeroswarm .` (runs then finish without CAD files).

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

For CAD files, install FreeCAD 1.1.3 (the official build from freecad.org, or conda-forge:
`micromamba create -p /opt/freecad -c conda-forge freecad=1.1.3`) and point the server at its headless command:
`AEROSWARM_FREECADCMD=/opt/freecad/bin/freecadcmd`. `freecadcmd` on the PATH is found without it.

Keep it alive with systemd or your host's process manager.

## Publishing a live run as a recorded replay

Finished live runs appear in the server's gallery automatically. To make one part of the committed gallery (it
then ships with the repository and every rebuild), export it into `viewer/runs/` and commit the JSON (and, with
FreeCAD installed, its `<name>_cad/` folder of CAD files):

```bash
uv run python scripts/export_run.py runs/live/<run_id> --name <short-name>
```
