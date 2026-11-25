import { describe, it, expect, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createTestingPinia } from '@pinia/testing'
import { ApiError } from '@/api'
import SettingsView from '@/views/SettingsView.vue'
import { useConfigStore } from '@/stores/config'
import { useToastsStore } from '@/stores/toasts'
import { useAuthStore } from '@/stores/auth'
import { useCameraAdminStore } from '@/stores/cameraAdmin'
import { useCameraStore } from '@/stores/camera'
import { routeQuery } from '@/components/shell/useTabs'
import { useLayoutMode } from '@/composables/useLayoutMode'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

const schema = {
  $defs: {
    Camera: {
      title: 'CameraConfig',
      type: 'object',
      properties: {
        download_photos: { type: 'boolean', title: 'Download photos' },
        filename_prefix: { anyOf: [{ type: 'string', maxLength: 40 }, { type: 'null' }] },
        keep_card_copy: { type: 'boolean', title: 'Keep a copy' },
      },
    },
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
    camera: { $ref: '#/$defs/Camera' },
    video: { $ref: '#/$defs/Video' },
    cors_origins: { type: 'array', items: { type: 'string' }, title: 'Cors origins' },
    timezone: { anyOf: [{ type: 'string', maxLength: 64 }, { type: 'null' }], title: 'Time zone' },
    demo_camera: { type: 'boolean' },
    api_key_set: { type: 'boolean', readOnly: true },
  },
}
const cfg = () => ({
  camera: { download_photos: true, filename_prefix: null, keep_card_copy: true },
  video: { crf: 23, codec: 'a' },
  cors_origins: [],
  timezone: null,
  demo_camera: false,
  api_key_set: false,
})

async function setup({ target = null } = {}) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const config = useConfigStore()
  config.fetch = vi.fn(async () => (config.config = cfg()))
  config.fetchSchema = vi.fn(async () => (config.schema = schema))
  const auth = useAuthStore()
  useCameraStore().connected = !!target
  const admin = useCameraAdminStore()
  admin.target = target
  admin.fetchTarget = vi.fn().mockResolvedValue()
  auth.fetchInfo = vi.fn(
    async () =>
      (auth.info = {
        version: '1.2.3',
        backend: 'demo',
        ffmpeg_available: true,
        libgphoto2_version: '2.5.31',
        output_free_bytes: 2048,
        auth_enabled: false,
      }),
  )
  const w = mount(SettingsView, { global: { plugins: [pinia] } })
  await flushPromises()
  return { w, config, auth, admin }
}

