/** Single source for display text. Raw API values go in; sentence-case labels come out. */

const ACRONYMS = new Set(['iso', 'ev', 'raw', 'jpeg', 'crf', 'smb', 'usb', 'api', 'id'])

/** snake/kebab case to sentence case, keeping known acronyms upper case. */
export function humanize(str) {
  if (str == null) return ''
  const words = String(str)
    .trim()
    .split(/[\s_-]+/)
    .filter(Boolean)
  if (!words.length) return ''
  return words
    .map((w, i) => {
      const lower = w.toLowerCase()
      if (ACRONYMS.has(lower)) return lower.toUpperCase()
      return i === 0 ? lower.charAt(0).toUpperCase() + lower.slice(1) : lower
    })
    .join(' ')
}

/** Build a lookup that falls back to humanize for unknown values. */
function labeller(map) {
  return (key) => (key != null && Object.hasOwn(map, key) ? map[key] : humanize(key))
}

export const JOB_KINDS = {
  'render-video': 'Video render',
  video: 'Video render',
  download_all: 'Download all',
  'download-all': 'Download all',
  'focus-stack': 'Focus stack',
  bracket: 'Bracket capture',
  bulb: 'Bulb exposure',
  recording_download: 'Recording download',
  fsck: 'Drive check',
  format: 'Drive format',
}
export const jobKind = labeller(JOB_KINDS)

export const JOB_STATUSES = {
  queued: 'Queued',
  running: 'Running',
  completed: 'Done',
  failed: 'Failed',
  cancelled: 'Cancelled',
}
export const jobStatus = labeller(JOB_STATUSES)

export const TIMELAPSE_STATES = {
  idle: 'Idle',
  created: 'Created',
  configured: 'Ready',
  running: 'Running',
  paused: 'Paused',
  stopping: 'Stopping',
  completed: 'Completed',
  stopped: 'Stopped',
  failed: 'Failed',
  interrupted: 'Interrupted',
}
export const timelapseState = labeller(TIMELAPSE_STATES)

export const LIVEVIEW_PAUSE_REASONS = {
  camera_disconnected: 'camera disconnected',
  camera_connecting: 'camera connecting',
  camera_idle: 'camera idle',
  camera_liveview: 'camera in live view',
  camera_capturing: 'camera capturing',
  camera_recording: 'camera recording',
  camera_bulb: 'bulb exposure running',
  camera_busy: 'camera busy',
  camera_error: 'camera error',
  preview_failed: 'preview failed',
  user: 'paused by you',
}
export const liveviewPauseReason = labeller(LIVEVIEW_PAUSE_REASONS)

export const TIMELAPSE_PAUSE_REASONS = {
  user: 'Paused by you',
  camera_disconnected: 'Camera disconnected',
}
export const timelapsePauseReason = labeller(TIMELAPSE_PAUSE_REASONS)

export const TIMELAPSE_WARNINGS = {
  frame_failed: 'Frame failed',
  interval_too_short: 'The interval is shorter than one frame takes',
  camera_disconnected: 'Camera disconnected',
  restore_failed: 'Could not restore camera settings',
}
export const timelapseWarning = labeller(TIMELAPSE_WARNINGS)

export const FILE_KINDS = {
  jpeg: 'JPEG',
  image: 'JPEG',
  raw: 'RAW',
  video: 'Video',
  other: 'Other',
}
export const fileKind = labeller(FILE_KINDS)

export const LEASE_OWNERS = {
  recording: 'Recording',
  bulb: 'Bulb exposure',
  bracket: 'Bracket capture',
  'focus-stack': 'Focus stack',
  timelapse: 'Time-lapse',
}
export const leaseOwner = labeller(LEASE_OWNERS)

export const CAMERA_BACKENDS = {
  demo: 'Demo camera',
  real: 'USB (gphoto2)',
  gphoto2: 'USB (gphoto2)',
}
export const cameraBackend = labeller(CAMERA_BACKENDS)

export const CAMERA_STATES = {
  disconnected: 'Disconnected',
  connecting: 'Connecting',
  idle: 'Ready',
  liveview: 'Live view',
  capturing: 'Capturing',
  recording: 'Recording',
  bulb: 'Bulb',
  busy: 'Busy',
  error: 'Error',
}
export const cameraState = labeller(CAMERA_STATES)

