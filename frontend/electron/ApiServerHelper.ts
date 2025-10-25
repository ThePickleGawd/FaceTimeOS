import { createServer, IncomingMessage, ServerResponse } from 'http'
import { AppState } from './main'

export class ApiServerHelper {
  private server: ReturnType<typeof createServer> | null = null
  private port: number = 3456

  constructor(private appState: AppState) {}

  start() {
    this.server = createServer((req: IncomingMessage, res: ServerResponse) => {
      // Enable CORS
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS')
      res.setHeader('Access-Control-Allow-Headers', 'Content-Type')

      // Handle preflight
      if (req.method === 'OPTIONS') {
        res.writeHead(200)
        res.end()
        return
      }

      // Handle POST /api/currentaction
      if (req.method === 'POST' && req.url === '/api/currentaction') {
        let body = ''

        req.on('data', (chunk) => {
          body += chunk.toString()
        })

        req.on('end', () => {
          try {
            // The body should be a plain string with the current action
            const currentAction = body.trim()

            console.log('Received current action:', currentAction)

            // Send the action to the renderer process
            const mainWindow = this.appState.getMainWindow()
            if (mainWindow) {
              mainWindow.webContents.send('current-action-update', currentAction)
            }

            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: true, received: currentAction }))
          } catch (error) {
            console.error('Error processing current action:', error)
            res.writeHead(400, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: false, error: 'Invalid request' }))
          }
        })
      } else {
        res.writeHead(404, { 'Content-Type': 'application/json' })
        res.end(JSON.stringify({ error: 'Not found' }))
      }
    })

    this.server.listen(this.port, () => {
      console.log(`API server listening on http://localhost:${this.port}`)
    })
  }

  stop() {
    if (this.server) {
      this.server.close()
      this.server = null
    }
  }
}
