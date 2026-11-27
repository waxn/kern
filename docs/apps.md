# Apps

Apps are small programs that Kern runs for you on the same server: a page to log the weights of
your chickens, a dashboard your laptops report their Claude usage to, a shared shopping list. Each
app runs in the background at its own address, `https://<your server>/<path>/`, as a page of its
own with nothing of Kern around it. You manage them under **Apps** in the sidebar.

An app comes from one of four places:

* **Build with AI**: describe what you want. The AI builder writes the code, deploys it, tries
  it and fixes what breaks. Ask for changes in the same conversation later.
* **A template**: a small working app to change (Tracker, Collector, Static page, Node.js server).
* **A Kern repository**: one of your repositories under Git. Every push to its branch deploys it.
* **A git URL**: GitHub, Gitea, GitLab… Deploy by hand, or call the deploy hook from the other side.

Template and AI apps get a Kern repository of their own (`app-<path>`), so their code is versioned
like any other: clone it, change it, push, and the new version goes live.

## Running Kern with apps

`docker-compose.yml` has an `apps` service. It runs every app as a process inside that one
container, so an app needs no container, image or port of its own. The web container sends every
address that isn't Kern's own to it. Start it with the rest:

```bash
docker compose up -d --build
```

Don't want apps? Remove the `apps` service; Kern works as before.

**Who may create apps:** Settings → Server → Apps: *Off*, *Administrators* (the default) or
*Everyone*. An app is code running on your server, so only give this to people you trust.

## What an app gets

| | |
|---|---|
| `PORT` | The port to listen on, on `127.0.0.1`. Kern checks it answers before sending traffic. |
| `APP_DATA_DIR` | A folder that survives deploys. Keep your data here (SQLite works well). |
| `KERN_BASE_PATH` | `/<path>`, where the app is served. |
| `KERN_APP_SECRET` | Compare it with the `X-Kern-App-Secret` request header to trust `X-Kern-User`. |
| Your variables | Settings → Environment variables (stored encrypted). |

Nothing else of Kern's environment reaches an app.

**Paths.** Kern removes `/<path>` before a request reaches the app, so the app sees `/` and
`/api/items`. Use **relative URLs** in pages (`api/items`, `style.css`) and the app works under any
path. Redirects to `/login` from the app become `/<path>/login`, and cookie paths are adjusted the
same way. An app that handles its base path itself can turn this off (Settings → *Remove /path
from paths*).

**Who is visiting.** When someone signed in to Kern opens the app, the request carries
`X-Kern-User` (the username) and `X-Kern-User-Id`. Trust them only when `X-Kern-App-Secret` equals
`KERN_APP_SECRET`.

## Who can open an app

* **Only me** (the default): you, signed in to Kern. Others are sent to Kern's sign-in page and
  come back to the app afterwards.
* **Signed-in users**: anyone with an account on this server.
* **Everyone**: no sign-in.

**Public paths** open parts of a private app to everyone, for example `/api/ingest`, where your
devices post data with a token the app checks itself. The Collector template works this way.

## How Kern builds and runs an app

Kern reads `.kern/app.yml` in the app's folder when there is one. Every field is optional:

```yaml
runtime: python          # static | python | node | command
build: pip install -r requirements.txt   # or a list of commands
start: python app.py     # must listen on $PORT
health: /healthz         # must answer (below 500) before traffic moves to a new version
static: dist             # static apps: the folder to serve
env:                     # defaults; Settings → Environment variables win
  MODE: production
```

Without a manifest Kern looks at the files:

| Found | Runtime | Build | Start |
|---|---|---|---|
| `package.json` | node | `npm ci` / `npm install` when there are dependencies, then `npm run build` if it exists | `npm start`, or `node server.js` / `index.js`; only a build script: serve the build output as static files |
| `app.py`, `main.py`, `server.py` or `requirements.txt` | python | a virtualenv with `requirements.txt` | `python app.py` (or main.py / server.py) |
| `index.html` | static | – | served by Kern; unknown paths without an extension get `index.html` |

Settings → *How it runs* overrides all of it for one app.

**A deployment** fetches the commit, writes its files to a new release folder, builds it, starts
it on a new port, waits until it answers, then moves traffic over and stops the old process. If the
new version doesn't start, the old one keeps running and the deployment is marked failed with its
log. Kern keeps the newest three releases, so going back (Deploys → *Roll back to this*) is
instant.

**Keeping it running.** An app that exits is started again after 1, 2, 4… up to 60 seconds. After
five crashes within five minutes Kern stops trying and shows it as crashed until you restart it.
Apps that were running start again when the server restarts.

