# Nikon Camera Control API 0.7.1

> Generated file. Do not edit. Regenerate with `make api` (`.venv/bin/python -m scripts.gen_api`); CI fails if it is stale.
> Source of truth: route declarations and pydantic schemas. Machine-readable spec: `openapi.json`.

## Authentication

When an API key is configured, send it as the `X-API-Key` request header. WebSocket clients cannot set headers, so they offer the subprotocol `apikey.<key>`. A rejected WebSocket is accepted and then closed with code 4401; an open socket is closed with 4401 when the key changes. Cross-origin protection: POST/PUT/PATCH/DELETE and WebSocket requests that carry an `Origin` header must be same-origin (same host:port as `Host`) or listed in `cors_origins`; otherwise HTTP gets 403 `FORBIDDEN_ORIGIN` and a WebSocket is closed with 4403 before it is accepted. Requests without `Origin` are unaffected.

## Error envelope

Every non-2xx response has the body `{"error": {"code", "message", "details", "request_id"}}`. `X-Request-ID` is echoed in the response header.

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `code` | string | yes |  |  |  |
| `message` | string | yes |  |  |  |
| `details` | object | no |  |  |  |
| `request_id` | string \| null | no | `null` |  |  |

| Code | HTTP status | Exception | Default message |
|---|---|---|---|
| `INTERNAL_ERROR` | 500 | `AppError` | Internal error |
| `CAMERA_NOT_CONNECTED` | 503 | `CameraNotConnected` | Camera is not connected |
| `CAMERA_NOT_FOUND` | 404 | `CameraNotFound` | No camera detected. Check that it is switched on and the USB cable is connected. |
| `CAMERA_PERMISSION_DENIED` | 503 | `CameraPermissionDenied` | Camera found, but the app can't open it. |
| `CAMERA_BUSY` | 409 | `CameraBusy` | Camera is busy with another operation |
| `CAMERA_TIMEOUT` | 504 | `CameraTimeout` | Camera operation timed out |
| `CAMERA_IO_ERROR` | 502 | `CameraIOError` | Camera I/O error |
| `CAMERA_OPERATION_FAILED` | 502 | `CameraOperationFailed` | Camera operation failed |
| `STORAGE_FULL` | 507 | `StorageFull` | Camera storage is full |
| `NO_CARD` | 409 | `NoCard` | No memory card in the camera. Insert a card or save to camera memory. |
| `CARD_LOCKED` | 409 | `CardLocked` | The memory card is locked (write-protected). Unlock it or save to camera memory. |
| `INVALID_STATE` | 409 | `InvalidState` | Operation not allowed in the current state |
| `SETTING_NOT_FOUND` | 404 | `SettingNotFound` | Setting not found |
| `SETTING_NOT_ALLOWED` | 403 | `SettingNotAllowed` | Setting cannot be changed |
| `SETTING_INVALID` | 422 | `SettingInvalid` | Invalid value for setting |
| `FILE_NOT_FOUND` | 404 | `FileNotFoundError_` | File not found |
| `PATH_NOT_ALLOWED` | 400 | `PathNotAllowed` | Path is outside the allowed directory |
| `JOB_NOT_FOUND` | 404 | `JobNotFound` | Job not found |
| `PRESET_NOT_FOUND` | 404 | `PresetNotFound` | Preset not found |
| `SESSION_NOT_FOUND` | 404 | `SessionNotFound` | Session not found |
| `UNAUTHORIZED` | 401 | `Unauthorized` | Authentication required |
| `CONFIG_INVALID` | 422 | `ConfigInvalid` | Invalid configuration |
| `FEATURE_UNSUPPORTED` | 501 | `FeatureUnsupported` | Feature not supported by this camera |
| `VALIDATION_ERROR` | by handler | - | Produced by the framework error handlers |
| `NOT_FOUND` | by handler | - | Produced by the framework error handlers |
| `UNSUPPORTED_MEDIA` | 415 | `UnsupportedMedia` | No thumbnail can be generated for this file type |
| `FORBIDDEN` | 403 | `Forbidden` | This operation is not allowed |
| `FORBIDDEN_ORIGIN` | 403 | `ForbiddenOrigin` | Cross-origin request not allowed |
| `BULB_SHUTTER_OPEN` | 502 | `ShutterOpen` | Could not close the shutter |
| `RATE_LIMITED` | 429 | `RateLimited` | Too many failed attempts. Try again later. |
| `NO_TARGET` | 409 | `NoTargetError` | No storage target is available. Select and mount a target in Settings. |
| `LOCATION_NOT_FOUND` | 404 | `LocationNotFound` | Storage location not found |
| `LOCATION_BUSY` | 409 | `LocationBusy` | Storage location is busy |
| `MOUNT_FAILED` | 502 | `MountFailed` | Mount failed |
| `FILE_TOO_LARGE` | 413 | `FileTooLarge` | File is too large for the target filesystem (FAT32 limit is 4 GiB) |

## Endpoints

### auth

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/auth/status` | `get_auth_status` | Get Auth Status |
| POST | `/api/v1/auth/login` | `login` | Login |
| POST | `/api/v1/auth/logout` | `logout` | Logout |
| PUT | `/api/v1/auth/password` | `set_password` | Set Password |
| DELETE | `/api/v1/auth/password` | `delete_password` | Delete Password |
| GET | `/api/v1/auth/sessions` | `list_auth_sessions` | List Auth Sessions |
| POST | `/api/v1/auth/sessions/revoke-all` | `revoke_all_auth_sessions` | Revoke All Auth Sessions |
| DELETE | `/api/v1/auth/sessions/{session_id}` | `revoke_auth_session` | Revoke Auth Session |
| POST | `/api/v1/auth/kiosk/code` | `get_kiosk_pairing_code` | Get Kiosk Pairing Code |
| POST | `/api/v1/auth/kiosk` | `pair_kiosk` | Pair Kiosk |
| POST | `/api/v1/auth/kiosk-token/rotate` | `rotate_kiosk_token` | Rotate Kiosk Token |

### camera

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/camera` | `get_camera` | Get Camera |
| POST | `/api/v1/camera/connect` | `connect_camera` | Connect Camera |
| POST | `/api/v1/camera/disconnect` | `disconnect_camera` | Disconnect Camera |
| GET | `/api/v1/camera/battery` | `get_camera_battery` | Get Camera Battery |
| GET | `/api/v1/camera/storage` | `get_camera_storage` | Get Camera Storage |
| GET | `/api/v1/camera/summary` | `get_camera_summary` | Get Camera Summary |
| GET | `/api/v1/camera/datetime` | `get_camera_datetime` | Get Camera Datetime |
| PUT | `/api/v1/camera/datetime` | `set_camera_datetime` | Set Camera Datetime |
| GET | `/api/v1/camera/capture-target` | `get_capture_target` | Get Capture Target |
| PUT | `/api/v1/camera/capture-target` | `set_capture_target` | Set Capture Target |

