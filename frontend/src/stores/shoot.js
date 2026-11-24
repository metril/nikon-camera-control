import { defineStore } from 'pinia'
import { computed, reactive, ref, watch } from 'vue'
import { isNoTarget } from '@/api'
import { leaseOwner } from '@/labels'
import { useBulbStore } from './bulb'
import { useCameraStore } from './camera'
import { useCaptureStore } from './capture'
import { useFocusStore } from './focus'
import { useJobsStore } from './jobs'
import { useStorageStore } from './storage'
import { useToastsStore } from './toasts'
import { evSeries, finite, stackIssue } from '@/components/shoot/helpers'

const ACTIVE = ['queued', 'pending', 'running']

export const CAPTURE_MODES = [
  { value: 'single', label: 'Single', title: 'Single frame' },
  { value: 'bracket', label: 'Bracket', title: 'Exposure bracket' },
  { value: 'bulb', label: 'Bulb', title: 'Bulb exposure' },
  { value: 'stack', label: 'Stack', title: 'Focus stack' },
]
/** Lease name each capture mode holds on the camera while it runs. */
const OWN_LEASE = { bracket: 'bracket', bulb: 'bulb', stack: 'focus-stack' }

/**
 * What the shutter does. One place owns the selected capture mode, its settings, and the
 * start/stop logic for Single, Bracket, Bulb and Stack, so the shutter button, the Space key
 * and the settings below it always agree.
 */
