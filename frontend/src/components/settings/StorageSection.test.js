import { describe, it, expect, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import StorageSection from './StorageSection.vue'
import StorageChip from '@/components/shell/StorageChip.vue'
import CaptureSide from '@/components/shoot/CaptureSide.vue'
import LocalFiles from '@/components/gallery/LocalFiles.vue'
import { useStorageStore } from '@/stores/storage'
import { useSessionsStore } from '@/stores/sessions'
import { useToastsStore } from '@/stores/toasts'
import { useJobsStore } from '@/stores/jobs'
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

  it('explains a blank or unknown drive and keeps real reasons verbatim', () => {
    const { pinia } = setup([
      loc({
        id: 'dev-sdb',
        name: 'sdb',
        fstype: null,
        supported: false,
        reason: 'unknown filesystem',
      }),
      loc({ id: 'usb-c', name: 'Enc', supported: false, reason: 'encrypted (LUKS) volume' }),
    ])
    const t = mnt(StorageSection, pinia).text()
    expect(t).toContain('Blank or unreadable — format it to use it')
    expect(t).toContain('encrypted (LUKS) volume')
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
    useCameraStore().state = 'idle'
    const w = mnt(CaptureSide, pinia)
    expect(w.find('[data-testid="capture-btn"]').attributes('aria-disabled')).toBe('true')
    expect(w.text()).toContain('No storage chosen')
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

describe('StorageSection fsck job', () => {
  const job = { id: 'j1', kind: 'fsck', target: 'usb-a', status: 'running' }

  it('shows Checking… from a running fsck job in the store (e.g. after reload)', async () => {
    const { pinia } = setup([loc({})])
    useJobsStore().upsert(job)
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    const b = w.find('[data-test="fsck"]')
    expect(b.text()).toContain('Checking')
    expect(b.attributes('disabled')).toBeDefined()
  })

  it('starts the job, then shows the result when it completes', async () => {
    const { pinia, s } = setup([loc({})])
    s.check = vi.fn(async () => useJobsStore().upsert(job))
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="fsck"]').trigger('click')
    await w.find('[data-test="fsck"]').trigger('click')
    await flushPromises()
    expect(w.find('[data-test="fsck"]').text()).toContain('Checking')
    useJobsStore().upsert({
      ...job,
      status: 'completed',
      result: { returncode: 0, output: 'clean' },
    })
    await flushPromises()
    expect(w.find('[data-test="fsck"]').text()).not.toContain('Checking')
    expect(w.find('[data-test="fsck-out"]').text()).toBe('clean')
  })

  it('does not toast a failed check itself (the Jobs panel does)', async () => {
    const { pinia } = setup([loc({})])
    useJobsStore().upsert(job)
    const toasts = useToastsStore()
    toasts.error = vi.fn()
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    useJobsStore().upsert({ ...job, status: 'failed', error: 'did not finish in time' })
    await flushPromises()
    expect(toasts.error).not.toHaveBeenCalled()
    expect(w.find('[data-test="fsck"]').text()).not.toContain('Checking')
  })

  it('shows the newest finished run: a newer failure hides an older clean result', async () => {
    const { pinia } = setup([loc({})])
    const jobs = useJobsStore()
    jobs.upsert({
      ...job,
      id: 'old',
      status: 'completed',
      created: '1',
      result: { returncode: 0, output: 'clean' },
    })
    jobs.upsert({ ...job, id: 'new', status: 'failed', created: '2', error: 'ran out of time' })
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    const out = w.find('[data-test="fsck-out"]')
    expect(out.text()).toBe('ran out of time')
    jobs.upsert({ ...job, id: 'newer', status: 'cancelled', created: '3' })
    await flushPromises()
    expect(w.find('[data-test="fsck-out"]').text()).toBe('Cancelled')
  })

  it('disables the button between confirm and the POST response (no double POST)', async () => {
    const { pinia, s } = setup([loc({})])
    let resolve
    s.check = vi.fn(() => new Promise((r) => (resolve = r)))
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="fsck"]').trigger('click')
    await w.find('[data-test="fsck"]').trigger('click')
    await flushPromises()
    expect(s.check).toHaveBeenCalledTimes(1)
    expect(w.find('[data-test="fsck"]').attributes('disabled')).toBeDefined()
    resolve()
    await flushPromises()
  })
})

describe('StorageSection format', () => {
  const disk = { name: 'sda', majmin: '8:0', size: 64e9, model: 'Ultra Fit' }
  const two = (o = {}) => [
    loc({ id: 'usb-a', disk, ...o }),
    loc({ id: 'dev-sda2', name: 'sda2', uuid: null, configured: false, disk }),
  ]
  const fjob = { id: 'f1', kind: 'format', target: 'sda', status: 'running' }

  it('groups partitions under their physical disk with one Format… action', () => {
    const { pinia } = setup(two())
    const w = mnt(StorageSection, pinia)
    const g = w.find('[data-test="disk-sda"]')
    expect(g.text()).toContain('Ultra Fit')
    expect(g.findAll('[data-test^="loc-"]')).toHaveLength(2)
    expect(w.findAll('[data-test="format-sda"]')).toHaveLength(1)
    expect(w.find('[data-test="format-sda"]').classes()).not.toContain('bg-camera-danger-fill')
    expect(w.find('[data-test="format-sda"]').attributes('disabled')).toBeUndefined()
  })

  it.each([
    [{ mounted: true }, 'Unmount'],
    [{ is_target: true }, 'photo location'],
    [{ is_backup: true }, 'backup'],
  ])('disables Format… with a reason when %j', (o, text) => {
    const { pinia } = setup(two(o))
    const w = mnt(StorageSection, pinia)
    expect(w.find('[data-test="format-sda"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="format-reason"]').text()).toContain(text)
  })

  it('disables Format… while a partition is being checked', async () => {
    const { pinia } = setup(two())
    useJobsStore().upsert({ id: 'c', kind: 'fsck', target: 'usb-a', status: 'running' })
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    expect(w.find('[data-test="format-sda"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="format-reason"]').text()).toContain('check')
  })

  it('opens the confirmation in the page (no window.confirm)', async () => {
    const { pinia } = setup(two())
    const spy = vi.spyOn(window, 'confirm')
    const w = mnt(StorageSection, pinia)
    await w.find('[data-test="format-sda"]').trigger('click')
    await flushPromises()
    expect(document.body.querySelector('[data-test="format-dialog"]')).not.toBeNull()
    expect(spy).not.toHaveBeenCalled()
    w.unmount()
  })

  it('shows Formatting… from a running format job (e.g. after reload) and blocks the partitions', async () => {
    const { pinia } = setup(two())
    useJobsStore().upsert(fjob)
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    const b = w.find('[data-test="format-sda"]')
    expect(b.text()).toContain('Formatting')
    expect(b.attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="mount"]').attributes('disabled')).toBeDefined()
    expect(w.find('[data-test="fsck"]').attributes('disabled')).toBeDefined()
  })

  it('refreshes the drive list when a format finishes and does not toast itself', async () => {
    const { pinia, s } = setup(two())
    s.fetch = vi.fn(async () => {})
    useJobsStore().upsert(fjob)
    const toasts = useToastsStore()
    toasts.error = vi.fn()
    const w = mnt(StorageSection, pinia)
    await flushPromises()
    useJobsStore().upsert({ ...fjob, status: 'failed', error: 'mkfs failed: boom' })
    await flushPromises()
    expect(s.fetch).toHaveBeenCalled()
    expect(toasts.error).not.toHaveBeenCalled()
    expect(w.find('[data-test="format-out"]').text()).toBe('mkfs failed: boom')
    expect(w.find('[data-test="format-sda"]').text()).not.toContain('Formatting')
  })
})