### camera-files

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/camera/folders` | `list_camera_folders` | List Camera Folders |
| GET | `/api/v1/camera/files` | `list_camera_files` | List Camera Files |
| GET | `/api/v1/camera/thumbnail` | `get_camera_thumbnail` | Get Camera Thumbnail |
| GET | `/api/v1/camera/preview` | `get_camera_preview` | Get Camera Preview |
| POST | `/api/v1/camera/files/download-all` | `download_all_camera_files` | Download All Camera Files |
| POST | `/api/v1/camera/files/delete` | `delete_camera_files` | Delete Camera Files |
| GET | `/api/v1/camera/files/{folder}/{name}` | `download_camera_file` | Download Camera File |
| DELETE | `/api/v1/camera/files/{folder}/{name}` | `delete_camera_file` | Delete Camera File |

### capture

| Method | Path | operation_id | Summary |
|---|---|---|---|
| POST | `/api/v1/capture` | `capture_photo` | Capture Photo |
| POST | `/api/v1/capture/trigger` | `trigger_capture` | Trigger Capture |
| GET | `/api/v1/capture/bulb` | `get_bulb_status` | Get Bulb Status |
| POST | `/api/v1/capture/bulb` | `start_bulb_capture` | Start Bulb Capture |
| POST | `/api/v1/capture/bracket` | `start_bracket_capture` | Start Bracket Capture |

### config

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/config` | `get_config` | Get Config |
| PATCH | `/api/v1/config` | `update_config` | Update Config |
| GET | `/api/v1/config/schema` | `get_config_schema` | Get Config Schema |
| POST | `/api/v1/config/reset` | `reset_config` | Reset Config |
| POST | `/api/v1/config/api-key` | `create_api_key` | Create Api Key |
| DELETE | `/api/v1/config/api-key` | `delete_api_key` | Delete Api Key |

### events

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/events/schema` | `get_event_schema` | Get Event Schema |

### files

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/files/zip/{ticket}` | `download_zip` | Download Zip |
| GET | `/api/v1/files` | `list_files` | List Files |
| POST | `/api/v1/files/delete` | `delete_files` | Delete Files |
| POST | `/api/v1/files/zip` | `create_zip_download` | Create Zip Download |
| GET | `/api/v1/files/{path}` | `download_file` | Download File |
| DELETE | `/api/v1/files/{path}` | `delete_file` | Delete File |
| GET | `/api/v1/thumbnails/{path}` | `get_thumbnail` | Get Thumbnail |

### focus

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/focus` | `get_focus` | Get Focus Status |
| POST | `/api/v1/focus/af` | `autofocus` | Autofocus |
| POST | `/api/v1/focus/point` | `set_af_point` | Set Af Point |
| POST | `/api/v1/focus/mf` | `manual_focus` | Manual Focus |
| POST | `/api/v1/focus/reset` | `reset_focus_position` | Reset Focus Position |
| POST | `/api/v1/focus/stack` | `start_focus_stack` | Start Focus Stack |

### jobs

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/jobs` | `list_jobs` | List Jobs |
| GET | `/api/v1/jobs/{job_id}` | `get_job` | Get Job |
| DELETE | `/api/v1/jobs/{job_id}` | `cancel_job` | Cancel Job |

### kiosk

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/kiosk/scale` | `stream_kiosk_scale` | Stream Kiosk Scale |
| GET | `/api/v1/kiosk/display` | `stream_kiosk_display` | Stream Kiosk Display |
| POST | `/api/v1/kiosk/display` | `set_kiosk_display` | Set Kiosk Display |

### liveview

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/liveview` | `get_liveview` | Get Liveview Status |
| POST | `/api/v1/liveview/start` | `start_liveview` | Start Liveview |
| POST | `/api/v1/liveview/stop` | `stop_liveview` | Stop Liveview |
| GET | `/api/v1/liveview/snapshot` | `get_liveview_snapshot` | Get Liveview Snapshot |

### presets

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/presets` | `list_presets` | List Presets |
| POST | `/api/v1/presets` | `create_preset` | Create Preset |
| GET | `/api/v1/presets/export` | `export_presets` | Export Presets |
| POST | `/api/v1/presets/import` | `import_presets` | Import Presets |
| POST | `/api/v1/presets/from-camera` | `create_preset_from_camera` | Create Preset From Camera |
| GET | `/api/v1/presets/{preset_id}` | `get_preset` | Get Preset |
| PUT | `/api/v1/presets/{preset_id}` | `update_preset` | Update Preset |
| DELETE | `/api/v1/presets/{preset_id}` | `delete_preset` | Delete Preset |
| POST | `/api/v1/presets/{preset_id}/apply` | `apply_preset` | Apply Preset |

### recording

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/recording` | `get_recording` | Get Recording Status |
| POST | `/api/v1/recording/start` | `start_recording` | Start Recording |
| POST | `/api/v1/recording/stop` | `stop_recording` | Stop Recording |

### sessions

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/sessions` | `list_sessions` | List Sessions |
| GET | `/api/v1/sessions/{session_id}` | `get_session` | Get Session |
| DELETE | `/api/v1/sessions/{session_id}` | `delete_session` | Delete Session |
| PATCH | `/api/v1/sessions/{session_id}` | `rename_session` | Rename Session |
| GET | `/api/v1/sessions/{session_id}/frames` | `list_session_frames` | List Session Frames |

### settings

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/settings` | `list_settings` | List Settings |
| PATCH | `/api/v1/settings` | `update_settings` | Update Settings |
| POST | `/api/v1/settings/refresh` | `refresh_settings` | Refresh Settings |
| GET | `/api/v1/settings/{name}` | `get_setting` | Get Setting |
| PUT | `/api/v1/settings/{name}` | `set_setting` | Set Setting |

### storage

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/locations` | `list_locations` | List Locations |
| POST | `/api/v1/locations` | `add_location` | Add Location |
| DELETE | `/api/v1/locations/{location_id}` | `delete_location` | Delete Location |
| PATCH | `/api/v1/locations/{location_id}` | `update_location` | Update Location |
| POST | `/api/v1/locations/{location_id}/mount` | `mount_location` | Mount Location |
| POST | `/api/v1/locations/{location_id}/unmount` | `unmount_location` | Unmount Location |
| POST | `/api/v1/locations/{location_id}/fsck` | `check_location` | Check Location |
| POST | `/api/v1/storage/disks/{disk}/format` | `format_disk` | Format Disk |
| POST | `/api/v1/locations/test-smb` | `test_smb_location` | Test Smb Location |
| PUT | `/api/v1/storage/target` | `set_storage_target` | Set Storage Target |
| PUT | `/api/v1/storage/backups` | `set_storage_backups` | Set Storage Backups |
| GET | `/api/v1/backup/status` | `get_backup_status` | Get Backup Status |
| POST | `/api/v1/backup/run` | `run_backup` | Run Backup |
| POST | `/api/v1/offload` | `start_offload` | Start Offload |
| POST | `/api/v1/verify` | `start_verify` | Start Verify |

### system

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/health` | `get_health` | Get Health |
| GET | `/api/v1/info` | `get_info` | Get Info |

