/** Pure helpers behind the exposure strip: which camera setting feeds which cell, what the mode governs. */
import { settingValueLabel } from '@/labels'

export const MODE_NAMES = {
  P: 'Program',
  A: 'Aperture priority',
  S: 'Shutter priority',
  M: 'Manual',
}

/** Which strip values the camera sets by itself in each mode. */
export const GOVERNED = {
  P: ['shutter', 'aperture'],
  A: ['shutter'],
  S: ['aperture'],
  M: [],
}

/** Camera setting names (first one found wins) for each strip cell. */
export const SETTING_FOR = {
  mode: ['expprogram', 'autoexposuremode'],
  shutter: ['shutterspeed', 'shutterspeed2'],
  aperture: ['f-number', 'aperture'],
  iso: ['iso'],
  comp: ['exposurecompensation'],
  wb: ['whitebalance'],
}

/** P, A, S or M from whatever the camera reports ("M", "Manual", "Aperture Priority"), else null. */
export function modeLetter(value) {
  if (value == null) return null
  const v = String(value).trim()
  if (/^[pasm]$/i.test(v)) return v.toUpperCase()
  if (/program/i.test(v)) return 'P'
  if (/aperture/i.test(v)) return 'A'
  if (/shutter/i.test(v)) return 'S'
  if (/manual/i.test(v)) return 'M'
  return null
}

/** Display text for a cell's raw value. */
export function formatValue(key, raw) {
  if (raw == null || raw === '') return '–'
  const v = String(raw)
  if (key === 'aperture') return /^f\//i.test(v) ? v : `f/${v.replace(/^f/i, '')}`
  if (key === 'comp') return settingValueLabel('exposurecompensation', v)
  if (key === 'wb') return /^automatic$/i.test(v) ? 'Auto' : settingValueLabel('whitebalance', v)
  if (key === 'mode') return modeLetter(v) || settingValueLabel('mode', v)
  return settingValueLabel(key, v)
}

/** A settings option as the picker shows it. */
export function optionFor(key, choice, selected) {
  const letter = key === 'mode' ? modeLetter(choice) : null
  const label = key === 'wb' ? settingValueLabel('whitebalance', choice) : formatValue(key, choice)
  const sub = letter ? MODE_NAMES[letter] || '' : ''
  return { value: choice, label, sub, selected: String(choice) === String(selected) }
}
