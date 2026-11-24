import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import SessionsPanel from './SessionsPanel.vue'
import RenderDialog from './RenderDialog.vue'
import { useSessionsStore } from '@/stores/sessions'
import { useVideosStore } from '@/stores/videos'

const session = (over = {}) => ({
  id: 's1',
  name: 'Harbour',
  status: 'completed',
  created: '2026-01-02T10:00:00Z',
  planned_frames: 100,
  frames_captured: 98,
  frames_failed: 2,
  video_count: 1,
  ...over,
})
const stubs = { UiModal: { template: '<div><slot /><slot name="footer" /></div>' } }

function setup(items = [session()], detail = null) {
  const pinia = createTestingPinia({ createSpy: vi.fn })
  const sessions = useSessionsStore()
  sessions.items = items
  sessions.detail = detail
  sessions.fetch.mockResolvedValue({})
  sessions.fetchOne.mockResolvedValue(detail)
  const w = mount(SessionsPanel, { global: { plugins: [pinia], stubs } })
  return { w, sessions, videos: useVideosStore() }
}
const btn = (w, text) => w.findAll('button').find((b) => b.text().includes(text))

describe('SessionsPanel', () => {
  it('lists name, shots, date and a status label', async () => {
    const { w } = setup()
    await flushPromises()
    const t = w.find('[data-test="session"]').text()
    expect(t).toContain('Harbour')
    expect(t).toContain('98 of 100 shots')
    expect(t).toContain('2 failed')
    expect(t).toContain('Completed')
  })

  it('deleting a session asks inline first, with a Keep way out', async () => {
    const { w, sessions } = setup()
    await btn(w, 'Delete').trigger('click')
    expect(sessions.remove).not.toHaveBeenCalled()
    await btn(w, 'Keep').trigger('click')
    expect(btn(w, 'Delete session')).toBeUndefined()
    await btn(w, 'Delete').trigger('click')
    await btn(w, 'Delete session').trigger('click')
    expect(sessions.remove).toHaveBeenCalledWith('s1')
  })

  it('renames inline and saves with Enter', async () => {
    const { w, sessions } = setup()
    await btn(w, 'Rename').trigger('click')
    const input = w.find('[data-rename] input')
    await input.setValue('Dusk')
    await input.trigger('keydown', { key: 'Enter' })
    await flushPromises()
    expect(sessions.rename).toHaveBeenCalledWith('s1', 'Dusk')
  })

  it('shows a session reason instead of silently disabling Delete while running', () => {
    const { w } = setup([session({ status: 'running' })])
    expect(w.text()).toContain('Stop the time-lapse before deleting it.')
  })

  it('expands to videos with Play, Download and an inline Delete confirm', async () => {
    const detail = {
      id: 's1',
      videos: [{ name: 'out.mp4', duration_s: 12, codec: 'libx264' }],
    }
    const { w, videos } = setup([session()], detail)
    await w.find('button[aria-expanded]').trigger('click')
    await flushPromises()
    const row = w.find('[data-test="video"]')
    expect(row.text()).toContain('out.mp4')
    expect(row.text()).toContain('H.264')
    await btn(row, 'Download').trigger('click')
    expect(videos.download).toHaveBeenCalledWith('s1', 'out.mp4')
    await btn(row, 'Delete').trigger('click')
    expect(videos.remove).not.toHaveBeenCalled()
    await btn(row, 'Delete video').trigger('click')
    await flushPromises()
    expect(videos.remove).toHaveBeenCalledWith('s1', 'out.mp4')
  })
})

describe('RenderDialog options', () => {
  function dialog(detail = null) {
    const pinia = createTestingPinia({ createSpy: vi.fn })
    const sessions = useSessionsStore()
    sessions.detail = detail
    sessions.fetchOne.mockResolvedValue(detail)
    return mount(RenderDialog, {
      props: { open: true, session: { id: 's1', name: 'Harbour', frames_captured: 240 } },
      global: { plugins: [pinia], stubs },
    })
  }

  it('shows the video length for the chosen frame rate and disables CRF with a quality', async () => {
    const w = dialog()
    await flushPromises()
    expect(w.find('[data-test="render-length"]').text()).toContain('240 frames')
    expect(w.find('[data-test="render-length"]').text()).toContain('10 s')
    const labels = w.findAll('label').map((l) => l.text())
    expect(labels).toEqual(
      expect.arrayContaining([
        'Frame rate',
        'Resolution',
        'Codec',
        'Quality',
        'CRF',
        'Encoder preset',
      ]),
    )
    expect(labels).not.toContain('Bracket frame')
    const crf = () => w.findAll('input').find((i) => i.attributes('disabled') !== undefined)
    expect(crf()).toBeUndefined()
    const quality = w.findAll('select')[2]
    await quality.setValue('high')
    expect(crf()).toBeDefined()
    expect(w.text()).toContain('Set by the quality choice')
  })

  it('offers Bracket frame only for bracketed sessions and counts bracket sets as frames', async () => {
    const w = dialog({
      id: 's1',
      config: { bracketing: { mode: 'steps', steps: [{}, {}, {}] } },
    })
    await flushPromises()
    expect(w.findAll('label').map((l) => l.text())).toContain('Bracket frame')
    expect(w.find('[data-test="render-length"]').text()).toContain('80 frames')
  })
})