### timelapse

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/timelapse` | `get_timelapse_status` | Get Timelapse Status |
| PUT | `/api/v1/timelapse/config` | `set_timelapse_config` | Set Timelapse Config |
| GET | `/api/v1/timelapse/preview` | `preview_timelapse` | Preview Timelapse |
| POST | `/api/v1/timelapse/preview` | `preview_timelapse_draft` | Preview Timelapse Draft |
| GET | `/api/v1/timelapse/presets` | `list_timelapse_presets` | List Timelapse Presets |
| POST | `/api/v1/timelapse/start` | `start_timelapse` | Start Timelapse |
| POST | `/api/v1/timelapse/pause` | `pause_timelapse` | Pause Timelapse |
| POST | `/api/v1/timelapse/resume` | `resume_timelapse` | Resume Timelapse |
| POST | `/api/v1/timelapse/stop` | `stop_timelapse` | Stop Timelapse |

### videos

| Method | Path | operation_id | Summary |
|---|---|---|---|
| POST | `/api/v1/sessions/{session_id}/video` | `render_session_video` | Render Session Video |
| GET | `/api/v1/videos` | `list_videos` | List Videos |
| GET | `/api/v1/videos/{session_id}/{name}` | `download_video` | Download Video |
| DELETE | `/api/v1/videos/{session_id}/{name}` | `delete_video` | Delete Video |

## auth

### `GET /api/v1/auth/status`

operation_id: `get_auth_status`

Open. What the login screen needs: whether sign-in is required and whether it is done.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthStatusOut` |
| 500 | Internal error | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/login`

operation_id: `login`

Open, rate-limited (429 with Retry-After). Sets the session cookie.

``password`` signs in with the app password. ``api_key`` works only while no password is set.

**Request body** (`application/json`): `LoginIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `password` | string \| null | no |  | `maxLength=1024` | The app password |
| `api_key` | string \| null | no |  | `maxLength=1024` | The API key; accepted only while no password is set |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthStatusOut` |
| 401 | Invalid credentials | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 429 | Too many failed attempts (see Retry-After) | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/logout`

operation_id: `logout`

Open. Revokes this browser's session and clears its cookie.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 500 | Internal error | `application/json`: `ErrorResponse` |

### `PUT /api/v1/auth/password`

operation_id: `set_password`

Set or change the app password; signs this browser in and revokes other browser sessions.

``current`` is required only when a password is already set (403 when wrong).

**Request body** (`application/json`): `PasswordSetIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `current` | string \| null | no |  | `maxLength=1024` | The current password; required only when a password is already set |
| `new` | string | yes |  | `minLength=8`, `maxLength=256` | The new password |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/auth/password`

operation_id: `delete_password`

Remove the app password (needs the current one). Browser sessions are revoked; with
no API key either, the app returns to open mode.

**Request body** (`application/json`): `PasswordDeleteIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `current` | string | yes |  | `maxLength=1024` | The current password |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/auth/sessions`

operation_id: `list_auth_sessions`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthSessionListOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/sessions/revoke-all`

operation_id: `revoke_all_auth_sessions`

Sign out every other browser. Keeps this session and the kiosk sessions.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `RevokedOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/auth/sessions/{session_id}`

operation_id: `revoke_auth_session`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/kiosk/code`

operation_id: `get_kiosk_pairing_code`

Open, rate-limited. Trades the kiosk device token for a single-use code (30 s).

**Request body** (`application/json`): `KioskCodeIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `token` | string | yes |  | `maxLength=1024` | The kiosk device token |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `KioskCodeOut` |
| 401 | Invalid credentials | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 429 | Too many failed attempts (see Retry-After) | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/kiosk`

operation_id: `pair_kiosk`

Open, rate-limited. Redeems a pairing code for a kiosk session cookie.

**Request body** (`application/json`): `KioskPairIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `code` | string | yes |  | `maxLength=256` | A pairing code from the kiosk code endpoint |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AuthStatusOut` |
| 401 | Invalid credentials | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 429 | Too many failed attempts (see Retry-After) | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |

### `POST /api/v1/auth/kiosk-token/rotate`

operation_id: `rotate_kiosk_token`

Write a new kiosk token file and revoke every kiosk session (the kiosk re-pairs).

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `RevokedOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## camera

### `GET /api/v1/camera`

operation_id: `get_camera`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/camera/connect`

operation_id: `connect_camera`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/camera/disconnect`

operation_id: `disconnect_camera`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/battery`

operation_id: `get_camera_battery`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `BatteryOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/storage`

operation_id: `get_camera_storage`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `StorageOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/summary`

operation_id: `get_camera_summary`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SummaryOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/datetime`

operation_id: `get_camera_datetime`

Camera clock, server clock and their offset.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraDateTimeOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/camera/datetime`

operation_id: `set_camera_datetime`

Set the camera clock to the server clock (`host`) or to `time` (`explicit`), showing
wall-clock time in `utc_offset_minutes` (default: the server's local zone; pass the
browser's offset to get the photographer's local time). Returns the clock read back.
409 while another owner holds the camera.

**Request body** (`application/json`): `CameraDateTimeIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `mode` | enum("host", "explicit") | yes |  |  | host: set the camera to the server clock; explicit: set `time`. |
| `time` | string(date-time) \| null | no |  |  | Required for explicit; a naive value is taken as UTC. |
| `utc_offset_minutes` | integer \| null | no |  | `>=-840.0`, `<=840.0` | Minutes east of UTC of the wall-clock time the camera should show (browsers: -new Date().getTimezoneOffset()). Omitted: the server's local zone. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraDateTimeOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/capture-target`

operation_id: `get_capture_target`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CaptureTargetOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/camera/capture-target`

operation_id: `set_capture_target`

`card`, `ram` or a raw choice. 409 during a recording or time-lapse.

**Request body** (`application/json`): `CaptureTargetIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `value` | string | yes |  | `minLength=1`, `maxLength=64` | 'card', 'ram' or one of the camera's raw choices. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CaptureTargetOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## camera-files

### `GET /api/v1/camera/folders`

operation_id: `list_camera_folders`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | no | `"/"` |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `FolderListOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/files`

operation_id: `list_camera_files`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | no | `"/"` |  |  |
| `recursive` | query | boolean | no | `false` |  |  |
| `order` | query | enum("newest", "oldest", "name") | no | `"newest"` |  |  |
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `50` | `>=1`, `<=500` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Page_CameraFileEntry_` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/thumbnail`

operation_id: `get_camera_thumbnail`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | yes |  |  |  |
| `name` | query | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | The camera's own preview JPEG of the file | `image/jpeg`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/preview`

operation_id: `get_camera_preview`

JPEG as rendered from the card file (RAW: its embedded preview); 415 for videos.

