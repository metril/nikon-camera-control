import { reactive, computed, ref } from 'vue'
import { useTimelapseStore } from '@/stores/timelapse'
import { bracketTypes, stepFromApi, stepToApi, newStep, sortValues } from './bracketUtils'

const emptyQuick = () => ({ exposure: [], iso: [], aperture: [], shutter: [], combine: 'sequence' })
const initial = () => ({
  name: 'Time-lapse',
  intervalS: 10,
  limit: 'frames', // 'frames' | 'duration'
  totalFrames: 100,
  durationMin: 60,
  fps: 24,
  bracket: {
    mode: 'none', // none | quick | steps | preset
    quick: emptyQuick(),
    steps: [newStep(), newStep()],
    presetName: '',
    presetRef: null, // {name, builtin, snapshot} while a loaded preset is unedited
  },
})

/** Shared form state (one time-lapse page) and the last server result. */
export const draft = reactive(initial())
export const applied = reactive({ result: null, key: null, errors: {}, busy: false })

/** Server estimate of the current draft (nothing saved). */
export const preview = reactive({ result: null, key: null, errors: {}, busy: false })
/** Latest server numbers: the preview of this draft, else the saved configuration. */
export const resultNow = computed(() => preview.result ?? applied.result)
/** The server has seen exactly this draft (previewed or saved). */
export const fresh = computed(
  () => !!draftKey.value && (preview.key === draftKey.value || applied.key === draftKey.value),
)

export function resetDraft() {
  Object.assign(draft, initial())
  Object.assign(applied, { result: null, key: null, errors: {}, busy: false })
  Object.assign(preview, { result: null, key: null, errors: {}, busy: false })
  previewSeq++
  baselineKey.value = draftKey.value
}
let previewSeq = 0

const finitePositive = (n) => typeof n === 'number' && Number.isFinite(n) && n > 0

function quickPayload() {
  const q = draft.bracket.quick
  const out = { mode: 'quick', combine_mode: q.combine }
  for (const t of bracketTypes) if (q[t.key].length) out[t.key] = [...q[t.key]]
  return out
}

/** Bracketing as editable content (never the preset-by-name form). */
export function contentBracketing() {
  const b = draft.bracket
  if (b.mode === 'quick') return quickPayload()
  if (b.mode === 'steps') return { mode: 'steps', steps: b.steps.map(stepToApi) }
  return null
}

function bracketingPayload() {
  const b = draft.bracket
  if (b.mode === 'preset' && b.presetName) return { mode: 'preset', preset: b.presetName }
  const content = contentBracketing()
  if (!content) return { mode: 'none' }
  // An unedited built-in goes by name; once edited it is sent as steps/quick.
  if (b.presetRef?.builtin && JSON.stringify(content) === b.presetRef.snapshot)
    return { mode: 'preset', preset: b.presetRef.name }
  return content
}

/** Local validation errors keyed like server errors; {} when sendable. */
export const localErrors = computed(() => {
  const e = {}
  if (!draft.name.trim()) e.name = 'Name is required'
  if (!finitePositive(draft.intervalS)) e.interval_s = 'Enter an interval above 0'
  if (draft.limit === 'frames') {
    if (!finitePositive(draft.totalFrames) || !Number.isInteger(draft.totalFrames))
      e.total_frames = 'Enter a whole number of frames'
  } else if (!finitePositive(draft.durationMin) || Math.round(draft.durationMin * 60) < 1) {
    e.duration_s = 'Enter a duration above 0'
  }
  const b = draft.bracket
  if (b.mode === 'quick' && !bracketTypes.some((t) => b.quick[t.key].length))
    e.bracketing = 'Select at least one value'
  if (b.mode === 'steps') {
    if (b.steps.length < 2 || b.steps.length > 15) e.bracketing = 'Use 2 to 15 steps'
    else if (b.steps.some((s) => !Object.keys(stepToApi(s).settings).length))
      e.bracketing = 'Every step needs a setting and value'
  }
  if (b.mode === 'preset' && !b.presetName) e.bracketing = 'Pick a preset'
  return e
})

/** TimelapseSetup for the server, or null while the draft is invalid (no NaN ever sent). */
export function buildSetup() {
  if (Object.keys(localErrors.value).length) return null
  const out = {
    name: draft.name.trim(),
    interval_s: draft.intervalS,
    bracketing: bracketingPayload(),
  }
  if (draft.limit === 'frames') out.total_frames = draft.totalFrames
  else out.duration_s = Math.round(draft.durationMin * 60)
  return out
}

export const draftKey = computed(() => {
  const s = buildSetup()
  return s ? JSON.stringify(s) : null
})
export const dirty = computed(() => draftKey.value !== applied.key)

/** The untouched form's key: "Unsaved changes" only shows once the draft differs from it (or was saved). */
const baselineKey = ref(null)
export const edited = computed(() => applied.key != null || draftKey.value !== baselineKey.value)
baselineKey.value = draftKey.value

export function fieldErrors(e) {
  const out = {}
  const d = e?.details
  const list = Array.isArray(d) ? d : Array.isArray(d?.errors) ? d.errors : []
  for (const it of list) {
    const loc = (it.loc || []).filter((p) => p !== 'body')
    out[String(loc[0] ?? '_')] ??= it.msg || it.message || 'Invalid value'
  }
  if (!list.length && d && typeof d === 'object')
    for (const [k, v] of Object.entries(d)) if (typeof v === 'string') out[k] = v
  if (!Object.keys(out).length) out._ = e?.message || 'Request failed'
  return out
}

/** Ask the server to validate/estimate the draft. Nothing is saved; stale answers are dropped. */
export async function previewDraft() {
  const setup = buildSetup()
  if (!setup) return null
  const key = JSON.stringify(setup)
  const seq = ++previewSeq
  preview.busy = true
  try {
    const result = await useTimelapseStore().previewDraft(setup)
    if (seq !== previewSeq) return null
    Object.assign(preview, { result, key, errors: {} })
    return result
  } catch (e) {
    if (seq === previewSeq) Object.assign(preview, { key: null, errors: fieldErrors(e) })
    throw e
  } finally {
    if (seq === previewSeq) preview.busy = false
  }
}

/** Send the draft to the server and keep the normalised result. Rejects after recording errors. */
export async function applyDraft() {
  const setup = buildSetup()
  if (!setup) return null
  const key = JSON.stringify(setup)
  applied.busy = true
  try {
    const result = await useTimelapseStore().setConfig(setup)
    applied.result = result
    applied.key = key
    applied.errors = {}
    Object.assign(preview, { result, key, errors: {} })
    return result
  } catch (e) {
    applied.errors = fieldErrors(e)
    throw e
  } finally {
    applied.busy = false
  }
}

/** Load a bracket preset's bracketing into the editor. */
export function loadPreset(preset) {
  const b = draft.bracket
  const br = preset.bracketing
  b.presetName = ''
  if (br.mode === 'steps') {
    b.mode = 'steps'
    b.steps = br.steps.map(stepFromApi)
  } else if (br.mode === 'quick') {
    b.mode = 'quick'
    const q = emptyQuick()
    for (const t of bracketTypes) q[t.key] = sortValues(br[t.key] || [])
    q.combine = br.combine_mode || 'sequence'
    b.quick = q
  } else {
    b.mode = 'preset'
    b.presetName = br.preset
    b.presetRef = null
    return
  }
  b.presetRef = {
    name: preset.name,
    builtin: !!preset.builtin,
    snapshot: JSON.stringify(contentBracketing()),
  }
}
