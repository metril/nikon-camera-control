import { computed, ref, unref, watch } from 'vue'
import { isTextTarget, useDocumentKeydown } from './useHotkeys'

const LONG_PRESS_MS = 500
const MOVE_TOLERANCE = 10

/**
 * Multi-select for grids and lists.
 *   const sel = useSelection({ ids: () => items.map((i) => i.id) })
 *   click:   if (!sel.click(id, event)) open(id)      // true = the click was a selection click
 *   touch:   v-bind="sel.longPress(id)"               // long-press enters selection mode
 *   keys:    Ctrl/Cmd+A selects all and Esc clears, while selecting (listener bound on mount)
 * Selecting is on while the mode is entered (start / longPress / selectAll) or anything is selected.
 */
export function useSelection({ ids, onEnter } = {}) {
  const order = () => unref(typeof ids === 'function' ? ids() : ids) || []
  const selected = ref(new Set())
  const mode = ref(false)
  const anchor = ref(null)
  let suppressClick = false

  const selecting = computed(() => mode.value || selected.value.size > 0)
  const count = computed(() => selected.value.size)
  const list = computed(() => [...selected.value])
  const isSelected = (id) => selected.value.has(id)
  const allSelected = computed(() => {
    const all = order()
    return all.length > 0 && all.every((i) => selected.value.has(i))
  })

  function set(next) {
    selected.value = new Set(next)
  }
  function enter() {
    if (!mode.value) onEnter?.()
    mode.value = true
  }
  function toggle(id, { shift = false } = {}) {
    if (shift && anchor.value != null && anchor.value !== id) {
      const all = order()
      const a = all.indexOf(anchor.value)
      const b = all.indexOf(id)
      if (a !== -1 && b !== -1) {
        const [lo, hi] = a < b ? [a, b] : [b, a]
        const next = new Set(selected.value)
        for (const i of all.slice(lo, hi + 1)) next.add(i)
        set(next)
        return
      }
    }
    const next = new Set(selected.value)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    set(next)
    anchor.value = id
  }
  /** Enter selection mode with `id` selected. */
  function start(id) {
    enter()
    if (id != null && !selected.value.has(id)) toggle(id)
    else if (id != null) anchor.value = id
  }
  function selectAll() {
    enter()
    set(order())
  }
  function clear() {
    set([])
    mode.value = false
    anchor.value = null
  }
  /** Returns true when the click was consumed by selection (the caller should not open the item). */
  function click(id, e) {
    if (suppressClick) {
      suppressClick = false
      return true
    }
    const shift = !!e?.shiftKey
    const ctrl = !!(e?.ctrlKey || e?.metaKey)
    if (selecting.value || ctrl || shift) {
      if (!selecting.value) enter()
      toggle(id, { shift })
      return true
    }
    return false
  }

  /** Spread onto an item: pointer handlers that enter selection after a long press. */
  function longPress(id) {
    let timer = null
    let x = 0
    let y = 0
    const cancel = () => {
      clearTimeout(timer)
      timer = null
    }
    return {
      onPointerdown(e) {
        if (e.pointerType === 'mouse' && e.button !== 0) return
        x = e.clientX
        y = e.clientY
        cancel()
        timer = setTimeout(() => {
          timer = null
          suppressClick = true
          start(id)
        }, LONG_PRESS_MS)
      },
      onPointermove(e) {
        if (timer && Math.hypot(e.clientX - x, e.clientY - y) > MOVE_TOLERANCE) cancel()
      },
      onPointerup: cancel,
      onPointercancel: cancel,
      onPointerleave: cancel,
      // the OS context menu would otherwise fight the long press on touch
      onContextmenu(e) {
        if (selecting.value || suppressClick) e.preventDefault()
      },
    }
  }

  function onKeydown(e) {
    if (!selecting.value || isTextTarget(e.target)) return
    if (document.querySelector('[aria-modal="true"]')) return
    if ((e.ctrlKey || e.metaKey) && String(e.key).toLowerCase() === 'a') {
      e.preventDefault()
      selectAll()
    } else if (e.key === 'Escape') {
      clear()
    }
  }
  useDocumentKeydown(onKeydown)

  // items that disappear (deleted, filtered out) leave the selection
  watch(
    () => order(),
    (all) => {
      if (!selected.value.size) return
      const present = new Set(all)
      const kept = [...selected.value].filter((i) => present.has(i))
      if (kept.length !== selected.value.size) set(kept)
    },
  )

  return {
    selected,
    selecting,
    count,
    list,
    allSelected,
    isSelected,
    toggle,
    click,
    start,
    selectAll,
    clear,
    longPress,
    onKeydown,
  }
}
