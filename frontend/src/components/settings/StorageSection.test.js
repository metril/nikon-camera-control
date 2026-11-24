import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import StorageSection from './StorageSection.vue'
import StorageChip from '@/components/shell/StorageChip.vue'
import CaptureControls from '@/components/shoot/CaptureControls.vue'
import LocalFiles from '@/components/gallery/LocalFiles.vue'
import { useStorageStore } from '@/stores/storage'
import { useSessionsStore } from '@/stores/sessions'
import { useToastsStore } from '@/stores/toasts'
import { useCameraStore } from '@/stores/camera'
import { useFilesStore } from '@/stores/files'
import { useEventsStore } from '@/stores/events'
import { ApiError, api } from '@/api'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

const loc = (o) => ({
  id: 'usb-a',
  kind: 'usb',
  name: 'Card A',
  uuid: 'a',
  configured: true,
  present: true,
  mounted: false,
  supported: true,
  fstype: 'ext4',
  size: 1e9,
  free: 5e8,
  has_password: false,
  is_target: false,
  is_backup: false,
  auto_mount: true,
  ...o,
})

function setup(locations = [], targetId = null) {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const s = useStorageStore()
  s.refresh = vi.fn(async () => {})
  s.locations = locations
  s.targetId = targetId
  s.loaded = true
  return { pinia, s }
}
const mnt = (C, pinia) => mount(C, { global: { plugins: [pinia] } })

describe('StorageSection', () => {
  it('lists drives, flags unsupported ones and disables Mount', () => {
    const { pinia } = setup([
      loc({}),
      loc({ id: 'usb-b', name: 'Odd', supported: false, reason: 'no driver' }),
    ])
    const w = mnt(StorageSection, pinia)
    expect(w.text()).toContain('Card A')
    expect(w.text()).toContain('no driver')
    const mounts = w.findAll('[data-test="mount"]')
    expect(mounts[0].attributes('disabled')).toBeUndefined()
    expect(mounts[1].attributes('disabled')).toBeDefined()
  })

  it('mounts a drive', async () => {
    const { pinia, s } = setup([loc({})])
    s.mount = vi.fn(async () => {})
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="mount"]').trigger('click')
    await flushPromises()
    expect(s.mount).toHaveBeenCalledWith('usb-a')
  })

  it('unmount needs an inline confirm click', async () => {
    const { pinia, s } = setup([loc({ mounted: true })])
    s.unmount = vi.fn(async () => {})
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="unmount"]').trigger('click')
    expect(s.unmount).not.toHaveBeenCalled()
    await w.find('[data-test="unmount"]').trigger('click')
    expect(s.unmount).toHaveBeenCalledWith('usb-a')
  })

  it('sets the target and backups (target excluded from backups)', async () => {
    const { pinia, s } = setup(
      [loc({ mounted: true }), loc({ id: 'usb-b', name: 'B', mounted: true })],
      'usb-a',
    )
    s.setTarget = vi.fn(async () => {})
    s.setBackups = vi.fn(async () => {})
    const w = mnt(StorageSection, pinia)
    expect(w.find('[data-test="backup-usb-a"]').exists()).toBe(false)
    await w.find('[data-test="target-usb-b"]').setValue(true)
    expect(s.setTarget).toHaveBeenCalledWith('usb-b')
    await w.find('[data-test="backup-usb-b"]').setValue(true)
    expect(s.setBackups).toHaveBeenCalledWith(['usb-b'])
  })

  it('tests an SMB share and never echoes the password', async () => {
    const { pinia, s } = setup([])
    s.testSmb = vi.fn(async () => ({ ok: true, message: 'Connected' }))
    const w = mnt(StorageSection, pinia)
    const inputs = w.findAll('form input')
    await inputs[0].setValue('//nas/photos')
    await inputs[4].setValue('pw')
    expect(inputs[4].attributes('type')).toBe('password')
    await w.find('[data-test="smb-test"]').trigger('click')
    await flushPromises()
    expect(s.testSmb).toHaveBeenCalledWith({ unc: '//nas/photos', password: 'pw' })
    expect(w.find('[data-test="smb-result"]').text()).toBe('Connected')
  })

  it('shows an error toast when mount fails', async () => {
    const { pinia, s } = setup([loc({})])
    s.mount = vi.fn(async () => {
      throw new ApiError({ code: 'MOUNT_FAILED', message: 'bad superblock', status: 502 })
    })
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="mount"]').trigger('click')
    await flushPromises()
    expect(useToastsStore().items.at(-1).message).toBe('bad superblock')
  })

  it('starts verify and opens the offload dialog', async () => {
    const { pinia, s } = setup(
      [loc({ mounted: true }), loc({ id: 'usb-b', name: 'B', mounted: true })],
      'usb-a',
    )
    s.verify = vi.fn(async () => ({}))
    s.offload = vi.fn(async () => ({}))
    const w = mount(StorageSection, { global: { plugins: [pinia] }, attachTo: document.body })
    await w.find('[data-test="verify"]').trigger('click')
    expect(s.verify).toHaveBeenCalled()
    await w.find('[data-test="offload-open"]').trigger('click')
    await flushPromises()
    document.querySelector('[data-test="offload-go"]').click()
    await flushPromises()
    expect(s.offload).toHaveBeenCalledWith({
      from_id: 'usb-a',
      to_id: 'usb-b',
      scope: { kind: 'all' },
      keep_source: true,
    })
    w.unmount()
  })
})

