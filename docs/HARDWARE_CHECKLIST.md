# Hardware checklist (Nikon D500)

Nothing in this project has been run against a real camera; it was developed against `FakeCamera`. This is the list to work through with a D500 attached. Items marked **auto** are also exercised by `pytest -m hardware --real-camera -n 0 -s tests/hardware`.

Setup: mode dial on P/A/S/M, card inserted, battery above 50%, camera on, USB direct to the host, `docker/udev/99-nikon.rules` installed, the app running with the demo camera switch OFF (Settings). Record firmware version and lens used. Where an item says "API", use `/docs` (live OpenAPI UI) or the Shoot/Advanced views.

Legend: **Verifies** is the code assumption that the result confirms or refutes. Report refutations as issues with the printed output.

## 1. Connection

| # | Action | Expected | Verifies |
|---|---|---|---|
| 1.1 | **auto** Click Connect (`POST /camera/connect`) | State `idle`, model contains "D500", serial set, within ~10 s | `Gphoto2Backend.open`, `get_abilities().model` |
| 1.2 | `GET /camera/summary` | Non-empty text | `summary()` works as the keepalive probe |
| 1.3 | Start the app while another process (gvfs, `gphoto2` CLI) holds the camera | Clear "claimed by another process" error (409/503), no crash; works after releasing | `GP_ERROR_IO_USB_CLAIM` -> `CameraBusy` |
| 1.4 | Connect with camera off | `camera_not_found` error, state stays `disconnected` | `GP_ERROR_MODEL_NOT_FOUND` mapping |

## 2. Settings

| # | Action | Expected | Verifies |
|---|---|---|---|
| 2.1 | **auto** `GET /settings`; note which widgets are missing (hardware test prints them) | All of iso, f-number, shutterspeed, exposurecompensation, autoexposuremode, focusmode, whitebalance, imagequality, imagesize, liveviewsize, viewfinder, capturetarget, meteringmode, batterylevel, datetime, bulb, movie, manualfocusdrive, autofocusdrive present | Widget names used across services exist on the D500 |
| 2.2 | **auto** `GET /settings/iso` | `path` like `/main/imgsettings/iso`, type radio, choices listed | Path format `/main/<section>/<name>`; `get_single_config` works |
| 2.3 | **auto** Read choices for iso, f-number, shutterspeed, exposurecompensation, whitebalance, imagequality (test prints them) | Formats match the tolerant matcher: iso `"100"`, f-number `"f/2.8"` or `"2.8"`, shutterspeed `"1/250"`/`"30"`/`"Bulb"`, EV `"-0.7"` vs `"-0.667"`, WB names, quality `"NEF+Fine"`-style | `SettingsService.prepare`/`resolve_name` tolerant matching |
| 2.4 | `PUT /settings/f-number` with `2.8`, `f/2.8`, `F2.8` | All resolve to the same choice; the value reads back equal | Tolerant matching of f-number |
| 2.5 | `PUT /settings/shutterspeed` with `1/250`, `0.004`, `2`, `2"` | Resolved to the camera choice; readback equal | Shutter speed parsing |
| 2.6 | `PUT /settings/exposurecompensation` with `-0.7`, `-0.667`, `1` | Resolved; readback equal | EV decimal matching |
| 2.7 | `PUT /settings/imagequality` with `NEF (RAW) + JPEG Fine` style and with alias `imageformat` | Accepted, alias works | Quality choices; `ALIASES` |
| 2.8 | Write every `WRITABLE` name once (iso, whitebalance, colorspace, drivemode, meteringmode, focusmode, flashmode, imagesize, liveviewsize, autoexposuremode, shutterspeed2, ...) with its current value | No `setting_not_found`; read-only ones are reported as read-only, not as errors | Allowlist names exist on the D500; names with `2` suffix may not exist |
| 2.9 | Set a value on the mode dial in Auto/scene mode | Error or no change, reported; never silent success | README mode-dial warning |
| 2.10 | `PATCH /settings` with aperture, shutterspeed, iso, mode together | Applied in the `WRITABLE` order, final state correct | Mode-before-exposure ordering |
| 2.11 | Change a setting on the camera body, then `POST /settings/refresh` | New value shown | Per-connection settings cache invalidation |

## 3. Capture and files

