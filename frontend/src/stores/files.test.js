import { describe, it, expect, vi, beforeEach } from 'vitest'
import { createTestingPinia } from '@pinia/testing'
import { useFilesStore } from './files'
import { api } from '@/api'

vi.mock('@/api', async (orig) => ({
  ...(await orig()),
  api: { deleteFiles: vi.fn(), createZipDownload: vi.fn(), downloadFile: vi.fn() },
}))

describe('files store bulk operations', () => {
  let files
  beforeEach(() => {
    createTestingPinia({ stubActions: false, createSpy: vi.fn })
    files = useFilesStore()
    vi.clearAllMocks()
  })

  it('removeMany posts the list once and drops only the deleted rows', async () => {
    files.items = ['a', 'b', 'c'].map((n) => ({ path: `x/${n}.jpg`, name: `${n}.jpg` }))
    files.total = 3
    api.deleteFiles.mockResolvedValue({
      deleted: ['x/a.jpg', 'x/b.jpg'],
      failed: [{ path: 'x/c.jpg', error: 'locked' }],
    })
    const out = await files.removeMany(['x/a.jpg', 'x/b.jpg', 'x/c.jpg'])
    expect(api.deleteFiles).toHaveBeenCalledTimes(1)
    expect(api.deleteFiles.mock.calls[0][0].body.paths).toHaveLength(3)
    expect(out.failed[0].error).toBe('locked')
    expect(files.items.map((f) => f.path)).toEqual(['x/c.jpg'])
    expect(files.total).toBe(1)
  })

  it('downloadZip redeems the ticket with a plain link; one file skips the ZIP', async () => {
    const clicks = []
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      clicks.push(this.getAttribute('href'))
    })
    api.createZipDownload.mockResolvedValue({ url: '/api/v1/files/zip/tkt' })
    await files.downloadZip(['a.jpg', 'b.jpg'])
    expect(api.createZipDownload.mock.calls[0][0].body).toEqual({ paths: ['a.jpg', 'b.jpg'] })
    expect(clicks).toEqual(['/api/v1/files/zip/tkt'])
    await files.downloadZip(['a.jpg'])
    expect(api.createZipDownload).toHaveBeenCalledTimes(1)
    expect(clicks[1]).toMatch(/files\/a\.jpg$/)
    click.mockRestore()
  })
})
