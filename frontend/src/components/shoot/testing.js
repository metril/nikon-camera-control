import { vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { useCameraStore } from '@/stores/camera'

/** Mount with a real-action testing pinia and a connected, idle camera (override via opts). */
export function mountCard(
  component,
  { connected = true, leasedBy = null, state = 'idle', setup, props, attachTo } = {},
) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const camera = useCameraStore()
  camera.connected = connected
  camera.state = connected ? state : 'disconnected'
  camera.leasedBy = leasedBy
  setup?.()
  const wrapper = mount(component, { props, attachTo, global: { plugins: [pinia] } })
  return { wrapper, pinia, camera }
}

export const deferred = () => {
  let resolve, reject
  const promise = new Promise((res, rej) => ((resolve = res), (reject = rej)))
  return { promise, resolve, reject }
}

export const button = (wrapper, text) =>
  wrapper.findAll('button').find((b) => b.text().includes(text))

/** The <input> whose <label for> text contains `text`. */
export function inputByLabel(wrapper, text) {
  const label = wrapper.findAll('label').find((l) => l.text().includes(text))
  return label ? wrapper.find(`#${label.attributes('for')}`) : undefined
}

/** Buttons rendered outside the wrapper (modals are teleported to <body>). */
export const bodyButton = (text) =>
  [...document.body.querySelectorAll('button')].find((b) => b.textContent.includes(text))
