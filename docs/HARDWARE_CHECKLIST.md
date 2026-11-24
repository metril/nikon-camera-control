# Hardware checklist (Nikon D500)

Nothing in this project has been run against a real camera; it was developed against `FakeCamera`. This is the list to work through with a D500 attached. Items marked **auto** are also exercised by `pytest -m hardware --real-camera -n 0 -s tests/hardware`.

Setup: mode dial on P/A/S/M, card inserted, battery above 50%, camera on, USB direct to the host, `docker/udev/99-nikon.rules` installed, the app running with the demo camera switch OFF (Settings). Record firmware version and lens used. Where an item says "API", use `/docs` (live OpenAPI UI) or the Shoot/Advanced views.

Legend: **Verifies** is the code assumption that the result confirms or refutes. Report refutations as issues with the printed output.

## 1. Connection

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 1.1 | **auto** Click Connect (`POST /camera/connect`) | State `idle`, model contains "D500", serial set, within ~10 s | `Gphoto2Backend.open`, `get_abilities().model` | ✅ App already connected at test start: state `idle`, model "Nikon DSC D500", serial set; connect time not re-measured. Firmware V1.31 (from summary), libgphoto2 2.5.34, app 0.3.0. |
| 1.2 | `GET /camera/summary` | Non-empty text | `summary()` works as the keepalive probe | ✅ 0.26 s, full text incl. both storage slots and property summary. |
| 1.3 | Start the app while another process (gvfs, `gphoto2` CLI) holds the camera | Clear "claimed by another process" error (409/503), no crash; works after releasing | `GP_ERROR_IO_USB_CLAIM` -> `CameraBusy` | ⏭ Needs user: on karpo run `gphoto2 --summary` (or mount via gvfs) while the app is connecting, then POST /camera/connect. |
| 1.4 | Connect with camera off | `camera_not_found` error, state stays `disconnected` | `GP_ERROR_MODEL_NOT_FOUND` mapping | ⏭ Needs user: power camera off, POST /camera/connect. Observed instead with the camera wedged (see sign-off): 504 `CAMERA_TIMEOUT` "Camera operation timed out" after 10 s, state `disconnected` (not `camera_not_found`). |