describe('offload session picker', () => {
  it('lists sessions by name instead of asking for an id', async () => {
    const { pinia, s } = setup(
      [loc({ mounted: true }), loc({ id: 'usb-b', name: 'B', mounted: true })],
      'usb-a',
    )
    s.offload = vi.fn(async () => ({}))
    const sessions = useSessionsStore()
    sessions.fetch = vi.fn(async () => {
      sessions.items = [{ id: 's1', name: 'Moon', created: '2026-01-02T00:00:00Z' }]
    })
    const w = mount(StorageSection, { global: { plugins: [pinia] }, attachTo: document.body })
    await w.find('[data-test="offload-open"]').trigger('click')
    await flushPromises()
    const scopes = [...document.querySelectorAll('[data-test="offload-dialog"] button')]
    scopes.find((b) => b.textContent.trim() === 'One session').click()
    await flushPromises()
    const picker = document.querySelector('[data-test="session-picker"] select')
    expect(picker.textContent).toContain('Moon')
    expect(document.body.textContent).not.toContain('Session id')
    document.querySelector('[data-test="offload-go"]').click()
    await flushPromises()
    expect(s.offload).toHaveBeenCalledWith(
      expect.objectContaining({ scope: { kind: 'session', session_id: 's1' } }),
    )
    w.unmount()
  })
})

describe('storage events and chip', () => {
  it('warns when an SMB share is mounted without encryption', () => {
    const smb = { kind: 'smb', id: 'smb-nas', name: 'NAS', mounted: true }
    const a = mnt(StorageSection, setup([loc({ ...smb, encrypted: false })]).pinia)
    expect(a.find('[data-test="unencrypted"]').exists()).toBe(true)
    const b = mnt(StorageSection, setup([loc({ ...smb, encrypted: true })]).pinia)
    expect(b.find('[data-test="unencrypted"]').exists()).toBe(false)
  })

  it('applies backup_status and refetches on locations_changed', () => {
    const { pinia, s } = setup([])
    api.listLocations = vi.fn(async () => ({ locations: [], target_id: null, backup_ids: [] }))
    const ev = useEventsStore()
    ev.dispatch({ type: 'backup_status', data: { running: true, pending: 3 } })
    expect(s.backup).toMatchObject({ running: true, pending: 3 })
    ev.dispatch({ type: 'locations_changed', data: { reason: 'mount' } })
    expect(api.listLocations).toHaveBeenCalled()
    void pinia
  })

  it('chip shows target, free space, backlog and switches target', async () => {
    const { pinia, s } = setup(
      [loc({ mounted: true, free: 2 * 1024 ** 3 }), loc({ id: 'usb-b', name: 'B', mounted: true })],
      'usb-a',
    )
    s.backup = { running: false, pending: 4 }
    s.setTarget = vi.fn(async () => {})
    const w = mnt(StorageChip, pinia)
    expect(w.find('[data-test="chip-target"]').text()).toContain('Card A')
    expect(w.find('[data-test="chip-target"]').text()).toContain('2.0 GB free')
    expect(w.find('[data-test="chip-backup"]').text()).toContain('4 to back up')
    await w.find('button').trigger('click')
    await w.find('[data-test="switch-usb-b"]').trigger('click')
    expect(s.setTarget).toHaveBeenCalledWith('usb-b')
  })
})

describe('NO_TARGET handling', () => {
  it('capture is disabled with a hint when there is no target', () => {
    const { pinia } = setup([], null)
    useCameraStore().connected = true
    const w = mnt(CaptureControls, pinia)
    expect(w.find('[data-testid="capture-btn"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-testid="trigger-btn"]').attributes('disabled')).toBeDefined()
    expect(w.text()).toContain('No storage target')
  })

  it('gallery shows the state instead of an error toast on NO_TARGET', async () => {
    const { pinia } = setup([loc({ mounted: true })], 'usb-a')
    const files = useFilesStore()
    files.load = vi.fn(async () => {
      throw new ApiError({ code: 'NO_TARGET', message: 'x', status: 409 })
    })
    const w = mnt(LocalFiles, pinia)
    await flushPromises()
    files.lastError = new ApiError({ code: 'NO_TARGET', message: 'x', status: 409 })
    await flushPromises()
    expect(w.find('[data-test="no-target"]').exists()).toBe(true)
    expect(useToastsStore().items).toHaveLength(0)
  })

  it('NO_TARGET toasts use the friendly message', () => {
    setup()
    const t = useToastsStore()
    t.error(new ApiError({ code: 'NO_TARGET', message: 'raw', status: 409 }))
    expect(t.items.at(-1).message).toContain('Settings › Storage')
  })
})
