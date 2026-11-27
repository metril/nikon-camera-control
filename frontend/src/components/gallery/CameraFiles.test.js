import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest'
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
    getCameraPreview: vi.fn().mockResolvedValue(new Blob(['p'])),
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

const FILES = ['A', 'B', 'C'].map((n, i) => ({
  folder: '/100NCD',
  name: `${n}.JPG`,
  size: 1000 + i,
  mtime: 1700000000 + i,
  type: 'jpeg',
  downloaded: false,
}))
const lightbox = () => document.body.querySelector('[data-testid=lightbox]')
const position = () =>
  document.body.querySelector('[data-testid=lightbox-position]').textContent.trim()

describe('CameraFiles viewer', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
  })
  function withFiles() {
    const ctx = setup()
    ctx.cf.items = FILES.slice(0, 2)
    ctx.cf.total = 3
    ctx.cf.query = { ...ctx.cf.query, page: 1, limit: 2 }
    ctx.cf.peekPage = vi.fn(async () => ({ items: FILES.slice(2), total: 3, page: 2, limit: 2 }))
    return ctx
  }

  it('opens from the thumbnail and the file name, with file info and a position', async () => {
    withFiles()
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[1].trigger('click')
    await flushPromises()
    expect(lightbox()).not.toBeNull()
    expect(position()).toBe('2 of 3')
    expect(lightbox().textContent).toContain('B.JPG')
    document.body.querySelector('[aria-label="Close viewer"]').click()
    await flushPromises()
    expect(lightbox()).toBeNull()
    await wrapper.findAll('[data-testid=card-file-open]')[0].trigger('click')
    await flushPromises()
    expect(position()).toBe('1 of 3')
  })

  it('next at the end of the page loads the next page from the listing', async () => {
    const { cf } = withFiles()
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[1].trigger('click')
    await flushPromises()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await flushPromises()
    expect(cf.peekPage).toHaveBeenCalledWith(2)
    expect(position()).toBe('3 of 3')
    expect(lightbox().textContent).toContain('C.JPG')
  })

  it('Download to storage starts a single-file job; Save to this device downloads in the browser', async () => {
    const { cf } = withFiles()
    cf.downloadAll = vi.fn().mockResolvedValue({ id: 'j1', status: 'queued', kind: 'download_all' })
    cf.download = vi.fn().mockResolvedValue()
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[0].trigger('click')
    await flushPromises()
    document.body.querySelector('[data-testid=viewer-to-storage]').click()
    await flushPromises()
    expect(cf.downloadAll).toHaveBeenCalledWith(
      expect.objectContaining({ file: { folder: '/100NCD', name: 'A.JPG' }, only_new: false }),
    )
    document.body.querySelector('[aria-label="Save to this device"]').click()
    await flushPromises()
    expect(cf.download).toHaveBeenCalledWith('/100NCD', 'A.JPG')
  })

  it('deleting in the viewer confirms in-page, removes the file and moves on', async () => {
    const { cf } = withFiles()
    cf.remove = vi.fn(async (folder, name) => {
      cf.items = cf.items.filter((f) => f.name !== name)
    })
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[0].trigger('click')
    await flushPromises()
    const del = () =>
      [...lightbox().querySelectorAll('button')].find((b) => b.textContent.includes('Delete'))
    del().click()
    await flushPromises()
    expect(cf.remove).not.toHaveBeenCalled()
    ;[...lightbox().querySelectorAll('button')]
      .find((b) => b.textContent.includes('Delete?'))
      .click()
    await flushPromises()
    expect(cf.remove).toHaveBeenCalledWith('/100NCD', 'A.JPG')
    expect(lightbox().textContent).toContain('B.JPG')
  })
})