## 2. Settings

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 2.1 | **auto** `GET /settings`; note which widgets are missing (hardware test prints them) | All of iso, f-number, shutterspeed, exposurecompensation, autoexposuremode, focusmode, whitebalance, imagequality, imagesize, liveviewsize, viewfinder, capturetarget, meteringmode, batterylevel, datetime, bulb, movie, manualfocusdrive, autofocusdrive present | Widget names used across services exist on the D500 | ✅ retest; earlier ❌ GET /settings returns 15 common widgets. `autoexposuremode` and `meteringmode` do not exist on the D500 (404 `SETTING_NOT_FOUND`); D500 names are `expprogram` and `exposuremetermode`. `datetime`, `bulb`, `movie`, `manualfocusdrive`, `autofocusdrive` exist via GET /settings/{name} (not in the list, `writable:false`). `viewfinder`, `liveviewsize`, `capturetarget`, `batterylevel` present. **Retest (fixes deployed):** ✅ `autoexposuremode` (path `expprogram`; P/A/M GET and PUT ok), `meteringmode` (`exposuremetermode`; Center Weighted <-> Multi Spot ok, 0.35-0.61 s), `isoauto` (`autoiso`, On/Off ok) now resolve. `drivemode` (`capturemode`) resolves; PUT -> 403 `SETTING_NOT_ALLOWED` "Setting 'capturemode' is read-only" (clean). All original values restored. |
| 2.2 | **auto** `GET /settings/iso` | `path` like `/main/imgsettings/iso`, type radio, choices listed | Path format `/main/<section>/<name>`; `get_single_config` works | ✅ `/main/imgsettings/iso`, radio, 31 choices (50..51200). Note PUT/PATCH responses return a shortened path (`/iso`) instead of the full path. |
| 2.3 | **auto** Read choices for iso, f-number, shutterspeed, exposurecompensation, whitebalance, imagequality (test prints them) | Formats match the tolerant matcher: iso `"100"`, f-number `"f/2.8"` or `"2.8"`, shutterspeed `"1/250"`/`"30"`/`"Bulb"`, EV `"-0.7"` vs `"-0.667"`, WB names, quality `"NEF+Fine"`-style | `SettingsService.prepare`/`resolve_name` tolerant matching | ✅ iso `"100"`; f-number `"f/2.8"`; shutterspeed decimal seconds `"0.0040s"` plus `"Bulb"`,`"Time"` (never `"1/250"`); shutterspeed2 has fractions incl. odd `"10/25"`,`"13/10"`,`"x 200"`; EV `"-0.666"`/`"-0.333"` (not -0.7); WB `Automatic, Daylight, Fluorescent, Tungsten, Flash, Cloudy, Shade, Color Temperature, Preset`; quality `"JPEG Fine*"`, `"NEF (Raw)"`, `"NEF+Fine*"` (star = size priority variant). Matcher accepts all of these. |
| 2.4 | `PUT /settings/f-number` with `2.8`, `f/2.8`, `F2.8` | All resolve to the same choice; the value reads back equal | Tolerant matching of f-number | ✅ Tested in M mode (in P, f-number is read-only: 403 `SETTING_NOT_ALLOWED`). `2.8`, `f/2.8`, `F2.8`, `"2.8"` all -> `f/2.8`, readback `f/2.8`. |
| 2.5 | `PUT /settings/shutterspeed` with `1/250`, `0.004`, `2`, `2"` | Resolved to the camera choice; readback equal | Shutter speed parsing | ✅ retest; earlier ❌ Matcher resolves correctly (`1/250` -> `0.0040s`) but the camera ends one 1/3 stop FASTER than requested: `1/250`->`0.0031s`(1/320), `0.004`->`0.0031s`, `1/125`->`0.0062s`, `1/1000`->1/1250, `1/500`->1/640, `1/30`->1/40, `1`->`0.7692s`, `2`->`1.6000s`, `30`->25. Exact only at the ends (`1/8000`, `Bulb`). Same via `shutterspeed2` (`1/250`->`1/320`). PUT returns 200 with the shifted readback, no warning. `2"` -> 422 `SETTING_INVALID` (not a choice). Likely libgphoto2 2.5.34 / body index quirk below the app (`gphoto2_backend.py:346` just calls `set_value`); the app should compare readback to request and warn or retry. **Retest (fixes deployed):** ✅ In M: `1/250` -> `0.0040s`, `1/60` -> `0.0166s`, `2` -> `2.0000s`, `1/1000` -> `0.0010s`; read-back equals request each time (~0.5 s per PUT, no warning needed). `2"` -> 422 `SETTING_INVALID` (not a choice); `1/8000` -> 422 `SETTING_INVALID` (choices start at `0.0001s`). |
| 2.6 | `PUT /settings/exposurecompensation` with `-0.7`, `-0.667`, `1` | Resolved; readback equal | EV decimal matching | ✅ `-0.7`->`-0.666`, `-0.667`->`-0.666`, `1`->`1`, `"-0.7"`->`-0.666`; readback equal. |
| 2.7 | `PUT /settings/imagequality` with `NEF (RAW) + JPEG Fine` style and with alias `imageformat` | Accepted, alias works | Quality choices; `ALIASES` | ✅ `imageformat` alias works (`NEF+Fine`). The literal `NEF (RAW) + JPEG Fine` is rejected 422 `SETTING_INVALID` (D500 strings are `NEF+Fine`, `NEF (Raw)`, `JPEG Fine`, ...), with `nearby` suggestions. |
| 2.8 | Write every `WRITABLE` name once (iso, whitebalance, colorspace, drivemode, meteringmode, focusmode, flashmode, imagesize, liveviewsize, autoexposuremode, shutterspeed2, ...) with its current value | No `setting_not_found`; read-only ones are reported as read-only, not as errors | Allowlist names exist on the D500; names with `2` suffix may not exist | ✅ retest; earlier ❌ Of 20 `WRITABLE` names, 5 do not exist on this body (404 `SETTING_NOT_FOUND`): `autoexposuremode`, `meteringmode`, `drivemode`, `isoauto`, `exposurecompensation2`. In P mode read-only (403 `SETTING_NOT_ALLOWED`, reported cleanly): `focusmode`, `f-number`, `shutterspeed`, `shutterspeed2`. Written fine: `expprogram`, `focusmode2`, `focusmetermode`, `iso`, `exposurecompensation`, `whitebalance`, `colorspace`, `imagequality`, `imagesize`, `flashmode`, `liveviewsize`. D500 metering widget is `exposuremetermode` (not on the allowlist). **Retest (fixes deployed):** ✅ Logical names `autoexposuremode`, `meteringmode`, `drivemode`, `isoauto` no longer 404 (see 2.1); writable ones round-tripped, read-only `drivemode` reported as 403 read-only. `exposurecompensation2` not retested. |
| 2.9 | Set a value on the mode dial in Auto/scene mode | Error or no change, reported; never silent success | README mode-dial warning | ⏭ N/A on D500 (P/A/S/M only, no Auto/scene). Related finding: mode IS settable remotely: PUT `expprogram` M/A/P all worked (mode before exposure, f-number and shutter became writable in M). |
| 2.10 | `PATCH /settings` with aperture, shutterspeed, iso, mode together | Applied in the `WRITABLE` order, final state correct | Mode-before-exposure ordering | ✅ PATCH `{expprogram:M, f-number:f/4, shutterspeed:1/125, iso:400}` applied in one 0.14 s call; final M, f/4, iso 400 (shutter read `0.0062s` = the 2.5 shift). In P mode the same PATCH with `f-number` is rejected whole with 403 `SETTING_NOT_ALLOWED`. |
| 2.11 | Change a setting on the camera body, then `POST /settings/refresh` | New value shown | Per-connection settings cache invalidation | ⏭ Needs user: change ISO on the body, then POST /settings/refresh and compare. |

