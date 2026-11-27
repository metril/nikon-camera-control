/** Pure helpers that turn the backend's JSON schema into a generic form model. */

export const SPECIAL_ROOT = ['demo_camera'] // rendered by their own section
const unitOf = (name) =>
  name.endsWith('_ms') ? 'ms' : name.endsWith('_s') ? 's' : name.endsWith('_min') ? 'min' : ''

const humanize = (s) => s.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

export function deref(schema, node) {
  let cur = node
  for (let i = 0; cur && cur.$ref && i < 10; i++) {
    const name = cur.$ref.split('/').pop()
    cur = { ...(schema.$defs?.[name] || schema.definitions?.[name] || {}), ...omitRef(cur) }
  }
  if (cur?.allOf?.length === 1) return deref(schema, { ...omitAllOf(cur), ...cur.allOf[0] })
  return cur || {}
}
const omit = (o, key) => Object.fromEntries(Object.entries(o).filter(([k]) => k !== key))
const omitRef = (o) => omit(o, '$ref')
const omitAllOf = (o) => omit(o, 'allOf')

/** Describe one property: {kind, nullable, min, max, step, options, unit, title, description}. */
export function describeField(schema, name, rawNode) {
  let node = deref(schema, rawNode)
  let nullable = false
  if (node.anyOf) {
    const rest = node.anyOf.filter((n) => n.type !== 'null')
    nullable = rest.length !== node.anyOf.length
    node = { ...node, ...deref(schema, rest[0] || {}) }
  }
  let kind = null
  if (node.enum) kind = 'enum'
  else if (node.type === 'boolean') kind = 'boolean'
  else if (node.type === 'integer') kind = 'integer'
  else if (node.type === 'number') kind = 'number'
  else if (node.type === 'string') kind = 'string'
  else if (node.type === 'array' && deref(schema, node.items || {}).type === 'string')
    kind = 'strings'
  const min = node.minimum ?? node.exclusiveMinimum
  const max = node.maximum ?? node.exclusiveMaximum
  const step =
    node.multipleOf ??
    (kind === 'integer' ? 1 : min != null && max != null && max - min <= 10 ? 0.1 : 1)
  return {
    name,
    kind,
    nullable,
    min,
    max,
    step,
    options: node.enum || null,
    unit: unitOf(name),
    title: node.title || humanize(name),
    description: node.description || '',
    default: node.default,
    readOnly: !!node.readOnly,
  }
}

/**
 * Sections: every object-typed top-level property becomes a section of its fields;
 * remaining scalar top-level properties are collected into "General".
 * Unknown/unsupported field kinds are skipped.
 */
export function buildSections(schema) {
  if (!schema?.properties) return []
  const sections = []
  const general = []
  for (const [key, raw] of Object.entries(schema.properties)) {
    const node = deref(schema, raw)
    if (node.type === 'object' && node.properties) {
      const fields = Object.entries(node.properties)
        .map(([n, f]) => describeField(schema, n, f))
        .filter((f) => f.kind && !f.readOnly)
      sections.push({
        key,
        title: node.title ? node.title.replace(/Config$/, '') : humanize(key),
        description: node.description || '',
        fields,
        path: (f) => `${key}.${f.name}`,
      })
    } else {
      const f = describeField(schema, key, raw)
      if (f.kind && !f.readOnly && !SPECIAL_ROOT.includes(key)) general.push(f)
    }
  }
  if (general.length)
    sections.push({
      key: 'general',
      title: 'General',
      description: '',
      fields: general,
      path: (f) => f.name,
    })
  return sections.filter((s) => s.fields.length)
}

export const getPath = (obj, path) => path.split('.').reduce((o, k) => o?.[k], obj)
export function setPath(obj, path, value) {
  const keys = path.split('.')
  const last = keys.pop()
  const target = keys.reduce((o, k) => (o[k] ??= {}), obj)
  target[last] = value
}
const same = (a, b) => JSON.stringify(a ?? null) === JSON.stringify(b ?? null)

/** All field paths whose draft value differs from the saved one. */
export function dirtyPaths(sections, saved, draft, extra = []) {
  const paths = []
  for (const s of sections) for (const f of s.fields) paths.push(s.path(f))
  return [...paths, ...extra].filter((p) => !same(getPath(saved, p), getPath(draft, p)))
}

/** Nested patch containing only the changed paths. */
export function buildPatch(paths, draft) {
  const patch = {}
  for (const p of paths) setPath(patch, p, getPath(draft, p) ?? null)
  return patch
}

/** 422 envelope details {errors:[{loc:['body','video','crf'],msg}]} -> {'video.crf': msg}. */
export function fieldErrors(details) {
  const out = {}
  const list = Array.isArray(details?.errors) ? details.errors : []
  for (const e of list) {
    const loc = (e.loc || []).filter((x) => x !== 'body')
    if (loc.length) out[loc.join('.')] = e.msg || e.message || 'Invalid value'
  }
  return out
}

/** Config path -> display title: "Live view › Target frame rate" (top-level fields: their own title). */
export function pathTitles(sections) {
  const out = {}
  for (const s of sections)
    for (const f of s.fields)
      out[s.path(f)] = s.key === 'general' ? f.title : `${s.title} › ${f.title}`
  return out
}
export function titleForPath(titles, path) {
  if (titles[path]) return titles[path]
  const parts = path.split('.').map(humanize)
  return parts.join(' › ')
}

/** Small tags shown beside a setting: kiosk.* rows apply to the touchscreen kiosk only. */
export const tagsFor = (path) => (path.startsWith('kiosk.') ? ['KIOSK'] : [])
