import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { api } from '@/api'
import { guard } from './helpers'

const TOOLS_KEY = 'liveview.tools'
export const GRID_MODES = ['thirds', 'golden', 'centre', 'off']
const DEFAULT_TOOLS = {
  grid: 'thirds',
  hist: true,
  clip: false,
  peak: false,
  loupe: false,
  onion: false,
}

function loadTools() {
  try {
    const saved = JSON.parse(localStorage.getItem(TOOLS_KEY) || 'null')
    if (saved && typeof saved === 'object') {
      const grid = GRID_MODES.includes(saved.grid) ? saved.grid : DEFAULT_TOOLS.grid
      const t = { ...DEFAULT_TOOLS, grid }
      for (const k of ['hist', 'clip', 'peak', 'loupe', 'onion'])
        if (typeof saved[k] === 'boolean') t[k] = saved[k]
      return t
    }
  } catch {
    /* storage unavailable or corrupt: use defaults */
  }
  return { ...DEFAULT_TOOLS }
}

export const useLiveViewStore = defineStore('liveview', () => {
  const status = ref(null)
  const lastError = ref(null)
  /** Overlay tools shown on the live view; remembered per browser. */
  const tools = ref(loadTools())
  const saveTools = () => {
    try {
      localStorage.setItem(TOOLS_KEY, JSON.stringify(tools.value))
    } catch {
      /* ignore */
    }
  }
  const toggleTool = (k) => {
    tools.value = { ...tools.value, [k]: !tools.value[k] }
    saveTools()
  }
  const cycleGrid = () => {
    const i = GRID_MODES.indexOf(tools.value.grid)
    tools.value = { ...tools.value, grid: GRID_MODES[(i + 1) % GRID_MODES.length] }
    saveTools()
  }
  const running = computed(() => !!status.value?.running)
  const set = (s) => (status.value = s)

  const fetchStatus = () => guard(lastError, async () => set(await api.getLiveview()))
  const start = () => guard(lastError, async () => set(await api.startLiveview()))
  const stop = () => guard(lastError, async () => set(await api.stopLiveview()))

  const onStarted = () => (status.value = { ...status.value, running: true, active: true })
  const onStopped = () =>
    status.value && (status.value = { ...status.value, running: false, active: false })
  const reset = () => (status.value = null)

  return {
    status,
    tools,
    toggleTool,
    cycleGrid,
    running,
    lastError,
    fetchStatus,
    start,
    stop,
    onStarted,
    onStopped,
    reset,
  }
})