``size`` and ``mtime`` (from the listing) are cache-busters only: the body reuses file
names. 409 while another owner holds the camera lease and the preview is not cached.
A client that goes away cancels the render (a still-queued camera read never runs).

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | yes |  |  |  |
| `name` | query | string | yes |  |  |  |
| `size` | query | integer \| null | no |  |  |  |
| `mtime` | query | number \| null | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Screen-sized JPEG (long edge 2560 px) of the file | `image/jpeg`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/camera/files/download-all`

operation_id: `download_all_camera_files`

**Request body** (`application/json`): `DownloadAllRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `file` | CameraFileRef \| null | no |  |  | Download only this file (folder is then ignored) |
| `files` | list[CameraFileRef] \| null | no |  | `maxItems=1000` | Download only these files (folder and file are then ignored) |
| `folder` | string \| null | no |  |  | Camera folder to download (recursively); null = whole card |
| `delete_after` | boolean | no | `false` |  | Delete each file from the card after |
| `only_new` | boolean | no | `true` |  | Skip files already downloaded earlier |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/camera/files/delete`

operation_id: `delete_camera_files`

Delete several files from the card. Failures (for example another owner holds the
camera lease) are reported per file; the rest are still deleted.

**Request body** (`application/json`): `DeleteCameraFilesRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `files` | list[CameraFileRef] | yes |  | `minItems=1`, `maxItems=1000` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `DeleteCameraFilesResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/camera/files/{folder}/{name}`

operation_id: `download_camera_file`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | path | string | yes |  |  |  |
| `name` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | The file from the card | `application/octet-stream`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/camera/files/{folder}/{name}`

operation_id: `delete_camera_file`

Delete one file from the card. 409 while another owner holds the camera lease.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | path | string | yes |  |  |  |
| `name` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## capture

### `POST /api/v1/capture`

operation_id: `capture_photo`

**Request body** (`application/json`): `CaptureRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `download` | boolean | no | `true` |  | Download the captured files to the server |
| `delete_from_camera` | boolean | no | `false` |  | Delete from the card after download (ignored if download=false) |
| `filename_prefix` | string \| null | no |  | `maxLength=40` | Prefix for file names; unsafe characters become - |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CaptureOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/capture/trigger`

operation_id: `trigger_capture`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/capture/bulb`

operation_id: `get_bulb_status`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `BulbStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/capture/bulb`

operation_id: `start_bulb_capture`

Open the shutter for ``seconds`` (body must be in M mode). Returns the job; cancelling
it closes the shutter at once and still keeps the frame.

**Request body** (`application/json`): `BulbRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `seconds` | number | yes |  | `>=1.0`, `<=3600.0` | Exposure time in seconds. |
| `download` | boolean | no | `true` |  | Download the frame(s) to the output dir. |
| `filename_prefix` | string \| null | no |  | `maxLength=80` | Prefix for file names; unsafe characters become - |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/capture/bracket`

operation_id: `start_bracket_capture`

Capture one bracket set (every step applied and shot), then restore the settings.

**Request body** (`application/json`): `BracketRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `bracketing` | NoBracketing \| StepsBracketing \| QuickBracketing \| PresetBracketing | no |  |  | Same union as the time-lapse; must resolve to at least 2 steps. |
| `download` | boolean | no | `true` |  | Download the frames to the output dir. |
| `filename_prefix` | string \| null | no |  | `maxLength=80` | Prefix for file names; unsafe characters become - |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## config

### `GET /api/v1/config`

operation_id: `get_config`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ConfigOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PATCH /api/v1/config`

operation_id: `update_config`

**Request body** (`application/json`): `ConfigPatch`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `camera` | CameraConfigPatch \| null | no |  |  |  |
| `liveview` | LiveViewConfigPatch \| null | no |  |  |  |
| `kiosk` | KioskConfigPatch \| null | no |  |  |  |
| `security` | SecurityConfigPatch \| null | no |  |  |  |
| `timelapse` | TimelapseConfigPatch \| null | no |  |  |  |
| `video` | VideoConfigPatch \| null | no |  |  |  |
| `media` | MediaConfigPatch \| null | no |  |  |  |
| `storage` | StorageConfigPatch \| null | no |  |  |  |
| `cors_origins` | list[string] \| null | no |  |  | Other sites allowed to call the API. Leave empty to allow only this site. |
| `timezone` | string \| null | no |  |  | IANA time zone name, e.g. America/New_York. Used for photo and session names and when setting the camera clock. Empty uses the server's own zone. |
| `demo_camera` | boolean \| null | no |  |  | Use the simulated camera |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ConfigUpdateOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/config/schema`

operation_id: `get_config_schema`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ConfigSchemaOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/config/reset`

operation_id: `reset_config`

Restore defaults (the API key is kept); ``changed`` lists what was reset, e.g.
``demo_camera`` when the demo camera was on.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ConfigUpdateOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/config/api-key`

operation_id: `create_api_key`

Generate (or rotate) the API key. The plaintext key is returned only here.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ApiKeyOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/config/api-key`

operation_id: `delete_api_key`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ApiKeyDeletedOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## events

### `GET /api/v1/events/schema`

operation_id: `get_event_schema`

No-op: returns a sample event. Its response model is the discriminated union of every
event delivered on ``/ws/events`` (discriminator ``type``); it exists so the spec and the
generated client carry the event types.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `CameraStateEvent \| CameraConnectedEvent \| CameraDisconnectedEvent \| SettingChangedEvent \| BatteryEvent \| CaptureStartedEvent \| CaptureCompleteEvent \| LiveviewStartedEvent \| LiveviewStoppedEvent \| TimelapseStartedEvent \| TimelapsePausedEvent \| TimelapseResumedEvent \| TimelapseStoppedEvent \| TimelapseCompletedEvent \| TimelapseFrameEvent \| TimelapseWarningEvent \| TimelapseErrorEvent \| RecordingStartedEvent \| RecordingStoppedEvent \| JobCreatedEvent \| JobProgressEvent \| JobCompletedEvent \| JobFailedEvent \| JobCancelledEvent \| ConfigChangedEvent \| PresetsChangedEvent \| LocationsChangedEvent \| BackupStatusEvent \| StorageChangedEvent \| CardListingEvent \| ErrorEvent` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## files

### `GET /api/v1/files/zip/{ticket}`

operation_id: `download_zip`

Redeem a ticket from ``POST /files/zip``. No other credential is needed; a ticket
works once.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `ticket` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | A ZIP archive, or the single file itself | `application/zip`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/files`

operation_id: `list_files`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | no | `""` |  | Folder relative to the output dir |
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `50` | `>=1`, `<=500` |  |
| `kind` | query | enum("image", "raw", "video", "photos", "all") | no | `"all"` |  |  |
| `sort` | query | enum("newest", "oldest", "name") | no | `"newest"` |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `FilePage` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/files/delete`

operation_id: `delete_files`

Delete many files. Failures are reported per path; the others are still deleted.

