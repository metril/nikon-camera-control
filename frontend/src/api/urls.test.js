import { describe, it, expect } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { URL_PATTERNS, thumbnailUrl, fileUrl, cameraFileUrl } from './urls'

describe('urls', () => {
  it('patterns exist in the generated SDK (fails if the spec renames a route)', () => {
    const sdk = readFileSync(resolve(process.cwd(), 'src/api/generated/sdk.gen.ts'), 'utf8')
    for (const p of Object.values(URL_PATTERNS)) expect(sdk).toContain(`url: '${p}'`)
  })
  it('builds URLs', () => {
    expect(thumbnailUrl('a/b.jpg', 128)).toContain('/api/v1/thumbnails/')
    expect(thumbnailUrl('a/b.jpg', 128)).toContain('size=128')
    expect(fileUrl('x.jpg')).toBe('/api/v1/files/x.jpg')
  })
  it('encodes nested paths as one segment (%2F); the backend decodes them', () => {
    expect(fileUrl('sessions/s1/f.jpg')).toBe('/api/v1/files/sessions%2Fs1%2Ff.jpg')
    expect(thumbnailUrl('sessions/s1/f.jpg')).toBe('/api/v1/thumbnails/sessions%2Fs1%2Ff.jpg')
    expect(cameraFileUrl('/store_1/DCIM/100NCD', 'a.jpg')).toBe(
      '/api/v1/camera/files/%2Fstore_1%2FDCIM%2F100NCD/a.jpg',
    )
  })
})
