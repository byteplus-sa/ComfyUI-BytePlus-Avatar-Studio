# BytePlus Avatar Studio

- Implementation follows `docs/development.md`; user-facing behavior is in
  `README.md` and `docs/usage.md`.
- This is a separate companion extension, not a fork of ModelArk.
- Requires ComfyUI-BytePlus-ModelArk >= 0.10.0; never duplicate provider clients.
- Python backend, SQLite project state, static React/Vite app and one launcher.
- All provider credentials stay in Settings > BytePlus. Comfy.org upload keys
  are session-only by default, with explicit opt-in owner-scoped server storage.
  Never put keys in projects, browser storage or logs, or return saved values.
- Prefer the supported Desktop Auth bridge for uploads when Studio is launched
  from Desktop. Pair tabs with scoped, expiring capabilities; resolve fresh
  OAuth only on the backend into the sensitive queue context. Never return
  OAuth tokens to Studio, scrape private auth stores, or silently switch sources.
- Approve the current prepared portrait and narration before video submission.
- Accept direct portrait/audio uploads as unapproved candidates; keep their
  origin distinct from generated assets. No separate rights-permission checkbox.
- Bind approval to immutable asset ID/hash and reject stale revisions.
- Generate starts directly without an extra billing-confirmation modal.
- Image/audio preparation runs in isolated CPU workers through existing companion
  nodes and native savers; no duplicate provider transport or global queue mutation.
- Never share the native queue's global interrupt flag with preparation workers.
  Pass stage credentials through stdin only, not arguments, logs or files.
- Definite pre-execution failures stay editable. Unknown preparation can only be
  dismissed with explicit acknowledgement after ruling out active/collectable work.
- Lock only the active preparation stage. Video waits for both reviewed assets
  and no active or unresolved preparation jobs.
- No automatic paid-submit retries. Preserve unknown submissions and task IDs.
- Cancellation delegates to the companion's existing queued-only helper, not
  the ordinary prompt queue, which may be occupied by the video wait.
- This release targets trusted single-owner ComfyUI, not public hosting.
- Run unittest, ruff, mypy, frontend tests/lint/typecheck/build and HTTP smoke.
- Use isolated temporary test environments, media and ComfyUI base directories.
- Never make paid generation calls, publish, push or commit without approval.
- Ship `studio_dist/`; do not put app bundles under auto-loaded `web/`.