**Request body** (`application/json`): `DeletePathsRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `paths` | list[string] | yes |  | `minItems=1`, `maxItems=5000` | Paths to delete |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `DeletePathsResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/files/zip`

operation_id: `create_zip_download`

Issue a single-use download URL (60 s). One path downloads the file itself, several
stream a ZIP archive.

**Request body** (`application/json`): `ZipRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `paths` | list[string] | yes |  | `minItems=1`, `maxItems=5000` | Files to download (one path = the file itself) |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ZipTicket` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/files/{path}`

operation_id: `download_file`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `path` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | The file content | `application/octet-stream`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/files/{path}`

operation_id: `delete_file`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `path` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/thumbnails/{path}`

operation_id: `get_thumbnail`

JPEG thumbnail of the file at ``path`` (relative to the output dir).

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `path` | path | string | yes |  |  |  |
| `size` | query | integer \| null | no |  | `>=64`, `<=1024` | Longest edge in px |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | JPEG thumbnail | `image/jpeg`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## focus

### `GET /api/v1/focus`

operation_id: `get_focus`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `FocusStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/focus/af`

operation_id: `autofocus`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AutofocusResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/focus/point`

operation_id: `set_af_point`

Move the camera's AF point (``changeafarea``) to a normalized live view position.

**Request body** (`application/json`): `AfPointRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `x` | number | yes |  | `>=0.0`, `<=1.0` | Horizontal position in the frame (0 = left) |
| `y` | number | yes |  | `>=0.0`, `<=1.0` | Vertical position in the frame (0 = top) |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `AfPointResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/focus/mf`

operation_id: `manual_focus`

**Request body** (`application/json`): `MfRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `steps` | integer | yes |  | `>=-1000000.0`, `<=1000000.0` | Signed motor steps (sign = direction); checked against the camera's range |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `MfResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/focus/reset`

operation_id: `reset_focus_position`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `FocusResetResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/focus/stack`

operation_id: `start_focus_stack`

Capture N shots, moving focus between them; returns the job (kind ``focus-stack``).

**Request body** (`application/json`): `StackRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `steps_per_shot` | integer | yes |  | `>=1.0`, `<=32767.0` | Focus steps between shots (within the camera's drive range) |
| `shots` | integer | yes |  | `>=2.0`, `<=200.0` |  |
| `direction` | enum("near_to_far", "far_to_near") | no | `"near_to_far"` |  |  |
| `settle_ms` | integer | no | `500` | `>=0.0`, `<=60000.0` | Wait after each move |
| `return_to_start` | boolean | no | `true` |  |  |
| `name` | string \| null | no |  | `maxLength=40` | Folder name suffix |
| `filename_prefix` | string \| null | no |  | `maxLength=40` | Prefix for file names; unsafe characters become -. Defaults to the File name prefix setting |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## jobs

### `GET /api/v1/jobs`

operation_id: `list_jobs`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `kind` | query | string \| null | no |  |  |  |
| `status` | query | JobStatus \| null | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `list[JobOut]` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/jobs/{job_id}`

operation_id: `get_job`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `job_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/jobs/{job_id}`

operation_id: `cancel_job`

Cancel a job (no-op for finished jobs) and return its final state.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `job_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## kiosk

### `GET /api/v1/kiosk/scale`

operation_id: `stream_kiosk_scale`

Open, read-only stream of the kiosk display scale (auto, 1, 1.25, 1.5 or 2).

Sends the current value on connect and again whenever it changes. Not sensitive, and the
kiosk holds no API key, so it is open like /health.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | One `data: <scale>` line per value | `text/event-stream`: `string(binary)` |

### `GET /api/v1/kiosk/display`

operation_id: `stream_kiosk_display`

Open, read-only stream of whether the kiosk screen should be on or off.

Sends the current state on connect and on every change (`on`, or `off <mode>` with the
sleep mode: black, dim or off), `off <mode>` again if the mode changes while asleep, and
`on` whenever the sleep setting is set to 0 (never). Open like the scale stream.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | One `data: on` or `data: off <black\|dim\|off>` line per state | `text/event-stream`: `string(binary)` |

### `POST /api/v1/kiosk/display`

operation_id: `set_kiosk_display`

Record the kiosk screen state (the kiosk page sends off when idle, on at a touch).

**Request body** (`application/json`): `KioskDisplayIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `on` | boolean | yes |  |  | True to wake the kiosk screen, false to let it sleep. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `KioskDisplayOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## liveview

### `GET /api/v1/liveview`

operation_id: `get_liveview`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LiveViewStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/liveview/start`

operation_id: `start_liveview`

Start the stream and keep it running until stopped, even with no clients.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LiveViewStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/liveview/stop`

operation_id: `stop_liveview`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LiveViewStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/liveview/snapshot`

operation_id: `get_liveview_snapshot`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | One live view JPEG | `image/jpeg`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## presets

### `GET /api/v1/presets`

operation_id: `list_presets`

User presets plus the read-only built-in bracket presets (`builtin: true`).

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `kind` | query | enum("settings", "bracket") \| null | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetCollection` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/presets`

operation_id: `create_preset`

Create a preset. Names are unique per kind (case-insensitive), 1-80 characters.

**Request body** (`application/json`): `SettingsPresetIn \| BracketPresetIn`

Body: `SettingsPresetIn \| BracketPresetIn`

**Responses**

| Status | Description | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: `PresetItem` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/presets/export`

operation_id: `export_presets`

All user presets as a JSON document (built-ins excluded) for backup or transfer.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetExport` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/presets/import`

operation_id: `import_presets`

Validate and import presets from an export; every item gets its own result.
`replace=true` swaps the whole user set for the valid items.

**Request body** (`application/json`): `PresetImportIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `schema_version` | integer | no | `1` | `>=1.0`, `<=1.0` |  |
| `replace` | boolean | no | `false` |  | true: replace ALL user presets with the valid imported ones. false: merge; a name that already exists is skipped. |
| `presets` | list[object] | yes |  | `maxItems=500` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetImportResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/presets/from-camera`

operation_id: `create_preset_from_camera`

Snapshot the camera's current values into a new settings preset (default: the common
writable settings).

**Request body** (`application/json`): `FromCameraIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `name` | string | yes |  | `minLength=1`, `maxLength=80` |  |
| `description` | string | no | `""` | `maxLength=500` |  |
| `names` | list[string] \| null | no |  | `maxItems=40` | Setting names to capture; null = the common writable settings. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: `PresetItem` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/presets/{preset_id}`

operation_id: `get_preset`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `preset_id` | path | string | yes |  | `pattern=^[a-z0-9][a-z0-9_-]{0,63}$` | Preset id. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetItem` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/presets/{preset_id}`

operation_id: `update_preset`

Replace a user preset (same kind). Built-ins answer 403.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `preset_id` | path | string | yes |  | `pattern=^[a-z0-9][a-z0-9_-]{0,63}$` | Preset id. |

**Request body** (`application/json`): `SettingsPresetIn \| BracketPresetIn`

Body: `SettingsPresetIn \| BracketPresetIn`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetItem` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/presets/{preset_id}`

operation_id: `delete_preset`

