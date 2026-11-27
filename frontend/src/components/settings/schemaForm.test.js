import { describe, it, expect } from 'vitest'
import {
  buildSections,
  buildPatch,
  dirtyPaths,
  fieldErrors,
  describeField,
  pathTitles,
  titleForPath,
  tagsFor,
} from './schemaForm'

const schema = {
  $defs: {
    Video: {
      title: 'VideoConfig',
      type: 'object',
      properties: {
        crf: { type: 'integer', minimum: 0, maximum: 51, title: 'Crf', description: 'quality' },
        codec: { enum: ['a', 'b'], type: 'string', title: 'Codec' },
        path: { anyOf: [{ type: 'string' }, { type: 'null' }], title: 'Path' },
        timeout_s: { type: 'number', minimum: 1, maximum: 5 },
        fancy: { type: 'object' },
      },
    },
  },
  properties: {
    video: { $ref: '#/$defs/Video' },
    cors_origins: { type: 'array', items: { type: 'string' }, title: 'Cors' },
    demo_camera: { type: 'boolean' },
    api_key_set: { type: 'boolean', readOnly: true },
    new_flag: { type: 'boolean', title: 'New flag' },
  },
}

describe('schemaForm', () => {
  const sections = buildSections(schema)
  it('builds sections from $ref objects and groups root scalars', () => {
    expect(sections.map((s) => s.key)).toEqual(['video', 'general'])
    expect(sections[0].title).toBe('Video')
    expect(sections[0].fields.map((f) => f.name)).toEqual(['crf', 'codec', 'path', 'timeout_s'])
    expect(sections[1].fields.map((f) => f.name)).toEqual(['cors_origins', 'new_flag'])
  })
  it('infers kinds, nullability, bounds and units', () => {
    const f = Object.fromEntries(sections[0].fields.map((x) => [x.name, x]))
    expect(f.crf).toMatchObject({ kind: 'integer', min: 0, max: 51, step: 1 })
    expect(f.codec.kind).toBe('enum')
    expect(f.path).toMatchObject({ kind: 'string', nullable: true })
    expect(f.timeout_s).toMatchObject({ kind: 'number', unit: 's', step: 0.1 })
    expect(describeField(schema, 'x_ms', { type: 'integer' }).unit).toBe('ms')
  })
  it('diffs only changed paths into a nested patch', () => {
    const saved = { video: { crf: 23, codec: 'a' }, cors_origins: [] }
    const draft = { video: { crf: 20, codec: 'a' }, cors_origins: ['x'] }
    const paths = dirtyPaths(sections, saved, draft)
    expect(paths).toEqual(['video.crf', 'cors_origins'])
    expect(buildPatch(paths, draft)).toEqual({ video: { crf: 20 }, cors_origins: ['x'] })
    expect(dirtyPaths(sections, saved, saved)).toEqual([])
  })
  it('tags kiosk rows', () => {
    expect(tagsFor('kiosk.scale')).toEqual(['KIOSK'])
    expect(tagsFor('video.crf')).toEqual([])
  })
  it('maps 422 details to field paths', () => {
    expect(
      fieldErrors({
        errors: [
          { loc: ['body', 'video', 'crf'], msg: 'too big' },
          { loc: ['body'], msg: 'x' },
        ],
      }),
    ).toEqual({ 'video.crf': 'too big' })
    expect(fieldErrors(null)).toEqual({})
  })

  it('maps paths to field titles, never raw paths', () => {
    const titles = pathTitles(sections)
    expect(titles['video.crf']).toBe('Video › Crf')
    expect(titles.new_flag).toBe('New flag')
    expect(titleForPath(titles, 'liveview.target_fps')).toBe('Liveview › Target fps')
  })
})
