/** Shots left across cards: null when there are no cards or any card does not report a count. */
export function shotsLeftOf(cards) {
  if (!cards?.length) return null
  let n = 0
  for (const c of cards) {
    if (typeof c.free_images !== 'number') return null
    n += c.free_images
  }
  return n
}
