/** Decodes a fetch response body stream into raw SSE `data:` payloads (the
 * text after `data: `, still unparsed) — byte/line buffering only, no
 * knowledge of what the payload means. api/ai.ts's streamChat() is a thin
 * AiEvent-specific JSON.parse wrapper over this. */
export async function* parseSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
): AsyncGenerator<string> {
  const decoder = new TextDecoder()
  let buf = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    const lines = buf.split('\n')
    buf = lines.pop() ?? ''
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        yield line.slice(6)
      }
    }
  }
}
