import { describe, it, expect } from 'vitest'
import {
  computeHistogram,
  computeClipping,
  computePeaking,
  gridSegments,
  COLORS,
} from './analysis.js'

function img(w, h, fill) {
  const data = new Uint8ClampedArray(w * h * 4)
  for (let p = 0; p < w * h; p++) {
    const v = fill(p % w, Math.floor(p / w))
    data.set([v, v, v, 255], p * 4)
  }
  return { width: w, height: h, data }
}

describe('computeHistogram', () => {
  it('bins luminance and reports clipping fractions', () => {
    // 4x4: 4 black, 4 white, 8 mid grey
    const im = img(4, 4, (x, y) => (y === 0 ? 0 : y === 1 ? 255 : 128))
    const { bins, lo, hi } = computeHistogram(im)
    expect(bins[0]).toBe(4)
    expect(bins[255]).toBe(4)
    expect(bins[128]).toBe(8)
    expect(lo).toBeCloseTo(0.25)
    expect(hi).toBeCloseTo(0.25)
  })
  it('reports no clipping for mid tones and handles empty input', () => {
    const r = computeHistogram(img(2, 2, () => 100))
    expect(r.lo).toBe(0)
    expect(r.hi).toBe(0)
    expect(computeHistogram({ width: 0, height: 0, data: new Uint8ClampedArray(0) }).hi).toBe(0)
  })
})

describe('computeClipping', () => {
  it('marks highlights in danger colour and shadows in cold colour', () => {
    const m = computeClipping(img(3, 1, (x) => [0, 128, 255][x]))
    expect([...m.slice(0, 4)]).toEqual([...COLORS.cold, 170])
    expect(m[7]).toBe(0)
    expect([...m.slice(8, 12)]).toEqual([...COLORS.danger, 170])
  })
})

describe('computePeaking', () => {
  it('marks a hard vertical edge but not a flat area', () => {
    const w = 8
    const edge = img(w, 4, (x) => (x < 4 ? 0 : 255))
    const m = computePeaking(edge)
    const alphaAt = (x, y) => m[(y * w + x) * 4 + 3]
    expect(alphaAt(3, 1)).toBeGreaterThan(0)
    expect([...m.slice((1 * w + 3) * 4, (1 * w + 3) * 4 + 3)]).toEqual(COLORS.accent)
    expect(alphaAt(0, 1)).toBe(0)
    expect(alphaAt(6, 1)).toBe(0)
    expect(computePeaking(img(8, 4, () => 90)).every((v) => v === 0)).toBe(true)
  })
  it('ignores gentle gradients below the threshold', () => {
    const m = computePeaking(img(8, 4, (x) => x * 2))
    expect(m.every((v) => v === 0)).toBe(true)
  })
})

describe('gridSegments', () => {
  it('draws 4 lines for thirds and golden, a cross for centre, nothing for off', () => {
    expect(gridSegments('thirds', 300, 200)).toHaveLength(4)
    expect(gridSegments('golden', 300, 200)).toHaveLength(4)
    expect(gridSegments('centre', 300, 200)).toHaveLength(2)
    expect(gridSegments('off', 300, 200)).toHaveLength(0)
    expect(gridSegments('thirds', 300, 200)[0]).toEqual([100, 0, 100, 200])
  })
})