export const useShootStore = defineStore('shoot', () => {
  const camera = useCameraStore()
  const capture = useCaptureStore()
  const bulb = useBulbStore()
  const jobs = useJobsStore()
  const focus = useFocusStore()
  const storage = useStorageStore()
  const toasts = useToastsStore()

  const mode = ref('single')
  const bracket = reactive({ frames: 3, step: 1 })
  const bulbForm = reactive({ seconds: 30 })
  const stack = reactive({
    shots: 10,
    steps: 20,
    direction: 'near_to_far',
    settle: 500,
    back: true,
    name: '',
  })
  /** Name of the preset last applied from the strip; cleared when a value is edited by hand. */
  const appliedPreset = ref(null)

  const bracketJobId = ref(null)
  const stackJobId = ref(null)
  const starting = ref(false)
  const bracketJob = computed(() => jobs.byId[bracketJobId.value] || null)
  const stackJob = computed(() => jobs.byId[stackJobId.value] || null)
  const bracketRunning = computed(
    () => !!bracketJob.value && ACTIVE.includes(bracketJob.value.status),
  )
  const stackRunning = computed(() => !!stackJob.value && ACTIVE.includes(stackJob.value.status))
  const bulbRunning = computed(() => bulb.active)
  const anyRunning = computed(() => bracketRunning.value || stackRunning.value || bulbRunning.value)

  const running = computed(
    () =>
      ({
        single: capture.inFlight,
        bracket: bracketRunning.value,
        bulb: bulbRunning.value,
        stack: stackRunning.value,
      })[mode.value],
  )
  const stoppable = computed(() => mode.value !== 'single' && running.value)

  const noTarget = computed(() => storage.noTarget || isNoTarget(capture.lastError))
  const stackProblem = computed(() => {
    const s = stack
    if (!finite(s.settle) || s.settle < 0 || s.settle > 60000)
      return 'Settle time must be 0 to 60000 ms'
    if (s.name && s.name.length > 40) return 'Name is too long'
    return stackIssue(
      { steps: s.steps, shots: s.shots, direction: s.direction },
      focus.status?.range,
    )
  })
  const bulbOk = computed(
    () => finite(bulbForm.seconds) && bulbForm.seconds >= 1 && bulbForm.seconds <= 3600,
  )

  /** Why the shutter is unavailable, as visible text ('' when it can fire). */
  const blockedReason = computed(() => {
    if (!camera.connected) return 'Connect the camera to capture.'
    const own = OWN_LEASE[mode.value]
    if (camera.leasedBy && camera.leasedBy !== own) return `Busy: ${leaseOwner(camera.leasedBy)}.`
    if (anyRunning.value && !stoppable.value) return 'Another capture is running.'
    if (!stoppable.value && !['idle', 'liveview'].includes(camera.state)) return 'Camera busy.'
    if (capture.inFlight) return 'Capturing…'
    if (noTarget.value) return 'No storage target. Choose one in Settings.'
    if (mode.value === 'bulb' && !bulbOk.value) return 'Exposure time must be 1 to 3600 s.'
    if (mode.value === 'stack' && stackProblem.value) return `${stackProblem.value}.`
    return ''
  })
  const canPress = computed(() => stoppable.value || (!blockedReason.value && !starting.value))

  const stackDone = computed(() => {
    const p = stackJob.value?.progress
    return finite(p) ? Math.min(stack.shots, Math.round(p * stack.shots)) : 0
  })
  const label = computed(() => {
    switch (mode.value) {
      case 'bracket':
        return bracketRunning.value ? 'Stop bracket' : `Capture ${bracket.frames} frames`
      case 'bulb':
        return bulbRunning.value ? 'Close shutter' : 'Open shutter'
      case 'stack':
        return stackRunning.value
          ? `Frame ${stackDone.value} of ${stack.shots}`
          : 'Start focus stack'
      default:
        return capture.inFlight ? 'Capturing…' : 'Capture'
    }
  })

  const fail = (e) => toasts.error(e)

  async function captureSingle() {
    try {
      await capture.capture({ download: true, delete_from_camera: false, filename_prefix: null })
    } catch (e) {
      fail(e)
    }
  }
  async function startBracket() {
    starting.value = true
    try {
      const j = await capture.bracket({
        bracketing: {
          mode: 'quick',
          exposure: evSeries(bracket.frames, bracket.step),
          combine_mode: 'sequence',
        },
        download: true,
        filename_prefix: null,
      })
      bracketJobId.value = j.id
      jobs.upsert(j)
    } catch (e) {
      fail(e)
    } finally {
      starting.value = false
    }
  }
  async function startBulb() {
    starting.value = true
    try {
      await bulb.start({ seconds: bulbForm.seconds, download: true, filename_prefix: null })
    } catch (e) {
      fail(e)
    } finally {
      starting.value = false
    }
  }
  async function startStack() {
    starting.value = true
    try {
      const j = await focus.stack({
        steps_per_shot: stack.steps,
        shots: stack.shots,
        direction: stack.direction,
        settle_ms: stack.settle,
        return_to_start: stack.back,
        name: stack.name.trim() || null,
      })
      stackJobId.value = j.id
      jobs.upsert(j)
    } catch (e) {
      fail(e)
    } finally {
      starting.value = false
    }
  }
  /** Cancel the running job of the selected mode (closes the bulb shutter). */
  async function stop() {
    const id = {
      bracket: bracketJobId.value,
      bulb: bulb.jobId || bulb.status?.job_id,
      stack: stackJobId.value,
    }[mode.value]
    if (!id) return
    try {
      await jobs.cancel(id)
    } catch (e) {
      fail(e)
    }
  }
  /** The shutter button and the Space key. */
  async function press() {
    if (stoppable.value) return stop()
    if (!canPress.value) return
    if (mode.value === 'single') return captureSingle()
    if (mode.value === 'bracket') return startBracket()
    if (mode.value === 'bulb') return startBulb()
    return startStack()
  }

  // Refresh the recent captures once a multi-frame job finishes.
  watch([bracketRunning, bulbRunning, stackRunning], (now, before) => {
    if (before.some((was, i) => was && !now[i])) capture.loadRecent().catch(() => {})
  })

  return {
    mode,
    bracket,
    bulbForm,
    stack,
    appliedPreset,
    bracketJobId,
    stackJobId,
    bracketJob,
    stackJob,
    bracketRunning,
    stackRunning,
    bulbRunning,
    anyRunning,
    running,
    stoppable,
    noTarget,
    stackProblem,
    bulbOk,
    blockedReason,
    canPress,
    stackDone,
    label,
    starting,
    press,
    stop,
    startBracket,
    startBulb,
    startStack,
  }
})
