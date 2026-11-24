import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import LocalFiles from './LocalFiles.vue'
import { useFilesStore } from '@/stores/files'
import { useStorageStore } from '@/stores/storage'
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
  useStorageStore(pinia).targetId = 'loc'
  files.items = items
  files.total = total ?? items.length
  vi.spyOn(files, 'loadCounts').mockResolvedValue()
  files.counts = { photos: 2, videos: 1 }
  vi.spyOn(files, 'acquireThumbnail').mockResolvedValue({ url: 'blob:x', release })
  const toasts = useToastsStore(pinia)
  vi.spyOn(toasts, 'error')
  vi.spyOn(toasts, 'success')
  wrapper = mount(LocalFiles, { global: { plugins: [pinia] }, attachTo: document.body })
  return { files, toasts, pinia }
}
const btn = (text) => wrapper.findAll('button').find((b) => b.text().includes(text))

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
    expect(wrapper.text()).toContain('Photos 2')
    expect(wrapper.text()).toContain('Videos 1')
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
    await btn('Videos').trigger('click')
    expect(files.load).toHaveBeenLastCalledWith({ kind: 'video', page: 1 })
    await btn('Photos').trigger('click')
    expect(files.load).toHaveBeenLastCalledWith({ kind: 'all', page: 1 })
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
    await btn('Select').trigger('click')
    await btn('Select all').trigger('click')
    await btn('Delete').trigger('click')
    await btn('Delete 3 items').trigger('click')
    await flushPromises()
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
    const pos = () =>
      document.body.querySelector('[data-testid=lightbox-position]').textContent.trim()
    expect(pos()).toBe('1 of 3')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await flushPromises()
    expect(pos()).toBe('2 of 3')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    await flushPromises()
    expect(pos()).toBe('1 of 3')

    const del = () =>
      [...document.body.querySelectorAll('button')].find(
        (b) => b.textContent.includes('Delete') && b.closest('[data-testid=lightbox]'),
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

  it('select mode: tiles toggle, Select all and Clear, delete asks inline first', async () => {
    const { files } = setup()
    vi.spyOn(files, 'remove').mockResolvedValue()
    await flushPromises()
    await btn('Select').trigger('click')
    await wrapper.find('button[aria-label="Select one.jpg"]').trigger('click')
    expect(wrapper.find('[data-testid=select-bar]').text()).toContain('1 selected')
    await btn('Select all').trigger('click')
    expect(wrapper.find('[data-testid=select-bar]').text()).toContain('3 selected')
    expect(btn('Clear')).toBeTruthy()
    await btn('Delete').trigger('click')
    expect(files.remove).not.toHaveBeenCalled()
    expect(btn('Delete 3 items')).toBeTruthy()
    await btn('Keep').trigger('click')
    expect(btn('Delete 3 items')).toBeUndefined()
    await btn('Clear').trigger('click')
    expect(wrapper.find('[data-testid=select-bar]').text()).toContain('0 selected')
  })

  it('long-press with touch starts selecting; a mouse press does not', async () => {
    vi.useFakeTimers()
    setup()
    const tile = () => wrapper.find('button[aria-label="Open one.jpg"]')
    await tile().trigger('pointerdown', { pointerType: 'mouse' })
    vi.advanceTimersByTime(600)
    expect(wrapper.find('[data-testid=select-bar]').exists()).toBe(false)
    await tile().trigger('pointerup')
    await tile().trigger('pointerdown', { pointerType: 'touch' })
    vi.advanceTimersByTime(600)
    await wrapper.vm.$nextTick()
    expect(wrapper.find('[data-testid=select-bar]').text()).toContain('1 selected')
    vi.useRealTimers()
  })

  it('Photos hides videos on the page; tiles show kind badges', async () => {
    setup({ items: [item('a'), item('b', { kind: 'raw' }), item('c', { kind: 'video' })] })
    await flushPromises()
    const badges = wrapper.findAll('[data-testid=grid] li').map((li) => li.text())
    expect(badges.join(' ')).toMatch(/JPEG/)
    expect(badges.join(' ')).toMatch(/RAW/)
    expect(badges.join(' ')).toMatch(/Video/)
    await btn('Photos').trigger('click')
    expect(wrapper.findAll('[data-testid=grid] li')).toHaveLength(2)
  })

  it('lightbox: Escape closes, double-click zooms to 250%, filmstrip jumps', async () => {
    setup()
    await flushPromises()
    await wrapper.find('button[aria-label="Open one.jpg"]').trigger('click')
    await flushPromises()
    const q = (s) => document.body.querySelector(s)
    expect(q('[data-testid=lightbox-strip]').querySelectorAll('button')).toHaveLength(3)
    q('[data-testid=lightbox-strip]').querySelectorAll('button')[2].click()
    await flushPromises()
    expect(q('[data-testid=lightbox-position]').textContent.trim()).toBe('3 of 3')
    q('[data-testid=lightbox-stage]').dispatchEvent(new MouseEvent('dblclick', { bubbles: true }))
    await flushPromises()
    expect(q('[data-testid=lightbox-zoom]').textContent).toBe('250%')
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    await flushPromises()
    expect(q('[data-testid=lightbox]')).toBeNull()
  })
})
