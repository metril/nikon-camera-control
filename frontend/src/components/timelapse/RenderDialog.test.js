import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import RenderDialog from './RenderDialog.vue'
import { useVideosStore } from '@/stores/videos'
import { useJobsStore } from '@/stores/jobs'
import { useConfigStore } from '@/stores/config'
import { flushPromises } from '@vue/test-utils'

describe('RenderDialog', () => {
  it('submits the render payload and shows live job progress with cancel', async () => {
    const pinia = createTestingPinia({ createSpy: vi.fn })
    const videos = useVideosStore()
    const jobs = useJobsStore()
    videos.render.mockResolvedValue({
      id: 'j1',
      status: 'running',
      progress: 0.25,
      message: 'encoding',
    })
    jobs.upsert.mockImplementation((j) => (jobs.byId = { ...jobs.byId, [j.id]: j }))
    const w = mount(RenderDialog, {
      props: { open: true, session: { id: 's1', name: 'Sky' } },
      global: {
        plugins: [pinia],
        stubs: { UiModal: { template: '<div><slot /><slot name="footer" /></div>' } },
      },
    })
    await w
      .findAll('button')
      .find((b) => b.text() === 'Render')
      .trigger('click')
    await vi.waitFor(() => expect(videos.render).toHaveBeenCalled())
    expect(videos.render).toHaveBeenCalledWith('s1', {
      codec: 'h264',
      resolution: 'source',
      bracket_frame: 'middle',
      deflicker: false,
      fps: 24,
      crf: 20,
    })
    await w.vm.$nextTick()
    expect(w.text()).toContain('encoding')
    jobs.byId = { j1: { id: 'j1', status: 'running', progress: 0.5, message: 'encoding 50%' } }
    await w.vm.$nextTick()
    expect(w.text()).toContain('50%')
    await w
      .findAll('button')
      .find((b) => b.text() === 'Cancel render')
      .trigger('click')
    expect(jobs.cancel).toHaveBeenCalledWith('j1')
  })

  it('initialises the form from the config video section, fetching it when not loaded', async () => {
    const pinia = createTestingPinia({ createSpy: vi.fn })
    const config = useConfigStore()
    const videos = useVideosStore()
    videos.render.mockResolvedValue({ id: 'j2', status: 'running' })
    useJobsStore().upsert.mockImplementation(() => {})
    config.fetch.mockImplementation(async () => {
      config.config = { video: { codec: 'libx265', fps: 30, crf: 18, preset: 'slow' } }
    })
    const w = mount(RenderDialog, {
      props: { open: true, session: { id: 's1', name: 'Sky' } },
      global: {
        plugins: [pinia],
        stubs: { UiModal: { template: '<div><slot /><slot name="footer" /></div>' } },
      },
    })
    await flushPromises()
    expect(config.fetch).toHaveBeenCalled()
    await w
      .findAll('button')
      .find((b) => b.text() === 'Render')
      .trigger('click')
    await vi.waitFor(() => expect(videos.render).toHaveBeenCalled())
    expect(videos.render).toHaveBeenCalledWith(
      's1',
      expect.objectContaining({ codec: 'h265', fps: 30, crf: 18, preset: 'slow' }),
    )
  })
})
