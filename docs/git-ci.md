# CI for Kern's git server

Push a `.kern/ci.yml` (or `.kern/ci.yaml`) to a repository and Kern runs it like GitHub Actions: jobs
in containers, logs you can watch live, secrets, artifacts. Open a repository's **Runs** tab to see
runs, start one with **Run**, cancel or re-run. Commits and branches show the status of their latest run.

> CI runs the code in your repositories on the machine that hosts Kern, and the `ci` service needs
> the host's Docker socket for that. That is fine for your own projects; do not run code you don't trust.
> Don't want CI? Remove the `ci` service from `docker-compose.yml` (pipelines are then just queued).

## Pipeline file

```yaml
on:
  push: {branches: ["*"], tags: ["v*"]}   # default: every branch push, no tags. `push: false` turns it off
  manual: true                             # "Run" button in the UI (default true)
image: python:3.13                         # default image of the jobs (KERN_CI_DEFAULT_IMAGE otherwise)
env: {PYTHONUNBUFFERED: "1"}               # for every job
timeout: 20                                # minutes per job (default 30)

jobs:
  test:
    steps:
      - run: pip install -r requirements.txt
      - name: Tests
        run: pytest
        timeout: 10                        # minutes for this step
        env: {LOG_LEVEL: debug}
  build:
    needs: [test]                          # runs after test; skipped if test did not succeed
    image: node:22                         # per job image
    artifacts: [dist/*.apk, reports]       # files kept after the job (globs, relative to the checkout)
    release: true                          # on a tag run that passes: attach the artifacts to the tag's release
    steps:
      - run: ./build.sh
  deploy:
    needs: [build]
    if: {branch: main}                     # or {tag: "v*"}; both = either. Otherwise the job is skipped
    secrets: [DEPLOY_KEY]                  # only listed secrets are injected, as environment variables
    steps:
      - run: ./deploy.sh
```

- `steps` are shell scripts run with `bash -e` (`sh -e` if the image has no bash). A step that exits
  non-zero fails its job and stops it. A step can also be a plain string.
- Jobs run one after another in dependency order. A job whose `needs` did not all succeed is skipped; other
  jobs still run. A run is *failed* if any job failed. Jobs do not share files; use artifacts to keep results.
- `on` can also be `on: push` or `on: [push, manual]` (then only the listed triggers exist).
- Globs: `*` stays within a folder, `**` crosses folders, a folder name collects everything below it.
  Branch/tag patterns use `*` for anything.
- Job and step `env` values are plain text. Names starting with `KERN_` are reserved.
- A mistake in the file (bad YAML, unknown key, unknown `needs`, circle) makes a run with state *error* and
  the message as its reason, instead of running anything.

## What a job sees

The files of the pushed commit (no `.git` folder) in the working directory, plus
`CI=1`, `KERN_CI=1`, `KERN_REPO`, `KERN_REF` (full ref), `KERN_BRANCH` or `KERN_TAG`, `KERN_SHA`,
`KERN_RUN_ID`, `KERN_JOB` and `KERN_TRIGGER` (`push`, `manual`, `rerun`). Nothing of Kern's own environment
is passed on. A run only ever sees its own repository and the secrets of that repository.

## Secrets

Repository → **Settings → CI secrets**. Names are letters, digits and `_`. Values are stored encrypted,
never returned by the API, injected only into jobs that list them, and replaced by `***` in logs (also when
split over several lines of output). A job listing a secret that is not set fails with a message.

## Runs

- A push queues a run for every updated branch/tag whose commit has a pipeline file that matches `on`.
  Deleting a ref queues nothing. A newer push to a branch cancels that branch's queued (not running) runs.
- Cancel a queued or running run, or **Re-run** a finished one (same commit, same pipeline).
- Timeouts: 30 minutes per job by default; no timeout can exceed 6 hours.
- Logs and artifacts are kept for the newest 50 runs of a repository, and deleted with the repository.

## Running it

`docker compose up -d` starts the `ci` service (`entrypoint.sh ci-worker` → `manage.py ci_worker`). It
mounts `/var/run/docker.sock` and starts one sibling container per job: the checkout is copied *into* the
container (the worker's own paths mean nothing to the host's Docker), logs are streamed, artifacts copied
out, and the container removed. Missing images are pulled. Containers carry the label `kern.ci=1`; leftovers
of a crash are removed when the worker starts, and runs left *running* by a crash become *error*.
The image used must have `sh`.

| Variable | Default | |
|---|---|---|
| `KERN_CI_RUNNER` | `docker` | `shell` runs steps with bash in a temp folder on the worker's machine (development, tests) |
| `KERN_CI_CONCURRENCY` | `1` | runs at the same time |
| `KERN_CI_DEFAULT_TIMEOUT_MIN` | `30` | job timeout when the pipeline has none |
| `KERN_CI_MAX_TIMEOUT_MIN` | `360` | upper limit for every timeout |
| `KERN_CI_KEEP_RUNS` | `50` | runs kept per repository |
| `KERN_CI_DEFAULT_IMAGE` | `debian:stable-slim` | image of jobs that name none |
| `KERN_CI_MAX_LOG_MB` / `KERN_CI_MAX_ARTIFACT_MB` | `20` / `500` | per job log, per job artifacts |
| `KERN_DOCKER_SOCKET` | `/var/run/docker.sock` | |
| `KERN_CI_DOCKER_MEMORY_MB`, `KERN_CI_DOCKER_NETWORK` | unset | optional container limits |

## API

Under `/api/git/repos/<name>/ci/`: `GET runs?ref=&page=`, `POST runs {ref}`, `GET runs/<id>`,
`POST runs/<id>/cancel`, `POST runs/<id>/rerun`, `GET runs/<id>/jobs/<job>/log?offset=` (JSON with the new
`text`, next `offset`, `done`), `GET runs/<id>/artifacts/<job>/<path>`, `GET secrets`,
`PUT|DELETE secrets/<NAME>`, `GET status?shas=a,b` (latest run per commit), `GET pipeline?ref=`.
Other features can call `notes.ci.run_artifacts(run)` for the files of a finished run.

### Publishing releases and webhooks

- A job with `release: true` publishes its artifacts when a **tag** run succeeds: each file is attached
  (by its file name) to the release of that tag, which is created if there isn't one yet
  (see [git-releases.md](git-releases.md)). Branch runs never publish.
- Every finished run is sent to the repository's webhooks that subscribe to **CI run finished**
  (event `ci_run`, payload `{run: {id, status, ref, sha, trigger, pusher, error, started, finished, jobs}}`;
  see [git-mirrors-webhooks.md](git-mirrors-webhooks.md)).

## Example

```yaml
on: {push: {branches: [main], tags: ["v*"]}}
image: python:3.13
jobs:
  test:
    steps:
      - run: pip install -r requirements.txt
      - {name: Tests, run: pytest -q}
  release:
    needs: [test]
    if: {tag: "v*"}
    secrets: [PYPI_TOKEN]
    artifacts: [dist/*.whl]
    steps:
      - run: pip install build twine && python -m build
      - run: twine upload -u __token__ -p "$PYPI_TOKEN" dist/*
```
