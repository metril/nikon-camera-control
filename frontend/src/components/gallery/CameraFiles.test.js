import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import CameraFiles from './CameraFiles.vue'
import { useCameraStore } from '@/stores/camera'
import { useCameraFilesStore } from '@/stores/cameraFiles'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { downloadCameraFile: vi.fn().mockResolvedValue(new Blob(['x'])) },
  downloadBlob: vi.fn(),
}))

let wrapper
function setup({ connected = true, leasedBy = null } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const cam = useCameraStore(pinia)
  cam.connected = connected
  cam.leasedBy = leasedBy
  cam.storage = { cards: [{ label: 'CF1', capacity_kb: 1048576, free_kb: 524288 }] }
  vi.spyOn(cam, 'fetchStorage').mockResolvedValue(cam.storage)
  vi.spyOn(cam, 'connect').mockResolvedValue()
  const cf = useCameraFilesStore(pinia)
  vi.spyOn(cf, 'loadFiles').mockImplementation(async (p = {}) => {
    cf.query = { ...cf.query, ...p }
  })
  vi.spyOn(cf, 'loadFolders').mockResolvedValue({ folders: [{ name: '100NCD', path: '/100NCD' }] })
  cf.items = [
    {
      folder: '/100NCD',
      name: 'A.NEF',
      size: 100,
      mtime: 1700000000,
      type: 'raw',
      downloaded: true,
    },
  ]
  cf.total = 1
  const toasts = useToastsStore(pinia)
  vi.spyOn(toasts, 'error')
  wrapper = mount(CameraFiles, { global: { plugins: [pinia] }, attachTo: document.body })
  return { cam, cf, toasts, jobs: useJobsStore(pinia) }
}
const btn = (text) => wrapper.findAll('button').find((b) => b.text().includes(text))
afterEach(() => wrapper?.unmount())

describe('CameraFiles', () => {
  it('shows an empty state with Connect when disconnected', async () => {
    const { cam, cf } = setup({ connected: false })
    expect(wrapper.text()).toContain('Camera not connected')
    expect(cf.loadFiles).not.toHaveBeenCalled()
    await btn('Connect').trigger('click')
    expect(cam.connect).toHaveBeenCalled()
  })

  it('lists files with downloaded badge and storage info', async () => {
    setup()
    await flushPromises()
    expect(wrapper.text()).toContain('A.NEF')
    expect(wrapper.text()).toContain('Downloaded')
    expect(wrapper.find('[data-testid=storage]').text()).toContain('CF1')
    expect(wrapper.text()).toContain('100NCD')
  })

  it('disables delete with a reason while the camera is leased', async () => {
    setup({ leasedBy: 'timelapse' })
    await flushPromises()
    const del = wrapper.find('[data-testid=delete-card-file]')
    expect(del.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('Busy: Time-lapse')
  })

  it('delete failure is visible via toast', async () => {
    const { cf, toasts } = setup()
    vi.spyOn(cf, 'remove').mockRejectedValue(new Error('card busy'))
    await flushPromises()
    const del = wrapper.find('[data-testid=delete-card-file]')
    await del.trigger('click')
    await del.trigger('click')
    await flushPromises()
    expect(cf.remove).toHaveBeenCalledWith('/100NCD', 'A.NEF')
    expect(toasts.error).toHaveBeenCalled()
  })

  it('download-all starts a job with chosen options and renders live progress, then result', async () => {
    const { cf, jobs } = setup()
    vi.spyOn(cf, 'downloadAll').mockResolvedValue({
      id: 'j1',
      kind: 'download_all',
      status: 'running',
      progress: 0.25,
    })
    await flushPromises()
    const toggles = wrapper.findAll('input[type=checkbox], [role=switch]')
    // second toggle = delete after
    await toggles[0].trigger('click')
    await toggles[1].trigger('click')
    await flushPromises()
    await btn('Download all').trigger('click')
    await flushPromises()
    expect(cf.downloadAll).toHaveBeenCalledWith({
      only_new: false,
      delete_after: true,
      folder: null,
    })
    jobs.upsert({
      id: 'j1',
      kind: 'download_all',
      status: 'running',
      progress: 0.5,
      message: 'B.NEF (2/4); 1 done, 0 failed',
    })
    await flushPromises()
    expect(wrapper.find('[data-testid=job-progress]').text()).toContain('B.NEF (2/4)')
    const cancel = vi.spyOn(jobs, 'cancel').mockResolvedValue({})
    await btn('Cancel').trigger('click')
    expect(cancel).toHaveBeenCalledWith('j1')
    jobs.upsert({
      id: 'j1',
      kind: 'download_all',
      status: 'completed',
      progress: 1,
      result: { downloaded: 3, skipped: 1, failed: 0 },
    })
    await flushPromises()
    expect(wrapper.find('[data-testid=job-result]').text()).toContain('Downloaded 3')
    expect(wrapper.find('[data-testid=job-result]').text()).toContain('skipped 1')
  })
})
