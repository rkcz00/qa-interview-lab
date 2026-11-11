import { writeFileSync, renameSync } from 'node:fs'
import { preview } from 'vite'

const readyFile = process.argv[2]
try {
  const server = await preview({ preview: { host: '127.0.0.1', port: 0, strictPort: true }, logLevel: 'silent' })
  const address = server.httpServer.address()
  if (!address || typeof address === 'string') throw new Error('Missing loopback address')
  writeFileSync(readyFile + '.tmp', String(address.port), 'ascii')
  renameSync(readyFile + '.tmp', readyFile)
} catch {
  writeFileSync(readyFile, 'error FrontendStartupError', 'ascii')
  process.exitCode = 1
}
