/** Pure helpers for bracketing: types, ordering, counting, step ids. */

export const bracketTypes = [
  { key: 'exposure', label: 'Exposure comp.', setting: 'exposurecompensation' },
  { key: 'iso', label: 'ISO', setting: 'iso' },
  { key: 'aperture', label: 'Aperture', setting: 'aperture' },
  { key: 'shutter', label: 'Shutter speed', setting: 'shutterspeed' },
]

/** Used while the camera is not connected; values are then "not validated". */
export const FALLBACK_CHOICES = {
  exposure: ['-2', '-1', '0', '1', '2'],
  iso: ['100', '200', '400', '800', '1600', '3200', '6400'],
  aperture: ['2.8', '4', '5.6', '8', '11', '16'],
  shutter: ['1/1000', '1/500', '1/250', '1/125', '1/60', '1/30', '1/15', '0.5', '1', '2', '4'],
}

/** "1/250" -> 0.004, "0.5" -> 0.5, "2s" -> 2, "f/2.8" -> 2.8, "+0.7" -> 0.7, text -> NaN. */
export function parseNumeric(v) {
  const s = String(v)
    .trim()
    .toLowerCase()
    .replace(/^f\/?/, '')
    .replace(/["s]+$/, '')
    .replace(/^\+/, '')
  const m = s.match(/^(-?\d+(?:\.\d+)?)\s*\/\s*(\d+(?:\.\d+)?)$/)
  if (m) return Number(m[2]) === 0 ? NaN : Number(m[1]) / Number(m[2])
  return /^-?\d+(\.\d+)?$/.test(s) ? Number(s) : NaN
}

/** Ascending exposure time; unparsable values (Bulb, Auto) sort last. */
export function compareValues(a, b) {
  const na = parseNumeric(a)
  const nb = parseNumeric(b)
  const fa = Number.isFinite(na)
  const fb = Number.isFinite(nb)
  if (fa && fb) return na - nb
  if (fa !== fb) return fa ? -1 : 1
  return String(a).localeCompare(String(b))
}
export const compareShutter = compareValues

export const sortValues = (values) => [...values].sort(compareValues)

/** One generic toggle for every bracket type: returns a new sorted list. */
export function toggleValue(list, value) {
  const next = list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
  return sortValues(next)
}

/** Number of shots per set for a quick config. */
export function quickShots(quick) {
  const lens = bracketTypes.map((t) => quick[t.key]?.length ?? 0).filter((n) => n > 0)
  if (!lens.length) return 0
  return quick.combine === 'paired' ? Math.max(...lens) : lens.reduce((a, b) => a + b, 0)
}

let counter = 0
export const newId = (prefix = 'id') => `${prefix}-${Date.now().toString(36)}-${counter++}`

export const newRow = (name = '', value = '') => ({ id: newId('row'), name, value })
export const newStep = (rows = [newRow()], label = '', delay_ms = 0) => ({
  id: newId('step'),
  label,
  delay_ms,
  rows,
})

export function stepFromApi(s) {
  const rows = Object.entries(s.settings || {}).map(([n, v]) => newRow(n, String(v)))
  return newStep(rows.length ? rows : [newRow()], s.label || '', s.delay_ms || 0)
}

export function stepToApi(s) {
  const settings = {}
  for (const r of s.rows)
    if (r.name && r.value !== '' && r.value != null) settings[r.name] = r.value
  return { settings, label: s.label || '', delay_ms: Number.isFinite(s.delay_ms) ? s.delay_ms : 0 }
}

export function choicesFor(settings, setting) {
  const all = [...(settings.common || []), ...(settings.all || [])]
  const s = all.find((x) => x.name === setting || x.alias === setting)
  return s?.choices?.length ? [...s.choices] : null
}

export function formatBytes(n) {
  if (!Number.isFinite(n) || n <= 0) return '0 B'
  const u = ['B', 'KB', 'MB', 'GB', 'TB']
  const i = Math.min(u.length - 1, Math.floor(Math.log(n) / Math.log(1024)))
  return `${(n / 1024 ** i).toFixed(i ? 1 : 0)} ${u[i]}`
}

export function formatDuration(s) {
  if (!Number.isFinite(s) || s < 0) return '-'
  if (s < 10 && s !== Math.round(s)) {
    const d = s.toFixed(1)
    if (d !== '0.0' && d !== '10.0') return `${d} s`
  }
  const t = Math.round(s)
  const h = Math.floor(t / 3600)
  const m = Math.floor((t % 3600) / 60)
  const sec = t % 60
  return h ? `${h} h ${m} min` : m ? `${m} min ${sec} s` : `${sec} s`
}
