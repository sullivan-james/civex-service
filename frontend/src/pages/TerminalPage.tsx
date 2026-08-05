import { useEffect, useRef } from 'react'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import '@xterm/xterm/css/xterm.css'
import { PageHeader } from '../components/ui'

export default function TerminalPage() {
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const term = new Terminal({
      cursorBlink: true,
      fontSize: 13,
      fontFamily: 'monospace',
    })
    const fitAddon = new FitAddon()
    term.loadAddon(fitAddon)
    term.open(containerRef.current!)

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    const ws = new WebSocket(
      `${protocol}//${window.location.host}/api/terminal/ws`,
    )
    ws.binaryType = 'arraybuffer'

    ws.onmessage = (e) => {
      if (e.data instanceof ArrayBuffer) {
        term.write(new Uint8Array(e.data))
      } else {
        term.write(e.data as string)
      }
    }

    const sendResize = () => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(
          JSON.stringify({ type: 'resize', cols: term.cols, rows: term.rows }),
        )
      }
    }

    ws.onopen = () => {
      fitAddon.fit()
      sendResize()
    }
    ws.onclose = () => term.write('\r\n\x1b[31m[disconnected]\x1b[0m\r\n')

    // Sent as binary so the backend can tell raw keystrokes apart from JSON resize control messages.
    term.onData((data) => {
      if (ws.readyState === WebSocket.OPEN)
        ws.send(new TextEncoder().encode(data))
    })

    term.onResize(sendResize)

    const onWindowResize = () => fitAddon.fit()
    window.addEventListener('resize', onWindowResize)

    return () => {
      window.removeEventListener('resize', onWindowResize)
      ws.close()
      term.dispose()
    }
  }, [])

  return (
    <>
      <PageHeader
        title="Terminal"
        description="Shell running in the civex server process"
      />
      <div
        ref={containerRef}
        className="rounded border border-border overflow-hidden"
        style={{ height: 'calc(100vh - 220px)' }}
      />
    </>
  )
}
