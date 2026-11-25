# Architecture And Development

[Quick start](../README.md) | [User guide](usage.md)

## Architecture

Studio is a separate companion extension requiring ModelArk >= 0.10.0.
The bundled React/Vite app calls same-origin Python routes backed by SQLite.
Provider clients belong to the installed ModelArk companion; do not duplicate
its transport or add a separate application server.

| Module | Responsibility |
| --- | --- |
| `avatar_studio/store.py` | Projects, revisions, immutable assets, approvals and job identity |
| `avatar_studio/workflows.py` | Restricted, internally constructed graphs |
| `avatar_studio/bridge.py` | Native ComfyUI integration, validation and queue access |
| `avatar_studio/preparation_process.py` | CPU subprocess lifetime and credential handoff |
| `avatar_studio/preparation_worker.py` | Installed core/companion bootstrap in each child |
| `avatar_studio/preparation.py` | Fixed preparation graphs, native input conversion and savers |
| `avatar_studio/service.py` | Output collection and recovery |
| `avatar_studio/routes.py` | Same-origin app/API routes |
| `avatar_studio/upload_credentials.py` | Opt-in, owner-scoped upload-key storage |
| `web/extension.js` | ComfyUI launcher |
| `studio_dist/` | Bundled frontend; never put these assets under auto-loaded `web/` |

Image/audio graphs validate before execution, including text-only narration
preflight. Each runs in an isolated CPU process using companion nodes and native
savers. Workers do not share the native queue's consume-on-read interrupt flag.
Pass only the stage's provider key and region through private stdin, never
arguments, logs or credential files. Worker stdout contains bounded safe
state/media metadata; other output is suppressed.

Shutdown cancels and reaps local children. A raw stdin EOF watchdog exits a
worker if its parent backend dies. This isolation adds startup time and memory
overhead but loads no local GPU model. Video and task recovery use the native
queue. Remote cancellation uses the companion helper directly, not that queue.

### Contracts

- Approval requires the current immutable asset ID and SHA-256 hash.
- New generated/uploaded candidates are never implicitly approved.
- Stage input tokens bind preparation to its source fields and current candidate.
  Clients without tokens retain strict revision checks.
- Image/audio lock only their own stage; video conflicts with active or unknown
  preparation and requires both current assets approved.
- Stable operation identity prevents duplicate submissions. New operations use
  new seeds. Never automatically retry an uncertain paid submission.
- Definite pre-execution failures leave inputs editable. Acknowledged dismissal
  of unknown preparation requires ruling out active/collectable work.
- Retain observed provider task IDs even when output collection fails.
- Provider keys remain companion-managed. Desktop OAuth belongs only in native
  sensitive execution context, never browser/project storage or logs.
- Resolve fresh Desktop authorization from its scoped originating tab.
  Logout, identity changes, tab loss or expiry fail closed without silent
  API-key fallback. Check OAuth queue idleness under the native queue mutex.
- Preserve unsaved editor state during polling, report revision conflicts, and
  save valid changes before direct Generate submission.

The frontend uses locally owned shadcn-derived/Radix controls, Tailwind CSS and
bundled Inter. `frontend/components.json` defines scaffolding conventions;
`frontend/src/components/ui/` holds components and `frontend/src/style.css`
defines theme/layout. See [third-party notices](../THIRD_PARTY_NOTICES.md).

## Verification

Run from the full source checkout, not the manual-install ZIP. Use a Python
environment with ComfyUI's dependencies.

```sh
python -m unittest discover -s tests -v
ruff check .
mypy -p avatar_studio
python -m compileall -q avatar_studio __init__.py
npm --prefix frontend ci
npm --prefix frontend run test
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run build
npm --prefix frontend audit --audit-level=moderate
node --check web/extension.js
```

Native graph and isolated-worker checks use mocked providers without paid
generation:

```sh
PYTHONPATH=. python tests/native_contracts.py \
  --comfy-root /path/to/ComfyUI \
  --companion-root /path/to/ComfyUI-BytePlus-ModelArk
```

Offline browser tests use real HTTP routes/state with a bridge that cannot
submit provider generation:

```sh
AVATAR_STUDIO_PYTHON=/path/to/comfy/python npm --prefix frontend run test:e2e
```

For native launcher checks, start the disposable harness:

```sh
/path/to/comfy/python tests/native_server.py \
  --comfy-root /path/to/ComfyUI \
  --companion-root /path/to/ComfyUI-BytePlus-ModelArk \
  --studio-root /path/to/ComfyUI-BytePlus-Avatar-Studio \
  --port 8209
```

It uses temporary user/input/output/database directories, strips provider
credentials, and enables only Studio and the companion. Wait for `Starting
server`, check readiness, then run only the intended native browser checks:

```sh
curl --fail http://127.0.0.1:8209/byteplus/avatar-studio/api/setup
AVATAR_STUDIO_URL=http://127.0.0.1:8209 \
  npm --prefix frontend run test:e2e -- e2e/studio.spec.ts \
  --grep 'ComfyUI loads the Studio launcher'
```

Stop the harness with Ctrl+C to shut down its child and remove temporary data.
Browser tests create projects and change synthetic upload-key settings; never
run the offline suite against a user's live installation. Paid tests require
separate explicit authorization and bounded cost; do not retry automatically.

CI is defined in [tests.yml](../.github/workflows/tests.yml). Native jobs cover
ComfyUI 0.31.0 and 0.46.0 with the released ModelArk 0.10.0 baseline. Treat live
test coverage separately from provider mocks; current unverified cases are
listed in the [user guide](usage.md#storage-and-limits).

## Packaging And Releases

Build and commit the matching frontend/backend versions and `studio_dist/`.
The manual ZIP includes only runtime files, metadata, README and licenses:

```sh
npm --prefix frontend run build
python scripts/package.py
shasum -a 256 -c ComfyUI-BytePlus-Avatar-Studio-0.2.0.zip.sha256
```

`scripts/package.py` verifies matching versions, required files, same-origin
asset references and no symlinks. Stable ordering/timestamps/permissions
produce identical ZIP bytes for unchanged inputs in the same environment.
Development docs, source frontend, tests, local state and credentials are
excluded. This command does not publish.

Registry packing includes Git-tracked files filtered by `.comfyignore`; stage
new runtime files before checking. Its exact entry set must match the runtime
manifest plus the Registry icon:

```sh
comfy --skip-prompt node validate
comfy --skip-prompt node pack
python scripts/check_registry_package.py node.zip
```

Publishing requires explicit authorization. Use an unused semantic version and
the [Publish Registry Release workflow](../.github/workflows/publish_action.yml)
on `main`. It verifies tests/packages, binds the version tag to the tested
commit, publishes once, then creates the GitHub Release.

```sh
gh workflow run publish_action.yml --ref main
```

Keep `REGISTRY_ACCESS_TOKEN` only in GitHub Actions secrets for `byteplus-sa`.
CI needs no provider credentials. After ambiguous upload failures, inspect
Registry state before retrying; published versions are immutable.

Verify the tag commit, workflow jobs, downloaded package and version scan
status separately. A successful upload is not Manager availability. Check
[Studio version statuses](https://api.comfy.org/nodes/ComfyUI-BytePlus-Avatar-Studio/versions?include_status_reason=true)
and the companion's status before announcing installation through Manager.
Pending or Flagged versions are not confirmed available. Restart ComfyUI and
reload Studio after backend updates.
