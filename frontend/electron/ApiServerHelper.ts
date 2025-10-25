import { createServer, IncomingMessage, ServerResponse, request } from 'http'
import { AppState } from './main'

export class ApiServerHelper {
  private server: ReturnType<typeof createServer> | null = null
  private port: number = 3456
  private agentServerUrl: string = 'http://localhost:5000' // Agent S server URL

  constructor(private appState: AppState) {}

  // Forward request to Agent S server
  private forwardToAgentServer(
    method: string,
    path: string,
    body: string,
    callback: (error: Error | null, response?: any) => void
  ) {
    const url = new URL(path, this.agentServerUrl)
    const options = {
      hostname: url.hostname,
      port: url.port,
      path: url.pathname,
      method: method,
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body)
      }
    }

    const req = request(options, (res) => {
      let responseData = ''

      res.on('data', (chunk) => {
        responseData += chunk.toString()
      })

      res.on('end', () => {
        try {
          const parsed = JSON.parse(responseData)
          callback(null, parsed)
        } catch (e) {
          callback(null, { success: true, data: responseData })
        }
      })
    })

    req.on('error', (error) => {
      console.error('Error forwarding to Agent S:', error)
      callback(error)
    })

    if (body) {
      req.write(body)
    }
    req.end()
  }

  start() {
    this.server = createServer((req: IncomingMessage, res: ServerResponse) => {
      // Enable CORS
      res.setHeader('Access-Control-Allow-Origin', '*')
      res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
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
            // Parse JSON body with original, mode, and message fields
            const actionData = JSON.parse(body)

            console.log('Received current action:', actionData)

            // Send the full action data to the renderer process
            const mainWindow = this.appState.getMainWindow()
            if (mainWindow) {
              mainWindow.webContents.send('current-action-update', actionData)
            }

            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: true, received: actionData }))
          } catch (error) {
            console.error('Error processing current action:', error)
            res.writeHead(400, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: false, error: 'Invalid request' }))
          }
        })
      }
      // Handle POST /api/chat - forward to Agent S
      else if (req.method === 'POST' && req.url === '/api/chat') {
        let body = ''

        req.on('data', (chunk) => {
          body += chunk.toString()
        })

        req.on('end', () => {
          console.log('Forwarding chat message to Agent S:', body)
          this.forwardToAgentServer('POST', '/api/chat', body, (error, response) => {
            if (error) {
              res.writeHead(500, { 'Content-Type': 'application/json' })
              res.end(JSON.stringify({ success: false, error: error.message }))
            } else {
              res.writeHead(200, { 'Content-Type': 'application/json' })
              res.end(JSON.stringify(response))
            }
          })
        })
      }
      // Handle GET /api/stop - forward to Agent S
      else if (req.method === 'GET' && req.url === '/api/stop') {
        console.log('Forwarding stop request to Agent S')
        this.forwardToAgentServer('GET', '/api/stop', '', (error, response) => {
          if (error) {
            res.writeHead(500, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: false, error: error.message }))
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(response))
          }
        })
      }
      // Handle GET /api/pause - forward to Agent S
      else if (req.method === 'GET' && req.url === '/api/pause') {
        console.log('Forwarding pause request to Agent S')
        this.forwardToAgentServer('GET', '/api/pause', '', (error, response) => {
          if (error) {
            res.writeHead(500, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: false, error: error.message }))
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(response))
          }
        })
      }
      // Handle GET /api/resume - forward to Agent S
      else if (req.method === 'GET' && req.url === '/api/resume') {
        console.log('Forwarding resume request to Agent S')
        this.forwardToAgentServer('GET', '/api/resume', '', (error, response) => {
          if (error) {
            res.writeHead(500, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify({ success: false, error: error.message }))
          } else {
            res.writeHead(200, { 'Content-Type': 'application/json' })
            res.end(JSON.stringify(response))
          }
        })
      }
      else {
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
