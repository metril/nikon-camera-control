import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { createTestingPinia } from '@pinia/testing'
import FormatDriveDialog from './FormatDriveDialog.vue'
import { labelError } from './formatDrive'
import { useStorageStore } from '@/stores/storage'
import { useToastsStore } from '@/stores/toasts'

vi.mock('@/api', async (orig) => ({ ...(await orig()), api: {} }))

const disk = {
  name: 'sda',
  majmin: '8:0',
  size: 64e9,
  diskseq: '42',
  model: 'Ultra Fit',
  items: [
    { id: 'usb-a', name: 'Card A', label: 'PHOTOS', fstype: 'ext4', size: 32e9 },
    { id: 'dev-sda2', name: 'sda2', label: null, fstype: null, size: 32e9 },
  ],
}
const make = () => {
  const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
  const s = useStorageStore()
  s.formatDisk = vi.fn(async () => ({ id: 'j' }))
  const w = mount(FormatDriveDialog, {
    props: { open: true, disk },
    global: { plugins: [pinia] },
    attachTo: document.body,
  })
  return { w, s }
}
const q = (sel) => document.body.querySelector(`[data-test="${sel}"]`)
const input = (sel) => q(sel).querySelector('input') || q(sel)
const type = async (sel, v) => {
  const el = input(sel)
  el.value = v
  el.dispatchEvent(new Event('input'))
  await flushPromises()
}
afterEach(() => (document.body.innerHTML = ''))

describe('FormatDriveDialog', () => {
  it('lists the disk and every partition that will be erased', () => {
    make()
    expect(q('format-disk').textContent).toContain('Ultra Fit')
    expect(q('format-disk').textContent).toContain('sda')
    const parts = q('format-parts').textContent
    expect(parts).toContain('PHOTOS')
    expect(parts).toContain('ext4')
    expect(parts).toContain('unknown filesystem')
    expect(q('format-warning').textContent).toContain('erased')
  })

  it('requires typing the device name before the button enables, then submits the whole disk', async () => {
    const { s } = make()
    expect(q('format-go').disabled).toBe(true)
    await type('format-confirm', 'SDA')
    expect(q('format-go').disabled).toBe(true)
    await type('format-confirm', 'sda')
    expect(q('format-go').disabled).toBe(false)
    await type('format-label', 'Trip 1')
    q('format-go').click()
    await flushPromises()
    expect(s.formatDisk).toHaveBeenCalledWith('sda', {
      fstype: 'exfat',
      label: 'Trip 1',
      majmin: '8:0',
      size: 64e9,
      diskseq: '42',
    })
  })

  it('defaults to exFAT with a one-line note and validates the label per filesystem', async () => {
    make()
    expect(q('format-fs-note').textContent).toContain('Windows, Mac and Linux')
    await type('format-label', 'a;b')
    expect(q('format-label-error')).not.toBeNull()
    await type('format-confirm', 'sda')
    expect(q('format-go').disabled).toBe(true)
    await type('format-label', 'GOOD')
    expect(q('format-label-error')).toBeNull()
    expect(q('format-go').disabled).toBe(false)
  })

  it('toasts a rejected request and stays open', async () => {
    const { s } = make()
    const toasts = useToastsStore()
    toasts.error = vi.fn()
    s.formatDisk = vi.fn(async () => {
      throw new Error('Unmount every partition of this drive before formatting it')
    })
    await type('format-confirm', 'sda')
    q('format-go').click()
    await flushPromises()
    expect(toasts.error).toHaveBeenCalled()
  })
})

describe('FAT32 on huge drives', () => {
  it('disables FAT32 over 2 TB and says to use exFAT', async () => {
    const pinia = createTestingPinia({ stubActions: false, createSpy: vi.fn })
    mount(FormatDriveDialog, {
      props: { open: true, disk: { ...disk, size: 4e12 } },
      global: { plugins: [pinia] },
      attachTo: document.body,
    })
    await flushPromises()
    const opt = [...q('format-fs').querySelectorAll('option')].find((o) => o.value === 'fat32')
    expect(opt.disabled).toBe(true)
    expect(q('format-fs-note').textContent).toContain('Use exFAT for drives over 2 TB')
  })
  it('keeps FAT32 selectable on small drives', () => {
    make()
    const opt = [...q('format-fs').querySelectorAll('option')].find((o) => o.value === 'fat32')
    expect(opt.disabled).toBe(false)
  })
})

describe('labelError', () => {
  it('applies the per-filesystem limits and charset', () => {
    expect(labelError('exfat', 'A'.repeat(15))).toBe('')
    expect(labelError('exfat', 'A'.repeat(16))).toContain('15')
    expect(labelError('fat32', 'A'.repeat(12))).toContain('11')
    expect(labelError('ntfs', 'A'.repeat(32))).toBe('')
    expect(labelError('ext4', 'A'.repeat(17))).toContain('16')
    expect(labelError('exfat', '')).toBe('')
    for (const bad of ['a/b', '-x', ' x', 'é', 'a.b']) expect(labelError('exfat', bad)).not.toBe('')
  })
})
