import { shallowRef } from 'vue'
import { useLayoutMode } from './useLayoutMode'

const TEXT_TYPES = ['', 'text', 'search', 'password', 'email', 'url', 'tel']

/** Text-like fields the on-screen keyboard serves (not number/readonly/disabled/opted-out). */
export function isOskTarget(el) {
  if (!el || el.nodeType !== 1 || el.disabled || el.readOnly || el.closest?.('[data-no-osk]')) {
    return false
  }
  const mode = el.getAttribute('inputmode')
  if (mode && mode !== 'none' && mode !== 'text') return false
  if (el.tagName === 'TEXTAREA') return true
  return (
    el.tagName === 'INPUT' && TEXT_TYPES.includes((el.getAttribute('type') || '').toLowerCase())
  )
}

/** The field the keyboard types into (null: keyboard closed). Shared by the whole app. */
export const oskTarget = shallowRef(null)

export function closeOsk({ blur = false } = {}) {
  const el = oskTarget.value
  oskTarget.value = null
  if (blur && el?.isConnected) el.blur()
}

function fire(el, type, init) {
  return el.dispatchEvent(new (type === 'input' ? InputEvent : KeyboardEvent)(type, init))
}

/** Insert text at the caret (replacing a selection), like typing; v-model sees a normal input event. */
export function oskInsert(str) {
  const el = oskTarget.value
  if (!el || !str) return
  const sel = el.selectionStart != null
  const s = sel ? el.selectionStart : el.value.length
  const e = sel ? el.selectionEnd : s
  if (el.maxLength >= 0 && el.value.length - (e - s) + str.length > el.maxLength) return
  if (sel) {
    el.setRangeText(str, s, e, 'end')
    el.setSelectionRange(s + str.length, s + str.length)
  } else el.value += str
  fire(el, 'input', { bubbles: true, data: str, inputType: 'insertText' })
}

/** Delete the selection, or the character before the caret. */
export function oskBackspace() {
  const el = oskTarget.value
  if (!el) return
  const sel = el.selectionStart != null
  let s = sel ? el.selectionStart : el.value.length
  const e = sel ? el.selectionEnd : s
  if (s === e) {
    if (s === 0) return
    s -= 1
  }
  if (sel) {
    el.setRangeText('', s, e, 'end')
    el.setSelectionRange(s, s)
  } else el.value = el.value.slice(0, s)
  fire(el, 'input', { bubbles: true, inputType: 'deleteContentBackward' })
}

/** Enter as a physical keyboard does: keydown handlers run; then submit the form and blur
 * (a textarea gets a newline instead). */
export function oskEnter() {
  const el = oskTarget.value
  if (!el) return
  const init = { key: 'Enter', code: 'Enter', bubbles: true, cancelable: true }
  const ok = fire(el, 'keydown', init)
  fire(el, 'keyup', init)
  if (!ok) return
  if (el.tagName === 'TEXTAREA') return oskInsert('\n')
  el.form?.requestSubmit?.()
  closeOsk({ blur: true })
}

let attached = 0
let off = null

/** Install the global listeners once (App.vue). Returns a detach function. */
export function attachOsk() {
  const { isTouch } = useLayoutMode()
  if (!attached++) {
    const prep = (e) => {
      const el = e.target
      // inputmode=none keeps tablets' native keyboard away; must be set before focus
      if (isTouch.value && isOskTarget(el) && !el.hasAttribute('inputmode')) {
        el.setAttribute('inputmode', 'none')
      }
    }
    const onFocusIn = (e) => {
      prep(e)
      if (isTouch.value && isOskTarget(e.target)) oskTarget.value = e.target
    }
    const onFocusOut = (e) => {
      if (e.target === oskTarget.value) oskTarget.value = null
    }
    const onPointerDown = (e) => {
      prep(e)
      const t = oskTarget.value
      if (t && e.target !== t && !e.target.closest?.('[data-osk]')) closeOsk({ blur: true })
    }
    const onHash = () => closeOsk({ blur: true })
    document.addEventListener('focusin', onFocusIn)
    document.addEventListener('focusout', onFocusOut)
    document.addEventListener('pointerdown', onPointerDown, true)
    window.addEventListener('hashchange', onHash)
    off = () => {
      document.removeEventListener('focusin', onFocusIn)
      document.removeEventListener('focusout', onFocusOut)
      document.removeEventListener('pointerdown', onPointerDown, true)
      window.removeEventListener('hashchange', onHash)
      oskTarget.value = null
    }
  }
  return () => {
    if (!--attached) off?.()
  }
}