describe('SettingsView', () => {
  beforeEach(() => localStorage.clear())

  it('renders fields from the schema and About info', async () => {
    const { w } = await setup()
    expect(w.find('[data-field="crf"]').exists()).toBe(true)
    expect(w.find('[data-field="codec"]').exists()).toBe(true)
    expect(w.find('[data-field="cors_origins"]').exists()).toBe(true)
    expect(w.find('[data-test="version"]').text()).toBe('1.2.3')
    expect(w.find('[data-test="backend"]').text()).toBe('Demo camera')
    expect(w.find('[data-test="ffmpeg"]').text()).toBe('Available')
    expect(w.find('[data-test="libgphoto2"]').text()).toBe('2.5.31')
    expect(w.find('[data-test="key-status"]').text()).toBe('Not set')
  })

  it('saves the time zone and offers the browser zone', async () => {
    const { w, config } = await setup()
    config.patch = vi.fn(async () => config.config)
    await w.find('[data-test="timezone"] select').setValue('Europe/Paris')
    await w.find('[data-test="save"]').trigger('click')
    expect(config.patch).toHaveBeenCalledWith({ timezone: 'Europe/Paris' })
    expect(w.find('[data-field="timezone"]').text()).toContain('photo and session names')
  })

  it('shows the prefix example and saves it', async () => {
    const { w, config } = await setup()
    config.patch = vi.fn(async () => config.config)
    await w.find('[data-test="filename-prefix"] input').setValue('my wedding!')
    expect(w.find('[data-test="prefix-example"]').text()).toContain('my-wedding-')
    await w.find('[data-test="save"]').trigger('click')
    expect(config.patch).toHaveBeenCalledWith({ camera: { filename_prefix: 'my wedding!' } })
  })

  it('turning downloads off locks the target, dims the copy rows and drops the example', async () => {
    const { w } = await setup()
    await w.find('[data-test="download-photos"]').trigger('click')
    expect(w.find('[data-test="target-locked"]').text()).toContain('Locked to memory card')
    expect(w.find('[data-test="camera-target"] select').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="filename-prefix"] input').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="photo-location"] select').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="prefix-unused"]').text()).toContain('Not used while photos stay')
    expect(w.find('[data-test="prefix-example"]').exists()).toBe(false)
  })

  it('switches a RAM target to the card before turning downloads off', async () => {
    const { w, admin } = await setup({
      target: { value: 'Internal RAM', choices: ['Internal RAM', 'Memory card'] },
    })
    admin.setTarget = vi.fn(async (v) => (admin.target = { ...admin.target, value: v }))
    await w.find('[data-test="download-photos"]').trigger('click')
    await flushPromises()
    expect(admin.setTarget).toHaveBeenCalledWith('Memory card')
    expect(w.find('[data-test="target-locked"]').exists()).toBe(true)
  })

  it('follows a server-side config change without showing unsaved changes', async () => {
    const { w, config } = await setup()
    config.config = { ...cfg(), video: { crf: 18, codec: 'b' } }
    await flushPromises()
    expect(w.find('[data-test="savebar"]').exists()).toBe(false)
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
    expect(w.find('[data-test="savebar"]').exists()).toBe(false)
    const input = w.find('[data-field="crf"] input')
    await input.setValue('20')
    expect(w.find('[data-field="crf"]').attributes('data-dirty')).toBeDefined()
    expect(w.find('[data-field="crf"] [aria-label="Unsaved change"]').exists()).toBe(true)
    expect(w.find('[data-test="savebar"]').text()).toContain('1 unsaved change')
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
    config.restartRequired = ['video.crf']
    config.patch = vi.fn(async () => {
      throw new ApiError({ code: 'X', status: 500, message: 'boom' })
    })
    await w.vm.$nextTick()
    expect(w.find('[data-test="restart"]').text()).toContain('Video › Crf')
    expect(w.find('[data-test="restart"]').text()).not.toContain('video.crf')
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
    config.onChanged({ config: cfg(), restart_required: ['video.crf'] })
    config.onChanged({ config: cfg(), restart_required: [] })
    await w.vm.$nextTick()
    expect(w.find('[data-test="restart"]').text()).toContain('Video › Crf')
    await w.find('[data-test="dismiss-restart"]').trigger('click')
    expect(w.find('[data-test="restart"]').exists()).toBe(false)
    config.resetChanged = ['video.crf']
    await w.vm.$nextTick()
    expect(w.find('[data-test="reset-changed"]').text()).toContain('Video › Crf')
    expect(w.find('[data-test="reset-changed"]').text()).not.toContain('video.crf')
    expect(w.text()).toContain('demo camera')
  })

  it('shows the Display and Capture sections and the camera clock row', async () => {
    const { w } = await setup()
    expect(w.find('[data-section="display"]').text()).toContain('Layout')
    await w.find('[data-test="layout"] button:last-child').trigger('click')
    expect(localStorage.getItem('layout')).toBe('touch')
    expect(document.documentElement.dataset.layout).toBe('touch')
    expect(w.find('[data-section="capture"]').text()).toContain('Camera saves to')
    expect(w.find('[data-test="target-reason"]').text()).toContain('Connect the camera')
    expect(w.find('[data-field="camera-clock"]').exists()).toBe(true)
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

  it('puts expert fields (CRF) in a closed Advanced disclosure that opens for unsaved edits', async () => {
    const { w } = await setup()
    const adv = w.find('[data-test="advanced"]')
    expect(adv.attributes('open')).toBeUndefined()
    expect(adv.find('[data-field="crf"]').exists()).toBe(true)
    expect(w.find('[data-section="video"] [data-field="crf"]').exists()).toBe(false)
    expect(w.find('[data-section="video"] [data-field="codec"]').exists()).toBe(true)
    await adv.find('[data-field="crf"] input').setValue('30')
    expect(w.find('[data-test="advanced"]').attributes('open')).toBeDefined()
  })

  it('lists the sections as chips and scrolls to the chosen one', async () => {
    const { w } = await setup()
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    const chips = w
      .findAll('[data-test="section-index"] button')
      .map((b) => b.attributes('data-chip'))
    expect(chips).toEqual(
      expect.arrayContaining(['display', 'capture', 'storage', 'api-key', 'about']),
    )
    await w.find('[data-chip="storage"]').trigger('click')
    expect(scroll).toHaveBeenCalledTimes(1)
    expect(scroll.mock.contexts[0].dataset.section).toBe('storage')
  })

  it('follows a #/settings?section= deep link', async () => {
    const { w } = await setup()
    const scroll = vi.fn()
    Element.prototype.scrollIntoView = scroll
    routeQuery.value = { section: 'api-key' }
    await flushPromises()
    expect(scroll.mock.contexts[0].dataset.section).toBe('api-key')
    routeQuery.value = {}
    w.unmount()
  })

  it('hides the keyboard hints setting in the touch layout', async () => {
    useLayoutMode().setPref('desktop')
    const { w } = await setup()
    expect(w.find('[data-test="hints"]').exists()).toBe(true)
    useLayoutMode().setPref('touch')
    await nextTick()
    expect(w.find('[data-test="hints"]').exists()).toBe(false)
    useLayoutMode().setPref('auto')
  })

  it('renames the photo copy target to Download to storage', async () => {
    const { w } = await setup()
    expect(w.find('[data-section="capture"]').text()).toContain('Download to storage')
  })
})