Delete a user preset. Built-ins answer 403.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `preset_id` | path | string | yes |  | `pattern=^[a-z0-9][a-z0-9_-]{0,63}$` | Preset id. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/presets/{preset_id}/apply`

operation_id: `apply_preset`

Settings preset: validate every value against the connected camera (all or nothing),
then apply and return what the camera now reports. Bracket preset: nothing is started; the
resolved steps are returned, and the UI then passes the preset's `bracketing` object to the
time-lapse config or one-shot bracket endpoint.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `preset_id` | path | string | yes |  | `pattern=^[a-z0-9][a-z0-9_-]{0,63}$` | Preset id. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `ApplyResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## recording

### `GET /api/v1/recording`

operation_id: `get_recording`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `RecordingStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/recording/start`

operation_id: `start_recording`

Start recording a movie to the card. Holds the camera lease until stopped; live view
is switched on if needed.

**Request body** (`application/json`): `RecordingStartRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `max_seconds` | integer \| null | no |  | `>=1.0`, `<=1799.0` | Stop automatically after this many seconds (default and maximum 1799, the D500's 29 min 59 s clip limit) |
| `download_after` | boolean | no | `false` |  | After stopping, download the clip(s) into <output>/recordings/ |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `RecordingStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/recording/stop`

operation_id: `stop_recording`

Stop the recording; returns the clip and the download job id, if requested.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `RecordingStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## sessions

### `GET /api/v1/sessions`

operation_id: `list_sessions`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `50` | `>=1`, `<=200` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Page_SessionSummary_` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/sessions/{session_id}`

operation_id: `get_session`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SessionDetail` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/sessions/{session_id}`

operation_id: `delete_session`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PATCH /api/v1/sessions/{session_id}`

operation_id: `rename_session`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |

**Request body** (`application/json`): `SessionRename`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `name` | string | yes |  | `minLength=1`, `maxLength=200` | New session name. |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SessionDetail` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/sessions/{session_id}/frames`

operation_id: `list_session_frames`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `100` | `>=1`, `<=500` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Page_SessionFrame_` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## settings

### `GET /api/v1/settings`

operation_id: `list_settings`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `group` | query | enum("common", "all") | no | `"common"` |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `list[SettingOut]` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PATCH /api/v1/settings`

operation_id: `update_settings`

**Request body** (`application/json`): `SettingsPatchIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `values` | map[boolean \| integer \| number \| string] | yes |  |  | Setting name or alias -> new value |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SettingsPatchOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/settings/refresh`

operation_id: `refresh_settings`

Re-read every setting from the camera, bypassing the cache (slow on a real body).

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `group` | query | enum("common", "all") | no | `"common"` |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `list[SettingOut]` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/settings/{name}`

operation_id: `get_setting`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `name` | path | string | yes |  |  |  |
| `fresh` | query | boolean | no | `false` |  | Re-read this one setting from the camera instead of the cache |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SettingOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/settings/{name}`

operation_id: `set_setting`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `name` | path | string | yes |  |  |  |

**Request body** (`application/json`): `SettingValueIn`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `value` | boolean \| integer \| number \| string | yes |  |  | New value; must match the widget type |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SettingOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## storage

### `GET /api/v1/locations`

operation_id: `list_locations`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationsOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/locations`

operation_id: `add_location`

**Request body** (`application/json`): `LocationCreate`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `kind` | enum("usb", "smb") | yes |  |  |  |
| `name` | string | no | `""` | `maxLength=64` |  |
| `uuid` | string \| null | no |  | `pattern=^[0-9A-Za-z-]{1,64}$` | usb |
| `unc` | string \| null | no |  | `pattern=^//[A-Za-z0-9._-]+/[A-Za-z0-9._ $-]+(/[A-Za-z0-9._ $-]+)*$` | smb: //host/share[/sub] |
| `username` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |
| `password` | string \| null | no |  | `maxLength=256`, `pattern=^[^\x00-\x1f]*$` | Write-only |
| `domain` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |
| `auto_mount` | boolean | no | `true` |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 201 | Successful Response | `application/json`: `LocationOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/locations/{location_id}`

operation_id: `delete_location`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `location_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PATCH /api/v1/locations/{location_id}`

operation_id: `update_location`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `location_id` | path | string | yes |  |  |  |

**Request body** (`application/json`): `LocationUpdate`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `name` | string \| null | no |  | `maxLength=64` |  |
| `unc` | string \| null | no |  | `pattern=^//[A-Za-z0-9._-]+/[A-Za-z0-9._ $-]+(/[A-Za-z0-9._ $-]+)*$` |  |
| `username` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |
| `password` | string \| null | no |  | `maxLength=256`, `pattern=^[^\x00-\x1f]*$` | Write-only; empty string removes the stored password |
| `domain` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |
| `auto_mount` | boolean \| null | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/locations/{location_id}/mount`

operation_id: `mount_location`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `location_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/locations/{location_id}/unmount`

operation_id: `unmount_location`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `location_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/locations/{location_id}/fsck`

operation_id: `check_location`

Check and repair an unmounted USB drive as a background job (up to an hour). The job
result is ``{returncode, output}``; cancelling the job stops the repair.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `location_id` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/storage/disks/{disk}/format`

operation_id: `format_disk`

Erase a whole USB disk and create one partition with a new filesystem, as a background
job (up to an hour). The disk is identified by name, device numbers, size and kernel
sequence number, all re-checked just before writing. Refused while any partition is
mounted, in use as the target or a backup, or being checked. Cancelling the job stops the
format; the disk may then be left blank or half-written.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `disk` | path | string | yes |  | `pattern=^[A-Za-z0-9_-]{1,32}$` |  |

**Request body** (`application/json`): `FormatRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `fstype` | enum("exfat", "fat32", "ntfs", "ext4") | no | `"exfat"` |  |  |
| `label` | string | no | `""` | `maxLength=32` | Empty for no label |
| `majmin` | string | yes |  | `pattern=^[0-9]+:[0-9]+$` | Expected device numbers |
| `size` | integer | yes |  | `>0.0`, `<1e+18` | Expected disk size in bytes |
| `diskseq` | string | yes |  | `pattern=^[0-9]{1,20}$` | Expected kernel sequence number of the disk |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/locations/test-smb`

operation_id: `test_smb_location`

**Request body** (`application/json`): `SmbTest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `unc` | string | yes |  | `pattern=^//[A-Za-z0-9._-]+/[A-Za-z0-9._ $-]+(/[A-Za-z0-9._ $-]+)*$` |  |
| `username` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |
| `password` | string \| null | no |  | `maxLength=256`, `pattern=^[^\x00-\x1f]*$` |  |
| `domain` | string \| null | no |  | `maxLength=128`, `pattern=^[^\x00-\x1f,]*$` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `SmbTestResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/storage/target`

operation_id: `set_storage_target`