## 3. Capture and files

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 3.1 | **auto** `POST /capture` with JPEG only | One file; total time printed (shutter + drain) | `capture()` returns path; `FILE_ADDED` timing | ✅ RAM target, JPEG Fine: 1 file 5.07 MB, 0.83 s total. |
| 3.2 | `POST /capture` with NEF only | One `.NEF`, downloaded fully (30-50 MB) | Chunked 1 MiB download (`read_file`) | ✅ RAM target, `NEF (Raw)`: 1 file 21.7 MB (not 30-50 MB), 0.73 s. Log shows `partial_read_unsupported ... [-1] Unspecified error` for every RAM-target file (chunked read falls back to whole-file read); no such line for card files, so chunked read works from the card. |
| 3.3 | `POST /capture` with NEF+JPEG | Two files (both names returned and downloaded) | RAW+JPEG yields two `FILE_ADDED` events; de-duplication | ✅ RAM NEF+Fine: `.jpg` 5.85 MB + `.nef` 21.8 MB, 1.09 s. Card NEF+Fine: `DSC_2153.NEF` (slot 1) + `DSC_2153.JPG` (slot 2), 31.4 s. Note: card JPEG-only or NEF-only returns the SAME file twice (slot 2 is backup: `DSC_2151.JPG` and `DSC_2151_1.JPG`, identical 5107985 B; same for NEF) - de-dup is by path only. **Retest (fixes deployed):** Card JPEG-only/NEF-only still yields 2 identical files from slots 1 and 2 (de-dup is by path, names differ by `_1`); NEF+Fine on card 2 files (correct). |
| 3.4 | Time the capture call; vary `event_quiet_window_s` (Settings, default 1.0) | Capture returns ~1 s after the last file event; lowering to 0.3 never loses the second file | Quiet window; `CAPTURE_COMPLETE` is often swallowed | ❌ RAM: 0.73-1.3 s. Memory card target: 30.95, 31.80, 31.38, 31.38 s (= `capture_timeout_s` 30 + ~1). With `capture_timeout_s`=10 the same capture took 11.34 s, so the drain never ends via CAPTURE_COMPLETE/quiet window on card target (likely UNKNOWN events keep resetting `last`, `camera_service.py:~813`, or `cam.capture()` itself blocks). `event_quiet_window_s` changed via PATCH /config (nested `camera.event_quiet_window_s`) has no effect at runtime (read once at startup, `app.py:127`). Lowering not testable usefully. **Retest (fixes deployed):** ✅ Card target now 4.10 s (JPEG Fine), 4.95 s (NEF Raw), 6.05 s (NEF+Fine) instead of ~31 s; RAM 0.75 / 0.83 / 1.05 s. `event_quiet_window_s` runtime effect not retested. ❌ Still: card JPEG-only and NEF-only return TWO files (slot 1 + slot 2 backup, `DSC_2158.JPG` + `DSC_2158_1.JPG`, identical 8402418 B; NEF 25560350 B x2). NEF+JPEG on card: 2 files (NEF + JPG), correct. RAM: JPEG 1, NEF 1, NEF+JPEG 2. See Retest block. |
| 3.5 | `POST /capture/trigger` | Shutter fires, file appears via event | `trigger_capture` + event path | ✅ POST /capture/trigger returns `{ok:true}` in 0.25 s; shutter fires. On card target the new file appears on the card listing. RAM-target arrival cannot be observed through the API (no download). |
| 3.6 | Capture with the card full or removed | `storage_full` / clear error, connection stays up | `GP_ERROR_NO_SPACE`, `CameraOperationFailed` classification | ⏭ Needs user: capture with both cards removed, then with a full card (or set card to write-protect). |
| 3.7 | Capture while live view is on | Photo taken, live view resumes (or app re-enables it) within a few seconds | `invalidate_preview` after capture; viewfinder re-enable | ✅ retest; earlier ❌ Capture in live view works (1.37 s, JPEG+NEF) but live view does NOT resume: `phase=waiting reason=preview_failed`, no frames for >=16 s; snapshot -> 409 `CAMERA_BUSY` "set_config(viewfinder): I/O in progress" (gphoto2 -110). Manual stop/start recovers. Cause: `gphoto2_backend.py:405-414` `invalidate_preview` clears `_viewfinder_on`, so each preview re-sets `viewfinder=1`; -110 is not in the swallowed exceptions (`:412`) and keeps failing while the body is still in live view. **Retest (fixes deployed):** ✅ Live view running (8.8 fps), capture 0.97 s (1 JPEG), first snapshot 2.4 s later 200, then frames continued; `frames_produced` 21 -> 102 over 12 s, phase `streaming`, ~8 fps. Log: `viewfinder_busy_assuming_on` (the -110 is now swallowed). |
| 3.8 | Capture with capture target = internal RAM (`PUT /camera/capture-target`) | Behaviour recorded: file transferable or not | `match_target`; RAM target semantics | ✅ `Internal RAM`: file transferable (names `capt00NN.jpg/.nef`, downloaded in full). Choices: `Internal RAM`, `Memory card`. |
| 3.9 | **auto** `GET /camera/storage` | One entry per card, capacity/free plausible, `free_images` set | `storage_info()`; note slot ordering and label | ✅ 2 entries: `NIKON D500  [Slot 1]` base `/store_00010001` cap 1000073216 KB, free 929944576 KB, 4630 images; `D500 SDXC [Slot 2]` base `/store_00020001` cap 125008896 KB, free 90677248 KB, 4630 images; `access: ro`. |
| 3.10 | `GET /camera/files` on a card with 1000+ images; time it; repeat | First listing time recorded; second served from cache | Card listing speed; listing cache | ❌ Slot 1 recursive (`folder=/store_00010001&recursive=true`): 2694 files, first listing 73.3 s, second 0.02 s (cached). Default `GET /camera/files` (folder `/`), also recursive from `/`: 502 `CAMERA_OPERATION_FAILED` "list_files(/): Unspecified error" (gphoto2 -1; root only has store folders), `files.py` should list per storage. **Retest (fixes deployed):** ❌/✅ Slot listing fast now: slot 1 recursive 2701 files 5.95 s first (0.07 s repeat), slot 2 41.8 s; a capture started 2 s into the slot-1 listing returned 200 in 0.68 s (not blocked). But `GET /camera/files` at root `/` still 502 `CAMERA_OPERATION_FAILED` "file_info(/capt0003.nef): Unspecified error" (gphoto2 -1; RAM-target captures leave `capt00NN.*` entries listed at `/` that cannot be stat'ed), also with `folder=/&limit=500`. |
| 3.11 | `POST /camera/files/download-all` with a NEF in the set; cancel midway | Files land under `output/camera/`; cancel leaves no partial files; re-run skips downloaded ones | Download job, ledger, tmp cleanup | ⏭ Not run: camera dropped before this was reached (see sign-off). Run with `folder=/store_00010001/DCIM/103ND500` (few files) after recovery; avoid whole-card (2694 files, ~60 GB). |
| 3.12 | `DELETE /camera/files/{folder}/{name}` on a test image | Gone from the card | `delete_file` | ⏭ Skipped by test rules (no deletes on the camera card). |
| 3.13 | Open the gallery for a downloaded NEF | Thumbnail renders, correct orientation | Embedded JPEG preview extraction (IFD walk, byte-scan fallback) in `thumbnails.py` | ✅ `/thumbnails/...NEF` 200 in 0.16 s, 200x133 JPEG (1.6 KB) of a dark landscape frame; orientation can only be judged on a known scene. |
| 3.14 | Same for a NEF+JPEG pair and a portrait-orientation NEF | Right thumbnails, rotation correct | EXIF orientation handling | ⏭ Needs user: take a portrait-orientation NEF+JPEG (rotate camera) and compare thumbnails. |

## 4. Live view

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 4.1 | **auto** Start live view; frames arrive; check mirror/viewfinder on the body | JPEG frames; test prints first-frame time, fps and frame size | `viewfinder`=1 enables live view; `capture_preview` | ✅ POST /liveview/start, first frame immediate, 65 frames / 8 s = 8.1 fps (status 7.97), QVGA 320x212, ~28.7 KB/frame. Whether the mirror/viewfinder shows live view: needs user (the `viewfinder` widget reads False during live view). |
| 4.2 | Stop live view | Body leaves live view; `viewfinder` reads 0 | `end_preview` via the `viewfinder` widget | ✅ stop -> `phase stopped`, camera state `idle`, `viewfinder` reads False. Needs user to confirm the body visually left live view. |
| 4.3 | Change `liveviewsize` (Settings/Advanced) while streaming | Frame size changes, stream continues | `liveviewsize` widget semantics | ✅ QVGA->VGA->XGA: frame ~28 KB -> 92 KB -> 190 KB, dims 320x212 -> 640x424 -> 1024x680, stream continued at ~8.3 fps; PUT 0.45 s. Restored to QVGA. |
| 4.4 | Open two browser tabs on live view, close one | Stream continues for the other; closing both stops live view | Refcounted producer | ⏭ Test invalid: it ran after the 3.7 failure so no stream was producing. Re-run after fix/recovery. Note a stream started with /liveview/start is `sticky` and stays running with 0 clients by design. |
| 4.5 | Leave live view on 10 minutes | No 60 s timeout disconnect; fps stable | Keepalive during live view; USB 2.0 8 fps target | ⏭ Not run: camera dropped (see sign-off). |
| 4.6 | Live view up, press the body's shutter / info button | App recovers or reports; no hang | `capture_preview` error mapping | ⏭ Needs user: with live view up press the body shutter / info button. |

## 5. Keepalive and recovery

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 5.1 | Connect, leave idle 5 minutes (keepalive on, 30 s) | Still connected, no auto power-off | `summary()` as keepalive resets the D500 60 s timer | ⏭ Not run: camera dropped (see sign-off). |
| 5.2 | Disable keepalive (Settings), idle 2 minutes | Record whether the body powers down / disconnects | Whether keepalive is actually required | ⏭ Not run. |
| 5.3 | Unplug USB for 10 s, replug | UI shows reconnecting then `idle` without restarting the app/container | `_lost` -> reconnect loop; Docker device remap on replug | ⏭ Needs user: unplug USB 10 s and replug. See sign-off: the app did not recover on its own after the camera wedged. **Retest (fixes deployed):** Retest: POST /camera/disconnect then /camera/connect recovers: from `error` disconnect 3.0 s (`gphoto2_exit_failed` + `usb_device_reset`) then connect 0.62 s -> `idle`; from healthy `idle` 0.03-0.06 s + 0.47-0.64 s. |
| 5.4 | Power the camera off and on | Same recovery | As above | ⏭ Needs user: power-cycle the camera. |
| 5.5 | Pull the cable mid-capture and mid-live-view | Error reported, state ends `disconnected` or `idle` after reconnect, no stuck lease | Link-loss during in-flight call; worker reset | ⏭ Needs user: pull the cable mid-capture / mid-live-view. |

## 6. Time-lapse

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 6.1 | `GET /timelapse/preview` for 1 s interval JPEG, then NEF+JPEG | Warning when interval is shorter than a measured frame | `SHOT_ESTIMATE_S` (1.0 s) estimate | ⏭ Estimate-only check offline: POST /timelapse/preview 1 s interval x10 JPEG-size estimate -> 9 s, 250 MB, no warning; 3 s interval with 3-step bracket -> 422 `CONFIG_INVALID` "Interval 3s is too short for 3 bracket shots; minimum is 4.4s". Measured-frame comparison not run. |
| 6.2 | Run 30 frames at the minimum interval accepted | Frames at steady cadence; `interval_too_short` warning appears iff real time exceeds the interval | Runner measurement vs estimate | ⏭ Not run: camera dropped. |
| 6.3 | Run with a 3-step EV bracket per interval | Three frames per slot; settings restored to the original after the set | `SETTLE_S` 0.3 s, `RESTORE_S` 0.5 s; bracket restore | ⏭ Not run: camera dropped. |
| 6.4 | Pause/resume, then stop mid-run | Session saved, camera released, settings restored | Lease handling | ⏭ Not run: camera dropped. |
| 6.5 | Unplug USB mid-run | Run aborts or pauses according to the failure budget, partial session kept | Failure budget and recovery | ⏭ Needs user: unplug USB mid-run. |
| 6.6 | Render the session to video | MP4 plays, frame count right | Video service (ffmpeg) | ⏭ Not run: needs a session first. |

## 7. Presets and brackets

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 7.1 | `POST /presets/from-camera`, change settings, `POST /presets/{id}/apply` | Camera back at captured values | Preset values valid against real choice strings | ❌ POST /presets/from-camera with default names captured `focusmode` (read-only on D500) plus `f-number`/`shutterspeed`; apply -> 403 `SETTING_NOT_ALLOWED` "Setting 'focusmode' is read-only" and nothing applied. With explicit `names` (iso, whitebalance, exposurecompensation, imagequality) apply restored all values (0.26 s). Cause: `presets.py:77` `DEFAULT_FROM_CAMERA` = COMMON intersect WRITABLE includes widgets the body reports read-only; apply is atomic. **Retest (fixes deployed):** ✅/❌ Explicit names (iso, whitebalance, exposurecompensation, imagequality, focusmode, f-number, shutterspeed): apply -> 200 (0.06 s), `applied` 4 values, `skipped` focusmode/f-number/shutterspeed with reason "Setting 'X' is read-only" (no 403). ❌ Default from-camera (no `names`) now fails at create: 403 `SETTING_NOT_ALLOWED` "Setting 'exposuremetermode' cannot be stored in a preset" (also with `names:[meteringmode,...]`); the preset allowlist lacks the D500 physical name. |
| 7.2 | Apply a built-in preset | Validated against the connected body; unsupported values reported clearly | Preset validation vs D500 choices | ✅ 9 built-in bracket presets (no settings presets); apply returns resolved steps without error (exposure_3: -2/0/+2 EV; iso_3: 200/800/3200; aperture_sweep f/2.8,5.6,11 validated in M mode; hdr_iso_combo; astro_stack). Nothing is started. |
| 7.3 | `POST /capture/bracket` with 3 and 5 EV steps | N frames, original exposure restored | One-shot bracket via `exposurecompensation` | ✅ Quick bracket `exposure` 3 steps: 3 JPEGs, job 5 s; 5 steps: 5 JPEGs, job 7 s. Exposure compensation and ISO restored to the pre-bracket values (tested starting at EC +1 / ISO 1600). |

## 8. Bulb

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 8.1 | Mode M, `POST /capture/bulb` for 5 s | Shutter opens, closes after ~5 s, file downloaded | `bulb` widget is a toggle writable as 1/0 (or whichever mechanism the driver uses) | ✅ M mode, 5 s: job completed in 7.1 s including download; 1 JPEG 6.6 MB; no warnings. |
| 8.2 | Same in P/A/S | Warning plus either a working exposure or a clear error | M-mode requirement is best effort | ✅ In A and P: job completes (3 s requested, 5.1 s) with warning "Exposure program is 'A', not M; bulb usually needs M (turn the mode dial to M, it cannot be set remotely)." The warning text is wrong: `expprogram` can be set remotely (see 2.9). Whether a true 3 s exposure happened in A/P was not checked. **Retest (fixes deployed):** Warning text now: "Exposure program is 'P', not M; bulb usually needs M (set the exposure program (expprogram) to M in Settings or on the mode dial)." (3 s job completed in 4.75 s, 1 JPEG). The wrong "cannot be set remotely" claim is gone. |
| 8.3 | 30 s bulb with long-exposure NR on | File arrives about 30 s later than shutter close | NR delays `FILE_ADDED` | ⏭ Skipped: 30 s exceeds the 10 s bulb limit for this run; also needs long-exposure NR enabled in the camera menu (user). |
| 8.4 | Cancel a bulb mid-exposure; stop the app mid-exposure | Shutter closes in both cases, image retrievable | Shielded close sequence; shutdown order | ✅ Cancel via DELETE /jobs/{id} at ~3 s of 10 s: job `cancelled` after 4.9 s, camera `idle`, bulb inactive, image still arrived and was saved (`capt0032.jpg` 7.17 MB). App-stop mid-exposure not tested (no restarts allowed). |
| 8.5 | Record what the Shutter Speed widget reads while bulb runs | Value noted | Whether `shutterspeed=Bulb` is needed first | ✅ Shutter Speed widget reads `Bulb` during the exposure (the app sets it itself) and returns afterwards, but not to the original: before 0.0100s, after 0.0062s / 0.0080s (same one-step drift as 2.5). |

## 9. Video recording

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 9.1 | `POST /recording/start` (live view on or off), 10 s, `POST /recording/stop` | Clip on the card (MOV); state returns to idle/live view | `movie` widget start/stop | ⏭ Needs user: set the live view selector to the movie icon. Now: POST /recording/start (live view on or off) -> 502 `CAMERA_OPERATION_FAILED` "The camera refused to start recording (set_config(movie): Unspecified error). On Nikon bodies the live view selector must be set to movie mode." Error is clear; state returned to `idle`. |
| 9.2 | Read `movie` right after start | Record the value (1? other constant?) | `_is_on` readback interpretation | ⏭ Blocked by 9.1. |
| 9.3 | Record with capture target = card vs RAM | Clip lands on the card in both; warning shown for RAM | Capture target irrelevance | ⏭ Blocked by 9.1. |
| 9.4 | Download the clip after stop (download-after option) | File intact, plays | `FILE_ADDED` for clip within the bounded wait (5 s) | ⏭ Blocked by 9.1. |
| 9.5 | Record past 29:59 (or use a card-limit test) | New segment event, `segments` increments, no hang | `MAX_CLIP_S` 1799; segment events | ⏭ Blocked by 9.1 (and >29 min). |
| 9.6 | Live view stream while recording | Frames continue | `capture_preview` works in RECORDING | ⏭ Blocked by 9.1. |
| 9.7 | Camera stops by itself (card full / battery) | Watchdog reports reason, lease released | Watchdog | ⏭ Blocked by 9.1. |

## 10. Focus

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 10.1 | `POST /focus/af` on a lens in AF | Focus acquired; error cleanly if no target or lens in MF | `autofocusdrive` semantics | ✅ Lens/body AF-C (`focusmode` AF-C): POST /focus/af idle 0.37 s `focused:true`; in live view 1.11 s `focused:true`. |
| 10.2 | `POST /focus/mf` +/- steps (1..3 and max) in live view | Focus moves near/far consistently; record which sign is near and the accepted step range | `manualfocusdrive` direction, step range | ⏭ Needs user: set lens switch to M and body focus mode to MF, then re-run. Now: every POST /focus/mf (+-1, +-3, +-500, +-32767) in live view -> 409 `CAMERA_BUSY` "set_config(manualfocusdrive): I/O in progress" (gphoto2 -110); 40000 -> 422 range check OK. `focusmode2` cannot be changed remotely (422 "set_config(focusmode2): Bad parameters" for AF-S and MF (selection)). Range -32767..32767. Direction not determined. |
| 10.3 | `POST /focus/mf` with live view off | Works (app enables live view and restores idle) or clear error | Live-view requirement | ⏭ Same -110 failure with live view off (0.85 s); app returned to `idle`/stopped cleanly. Re-run after MF is set. |
| 10.4 | `POST /focus/stack` 5 frames, step size 2 | 5 images with progressive focus; camera returns to origin | Relative position tracking; `RETURN_TIMEOUT_S` | ✅ retest; earlier ❌ POST /focus/stack (5 shots, 2 steps) with capture target accidentally left on `Memory card`: job failed at "Shot 1/5" `CAMERA_TIMEOUT` "Camera operation timed out" (card capture takes ~31 s, 3.4), camera state went to `error`, then the camera could not be reconnected (see sign-off). Retest on RAM target with the lens in MF. **Retest (fixes deployed):** ✅ In AF-C: POST /focus/stack -> 409 `INVALID_STATE` "Manual focus drive and focus stacking need focus mode AF-S or MF; the camera is in AF-C. Change the focus mode on the body." (0.0 s, camera stays `idle`); same for /focus/mf. A 3-frame stack was not possible (body in AF-C, not remotely changeable). |
| 10.5 | Cancel a stack mid-run | Focus returns, lease released | Cancel path | ⏭ Not run: camera dropped. |

## 11. Clock and capture target

| # | Action | Expected | Verifies | Result |
|---|---|---|---|---|
| 11.1 | `GET /camera/datetime` and compare with the camera menu | Same wall time, offset to host small | `datetime` widget epoch semantics | ⏭ Needs user to compare with the menu. GET: `camera_wall_time` 2015-12-31T21:10:02, host 2026-11-24T08:31:01Z, offset -343912859.5 s (camera clock looks unset). |
| 11.2 | `PUT /camera/datetime` with a known wall time, check menu; repeat with the host in a different time zone (`TZ` of the host) | Camera shows the requested wall time in both cases | libgphoto2 converts with the SERVER zone (`_raw_epoch_for`) | ⏭ Skipped by test rules (no clock changes). |
| 11.3 | `PUT /camera/datetime` around a DST change date | Correct wall time | DST handling | ⏭ Skipped by test rules (no clock changes). |
| 11.4 | `GET`/`PUT /camera/capture-target` card and ram | Value changes on the body; subsequent captures follow | `capturetarget` choice names; `match_target` | ✅ GET/PUT work (`Internal RAM`/`Memory card`); captures follow the target (`capt00NN.*` vs `DSC_NNNN.*`). Card target = ~31 s captures (3.4). |

## 12. Sign-off

## Results (2026-11-24, ui-polish branch)

Body: Nikon D500, firmware V1.31; libgphoto2 2.5.34; app 0.3.0 in Docker on karpo (patched backend with the capture-download fix). Slot 1 1 TB (2694 images), slot 2 128 GB SDXC (backup). Lens not recorded (dark frames). Mode switched remotely P -> M -> A -> P through `expprogram`.

Totals (70 items): ✅ 26 pass, ❌ 8 fail, ⏭ 36 needs user / not run / skipped by rules.

Failures:
- 2.1 / 2.8: `autoexposuremode`, `meteringmode`, `drivemode`, `isoauto`, `exposurecompensation2` do not exist on the D500 (404 `SETTING_NOT_FOUND`); D500 uses `expprogram`, `exposuremetermode` (not on the allowlist).
- 2.5: shutter speed lands one 1/3 stop faster than requested (`1/250` -> `1/320`), 200 OK with no warning (also via `shutterspeed2`; bulb/restore drift 8.5).
- 3.4: capture with target `Memory card` takes ~31 s (30 s `capture_timeout_s` + quiet window); `event_quiet_window_s` is not applied at runtime.
- 3.7: live view does not resume after a capture (`preview_failed`, 409 `CAMERA_BUSY` "set_config(viewfinder): I/O in progress"); `gphoto2_backend.py:405-414`.
- 3.10: `GET /camera/files` default folder `/` -> 502 "list_files(/): Unspecified error"; first slot-1 listing 73 s.
- 7.1: default from-camera preset includes read-only `focusmode`; apply -> 403 "Setting 'focusmode' is read-only".
- 10.4: focus stack on card target -> `CAMERA_TIMEOUT`, camera went to `error`.
- Unplanned: after the 10.4 timeout the camera never reconnected. State `error`, then `disconnected`; POST /camera/connect -> 504 `CAMERA_TIMEOUT` "Camera operation timed out" every 10 s (more than 25 attempts over about 8 min; each attempt re-creates the USB device node, so the camera is being reset). No automatic recovery. The camera needs a power cycle or USB replug (user).

Other findings: card JPEG-only / NEF-only returns the same file twice (slot 2 backup); `partial_read_unsupported` for every RAM-target file; bulb warning text says the mode cannot be set remotely but it can; PUT/PATCH setting responses return short paths.

Needs user: power-cycle the camera (and replug USB if needed) so the app reconnects; then physically: live view selector to movie (section 9), lens and body to MF (10.2-10.5), portrait shot (3.14), card removal/full (3.6), press body buttons in live view (4.6), unplug/power-cycle tests (1.3, 1.4, 5.3-5.5, 6.5), camera-body setting change (2.11), compare clock menu (11.1), enable long-exposure NR (8.3), confirm the body leaves live view (4.1, 4.2). Not run for time/risk: 4.5, 5.1, 5.2, 6.2-6.4, 6.6, 3.11, 4.4.

State left behind (camera unreachable, could not restore): ISO 400 (was 2500), image quality `JPEG Fine` (was `NEF+Fine*`), capture target `Memory card` (was `Internal RAM`; app capturetarget is usually per session). Exposure program P, white balance Automatic, EC 0, live view size QVGA, focus mode AF-C are as found. App config (quiet window 1.0, capture timeout 30) restored. Restore ISO/quality/target after reconnecting.


## Retest (fixes deployed, 2026-11-24)

Same body (D500, V1.31), app 0.3.0 with the fixes. Scope: the 8 failed items. Result: 4 pass (2.1/2.8, 2.5, 3.7, 10.4), 2 partial (3.4, 3.10), 1 fail (7.1), 1 safe-subset only (8). 

| Item | Result | Numbers / errors |
|---|---|---|
| 2.1 / 2.8 | ✅ | GET+PUT `autoexposuremode`, `meteringmode`, `isoauto` work and restore; `drivemode` read-only -> 403 "Setting 'capturemode' is read-only". |
| 2.5 | ✅ | `1/250`->`0.0040s`, `1/60`->`0.0166s`, `2`->`2.0000s`, `1/1000`->`0.0010s`, all exact. |
| 3.4 | ❌ partial | Time fixed: card 4.1 / 4.95 / 6.05 s (was ~31 s); RAM 0.75 / 0.83 / 1.05 s. Still duplicates on card: JPEG-only and NEF-only give 2 identical files (slot 2 `_1` copy); NEF+JPEG gives 2 correct files. |
| 3.7 | ✅ | Frames resumed after capture; first snapshot 2.4 s, `frames_produced` 21->102, ~8 fps. |
| 3.10 | ❌ partial | Slot 1 listing 5.95 s (was 73 s), slot 2 41.8 s, capture during listing 0.68 s. Root `/` still 502 "file_info(/capt0003.nef): Unspecified error". |
| 7.1 | ❌ partial | Explicit names: apply 200 with `skipped` for read-only (good). Default from-camera create: 403 "Setting 'exposuremetermode' cannot be stored in a preset". |
| 10.4 | ✅ | AF-C -> 409 `INVALID_STATE` with a clear message. Real 3-frame stack not run (body stayed AF-C). |
| Bulb warning | ✅ | Now correct: "...set the exposure program (expprogram) to M in Settings or on the mode dial". |
| 8 | ✅ safe subset | Disconnect/connect recovery works (3.0 s + 0.62 s from `error`; 0.03 s + 0.5 s from idle). Full hang recovery: Needs hardware fault injection. |

Remaining failures:
- Root `GET /camera/files`: 502 "file_info(/capt0003.nef): Unspecified error" (stale RAM-target entries at `/`).
- Default `POST /presets/from-camera`: 403 "Setting 'exposuremetermode' cannot be stored in a preset".
- Card capture with slot 2 backup returns the same file twice for JPEG-only / NEF-only (de-dup by path only).
- New observation: after a `/camera/disconnect` + `/camera/connect` (USB reset) the body reverts to its dial position (`expprogram` M, shutterspeed `Bulb`, remote P is lost). The next POST /capture then opens the shutter on Bulb and hangs: client timeout at 60 s, camera state `error`, "camera operation timed out" (and POST /capture/trigger timed out at 15 s, then 409 `INVALID_STATE` "Cannot go from error to capturing"). Reproduced 3 times. disconnect/connect recovered each time; setting `expprogram` P first then capture 200 in 0.76 s. The app should warn or refuse capture in M with Bulb, or re-apply the mode after reconnect.
- PUT `drivemode` is read-only on this body in the current mode (info, not a fault).

Camera state restored: P, ISO 2500, auto ISO On, metering Multi Spot, WB Automatic, EC 0, quality `NEF+Fine*`, capture target `Internal RAM`, focus mode AF-C, liveview stopped, state `idle`.


Record firmware, lens, card, host OS, Docker version, and any item that failed with the printed output. Failed items should become issues that name the code assumption in the last column.