| # | Action | Expected | Verifies |
|---|---|---|---|
| 3.1 | **auto** `POST /capture` with JPEG only | One file; total time printed (shutter + drain) | `capture()` returns path; `FILE_ADDED` timing |
| 3.2 | `POST /capture` with NEF only | One `.NEF`, downloaded fully (30-50 MB) | Chunked 1 MiB download (`read_file`) |
| 3.3 | `POST /capture` with NEF+JPEG | Two files (both names returned and downloaded) | RAW+JPEG yields two `FILE_ADDED` events; de-duplication |
| 3.4 | Time the capture call; vary `event_quiet_window_s` (Settings, default 1.0) | Capture returns ~1 s after the last file event; lowering to 0.3 never loses the second file | Quiet window; `CAPTURE_COMPLETE` is often swallowed |
| 3.5 | `POST /capture/trigger` | Shutter fires, file appears via event | `trigger_capture` + event path |
| 3.6 | Capture with the card full or removed | `storage_full` / clear error, connection stays up | `GP_ERROR_NO_SPACE`, `CameraOperationFailed` classification |
| 3.7 | Capture while live view is on | Photo taken, live view resumes (or app re-enables it) within a few seconds | `invalidate_preview` after capture; viewfinder re-enable |
| 3.8 | Capture with capture target = internal RAM (`PUT /camera/capture-target`) | Behaviour recorded: file transferable or not | `match_target`; RAM target semantics |
| 3.9 | **auto** `GET /camera/storage` | One entry per card, capacity/free plausible, `free_images` set | `storage_info()`; note slot ordering and label |
| 3.10 | `GET /camera/files` on a card with 1000+ images; time it; repeat | First listing time recorded; second served from cache | Card listing speed; listing cache |
| 3.11 | `POST /camera/files/download-all` with a NEF in the set; cancel midway | Files land under `output/camera/`; cancel leaves no partial files; re-run skips downloaded ones | Download job, ledger, tmp cleanup |
| 3.12 | `DELETE /camera/files/{folder}/{name}` on a test image | Gone from the card | `delete_file` |
| 3.13 | Open the gallery for a downloaded NEF | Thumbnail renders, correct orientation | Embedded JPEG preview extraction (IFD walk, byte-scan fallback) in `thumbnails.py` |
| 3.14 | Same for a NEF+JPEG pair and a portrait-orientation NEF | Right thumbnails, rotation correct | EXIF orientation handling |

## 4. Live view

| # | Action | Expected | Verifies |
|---|---|---|---|
| 4.1 | **auto** Start live view; frames arrive; check mirror/viewfinder on the body | JPEG frames; test prints first-frame time, fps and frame size | `viewfinder`=1 enables live view; `capture_preview` |
| 4.2 | Stop live view | Body leaves live view; `viewfinder` reads 0 | `end_preview` via the `viewfinder` widget |
| 4.3 | Change `liveviewsize` (Settings/Advanced) while streaming | Frame size changes, stream continues | `liveviewsize` widget semantics |
| 4.4 | Open two browser tabs on live view, close one | Stream continues for the other; closing both stops live view | Refcounted producer |
| 4.5 | Leave live view on 10 minutes | No 60 s timeout disconnect; fps stable | Keepalive during live view; USB 2.0 8 fps target |
| 4.6 | Live view up, press the body's shutter / info button | App recovers or reports; no hang | `capture_preview` error mapping |

## 5. Keepalive and recovery

| # | Action | Expected | Verifies |
|---|---|---|---|
| 5.1 | Connect, leave idle 5 minutes (keepalive on, 30 s) | Still connected, no auto power-off | `summary()` as keepalive resets the D500 60 s timer |
| 5.2 | Disable keepalive (Settings), idle 2 minutes | Record whether the body powers down / disconnects | Whether keepalive is actually required |
| 5.3 | Unplug USB for 10 s, replug | UI shows reconnecting then `idle` without restarting the app/container | `_lost` -> reconnect loop; Docker device remap on replug |
| 5.4 | Power the camera off and on | Same recovery | As above |
| 5.5 | Pull the cable mid-capture and mid-live-view | Error reported, state ends `disconnected` or `idle` after reconnect, no stuck lease | Link-loss during in-flight call; worker reset |

## 6. Time-lapse

| # | Action | Expected | Verifies |
|---|---|---|---|
| 6.1 | `GET /timelapse/preview` for 1 s interval JPEG, then NEF+JPEG | Warning when interval is shorter than a measured frame | `SHOT_ESTIMATE_S` (1.0 s) estimate |
| 6.2 | Run 30 frames at the minimum interval accepted | Frames at steady cadence; `interval_too_short` warning appears iff real time exceeds the interval | Runner measurement vs estimate |
| 6.3 | Run with a 3-step EV bracket per interval | Three frames per slot; settings restored to the original after the set | `SETTLE_S` 0.3 s, `RESTORE_S` 0.5 s; bracket restore |
| 6.4 | Pause/resume, then stop mid-run | Session saved, camera released, settings restored | Lease handling |
| 6.5 | Unplug USB mid-run | Run aborts or pauses according to the failure budget, partial session kept | Failure budget and recovery |
| 6.6 | Render the session to video | MP4 plays, frame count right | Video service (ffmpeg) |

