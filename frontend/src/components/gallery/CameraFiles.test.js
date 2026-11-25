import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import CameraFiles from './CameraFiles.vue'
import { useCameraStore } from '@/stores/camera'
import { useCameraFilesStore } from '@/stores/cameraFiles'
import { useJobsStore } from '@/stores/jobs'
import { useToastsStore } from '@/stores/toasts'
import { useStorageStore } from '@/stores/storage'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: {
    downloadCameraFile: vi.fn().mockResolvedValue(new Blob(['x'])),
    getCameraThumbnail: vi.fn().mockResolvedValue(new Blob(['t'])),
  },
  downloadBlob: vi.fn(),
}))

let wrapper
function setup({ connected = true, leasedBy = null, noTarget = false } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const storage = useStorageStore(pinia)
  storage.loaded = true
  storage.targetId = noTarget ? null : 'loc'
  vi.spyOn(storage, 'refresh').mockResolvedValue([])
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
  vi.spyOn(cf, 'loadFolders').mockImplementation(async (f) => ({
    folders:
      f === '/'
        ? [{ name: 'store_00010001', path: '/store_00010001' }]
        : [{ name: '100NCD', path: '/store_00010001/100NCD' }],
  }))
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
  })

  it('defaults to a flat listing of every file and never shows the store_ level', async () => {
    const { cf } = setup()
    await flushPromises()
    expect(cf.loadFiles).toHaveBeenCalledWith({ folder: '/', recursive: true, page: 1 })
    expect(wrapper.text()).not.toContain('store_')
    await btn('By folder').trigger('click')
    await flushPromises()
    // the lone store_ folder is stepped over: the first level shown is its content
    expect(cf.loadFiles).toHaveBeenLastCalledWith({ folder: '/store_00010001', page: 1 })
    expect(wrapper.find('[data-testid=card-folders]').text()).toContain('100NCD')
    expect(wrapper.text()).not.toContain('store_00010001')
    await wrapper.find('[data-testid=card-folders] button').trigger('click')
    await flushPromises()
    const crumbs = wrapper.find('nav[aria-label="Card folder"]').text()
    expect(crumbs).toContain('100NCD')
    expect(crumbs).not.toContain('store_')
  })

  it('labels several stores by the camera-reported card label, never store_*', async () => {
    const { cam, cf } = setup()
    cam.storage = {
      cards: [
        { label: 'XQD', base_dir: '/store_00010001', capacity_kb: 1, free_kb: 1 },
        { label: '', base_dir: '/store_00020001', capacity_kb: 1, free_kb: 1 },
      ],
    }
    cf.loadFolders.mockImplementation(async (f) => ({
      folders:
        f === '/'
          ? [
              { name: 'store_00010001', path: '/store_00010001' },
              { name: 'store_00020001', path: '/store_00020001' },
            ]
          : [],
    }))
    await flushPromises()
    await btn('By folder').trigger('click')
    await flushPromises()
    const folders = wrapper.find('[data-testid=card-folders]').text()
    expect(folders).toContain('XQD')
    expect(folders).toContain('Card 2')
    expect(wrapper.text()).not.toContain('store_')
  })

  it('shows the camera preview as the thumbnail', async () => {
    vi.stubGlobal(
      'IntersectionObserver',
      class {
        constructor(cb) {
          this.cb = cb
        }
        observe() {
          this.cb([{ isIntersecting: true }])
        }
        disconnect() {}
      },
    )
    setup()
    await flushPromises()
    const { api } = await import('@/api')
    expect(api.getCameraThumbnail).toHaveBeenCalledWith({
      query: { folder: '/100NCD', name: 'A.NEF' },
      parseAs: 'blob',
    })
    vi.unstubAllGlobals()
  })

  it('Download all is disabled with the reason and a settings button when no storage is chosen', async () => {
    setup({ noTarget: true })
    await flushPromises()
    expect(wrapper.find('[data-testid=download-all]').attributes('disabled')).toBeDefined()
    expect(wrapper.find('[data-test=no-target]').text()).toContain('Settings › Storage')
    expect(wrapper.find('[data-test=open-storage]').exists()).toBe(true)
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
    await wrapper.find('[data-testid=download-options]').trigger('click')
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