describe('CameraFiles viewer after a delete', () => {
  beforeEach(() => {
    URL.createObjectURL = vi.fn(() => 'blob:x')
    URL.revokeObjectURL = vi.fn()
  })
  const NAMES = ['A', 'B', 'C', 'D', 'E', 'F', 'G']
  // a server whose paging shifts when a file is deleted, like the real listing
  function withServer(startPage) {
    const server = NAMES.map((n, i) => ({ ...FILES[0], name: `${n}.JPG`, size: 10 + i, mtime: i }))
    const ctx = setup()
    const limit = 2
    const page = (p) => ({
      items: server.slice((p - 1) * limit, p * limit),
      total: server.length,
      page: p,
      limit,
    })
    ctx.cf.items = page(startPage).items
    ctx.cf.total = server.length
    ctx.cf.query = { ...ctx.cf.query, page: startPage, limit }
    ctx.cf.peekPage = vi.fn(async (p) => page(p))
    ctx.cf.remove = vi.fn(async (folder, name) => {
      server.splice(
        server.findIndex((f) => f.name === name),
        1,
      )
      ctx.cf.items = ctx.cf.items.filter((f) => f.name !== name)
      ctx.cf.total = server.length
    })
    return ctx
  }
  const del = async () => {
    ;[...lightbox().querySelectorAll('button')]
      .find((b) => b.textContent.includes('Delete'))
      .click()
    await flushPromises()
    ;[...lightbox().querySelectorAll('button')]
      .find((b) => b.textContent.includes('Delete?'))
      .click()
    await flushPromises()
  }
  const key = (k) => {
    window.dispatchEvent(new KeyboardEvent('keydown', { key: k }))
    return flushPromises()
  }
  const shown = () => lightbox().textContent

  it('next page after a delete does not skip a file', async () => {
    withServer(1)
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[0].trigger('click') // A
    await flushPromises()
    await key('ArrowRight') // B
    await del() // B deleted: A C D E F G on the server
    expect(shown()).toContain('C.JPG')
    expect(position()).toBe('2 of 6')
    await key('ArrowRight')
    expect(shown()).toContain('D.JPG')
    await key('ArrowRight')
    expect(shown()).toContain('E.JPG')
    await key('ArrowRight')
    expect(shown()).toContain('F.JPG')
    await key('ArrowRight')
    expect(shown()).toContain('G.JPG')
    expect(position()).toBe('6 of 6')
  })

  it('previous page after a delete shows each file once and keeps the counter right', async () => {
    withServer(3) // E F
    await flushPromises()
    await wrapper.findAll('[data-testid=card-thumb]')[1].trigger('click') // F
    await flushPromises()
    await del() // F deleted: A B C D E G, G is shown
    expect(shown()).toContain('G.JPG')
    expect(position()).toBe('6 of 6')
    const seen = []
    for (let i = 0; i < 5; i++) {
      await key('ArrowLeft')
      seen.push(position())
    }
    expect(seen).toEqual(['5 of 6', '4 of 6', '3 of 6', '2 of 6', '1 of 6'])
    expect(shown()).toContain('A.JPG')
    await key('ArrowRight')
    expect(shown()).toContain('B.JPG')
  })
})

describe('CameraFiles', () => {
  it('shows the running file count while a cold listing loads', async () => {
    const { cf } = setup()
    cf.items = []
    cf.total = 0
    cf.loading = true
    cf.listing = { count: 1234, done: false }
    await flushPromises()
    expect(wrapper.text()).toContain('Reading card… 1234 files')
  })

  it('sorts newest first by default and reloads page 1 on a new order', async () => {
    const { cf } = setup()
    await flushPromises()
    const sel = wrapper.find('select[id]')
    expect([...sel.element.options].map((o) => o.text)).toEqual(['Newest', 'Oldest', 'Name'])
    expect(sel.element.value).toBe('newest')
    await sel.setValue('oldest')
    expect(cf.loadFiles).toHaveBeenLastCalledWith({ order: 'oldest', page: 1 })
  })

  it('shows the load error verbatim with Retry and no duplicate toast', async () => {
    const { cf, toasts } = setup()
    cf.items = []
    cf.total = 0
    cf.loadFiles.mockImplementationOnce(async () => {
      cf.lastError = new Error('Could not get folder list')
      throw cf.lastError
    })
    await btn('By folder').trigger('click')
    await flushPromises()
    expect(wrapper.text()).toContain('Could not get folder list')
    expect(toasts.error).not.toHaveBeenCalled()
    cf.loadFiles.mockClear()
    await btn('Retry').trigger('click')
    expect(cf.loadFiles).toHaveBeenCalled()
  })

  it('shows a failed refresh verbatim above the list that is already there', async () => {
    const { cf } = setup()
    cf.loadFiles.mockImplementationOnce(async () => {
      cf.lastError = new Error('Camera busy')
      throw cf.lastError
    })
    wrapper.findComponent({ name: 'UiSelect' }).vm.$emit('update:modelValue', 'oldest')
    await flushPromises()
    expect(wrapper.find('[data-testid=load-error]').text()).toContain('Camera busy')
    expect(wrapper.find('[data-testid=card-files]').exists()).toBe(true)
  })

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

  it('selecting card files: Save to storage downloads exactly those files; Delete removes them in one request', async () => {
    const { cf } = setup()
    cf.items = FILES
    cf.total = 3
    cf.downloadAll = vi.fn().mockResolvedValue({ id: 'j9', status: 'queued', kind: 'download_all' })
    cf.removeMany = vi.fn().mockResolvedValue({
      deleted: [{ folder: '/100NCD', name: 'A.JPG' }],
      failed: [],
    })
    await flushPromises()
    await wrapper.find('[data-testid=select]').trigger('click')
    await wrapper.find('button[aria-label="Select A.JPG"]').trigger('click')
    await wrapper.find('button[aria-label="Select C.JPG"]').trigger('click')
    expect(wrapper.find('[data-testid=select-bar]').text()).toContain('2 selected')
    await btn('Save to storage').trigger('click')
    await flushPromises()
    expect(cf.downloadAll).toHaveBeenCalledWith({
      files: [
        { folder: '/100NCD', name: 'A.JPG' },
        { folder: '/100NCD', name: 'C.JPG' },
      ],
      only_new: false,
      delete_after: false,
    })
    await wrapper.find('[data-testid=select]').trigger('click')
    await wrapper.find('button[aria-label="Select A.JPG"]').trigger('click')
    await wrapper.find('[data-testid=delete]').trigger('click')
    await btn('Delete 1 item').trigger('click')
    await flushPromises()
    expect(cf.removeMany).toHaveBeenCalledWith([{ folder: '/100NCD', name: 'A.JPG' }])
  })
})
