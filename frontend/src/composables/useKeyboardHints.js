import { ref } from 'vue'

const KEY = 'hints'

function read() {
  try {
    return localStorage.getItem(KEY) !== '0'
  } catch {
    return true
  }
}
const hints = ref(read())

/** Whether to show keyboard shortcut hints; stored per browser under "hints". */
export function useKeyboardHints() {
  function setHints(on) {
    hints.value = !!on
    try {
      localStorage.setItem(KEY, on ? '1' : '0')
    } catch {
      /* storage unavailable: the choice lasts for this session */
    }
  }
  return { hints, setHints }
}
