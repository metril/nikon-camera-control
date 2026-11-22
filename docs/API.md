# Nikon Camera Control API 0.2.0

> Generated file. Do not edit. Regenerate with `make api` (`.venv/bin/python -m scripts.gen_api`); CI fails if it is stale.
> Source of truth: route declarations and pydantic schemas. Machine-readable spec: `openapi.json`.

## Authentication

When an API key is configured, send it as the `X-API-Key` request header. WebSocket clients cannot set headers, so they offer the subprotocol `apikey.<key>`. A rejected WebSocket is accepted and then closed with code 4401.

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
| `CAMERA_NOT_FOUND` | 404 | `CameraNotFound` | No camera detected. Check the USB connection. |
| `CAMERA_BUSY` | 409 | `CameraBusy` | Camera is busy with another operation |
| `CAMERA_TIMEOUT` | 504 | `CameraTimeout` | Camera operation timed out |
| `CAMERA_IO_ERROR` | 502 | `CameraIOError` | Camera I/O error |
| `CAMERA_OPERATION_FAILED` | 502 | `CameraOperationFailed` | Camera operation failed |
| `STORAGE_FULL` | 507 | `StorageFull` | Camera storage is full |
| `INVALID_STATE` | 409 | `InvalidState` | Operation not allowed in the current state |
| `SETTING_NOT_FOUND` | 404 | `SettingNotFound` | Setting not found |
| `SETTING_NOT_ALLOWED` | 403 | `SettingNotAllowed` | Setting cannot be changed |
| `SETTING_INVALID` | 422 | `SettingInvalid` | Invalid value for setting |
| `FILE_NOT_FOUND` | 404 | `FileNotFoundError_` | File not found |
| `PATH_NOT_ALLOWED` | 400 | `PathNotAllowed` | Path is outside the allowed directory |
| `JOB_NOT_FOUND` | 404 | `JobNotFound` | Job not found |
| `PRESET_NOT_FOUND` | 404 | `PresetNotFound` | Preset not found |
| `SESSION_NOT_FOUND` | 404 | `SessionNotFound` | Session not found |
| `UNAUTHORIZED` | 401 | `Unauthorized` | Missing or invalid API key |
| `CONFIG_INVALID` | 422 | `ConfigInvalid` | Invalid configuration |
| `FEATURE_UNSUPPORTED` | 501 | `FeatureUnsupported` | Feature not supported by this camera |
| `VALIDATION_ERROR` | by handler | - | Produced by the framework error handlers |
| `NOT_FOUND` | by handler | - | Produced by the framework error handlers |
| `UNSUPPORTED_MEDIA` | 415 | `UnsupportedMedia` | No thumbnail can be generated for this file type |

## Endpoints

### camera

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/camera` | `get_camera` | Get Camera |
| POST | `/api/v1/camera/connect` | `connect_camera` | Connect Camera |
| POST | `/api/v1/camera/disconnect` | `disconnect_camera` | Disconnect Camera |
| GET | `/api/v1/camera/battery` | `get_camera_battery` | Get Camera Battery |
| GET | `/api/v1/camera/storage` | `get_camera_storage` | Get Camera Storage |
| GET | `/api/v1/camera/summary` | `get_camera_summary` | Get Camera Summary |

### camera files

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/camera/folders` | `list_camera_folders` | List Camera Folders |
| GET | `/api/v1/camera/files` | `list_camera_files` | List Camera Files |
| POST | `/api/v1/camera/files/download-all` | `download_all_camera_files` | Download All Camera Files |
| GET | `/api/v1/camera/files/{folder}/{name}` | `download_camera_file` | Download Camera File |
| DELETE | `/api/v1/camera/files/{folder}/{name}` | `delete_camera_file` | Delete Camera File |

### capture

| Method | Path | operation_id | Summary |
|---|---|---|---|
| POST | `/api/v1/capture` | `capture_photo` | Capture Photo |
| POST | `/api/v1/capture/trigger` | `trigger_capture` | Trigger Capture |

### config

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/config` | `get_config` | Get Config |
| PATCH | `/api/v1/config` | `update_config` | Update Config |
| GET | `/api/v1/config/schema` | `get_config_schema` | Get Config Schema |
| POST | `/api/v1/config/reset` | `reset_config` | Reset Config |
| POST | `/api/v1/config/api-key` | `create_api_key` | Create Api Key |
| DELETE | `/api/v1/config/api-key` | `delete_api_key` | Delete Api Key |

### files

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/files` | `list_files` | List Files |
| GET | `/api/v1/files/{path}` | `download_file` | Download File |
| DELETE | `/api/v1/files/{path}` | `delete_file` | Delete File |
| GET | `/api/v1/thumbnails/{path}` | `get_thumbnail` | Get Thumbnail |

