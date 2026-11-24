import { computed } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { isNoPermission } from './connectError'

const BUSY_STATES = ['capturing', 'recording', 'bulb', 'busy']

/** One reading of the camera for the header chip and the status stripe. */
export function useCameraStatus() {
  const camera = useCameraStore()
  const noPermission = computed(() => !camera.connected && isNoPermission(camera.lastError))
  const busy = computed(
    () => camera.connected && (!!camera.leasedBy || BUSY_STATES.includes(camera.state)),
  )
  /** key: ready | busy | connecting | disconnected | permission; dot: ok | busy | off */
  const status = computed(() => {
    if (camera.state === 'connecting')
      return { key: 'connecting', label: 'Connecting…', short: '…', dot: 'busy' }
    if (noPermission.value)
      return { key: 'permission', label: 'No permission', short: 'No', dot: 'off' }
    if (!camera.connected)
      return { key: 'disconnected', label: 'Disconnected', short: 'Off', dot: 'off' }
    if (busy.value) return { key: 'busy', label: 'Busy', short: 'Busy', dot: 'busy' }
    return { key: 'ready', label: 'Connected', short: 'On', dot: 'ok' }
  })
  /** Thin stripe under the header: red when disconnected, amber when busy, hidden when ready. */
  const stripe = computed(() => ({ off: 'off', busy: 'busy', ok: '' })[status.value.dot])
  return { status, stripe, noPermission, busy }
}
