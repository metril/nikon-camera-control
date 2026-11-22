import { onUnmounted } from 'vue'

/**
 * Press-and-hold repeat. `send` is awaited before the next repeat is scheduled, so there is
 * never more than one request in flight. A failure stops the repeat and goes to `onError`.
 */
export function useHoldRepeat(send, { onError, delay = 400, interval = 120 } = {}) {
  let holding = false
  let busy = false
  let timer = null

  async function fire() {
    if (busy) return false
    busy = true
    try {
      await send()
      return true
    } catch (e) {
      stop()
      onError?.(e)
      return false
    } finally {
      busy = false
    }
  }
  async function loop() {
    if (!holding) return
    const ok = await fire()
    if (holding && ok) timer = setTimeout(loop, interval)
  }
  async function start() {
    if (holding) return
    holding = true
    const ok = await fire()
    if (holding && ok) timer = setTimeout(loop, delay)
  }
  function stop() {
    holding = false
    clearTimeout(timer)
    timer = null
  }
  /** Single step (keyboard activation). */
  const once = () => fire().catch(() => {})

  onUnmounted(stop)
  return { start, stop, once }
}