## 7. Presets and brackets

| # | Action | Expected | Verifies |
|---|---|---|---|
| 7.1 | `POST /presets/from-camera`, change settings, `POST /presets/{id}/apply` | Camera back at captured values | Preset values valid against real choice strings |
| 7.2 | Apply a built-in preset | Validated against the connected body; unsupported values reported clearly | Preset validation vs D500 choices |
| 7.3 | `POST /capture/bracket` with 3 and 5 EV steps | N frames, original exposure restored | One-shot bracket via `exposurecompensation` |

## 8. Bulb

| # | Action | Expected | Verifies |
|---|---|---|---|
| 8.1 | Mode M, `POST /capture/bulb` for 5 s | Shutter opens, closes after ~5 s, file downloaded | `bulb` widget is a toggle writable as 1/0 (or whichever mechanism the driver uses) |
| 8.2 | Same in P/A/S | Warning plus either a working exposure or a clear error | M-mode requirement is best effort |
| 8.3 | 30 s bulb with long-exposure NR on | File arrives about 30 s later than shutter close | NR delays `FILE_ADDED` |
| 8.4 | Cancel a bulb mid-exposure; stop the app mid-exposure | Shutter closes in both cases, image retrievable | Shielded close sequence; shutdown order |
| 8.5 | Record what the Shutter Speed widget reads while bulb runs | Value noted | Whether `shutterspeed=Bulb` is needed first |

## 9. Video recording

| # | Action | Expected | Verifies |
|---|---|---|---|
| 9.1 | `POST /recording/start` (live view on or off), 10 s, `POST /recording/stop` | Clip on the card (MOV); state returns to idle/live view | `movie` widget start/stop |
| 9.2 | Read `movie` right after start | Record the value (1? other constant?) | `_is_on` readback interpretation |
| 9.3 | Record with capture target = card vs RAM | Clip lands on the card in both; warning shown for RAM | Capture target irrelevance |
| 9.4 | Download the clip after stop (download-after option) | File intact, plays | `FILE_ADDED` for clip within the bounded wait (5 s) |
| 9.5 | Record past 29:59 (or use a card-limit test) | New segment event, `segments` increments, no hang | `MAX_CLIP_S` 1799; segment events |
| 9.6 | Live view stream while recording | Frames continue | `capture_preview` works in RECORDING |
| 9.7 | Camera stops by itself (card full / battery) | Watchdog reports reason, lease released | Watchdog |

## 10. Focus

| # | Action | Expected | Verifies |
|---|---|---|---|
| 10.1 | `POST /focus/af` on a lens in AF | Focus acquired; error cleanly if no target or lens in MF | `autofocusdrive` semantics |
| 10.2 | `POST /focus/mf` +/- steps (1..3 and max) in live view | Focus moves near/far consistently; record which sign is near and the accepted step range | `manualfocusdrive` direction, step range |
| 10.3 | `POST /focus/mf` with live view off | Works (app enables live view and restores idle) or clear error | Live-view requirement |
| 10.4 | `POST /focus/stack` 5 frames, step size 2 | 5 images with progressive focus; camera returns to origin | Relative position tracking; `RETURN_TIMEOUT_S` |
| 10.5 | Cancel a stack mid-run | Focus returns, lease released | Cancel path |

## 11. Clock and capture target

| # | Action | Expected | Verifies |
|---|---|---|---|
| 11.1 | `GET /camera/datetime` and compare with the camera menu | Same wall time, offset to host small | `datetime` widget epoch semantics |
| 11.2 | `PUT /camera/datetime` with a known wall time, check menu; repeat with the host in a different time zone (`TZ` of the host) | Camera shows the requested wall time in both cases | libgphoto2 converts with the SERVER zone (`_raw_epoch_for`) |
| 11.3 | `PUT /camera/datetime` around a DST change date | Correct wall time | DST handling |
| 11.4 | `GET`/`PUT /camera/capture-target` card and ram | Value changes on the body; subsequent captures follow | `capturetarget` choice names; `match_target` |

## 12. Sign-off

Record firmware, lens, card, host OS, Docker version, and any item that failed with the printed output. Failed items should become issues that name the code assumption in the last column.
