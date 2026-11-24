/**
 * Pure pixel analysis for the live view overlays. Inputs are ImageData-like objects
 * ({ width, height, data: RGBA bytes }) already downsampled by the caller, so these stay cheap.
 */

export const HIGHLIGHT_AT = 252
export const SHADOW_AT = 3
export const PEAK_THRESHOLD = 46

// Canvas can't read Tailwind classes; these mirror the camera-* tokens in tailwind.config.js.
export const COLORS = {
  accent: [249, 115, 22],
  danger: [248, 113, 113],
  cold: [96, 165, 250],
  ok: [74, 222, 128],
}

const luma = (d, i) => d[i] * 0.299 + d[i + 1] * 0.587 + d[i + 2] * 0.114

/** Luminance histogram: 256 bins plus the fraction of pixels clipped at each end. */
export function computeHistogram(img) {
  const { data } = img
  const bins = new Uint32Array(256)
  const total = Math.floor(data.length / 4)
  let lo = 0
  let hi = 0
  for (let i = 0; i < total * 4; i += 4) {
    const l = Math.round(luma(data, i))
    bins[l]++
    if (l <= SHADOW_AT) lo++
    else if (l >= HIGHLIGHT_AT) hi++
  }
  return { bins, lo: total ? lo / total : 0, hi: total ? hi / total : 0 }
}

function emptyMask(img) {
  return new Uint8ClampedArray(img.width * img.height * 4)
}

/** RGBA mask: highlights in the danger colour, shadows in the cold colour. */
export function computeClipping(img, alpha = 170) {
  const { data } = img
  const out = emptyMask(img)
  for (let i = 0; i < data.length; i += 4) {
    const l = luma(data, i)
    const c = l >= HIGHLIGHT_AT ? COLORS.danger : l <= SHADOW_AT ? COLORS.cold : null
    if (c) {
      out[i] = c[0]
      out[i + 1] = c[1]
      out[i + 2] = c[2]
      out[i + 3] = alpha
    }
  }
  return out
}

/** RGBA mask in the accent colour wherever the luminance gradient (right plus below) is steep. */
export function computePeaking(img, threshold = PEAK_THRESHOLD, alpha = 230) {
  const { width: w, height: h, data } = img
  const out = emptyMask(img)
  const [r, g, b] = COLORS.accent
  for (let y = 0; y < h - 1; y++) {
    for (let x = 0; x < w - 1; x++) {
      const i = (y * w + x) * 4
      const l = luma(data, i)
      const grad = Math.abs(l - luma(data, i + 4)) + Math.abs(l - luma(data, i + w * 4))
      if (grad > threshold) {
        out[i] = r
        out[i + 1] = g
        out[i + 2] = b
        out[i + 3] = alpha
      }
    }
  }
  return out
}

/** Line segments [x1, y1, x2, y2] for a grid mode on a w by h frame. */
export function gridSegments(mode, w, h) {
  const seg = []
  if (mode === 'thirds' || mode === 'golden') {
    const fr = mode === 'thirds' ? [1 / 3, 2 / 3] : [0.382, 0.618]
    for (const f of fr) seg.push([w * f, 0, w * f, h], [0, h * f, w, h * f])
  } else if (mode === 'centre') {
    const c = Math.min(w, h) * 0.03
    seg.push([w / 2 - c, h / 2, w / 2 + c, h / 2], [w / 2, h / 2 - c, w / 2, h / 2 + c])
  }
  return seg
}
