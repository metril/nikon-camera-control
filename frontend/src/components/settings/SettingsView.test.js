import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import { ApiError } from '@/api'
import SettingsView from '@/views/SettingsView.vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { useAuthStore } from '@/stores/auth'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

const schema = {
  $defs: {
    Video: {
      title: 'VideoConfig',
      type: 'object',
      properties: {
        crf: { type: 'integer', minimum: 0, maximum: 51, title: 'Crf', description: 'quality' },
        codec: { enum: ['a', 'b'], type: 'string', title: 'Codec' },
      },
    },
  },
  properties: {
    video: { $ref: '#/$defs/Video' },
    cors_origins: { type: 'array', items: { type: 'string' }, title: 'Cors origins' },
    demo_camera: { type: 'boolean' },
    api_key_set: { type: 'boolean', readOnly: true },
  },
}
const cfg = () => ({
  video: { crf: 23, codec: 'a' },
  cors_origins: [],
  demo_camera: false,
  api_key_set: false,
})

async function setup() {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const config = useConfigStore()
  config.fetch = vi.fn(async () => (config.config = cfg()))
  config.fetchSchema = vi.fn(async () => (config.schema = schema))
  const auth = useAuthStore()
  auth.fetchInfo = vi.fn(
    async () =>
      (auth.info = {
        version: '1.2.3',
        backend: 'demo',
        ffmpeg_available: true,
        output_free_bytes: 2048,
        auth_enabled: false,
      }),
  )
  const w = mount(SettingsView, { global: { plugins: [pinia] } })
  await flushPromises()
  return { w, config, auth }
}

describe('SettingsView', () => {
  beforeEach(() => localStorage.clear())

  it('renders fields from the schema and About info', async () => {
    const { w } = await setup()
    expect(w.find('[data-field="crf"]').exists()).toBe(true)
    expect(w.find('[data-field="codec"]').exists()).toBe(true)
    expect(w.find('[data-field="cors_origins"]').exists()).toBe(true)
    expect(w.find('[data-test="version"]').text()).toBe('1.2.3')
    expect(w.find('[data-test="backend"]').text()).toBe('demo')
    expect(w.find('[data-test="key-status"]').text()).toBe('Not set')
  })

  it('follows a server-side config change without showing unsaved changes', async () => {
    const { w, config } = await setup()
    config.config = { ...cfg(), video: { crf: 18, codec: 'b' } }
    await flushPromises()
    expect(w.find('[data-test="save"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-field="crf"] input').element.value).toBe('18')
  })

  it('keeps unsaved edits when the server config changes', async () => {
    const { w, config } = await setup()
    await w.find('[data-field="crf"] input').setValue('30')
    config.config = { ...cfg(), video: { crf: 23, codec: 'b' } }
    await flushPromises()
    expect(w.find('[data-field="crf"] input').element.value).toBe('30')
  })

  it('saves only changed fields', async () => {
    const { w, config } = await setup()
    config.patch = vi.fn(async () => (config.config = { ...cfg(), video: { crf: 20, codec: 'a' } }))
    expect(w.find('[data-test="save"]').attributes('disabled')).toBeDefined()
    const input = w.find('[data-field="crf"] input')
    await input.setValue('20')
    expect(w.find('[data-field="crf"]').attributes('data-dirty')).toBeDefined()
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(config.patch).toHaveBeenCalledWith({ video: { crf: 20 } })
    expect(w.find('[data-field="crf"]').attributes('data-dirty')).toBeUndefined()
  })

  it('shows field-level errors from the 422 envelope', async () => {
    const { w, config } = await setup()
    config.patch = vi.fn(async () => {
      throw new ApiError({
        code: 'VALIDATION_ERROR',
        status: 422,
        message: 'bad',
        details: { errors: [{ loc: ['body', 'video', 'crf'], msg: 'must be <= 51' }] },
      })
    })
    await w.find('[data-field="crf"] input').setValue('20')
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-field="crf"] [data-test="field-error"]').text()).toBe('must be <= 51')
  })

  it('lists restart-required fields and toasts non-validation errors', async () => {
    const { w, config } = await setup()
    config.restartRequired = ['liveview.target_fps']
    config.patch = vi.fn(async () => {
      throw new ApiError({ code: 'X', status: 500, message: 'boom' })
    })
    await w.vm.$nextTick()
    expect(w.find('[data-test="restart"]').text()).toContain('liveview.target_fps')
    await w.find('[data-field="codec"] select').setValue('b')
    await w.find('[data-test="save"]').trigger('click')
    await flushPromises()
    expect(useToastsStore().items.at(-1).message).toBe('boom')
  })

  it('reset to defaults needs confirmation', async () => {
    const { w, config } = await setup()
    config.reset = vi.fn(async () => config.config)
    await w.find('[data-test="reset"]').trigger('click')
    expect(config.reset).not.toHaveBeenCalled()
    await w.find('[data-test="reset"]').trigger('click')
    expect(config.reset).toHaveBeenCalledTimes(1)
  })

  it('keeps the restart banner across later config changes, dismissable; shows reset changes and the demo warning', async () => {
    const { w, config } = await setup()
    config.onChanged({ config: cfg(), restart_required: ['liveview.target_fps'] })
    config.onChanged({ config: cfg(), restart_required: [] })
    await w.vm.$nextTick()
    expect(w.find('[data-test="restart"]').text()).toContain('liveview.target_fps')
    await w.find('[data-test="dismiss-restart"]').trigger('click')
    expect(w.find('[data-test="restart"]').exists()).toBe(false)
    config.resetChanged = ['video.crf']
    await w.vm.$nextTick()
    expect(w.find('[data-test="reset-changed"]').text()).toContain('video.crf')
    expect(w.text()).toContain('demo camera')
  })

  it('shows a generated key once and requires confirmation', async () => {
    const { w, config } = await setup()
    config.createApiKey = vi.fn(async () => 'secret-key-123')
    await w.find('[data-test="generate"]').trigger('click')
    await flushPromises()
    const body = document.body
    expect(body.querySelector('[data-test="new-key"]').textContent).toBe('secret-key-123')
    body.querySelector('[data-test="saved"]').click()
    await flushPromises()
    expect(body.querySelector('[data-test="new-key"]')).toBeNull()
    w.unmount()
  })
})