**Request body** (`application/json`): `TargetSet`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `id` | string \| null | yes |  |  | Location id, or null for no target |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationsOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/storage/backups`

operation_id: `set_storage_backups`

**Request body** (`application/json`): `BackupsSet`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `ids` | list[string] | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `LocationsOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/backup/status`

operation_id: `get_backup_status`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `BackupStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/backup/run`

operation_id: `run_backup`

Start a sync now (a run in progress is repeated once it ends).

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `BackupStatusOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/offload`

operation_id: `start_offload`

Verified copy of files from one mounted location to another, then delete the source
files (unless ``keep_source``) once the copy re-hashed equal. Files of running, paused or
render-held sessions and files modified in the last 10 seconds are skipped.

**Request body** (`application/json`): `OffloadRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `from_id` | string | yes |  |  |  |
| `to_id` | string | yes |  |  |  |
| `scope` | OffloadScope | yes |  |  |  |
| `keep_source` | boolean | no | `false` |  | Verified copy only; keep the source |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/verify`

operation_id: `start_verify`

Re-hash a location's files against its own SHA256SUMS (job result: ok, mismatched,
missing and unlisted counts and lists).

**Request body** (`application/json`): `VerifyRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `location_id` | string \| null | no |  |  | Default: the target |
| `folder` | string | no | `""` |  | Sub-folder to check, relative to the root |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## system

### `GET /api/v1/health`

operation_id: `get_health`

Open liveness probe. Always 200 while the server is up; 'degraded' on camera ERROR.

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `HealthOut` |

### `GET /api/v1/info`

operation_id: `get_info`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `InfoOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## timelapse

### `GET /api/v1/timelapse`

operation_id: `get_timelapse_status`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `PUT /api/v1/timelapse/config`

operation_id: `set_timelapse_config`

**Request body** (`application/json`): `TimelapseSetup`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `name` | string | yes |  | `minLength=1`, `maxLength=200` | Session name. |
| `interval_s` | number | yes |  | `<=86400.0`, `>0.0` | Seconds between shot sets. |
| `total_frames` | integer \| null | no |  | `>=1.0`, `<=100000.0` | Number of intervals (bracket sets). |
| `duration_s` | integer \| null | no |  | `>=1.0` | Hard deadline for starting new sets. |
| `bracketing` | NoBracketing \| StepsBracketing \| QuickBracketing \| PresetBracketing | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseConfigResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/timelapse/preview`

operation_id: `preview_timelapse`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseConfigResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/timelapse/preview`

operation_id: `preview_timelapse_draft`

Validate and estimate a draft; nothing is saved and it works during a run.

**Request body** (`application/json`): `TimelapseSetup`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `name` | string | yes |  | `minLength=1`, `maxLength=200` | Session name. |
| `interval_s` | number | yes |  | `<=86400.0`, `>0.0` | Seconds between shot sets. |
| `total_frames` | integer \| null | no |  | `>=1.0`, `<=100000.0` | Number of intervals (bracket sets). |
| `duration_s` | integer \| null | no |  | `>=1.0` | Hard deadline for starting new sets. |
| `bracketing` | NoBracketing \| StepsBracketing \| QuickBracketing \| PresetBracketing | no |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseConfigResult` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/timelapse/presets`

operation_id: `list_timelapse_presets`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `PresetList` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/timelapse/start`

operation_id: `start_timelapse`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/timelapse/pause`

operation_id: `pause_timelapse`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/timelapse/resume`

operation_id: `resume_timelapse`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `POST /api/v1/timelapse/stop`

operation_id: `stop_timelapse`

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `TimelapseStatus` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## videos

### `POST /api/v1/sessions/{session_id}/video`

operation_id: `render_session_video`

Start rendering the session's frames (so far) into a video; returns the job.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |

**Request body** (`application/json`): `RenderRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
| `fps` | number \| null | no |  | `>=1.0`, `<=120.0` | Output frame rate. |
| `codec` | enum("h264", "h265", "prores", "vp9") \| null | no |  |  | h264, h265 (mp4), prores (mov) or vp9 (webm). |
| `crf` | integer \| null | no |  | `>=0.0`, `<=51.0` | Constant rate factor (lower is better). |
| `quality` | enum("low", "medium", "high") \| null | no |  |  | Shortcut overriding crf (and the ProRes profile). |
| `preset` | enum("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow") \| null | no |  |  | x264/x265 speed preset. |
| `resolution` | enum("source", "2160p", "1080p", "720p") | no | `"source"` |  | Fit inside this size, keeping aspect ratio. |
| `bracket_frame` | enum("middle", "first", "last") \| integer | no | `"middle"` | `>=0.0` | Which shot of each bracket set to use: middle, first, last or a zero-based step index (>= 0; an index past the end of a set uses its last shot). |
| `deflicker` | boolean | no | `false` |  | Apply ffmpeg's deflicker filter. |
| `output_name` | string \| null | no |  | `maxLength=120` | File name (sanitised; extension is set by the codec; never overwrites). |

**Responses**

| Status | Description | Body |
|---|---|---|
| 202 | Successful Response | `application/json`: `JobOut` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/videos`

