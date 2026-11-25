import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { nextTick } from 'vue'
import { useCameraStore } from '@/stores/camera'
import { useCaptureStore } from '@/stores/capture'
import { useStorageStore } from '@/stores/storage'
import AppHeader from './AppHeader.vue'

describe('AppHeader shots left', () => {
  it('refreshes the card on capture complete, but not while leased', async () => {
    const p = createTestingPinia({ stubActions: false, createSpy: vi.fn })
    const camera = useCameraStore()
    camera.fetchStorage = vi.fn(async () => {})
    useStorageStore().refresh = vi.fn(async () => {})
    camera.connected = true
    const w = mount(AppHeader, { props: { activeTab: 'shoot' }, global: { plugins: [p] } })
    camera.fetchStorage.mockClear()
    const cap = useCaptureStore()
    cap.onStarted({})
    await nextTick()
    cap.onComplete({ files: [] })
    await nextTick()
    expect(camera.fetchStorage).toHaveBeenCalledTimes(1)
    camera.leasedBy = 'timelapse'
    await nextTick()
    camera.fetchStorage.mockClear()
    cap.onStarted({})
    await nextTick()
    cap.onComplete({ files: [] })
    await nextTick()
    expect(camera.fetchStorage).not.toHaveBeenCalled()
    w.unmount()
  })
})
