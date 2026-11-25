import { describe, it, expect } from 'vitest'
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { buildSections } from '@/components/settings/schemaForm'

const walk = (d) =>
  readdirSync(d).flatMap((n) => {
    const p = join(d, n)
    if (n === 'generated') return []
    return statSync(p).isDirectory() ? walk(p) : [p]
  })
const files = walk('src').filter((f) => /\.(vue|js)$/.test(f) && !/\.test\.js$/.test(f))
const text = files.map((f) => readFileSync(f, 'utf8')).join('\n')

describe('settings deep links', () => {
  it('every linked section id exists as a data-section', () => {
    const linked = new Set(
      [...text.matchAll(/section=([\w-]+)/g), ...text.matchAll(/section: '([\w-]+)'/g)].map(
        (m) => m[1],
      ),
    )
    const declared = new Set([...text.matchAll(/data-section="([\w-]+)"/g)].map((m) => m[1]))
    // schema-driven sections are rendered with :data-section="s.key"
    declared.add('general')
    expect(linked.size).toBeGreaterThan(0)
    for (const id of linked) expect(declared, id).toContain(id)
  })
  it('schema section keys are clean ids', () => {
    const sections = buildSections({
      properties: {
        a: { type: 'string' },
        v: { type: 'object', properties: { x: { type: 'string' } } },
      },
    })
    for (const s of sections) expect(s.key).toMatch(/^[a-z][\w-]*$/)
  })
})
