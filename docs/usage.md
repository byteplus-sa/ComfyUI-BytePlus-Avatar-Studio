# Avatar Studio Guide

[Quick start](../README.md) | [Developer guide](development.md)

## Install And Update

Start in the ComfyUI editor: **top-left dropdown > Extensions > Nodes Manager >
search `byteplus`**. Install **ComfyUI-BytePlus-ModelArk** and
**ComfyUI-BytePlus-Avatar-Studio**, both from **byteplus-sa**. For an installed
package, open its card and use **Update** when a newer release is available.
Wait for completion, then **Apply Changes** if prompted or restart ComfyUI,
and reload the editor.

The [illustrated installation guide](../README.md#install) lists **Nodes Manager
first**, **Comfy CLI second**, and **release ZIP installation last**. Both
packages must be in the same active ComfyUI installation.

## Credentials

Provider credentials are managed by the ModelArk companion in
**ComfyUI Settings > BytePlus**, not stored in Studio projects.

| Service | Variable |
| --- | --- |
| ModelArk / Seedream | `BYTEPLUS_API_KEY` |
| Seed Speech / Seed Audio | `BYTEPLUS_SEED_SPEECH_API_KEY` |
| Vision AI / OmniHuman | `BYTEPLUS_CV_API_KEY` |

In Studio, **Settings > API keys > BytePlus connections** shows connection
status. Use **Manage in ComfyUI** to edit keys and **Refresh connections** to
check the current configuration. These are separate keys; none substitutes for
Comfy.org upload authorization.

### Comfy Desktop Login

Launch Studio from the BytePlus menu or context menu inside Comfy Desktop.
Studio opens in the system browser. In **Settings > API keys > ComfyUI login**,
choose **Sign in with ComfyUI** if needed and complete Desktop's native OAuth
authorization. A connected Desktop login is selected automatically.

No separate Comfy.org API key is needed. The integration uses Desktop's native
login, not the older email/password dialog inside the ComfyUI canvas.

Keep the originating ComfyUI tab open. After reloading Studio, reopen it from
ComfyUI to reconnect. The link expires after eight hours or a backend restart.
Logout, account/workspace changes, source-tab closure and expiration block new
submissions. Studio never silently switches to a saved upload key; select
**Use API key instead** explicitly.

OAuth video submission requires an idle native ComfyUI queue. Wait for current
work to finish before generating, or explicitly choose an upload API key for
normal queuing. Authorization is refreshed before submission, not during
execution, so logout or token expiry during an upload can still cause failure.

Desktop owns OAuth and refresh tokens. Studio receives only a scoped pairing
capability; tokens are passed directly to ComfyUI's sensitive execution context,
never to the Studio browser or its project database. Disconnecting Studio does
not sign out Desktop globally or cancel accepted work.

Desktop integration feature-detects `__comfyDesktop2.Auth`. Browser-only ComfyUI,
direct Studio URLs and unsupported Desktop builds use the explicit API-key path.

### Comfy.org Upload Key

Open **Settings > API keys > Set API key** under **Comfy.org upload key**.
Choose **Use for this tab**, or opt into **Remember on this ComfyUI server** and
choose **Save API key**.

Session-only is the default. The key stays in tab memory and is cleared by
reload or tab closure. Remembered keys survive reloads and backend restarts at:

```text
<ComfyUI user directory>/byteplus_avatar_studio/credentials/<SHA256 of user ID>.json
```

**The file is plaintext, not encrypted.** On macOS/Linux, its directory uses
mode `0700` and the file uses `0600`. Windows ACLs are not managed or verified.
The ComfyUI process, administrators and accessible backups can read it. The
hashed filename scopes ownership; it does not encrypt the value.

The settings API returns configuration status, never the saved key. Neither
mode writes it to projects, SQLite, browser storage, workflow metadata or logs.
**Replace** opens an empty field; choosing a session-only replacement removes
the saved copy first. **Remove** clears this tab's key and the saved copy, but
does not revoke the provider key, clear other tabs, erase backups or stop work.
Saving validates format, not live API access, and never generates media.

## Preparation And Review

Portrait and narration have independent Generate buttons and progress states.
Start either branch, or both concurrently. Only the active branch's inputs,
uploads and approval are locked. Reloading Studio preserves running jobs while
the backend remains open. Video waits for both current assets to be approved
and for all preparation to finish or be resolved.

Generate saves valid edits and submits directly. Incomplete drafts can still
be saved using **Save**, **Ctrl+S / Cmd+S**, or Enter; Enter never generates.
Polling preserves unsaved edits and reports conflicting changes from other tabs.
Save edits before approving an asset.

Approvals bind the immutable asset ID and file hash. Changing source settings
invalidates a generated asset's approval; replacing media always requires new
approval. Unused generation settings do not invalidate uploaded candidates.
Opening a portrait preview or listening to audio does not approve it.

Seed Audio has a combined script/style prompt limit of 3000 characters. This
does not guarantee a five-minute clip. OmniHuman needs one non-silent narration
clip lasting 4-300 seconds. Short or silent results cannot be approved.
Video duration follows the approved audio; trim or regenerate it before review
to change the duration.

## Uploads

Use **Upload portrait** or **Upload narration**, or combine an upload with a
generated asset. Script and character text are required only for generation.
Uploading/reviewing media needs no provider keys; video still needs the
companion, Vision AI key and Comfy.org upload access.

| Input | Accepted files | Limits |
| --- | --- | --- |
| Portrait | PNG, JPEG, WebP | 10 MB; still image; 300-6000 px per side; <= 24 MP; aspect ratio 0.4-2.5 |
| Narration | WAV, MP3, FLAC | 64 MB source file; 4-300 seconds; non-silent |

Portraits are orientation-corrected and stored as RGB PNG without source
metadata. Narration is prepared as mono, 24 kHz PCM16 WAV before review, without
speed, pitch or loudness changes. The companion may re-encode equivalent media
for upload. Clips are never truncated. M4A/MP4, URLs and playlists are not
accepted by this uploader.

**Add reference image** guides Seedream; it does not select that file as the
portrait for OmniHuman. Use **Upload portrait** for a finished portrait.
Invalid, stale or canceled uploads do not replace the current candidate.

## Troubleshooting And Recovery

| Situation | What to do |
| --- | --- |
| Install path already exists | Close ComfyUI, back up the affected extension outside `custom_nodes`, then install through Nodes Manager and restart. Keep `user/`, Studio projects and `user/.env`. |
| No release is available for the selected update option | Check the update dropdown and Registry versions. This is not proof that you are up to date; pending or flagged versions may be unavailable through both Manager and CLI. |
| Studio will not open | Confirm both extensions and minimum versions are installed, keep `studio_dist/`, and restart ComfyUI. |
| Desktop login disconnected | Reopen Studio from its originating ComfyUI window; use an upload key only as an explicit alternative. |
| OAuth submission says the queue is busy | Wait for native work to finish, then click Generate again. |
| Video generation is disabled | Check current asset approvals, upload authorization and active/unresolved preparation jobs. |
| Definite preparation validation/setup failure | Correct the input or configuration; the stage remains editable. |
| Unknown preparation | Check provider usage and existing outputs, then use **Resolve preparation** in Activity with acknowledgement. |
| Video failed or waiting was interrupted | Retain its task ID and use **Collect task** to retrieve accepted work, not Generate again. |
| Cancellation refused | The task has started or finished; inspect/collect it and assume it may still be billed. |

Resolving preparation dismisses the local uncertain operation. It does not
cancel remote work, infer provider failure or generate a replacement. Active
or collectable results cannot be dismissed. Backend restarts mark missing
preparation unresolved rather than resubmitting it.

**Request cancellation** calls the companion's queued-only OmniHuman helper
directly, outside the busy video queue. Stopping local waiting is not remote
cancellation. ModelArk >= 0.11.0 handles HTTP `400` / integer code `50217`
refusal directly; Studio retains compatibility for 0.10.0. Other errors remain
errors. Uncertain paid submissions are never automatically retried.

## Storage And Limits

Use a trusted single-owner installation; do not expose ComfyUI publicly.
Studio does not provide authentication, public multi-user isolation, quotas or
automatic retention cleanup. Ownership checks on Studio routes do not turn the
native ComfyUI media directories into a multi-tenant boundary.

Projects and media live under `<ComfyUI user directory>/byteplus_avatar_studio/`.
Native input/output directories also contain workflow media. Assets remain
until managed outside Studio. Returned videos larger than 750 MB are not
collected.

Voice cloning, script rewriting, captions, automatic approval/cost estimation
and long-script chunking/stitching are not included. Reverse-proxy subpath
deployments, older Desktop binaries and Windows worker lifecycle have not been
validated. Successful live queued cancellation, paid parallel preparation and
five-minute generation are not verified.