### jobs

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/jobs` | `list_jobs` | List Jobs |
| GET | `/api/v1/jobs/{job_id}` | `get_job` | Get Job |
| DELETE | `/api/v1/jobs/{job_id}` | `cancel_job` | Cancel Job |

### liveview

| Method | Path | operation_id | Summary |
|---|---|---|---|
| GET | `/api/v1/liveview` | `get_liveview` | Get Liveview Status |
| POST | `/api/v1/liveview/start` | `start_liveview` | Start Liveview |
| POST | `/api/v1/liveview/stop` | `stop_liveview` | Stop Liveview |
| GET | `/api/v1/liveview/snapshot` | `get_liveview_snapshot` | Get Liveview Snapshot |

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
| GET | `/api/v1/settings/{name}` | `get_setting` | Get Setting |
| PUT | `/api/v1/settings/{name}` | `set_setting` | Set Setting |

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

## camera files

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

### `POST /api/v1/camera/files/download-all`

operation_id: `download_all_camera_files`

**Request body** (`application/json`): `DownloadAllRequest`

| Field | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|
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
| 200 | Successful Response | `application/octet-stream`: `any` |
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
| `filename_prefix` | string \| null | no |  | `maxLength=40` | Prefix for file names; unsafe characters become _ |

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
| `timelapse` | TimelapseConfigPatch \| null | no |  |  |  |
| `video` | VideoConfigPatch \| null | no |  |  |  |
| `media` | MediaConfigPatch \| null | no |  |  |  |
| `cors_origins` | list[string] \| null | no |  |  | Allowed CORS origins; empty = same-origin only |
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

## files

### `GET /api/v1/files`

operation_id: `list_files`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `folder` | query | string | no | `""` |  | Folder relative to the output dir |
| `page` | query | integer | no | `1` | `>=1` |  |
| `limit` | query | integer | no | `50` | `>=1`, `<=500` |  |
| `kind` | query | enum("image", "raw", "video", "all") | no | `"all"` |  |  |
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

### `GET /api/v1/files/{path}`

operation_id: `download_file`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `path` | path | string | yes |  |  |  |

**Responses**

| Status | Description | Body |
|---|---|---|
| 200 | Successful Response | `application/octet-stream`: `any` |
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
| 200 | Successful Response | `image/jpeg`: `any` |
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
| 200 | One live view JPEG | `image/jpeg`: `any` |
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

### `GET /api/v1/settings/{name}`

operation_id: `get_setting`

**Parameters**

| Name | In | Type | Required | Default | Constraints | Description |
|---|---|---|---|---|---|---|
| `name` | path | string | yes |  |  |  |

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
| `bracket_frame` | enum("middle", "first", "last") \| integer | no | `"middle"` |  | Which shot of each bracket set to use: middle, first, last or a step index. |
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
| 200 | Successful Response | `video/*`: `any` |
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
| `capture_started` | (empty) |
| `capture_complete` | `files` |
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
| `recording_started` | (not found) |
| `recording_stopped` | (not found) |
| `job_created` | `job` |
| `job_progress` | `job` |
| `job_completed` | `job` |
| `job_failed` | `job` |
| `job_cancelled` | `job` |
| `config_changed` | `config`, `restart_required` |
| `error` | (not found) |

## Configuration reference

Edited through the web UI / `/config` endpoints. Never through the environment.

| Section | Field | Type | Default | Constraints | Description |
|---|---|---|---|---|---|
| camera | `keepalive_enabled` | boolean | `true` |  | Send periodic keepalives (D500 times out at 60 s) |
| camera | `keepalive_interval_s` | number | `30.0` | `>=5.0`, `<=55.0` | Keepalive interval |
| camera | `connect_timeout_s` | number | `10.0` | `>=1.0`, `<=120.0` | Timeout for one connect attempt |
| camera | `connect_retries` | integer | `5` | `>=0`, `<=50` | Reconnect attempts after a lost link |
| camera | `reconnect_interval_s` | number | `2.0` | `>=0.5`, `<=60.0` | Delay between reconnects |
| camera | `capture_timeout_s` | number | `30.0` | `>=1.0`, `<=300.0` | Capture timeout |
| camera | `event_quiet_window_s` | number | `1.0` | `>=0.0`, `<=10.0` | After a capture, stop draining camera events after this quiet period |
| liveview | `target_fps` | integer | `8` | `>=1`, `<=30` | Target live view frame rate |
| liveview | `quality` | enum("small", "medium", "large") | `"medium"` |  | Frame size preset |
| liveview | `jpeg_quality` | integer | `75` | `>=10`, `<=100` | Re-encode quality for streamed frames |
| liveview | `max_width` | integer \| null | `null` | `>=64`, `<=8192` | Downscale frames wider than this (px); None = off |
| timelapse | `min_interval_s` | number | `1.0` | `>=0.1`, `<=3600.0` | Minimum frame interval |
| timelapse | `max_duration_s` | integer | `86400` | `>=60`, `<=2592000` | Maximum session length |
| timelapse | `failure_budget` | integer | `5` | `>=1`, `<=100` | Consecutive failed frames before abort |
| video | `ffmpeg_path` | string \| null | `null` |  | Path to the ffmpeg binary; None = autodetect |
| video | `codec` | enum("libx264", "libx265", "libvpx-vp9") | `"libx264"` |  | ffmpeg codec |
| video | `crf` | integer | `23` | `>=0`, `<=51` | Constant rate factor (lower is better) |
| video | `preset` | enum("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow") | `"medium"` |  | ffmpeg preset |
| video | `fps` | integer | `24` | `>=1`, `<=120` | Output frame rate |
| video | `timeout_s` | integer | `3600` | `>=10`, `<=86400` | Upper bound for one ffmpeg run (s) |
| media | `thumbnail_size` | integer | `200` | `>=32`, `<=1024` | Thumbnail longest edge (px) |
| (root) | `cors_origins` | list[string] |  |  | Allowed CORS origins; empty = same-origin only |
| (root) | `demo_camera` | boolean | `false` |  | Use the simulated camera |
| (root) | `api_key_hash` | string \| null | `null` |  | sha256 of the API key; None = open |