operation_id: `list_videos`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | query | string \| null | no |  |  |  |
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `50` | `>=1`, `<=200` |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Page_VideoEntry_` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `GET /api/v1/videos/{session_id}/{name}`

operation_id: `download_video`

Stream the video; HTTP Range requests are supported.

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |
| `name` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | The video file | `video/*`: `string(binary)` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

### `DELETE /api/v1/videos/{session_id}/{name}`

operation_id: `delete_video`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `session_id` | path | string | yes |  |  |  |
| `name` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/json`: `Ok` |
| 401 | Missing or invalid API key | `application/json`: `ErrorResponse` |
| 404 | Not found | `application/json`: `ErrorResponse` |
| 409 | Conflict with current state | `application/json`: `ErrorResponse` |
| 422 | Validation error | `application/json`: `ErrorResponse` |
| 500 | Internal error | `application/json`: `ErrorResponse` |
| 503 | Camera unavailable | `application/json`: `ErrorResponse` |

## WebSocket endpoints

Not part of OpenAPI. Paths are relative to `/api/v1`.

## Events

Events are delivered on `/ws/events` as `{"type": <event type>, "ts": <ISO-8601 UTC>, "data": {...}}`.

Payload keys are found by a static scan of `publish(...)` call sites; `(dynamic)` means the payload is not a dict literal.

| Type | Payload keys |
|---|---|
| `camera_state` | `previous`, `state` |
| `camera_connected` | `model`, `serial` |
| `camera_disconnected` | `reason` |
| `setting_changed` | `name`, `value` |
| `battery` | `level` |
| `capture_started` | `bulb`, `seconds`, `warnings` |
| `capture_complete` | `bulb`, `files` |
| `liveview_started` | (empty) |
| `liveview_stopped` | `frames` |
| `timelapse_started` | `failures`, `frames_done`, `planned_shots`, `session_id`, `sets_done` |
| `timelapse_paused` | `failures`, `frames_done`, `reason`, `session_id`, `sets_done` |
| `timelapse_resumed` | `failures`, `frames_done`, `session_id`, `sets_done` |
| `timelapse_stopped` | `failures`, `frames_done`, `interrupted`, `session_id`, `sets_done` |
| `timelapse_completed` | `failures`, `frames_done`, `session_id`, `sets_done` |
| `timelapse_frame` | `failures`, `frames_done`, `index`, `session_id`, `set_index`, `sets_done`, `step` |
| `timelapse_warning` | `code`, `failures`, `frames_done`, `message`, `session_id`, `sets_done` |
| `timelapse_error` | `error`, `failures`, `frames_done`, `session_id`, `sets_done` |
| `recording_started` | `download_after`, `max_seconds` |
| `recording_stopped` | `clips`, `duration_s`, `job_id`, `reason`, `warning` |
| `job_created` | `job` |
| `job_progress` | `job` |
| `job_completed` | `job` |
| `job_failed` | `job` |
| `job_cancelled` | `job` |
| `config_changed` | `config`, `restart_required` |
| `presets_changed` | `action`, `id`, `kind` |
| `locations_changed` | `id`, `reason`, `target_id` |
| `backup_status` | `copied`, `current`, `failed`, `pending`, `running` |
| `storage_changed` | `cards` |
| `card_listing` | `count`, `done`, `folder`, `recursive` |
| `error` | `cause`, `code`, `message` |

## Configuration reference

Edited through the web UI / `/config` endpoints. Never through the environment.

| Section | Field | Type | Default | Constraints | Description |
|---|---|---|---|---|---|
| camera | `keepalive_enabled` | boolean | `true` |  | Send a keepalive now and then. The D500 drops the USB link after 60 s idle. |
| camera | `keepalive_interval_s` | number | `30.0` | `>=5.0`, `<=55.0` | How often to send a keepalive. Keep it below 60 s. |
| camera | `connect_timeout_s` | number | `10.0` | `>=1.0`, `<=120.0` | How long to wait for the camera before giving up. |
| camera | `connect_retries` | integer | `5` | `>=0`, `<=50` | How many times to try again after the link is lost. |
| camera | `reconnect_interval_s` | number | `2.0` | `>=0.5`, `<=60.0` | Wait this long between reconnect attempts. |
| camera | `capture_timeout_s` | number | `30.0` | `>=1.0`, `<=300.0` | How long to wait for a photo to arrive before reporting a failure. |
| camera | `event_quiet_window_s` | number | `1.0` | `>=0.0`, `<=10.0` | After a capture, stop listening for camera events once none arrive for this long. |
| camera | `keep_card_copy` | boolean | `true` |  | Turn off to delete the card copy once the download is verified. Only applies when the camera saves to the memory card. |
| camera | `download_photos` | boolean | `true` |  | Turn off to only fire the shutter. Photos stay on the camera's card and Shoot is ready for the next shot sooner. |
| camera | `filename_prefix` | string \| null | `null` | `maxLength=40` | Added to the start of every downloaded photo's name. Up to 40 characters; spaces and symbols become dashes. |
| camera | `focus_step_small` | integer | `150` | `>=1`, `<=32767` | Motor steps per click; lenses differ, a full sweep on a typical zoom is ~6000-8000 steps. |
| camera | `focus_step_large` | integer | `1000` | `>=1`, `<=32767` | Motor steps per click; lenses differ, a full sweep on a typical zoom is ~6000-8000 steps. |
| liveview | `target_fps` | integer | `8` | `>=1`, `<=30` | Higher is smoother but uses more USB bandwidth. 5-15 fps is typical. |
| liveview | `quality` | enum("small", "medium", "large") | `"medium"` |  | Size of the frames the camera sends. |
| liveview | `jpeg_quality` | integer | `75` | `>=10`, `<=100` | Quality used when re-encoding streamed frames. |
| liveview | `max_width` | integer \| null | `null` | `>=64`, `<=8192` | Shrink frames wider than this, in pixels. Leave empty to turn off. |
| kiosk | `scale` | enum("auto", "1", "1.25", "1.5", "2") | `"auto"` |  | Size of the touchscreen kiosk's interface. Auto works it out from the screen. |
| kiosk | `sleep_after_min` | integer | `5` | `>=0`, `<=1440` | Turns the kiosk screen off after this many minutes without a touch. 0 keeps it on. |
| kiosk | `sleep_mode` | enum("black", "dim", "off") | `"dim"` |  | How the kiosk screen sleeps. Black covers it with black only. Dim also sets the monitor's brightness to 0 over DDC. Off powers the panel off (DPMS), which may also cut power to a touchscreen wired through the monitor's USB hub. |
| security | `secure_cookie` | enum("auto", "always") | `"auto"` |  | Auto marks the sign-in cookie Secure only when the request arrived over HTTPS. Choose Always when a reverse proxy terminates HTTPS in front of this app. |
| timelapse | `min_interval_s` | number | `1.0` | `>=0.1`, `<=3600.0` | The shortest time allowed between frames. |
| timelapse | `max_duration_s` | integer | `86400` | `>=60`, `<=2592000` | A time-lapse stops after this long. |
| timelapse | `failure_budget` | integer | `5` | `>=1`, `<=100` | Stop the time-lapse after this many failed frames in a row. |
| video | `ffmpeg_path` | string \| null | `null` |  | Path to the ffmpeg program. Leave empty to detect it automatically. |
| video | `codec` | enum("libx264", "libx265", "libvpx-vp9") | `"libx264"` |  | Video codec used by ffmpeg. |
| video | `crf` | integer | `23` | `>=0`, `<=51` | Constant rate factor. Lower means better quality and larger files. |
| video | `preset` | enum("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow") | `"medium"` |  | Slower presets make smaller files. |
| video | `fps` | integer | `24` | `>=1`, `<=120` | Frame rate of the video. |
| video | `timeout_s` | integer | `3600` | `>=10`, `<=86400` | Stop an ffmpeg run that takes longer than this. |
| media | `thumbnail_size` | integer | `200` | `>=32`, `<=1024` | Length of the longest thumbnail edge, in pixels. |
| storage | `locations` | list[StorageLocation] |  |  | Configured storage locations. |
| storage | `target_id` | string \| null | `null` |  | Location that receives every photo. |
| storage | `backup_ids` | list[string] |  |  | Locations used for backups. |
| storage | `backup_interval_min` | integer | `15` | `>=1`, `<=1440` | How often backups run. |
| storage | `deep_verify` | boolean | `false` |  | Check every file already on the backup against its checksum on each run. |
| storage | `sidecars` | boolean | `true` |  | Save a SHA-256 checksum file next to every photo. |
| (root) | `cors_origins` | list[string] |  |  | Other sites allowed to call the API. Leave empty to allow only this site. |
| (root) | `timezone` | string \| null | `null` | `maxLength=64` | IANA time zone name, e.g. America/New_York. Used for photo and session names and when setting the camera clock. Empty uses the server's own zone. |
| (root) | `demo_camera` | boolean | `false` |  | Use the simulated camera |
| (root) | `api_key_hash` | string \| null | `null` |  | sha256 of the API key; None = open |
