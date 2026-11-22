import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import LocalFiles from './LocalFiles.vue'
import { useFilesStore } from '@/stores/files'
import { useToastsStore } from '@/stores/toasts'
import { useCaptureStore } from '@/stores/capture'

const item = (n, extra = {}) => ({
  path: `a/${n}.jpg`,
  name: `${n}.jpg`,
  folder: 'a',
  size: 2048,
  modified: 1700000000,
  kind: 'image',
  has_thumbnail: true,
  ...extra,
})

let wrapper
const release = vi.fn()
function setup({ items = [item('one'), item('two'), item('three')], total } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const files = useFilesStore(pinia)
  vi.spyOn(files, 'load').mockImplementation(async (p = {}) => {
    files.query = { ...files.query, ...p }
  })
  files.items = items
  files.total = total ?? items.length
  vi.spyOn(files, 'acquireThumbnail').mockResolvedValue({ url: 'blob:x', release })
  const toasts = useToastsStore(pinia)
  vi.spyOn(toasts, 'error')
  vi.spyOn(toasts, 'success')
  wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
  return { files, toasts, pinia }
}
const btn = (text) => wrapper.findAll('button').find((b) => b.text().includes(text))
const confirmClick = async (b) => {
  await b.trigger('click')
  await b.trigger('click')
  await flushPromises()
}

beforeEach(() => {
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      observe() {}
      disconnect() {}
    },
  )
})
afterEach(() => {
  wrapper?.unmount()
  vi.unstubAllGlobals()
  document.body.innerHTML = ''
})

describe('LocalFiles', () => {
  it('loads on mount and renders tiles', async () => {
    const { files } = setup()
    await flushPromises()
    expect(files.load).toHaveBeenCalled()
    expect(wrapper.findAll('[data-testid=grid] li')).toHaveLength(3)
    expect(wrapper.text()).toContain('one.jpg')
    expect(wrapper.text()).toContain('3 files')
  })

  it('does not fetch thumbnails for off-screen tiles (IntersectionObserver)', async () => {
    const { files } = setup()
    await flushPromises()
    expect(files.acquireThumbnail).not.toHaveBeenCalled()
  })

  it('failed thumbnail shows the placeholder and the grid still renders', async () => {
    const { files, pinia } = setup()
    files.acquireThumbnail.mockRejectedValueOnce(new Error('boom'))
    // fall back to eager loading when no IntersectionObserver
    vi.stubGlobal('IntersectionObserver', undefined)
    wrapper.unmount()
    wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(wrapper.findAll('[data-testid=thumb-placeholder]')).toHaveLength(1)
    expect(wrapper.findAll('[data-testid=grid] li')).toHaveLength(3)
    expect(wrapper.findAll('img')).toHaveLength(2)
  })

  it('unsupported thumbnails use the placeholder without fetching', async () => {
    const { files, pinia } = setup({ items: [item('x', { has_thumbnail: false })] })
    vi.stubGlobal('IntersectionObserver', undefined)
    wrapper.unmount()
    wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(files.acquireThumbnail).not.toHaveBeenCalled()
    expect(wrapper.find('[data-testid=thumb-placeholder]').exists()).toBe(true)
  })

  it('pagination and filters call the store with the right query', async () => {
    const { files } = setup({ total: 120 })
    await flushPromises()
    files.load.mockClear()
    await btn('Next').trigger('click')
    expect(files.load).toHaveBeenLastCalledWith({ page: 2 })
    await btn('RAW').trigger('click')
    expect(files.load).toHaveBeenLastCalledWith({ kind: 'raw', page: 1 })
    await wrapper.find('select').setValue('oldest')
    expect(files.load).toHaveBeenLastCalledWith({ sort: 'oldest', page: 1 })
  })

  it('shows folders and navigates into one', async () => {
    const { files } = setup()
    files.folders = [{ name: 'timelapse-1', path: 'timelapse-1' }]
    await flushPromises()
    await btn('timelapse-1').trigger('click')
    expect(files.load).toHaveBeenLastCalledWith({ folder: 'timelapse-1', page: 1 })
  })

  it('refreshes when a capture completes', async () => {
    const { files, pinia } = setup()
    await flushPromises()
    files.load.mockClear()
    useCaptureStore(pinia).lastCapture = { files: [] }
    await flushPromises()
    expect(files.load).toHaveBeenCalledTimes(1)
  })

  it('bulk delete aggregates failures into a single toast', async () => {
    const { files, toasts } = setup()
    vi.spyOn(files, 'remove').mockImplementation(async (p) => {
      if (p !== 'a/two.jpg') throw new Error('locked')
      files.items = files.items.filter((f) => f.path !== p)
    })
    await flushPromises()
    for (const cb of wrapper.findAll('input[type=checkbox]')) await cb.setValue(true)
    await confirmClick(btn('Delete selected'))
    expect(files.remove).toHaveBeenCalledTimes(3)
    expect(toasts.error).toHaveBeenCalledTimes(1)
    expect(toasts.error.mock.calls[0][0]).toMatch(/2 of 3/)
    expect(toasts.error.mock.calls[0][0]).toMatch(/locked/)
  })

  it('lightbox: arrow keys navigate, delete success and failure are visible', async () => {
    const { files, toasts } = setup()
    await flushPromises()
    await wrapper.find('button[aria-label="Open one.jpg"]').trigger('click')
    await flushPromises()
    const title = () => document.body.textContent
    expect(title()).toContain('a/one.jpg')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await flushPromises()
    expect(title()).toContain('a/two.jpg')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await flushPromises()
    expect(title()).toContain('a/one.jpg')

    const del = () =>
      [...document.body.querySelectorAll('button')].find(
        (b) => b.textContent.trim() === 'Delete' || b.textContent.includes('Confirm?'),
      )
    vi.spyOn(files, 'remove').mockRejectedValueOnce(new Error('nope'))
    del().click()
    await flushPromises()
    del().click()
    await flushPromises()
    expect(toasts.error).toHaveBeenCalledTimes(1)
    expect(toasts.error.mock.calls[0][0]).toMatch(/nope/)

    files.remove.mockImplementationOnce(async (p) => {
      files.items = files.items.filter((f) => f.path !== p)
    })
    del().click()
    await flushPromises()
    del().click()
    await flushPromises()
    expect(toasts.success).toHaveBeenCalledWith('File deleted')
  })

  it('releases its own thumbnail references on unmount and never clears the shared cache', async () => {
    const { files, pinia } = setup()
    files.clearThumbnails = vi.fn()
    vi.stubGlobal('IntersectionObserver', undefined)
    wrapper.unmount()
    release.mockClear()
    wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(release).not.toHaveBeenCalled()
    wrapper.unmount()
    expect(release).toHaveBeenCalledTimes(3)
    expect(files.clearThumbnails).not.toHaveBeenCalled()
    wrapper = null
  })

  it('shows an empty state and an inline retry on load failure', async () => {
    const { files, toasts, pinia } = setup({ items: [] })
    files.load.mockRejectedValueOnce(new Error('down'))
    wrapper.unmount()
    wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
    await flushPromises()
    expect(toasts.error).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Could not load files')
    await btn('Retry').trigger('click')
    expect(files.load).toHaveBeenCalledTimes(3)
  })
})