**Deploy hook.** Settings → Source shows a secret URL; a `POST` to it deploys the branch (for git
URL sources, from GitHub's webhooks or a CI job). Kern repositories deploy on push by themselves.

### The deploy log

Every phase of a deployment writes a line to its log (Deploys → the deployment): `[12:00:01] ▸ Name` when
it begins, `[12:00:03] ✓ note · 1.2 s` (or `✗`) when it ends, with the time in UTC. The phases are: get the
code, write the release, plan, each build step (with its exit code and duration), start on a port, wait for
the app to answer, switch traffic, stop the old version, and a last `✓ Live` or `✗ Deployment failed: why`
with the total time. When the new version does not start, the log ends with the last lines of what it printed
(`!` marks stderr). `GET /api/apps/<slug>/deploys/<n>/log` returns the text as before (`text`, `offset`,
`size`, `status`, `done`, `deploy`) and also `phases`: `[{name, status: "running"|"ok"|"fail", started, seconds,
detail}]`, kept in `deploy-<n>.phases.json` next to the log. `done` is true only once the deployment is over
and the reader has everything written to the log.

## The AI builder

The *Build with AI* tab is a conversation about one app, using the AI provider from Settings → AI.
For each message the builder looks at the files, writes or edits them, deploys, reads the build
and app logs, and makes requests to the app until it works; you see each step as it happens.
Every change is a commit on the app's branch, made by "<you> (AI builder)". Changes it didn't
deploy are committed when the turn ends. *Stop* ends a turn after the current step. The builder
runs in the apps service, so it keeps going when you close the page.

It can also change the app's description, icon and public paths. It can't change who may open
the app, environment variables or anything outside the app.

## Data and backups

`APP_DATA_DIR` lives in the `kern_data` volume under `apps/<id>/home/data` and survives deploys,
restarts and rebuilds. It is **not part of Kern's backups** (Settings → Data & backups): download
it from the app's Settings → Data now and then. The code is in your repository.

**Looking inside.** The app's Database view opens the SQLite files in `APP_DATA_DIR` read-only:
`GET /api/apps/<slug>/db` (files, and the tables of one), `GET /api/apps/<slug>/db/rows` (a page of one
table) and `POST /api/apps/<slug>/db/query` (one SELECT, WITH, EXPLAIN or `PRAGMA table_info` statement,
500 rows, 5 seconds). Kern refuses links: a file is only opened when no part of its path is a symbolic link,
it is a regular file owned by the app's user, and nothing else can be written through the connection.
`GET /api/apps/<slug>/tasks` shows what the app is running (its processes, the deployment in progress,
those waiting, the builder). The AI builder has the same two views as its `query_db` and `list_processes` tools.

Deleting an app stops it and deletes its data and releases; tick the box to delete its repository
too. Deleting a user deletes their apps.

## Security

Apps share Kern's address, so they share its origin in the browser. Kern limits what that means:

* **On the server**, in Docker, every app (and every build step, e.g. `npm install` scripts) runs
  as a user of its own (uid 20000 + the app's id) with no capabilities. It can read and write its
  own folder and nothing of Kern's: the data folder is closed to other users. The apps service
  itself keeps only the capabilities that needs (switch user, hand over a folder, stop a process).
  Run outside Docker (a checkout on your machine), apps run as your user; Kern says so on the Apps
  page.
* **Kern's session never reaches an app**: the gateway takes the `kern_sid` cookie out of every
  request and drops any attempt by an app to set it.
* **In the browser**, an app's own JavaScript runs on Kern's origin and could call Kern's API as
  whoever has it open. Only run apps whose code you trust, which is why apps are for administrators
  by default. Opening another person's "signed-in users" app is like opening a page they wrote.
* An app's environment is built from nothing (no Kern secrets), and its variables are stored
  encrypted like mail passwords.

## Configuration

| Variable | Default | |
|---|---|---|
| `KERN_APPS_BUILD_TIMEOUT` | `900` | Seconds one build step may take. |
| `KERN_APPS_START_TIMEOUT` | `60` | Seconds a new version has to answer. |
| `KERN_APPS_CONCURRENT_DEPLOYS` | `2` | Deployments built at the same time. |
| `KERN_APPS_ISOLATION` | `auto` | `require`: refuse to start without per-app users; `off`: never switch users. |
| `KERN_APPS_PORT`, `KERN_APPS_CONTROL_PORT` | `8100`, `8101` | The gateway and the backend's control port. |
| `KERN_APPS_CONTROL` | `http://127.0.0.1:8101` | Where the backend reaches the apps service (`http://apps:8101` in Docker). |

### Developing Kern itself

Run the worker next to the backend: `python manage.py apps_worker` (`.claude/launch.json` has
`kern-apps-backend`, `kern-apps-worker` and `kern-apps-frontend`). The Vite dev server proxies
app paths to it (`KERN_APPS_GATEWAY`, default `http://127.0.0.1:8100`).

When you add a top-level route to the web app, add its name to `KERN_ROUTES` in
`backend/kernapps/core.py` and `frontend/src/lib/kernRoutes.ts`; `kernapps/tests.py` fails until
both list it, so no app can take it.
