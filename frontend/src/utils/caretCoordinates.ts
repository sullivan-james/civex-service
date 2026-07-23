// Textarea style properties that affect text layout/wrapping and therefore
// need to be mirrored exactly for the caret-coordinate mirror div below.
const MIRRORED_PROPERTIES: (keyof CSSStyleDeclaration)[] = [
  'boxSizing',
  'width',
  'fontFamily',
  'fontSize',
  'fontWeight',
  'lineHeight',
  'letterSpacing',
  'paddingTop',
  'paddingRight',
  'paddingBottom',
  'paddingLeft',
  'borderTopWidth',
  'borderRightWidth',
  'borderBottomWidth',
  'borderLeftWidth',
  'whiteSpace',
  'wordWrap',
]

/** Pixel offset of the caret at `position` within `el`, relative to `el`'s
 * own top-left corner — computed by mirroring the textarea into an
 * offscreen div and measuring a marker span inserted at that position. */
export function getCaretCoordinates(
  el: HTMLTextAreaElement,
  position: number,
): { top: number; left: number; height: number } {
  const div = document.createElement('div')
  const style = window.getComputedStyle(el)
  for (const prop of MIRRORED_PROPERTIES) {
    // CSSStyleDeclaration keys line up with style properties by design here.
    ;(div.style as unknown as Record<string, string>)[prop as string] = style[
      prop
    ] as string
  }
  div.style.position = 'absolute'
  div.style.visibility = 'hidden'
  div.style.top = '0'
  div.style.left = '0'
  div.style.height = 'auto'
  div.style.overflow = 'hidden'
  div.style.whiteSpace = 'pre-wrap'
  div.style.wordWrap = 'break-word'
  div.style.width = `${el.clientWidth}px`

  div.textContent = el.value.slice(0, position)
  const marker = document.createElement('span')
  marker.textContent = el.value.slice(position) || '.'
  div.appendChild(marker)

  document.body.appendChild(div)
  const top = marker.offsetTop - el.scrollTop
  const left = marker.offsetLeft - el.scrollLeft
  const height = marker.offsetHeight
  document.body.removeChild(div)

  return { top, left, height }
}
