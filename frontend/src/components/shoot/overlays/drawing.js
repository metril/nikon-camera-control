import { gridSegments, COLORS } from './analysis.js'

const rgb = (c, a = 1) => `rgba(${c[0]},${c[1]},${c[2]},${a})`

export function drawGrid(ctx, mode, w, h) {
  const seg = gridSegments(mode, w, h)
  if (!seg.length) return
  ctx.save()
  ctx.strokeStyle = 'rgba(255,255,255,.4)'
  ctx.lineWidth = Math.max(1, w / 640)
  ctx.beginPath()
  for (const [x1, y1, x2, y2] of seg) {
    ctx.moveTo(x1, y1)
    ctx.lineTo(x2, y2)
  }
  ctx.stroke()
  ctx.restore()
}

/** Corner brackets around a focus point. state: 'moving' (accent) | 'locked' (ok) | 'idle'. */
export function drawFocusBrackets(ctx, pt, w, state) {
  const s = w / 600
  const bw = 56 * s
  const bh = 40 * s
  const c = 10 * s
  const x0 = pt.x - bw / 2
  const y0 = pt.y - bh / 2
  ctx.save()
  ctx.strokeStyle =
    state === 'locked'
      ? rgb(COLORS.ok)
      : state === 'moving'
        ? rgb(COLORS.accent)
        : 'rgba(255,255,255,.85)'
  ctx.lineWidth = Math.max(2, 2 * s)
  ctx.beginPath()
  for (const [x, y, sx, sy] of [
    [x0, y0, 1, 1],
    [x0 + bw, y0, -1, 1],
    [x0, y0 + bh, 1, -1],
    [x0 + bw, y0 + bh, -1, -1],
  ]) {
    ctx.moveTo(x + sx * c, y)
    ctx.lineTo(x, y)
    ctx.lineTo(x, y + sy * c)
  }
  ctx.stroke()
  ctx.restore()
}

/** 3x magnifier of `source` around pt. */
export function drawLoupe(ctx, source, pt, w) {
  const s = w / 600
  const R = 78 * s
  const src = R / 3
  ctx.save()
  ctx.beginPath()
  ctx.arc(pt.x, pt.y, R, 0, Math.PI * 2)
  ctx.clip()
  ctx.imageSmoothingEnabled = false
  ctx.drawImage(source, pt.x - src, pt.y - src, src * 2, src * 2, pt.x - R, pt.y - R, R * 2, R * 2)
  ctx.restore()
  ctx.save()
  ctx.strokeStyle = '#ececec'
  ctx.lineWidth = Math.max(2, 2 * s)
  ctx.beginPath()
  ctx.arc(pt.x, pt.y, R, 0, Math.PI * 2)
  ctx.stroke()
  ctx.fillStyle = 'rgba(21,21,21,.85)'
  ctx.fillRect(pt.x - 18 * s, pt.y + R - 22 * s, 36 * s, 18 * s)
  ctx.fillStyle = '#ececec'
  ctx.font = `500 ${11 * s}px monospace`
  ctx.textAlign = 'center'
  ctx.fillText('3×', pt.x, pt.y + R - 9 * s)
  ctx.restore()
}
