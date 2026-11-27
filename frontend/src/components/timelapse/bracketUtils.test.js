import { describe, it, expect } from 'vitest'
import {
  sortValues,
  toggleValue,
  parseNumeric,
  quickShots,
  formatBytes,
  formatDuration,
  formatEndsAt,
} from './bracketUtils'

describe('bracketUtils', () => {
  it('orders shutter speeds by real duration, Bulb last', () => {
    const shuffled = ['30', 'Bulb', '0.5', '1/250', '2', '1/4000']
    expect(sortValues(shuffled)).toEqual(['1/4000', '1/250', '0.5', '2', '30', 'Bulb'])
  })
  it('parses fractions, f-numbers and signed EV', () => {
    expect(parseNumeric('1/250')).toBeCloseTo(0.004)
    expect(parseNumeric('f/2.8')).toBe(2.8)
    expect(parseNumeric('+0.7')).toBe(0.7)
    expect(parseNumeric('1/0')).toBeNaN()
    expect(sortValues(['1', '-1', '0', '-2'])).toEqual(['-2', '-1', '0', '1'])
  })
  it('toggles and keeps the list sorted', () => {
    expect(toggleValue(['1/250', '2'], '1/4000')).toEqual(['1/4000', '1/250', '2'])
    expect(toggleValue(['1/250', '2'], '2')).toEqual(['1/250'])
  })
  it('counts shots per combine mode', () => {
    const q = {
      exposure: [],
      iso: ['100', '200'],
      aperture: ['4', '8', '11'],
      shutter: [],
      combine: 'sequence',
    }
    expect(quickShots(q)).toBe(5)
    expect(quickShots({ ...q, combine: 'paired' })).toBe(3)
  })
  it('formats bytes safely', () => {
    expect(formatBytes(NaN)).toBe('0 B')
    expect(formatBytes(1536)).toBe('1.5 KB')
  })

  it('shows sub-10 s durations with one decimal', () => {
    expect(formatDuration(8 / 24)).toBe('0.3 s')
    expect(formatDuration(2.5)).toBe('2.5 s')
    expect(formatDuration(0)).toBe('0 s')
    expect(formatDuration(45)).toBe('45 s')
    expect(formatDuration(90)).toBe('1 min 30 s')
  })

  it('computes the local end time, with a weekday when it is another day', () => {
    const start = new Date(2026, 5, 1, 6, 0, 0).getTime() // a Monday, 06:00 local
    expect(formatEndsAt(start, 990)).toBe(
      new Date(start + 990_000).toLocaleTimeString([], {
        hour: '2-digit',
        minute: '2-digit',
        hour12: false,
      }),
    )
    expect(formatEndsAt(start, 0)).toMatch(/^\d{2}:\d{2}$/)
    expect(formatEndsAt(start, 36 * 3600)).toMatch(/^\S+ \d{2}:\d{2}$/)
    expect(formatEndsAt(start, NaN)).toBeNull()
    expect(formatEndsAt(start, -1)).toBeNull()
  })
})