/** Render request codec enum (API `codec`), each once. */
export const VIDEO_CODECS = {
  h264: 'H.264',
  h265: 'H.265',
  prores: 'ProRes',
  vp9: 'VP9',
}
export const ENCODER_PRESETS = {
  ultrafast: 'Ultrafast',
  superfast: 'Superfast',
  veryfast: 'Very fast',
  faster: 'Faster',
  fast: 'Fast',
  medium: 'Medium',
  slow: 'Slow',
  slower: 'Slower',
  veryslow: 'Very slow',
}
export const VIDEO_QUALITIES = {
  '': 'Default',
  low: 'Low',
  medium: 'Medium',
  high: 'High',
}
export const VIDEO_RESOLUTIONS = {
  source: 'Source',
  '2160p': '2160p',
  '1080p': '1080p',
  '720p': '720p',
}
/** Encoder names as ffprobe reports them on rendered videos. */
export const VIDEO_ENCODERS = {
  libx264: 'H.264',
  libx265: 'H.265',
  'libvpx-vp9': 'VP9',
  prores_ks: 'ProRes',
  ...VIDEO_CODECS,
}
export const BRACKET_FRAMES = { middle: 'Middle', first: 'First', last: 'Last' }
export const BRACKET_MODES = {
  none: 'None',
  quick: 'Quick',
  steps: 'Custom steps',
  preset: 'Preset',
}
export const videoCodec = labeller(VIDEO_ENCODERS)
export const encoderPreset = labeller(ENCODER_PRESETS)
export const videoQuality = labeller(VIDEO_QUALITIES)
export const videoResolution = labeller(VIDEO_RESOLUTIONS)

export const LIVEVIEW_QUALITIES = { small: 'Small', medium: 'Medium', large: 'Large' }
export const liveviewQuality = labeller(LIVEVIEW_QUALITIES)

/** Where the camera stores a photo, as its capture-target choices are worded. */
export const CAPTURE_TARGETS = {
  'Internal RAM': 'Camera memory',
  'Internal memory': 'Camera memory',
  'Memory card': 'Memory card',
}
export const captureTarget = labeller(CAPTURE_TARGETS)

/** Label for one value of an enum config field, chosen by the field's name. */
const CONFIG_ENUMS = { codec: videoCodec, preset: encoderPreset, quality: liveviewQuality }
export const configEnum = (field, value) => (CONFIG_ENUMS[field] || humanize)(value)

/** Select options ({ value, label }) for the enums above. */
export const options = (map) => Object.entries(map).map(([value, label]) => ({ value, label }))

/** Camera setting names as the camera reports them (label) or by widget name. */
export const SETTING_NAMES = {
  'ISO Speed': 'ISO',
  'F-Number': 'Aperture',
  'Fixed Aperture': 'Aperture',
  'Shutter Speed': 'Shutter speed',
  'Exposure Compensation': 'Exposure compensation',
  'Auto Exposure Mode': 'Exposure mode',
  'Focus Mode': 'Focus mode',
  'Metering Mode': 'Metering',
  'White Balance': 'White balance',
  'Image Quality': 'Image quality',
  'Image Size': 'Image size',
  'Capture Target': 'Capture target',
  iso: 'ISO',
  'f-number': 'Aperture',
  shutterspeed: 'Shutter speed',
  exposurecompensation: 'Exposure compensation',
  autoexposuremode: 'Exposure mode',
  focusmode: 'Focus mode',
  liveviewaffocus: 'Live view AF mode',
  meteringmode: 'Metering',
  whitebalance: 'White balance',
  imagequality: 'Image quality',
  imagesize: 'Image size',
  capturetarget: 'Capture target',
  liveviewsize: 'Live view size',
  batterylevel: 'Battery',
}
export const settingName = labeller(SETTING_NAMES)

/** Format a signed EV step with a true minus sign; zero is shown as ±0.0. */
function signedEv(n) {
  if (Math.abs(n) < 0.05) return '±0.0'
  const t = Math.abs(n).toFixed(1)
  return `${n < 0 ? '\u2212' : '+'}${t}`
}

/** A camera setting value as people read it: × in sizes, true-minus EV, sentence case words. */
export function settingValueLabel(name, value) {
  if (value == null || value === '') return '–'
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  const v = String(value)
  const key = String(name || '').toLowerCase()
  if (/^\d+\s*x\s*\d+$/i.test(v)) return v.replace(/\s*x\s*/i, ' \u00d7 ').replace(/ /g, '')
  if (key === 'exposurecompensation' || key === 'exposure compensation') {
    const n = Number(v)
    if (Number.isFinite(n)) return signedEv(Math.round(n * 3) / 3)
  }
  // Title Case words ("Center Weighted") become sentence case; ISO/WB style acronyms stay put
  if (/^[A-Z][a-z]+( [A-Z][a-z]+)+$/.test(v)) return v.charAt(0) + v.slice(1).toLowerCase()
  return v
}

const pad = (n) => String(n).padStart(2, '0')
/** Same cleaning as the backend's sanitize_prefix: unsafe runs become '-', ends trimmed, max 40. */
export function cleanPrefix(prefix) {
  const trim = (s) => s.replace(/^[_-]+|[_-]+$/g, '')
  const c = trim(trim(String(prefix || '').replace(/[^A-Za-z0-9_-]+/g, '-')).slice(0, 40))
  return c ? `${c}-` : ''
}
/** Example of a downloaded file name: [prefix, 'YYYY-MM-DD-HHMMSS-DSC_2161.JPG']. */
export function sampleName(prefix, d = new Date()) {
  const stamp = `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
  return [
    cleanPrefix(prefix),
    `${stamp}-${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}-DSC_2161.JPG`,
  ]
}
