import { createServer, IncomingMessage, ServerResponse, request } from "http";
import { AppState } from "./main";
import path from "path";
import fs from "fs";

type ForwardResponse = unknown;
type ForwardHeaders = Record<string, string>;

export class ApiServerHelper {
  private static envLoaded = false;

  private server: ReturnType<typeof createServer> | null = null;
  private listenHost: string;
  private listenPort: number;
  private serverHost: string;
  private serverPort: number;

  constructor(private appState: AppState) {
    ApiServerHelper.ensureEnvLoaded();

    this.listenHost = process.env.UI_HOST || "127.0.0.1";
    this.listenPort = Number(process.env.UI_PORT || 8002);
    this.serverHost = process.env.SERVER_HOST || "127.0.0.1";
    this.serverPort = Number(process.env.SERVER_PORT || 8003);
  }

  private static ensureEnvLoaded(): void {
    if (ApiServerHelper.envLoaded) return;

    const candidatePaths = [
      path.resolve(process.cwd(), ".env"),
      path.resolve(process.cwd(), "..", ".env"),
      path.resolve(__dirname, "..", "..", ".env"),
    ];

    for (const envPath of candidatePaths) {
      if (!fs.existsSync(envPath)) continue;

      const contents = fs.readFileSync(envPath, "utf8");
      contents.split(/\r?\n/).forEach((line) => {
        const trimmed = line.trim();
        if (!trimmed || trimmed.startsWith("#")) return;

        const separatorIndex = trimmed.indexOf("=");
        if (separatorIndex === -1) return;

        const key = trimmed.slice(0, separatorIndex).trim();
        const rawValue = trimmed.slice(separatorIndex + 1).trim();
        const value = rawValue.replace(/^['"]|['"]$/g, "");

        if (!(key in process.env)) {
          process.env[key] = value;
        }
      });

      break;
    }

    ApiServerHelper.envLoaded = true;
  }

  private forwardToServer(
    method: string,
    pathName: string,
    body: string = "",
    headers: ForwardHeaders = {}
  ): Promise<ForwardResponse> {
    return new Promise((resolve, reject) => {
      const requestBody = body ?? "";
      const finalHeaders: ForwardHeaders = { ...headers };

      if (requestBody.length > 0) {
        if (!finalHeaders["Content-Type"]) {
          finalHeaders["Content-Type"] = "application/json";
        }
        finalHeaders["Content-Length"] =
          Buffer.byteLength(requestBody).toString();
      }

      const req = request(
        {
          hostname: this.serverHost,
          port: this.serverPort,
          path: pathName,
          method,
          headers: finalHeaders,
        },
        (res) => {
          let responseData = "";

          res.on("data", (chunk) => {
            responseData += chunk.toString();
          });

          res.on("end", () => {
            const statusCode = res.statusCode ?? 0;
            const contentType = res.headers["content-type"] || "";

            let parsed: ForwardResponse = responseData;
            if (
              responseData.length > 0 &&
              /application\/json/i.test(contentType)
            ) {
              try {
                parsed = JSON.parse(responseData);
              } catch (error) {
                console.warn(
                  "Failed to parse JSON response from server:",
                  error
                );
              }
            }

            if (statusCode >= 400) {
              const message =
                typeof parsed === "object" &&
                parsed !== null &&
                "error" in (parsed as Record<string, unknown>)
                  ? String((parsed as Record<string, unknown>).error)
                  : `Server responded with status ${statusCode}`;
              reject(new Error(message));
              return;
            }

            resolve(parsed);
          });
        }
      );

      req.on("error", (error) => {
        console.error("Error forwarding to server:", error);
        reject(error);
      });

      if (requestBody.length > 0) {
        req.write(requestBody);
      }

      req.end();
    });
  }

  public sendChat(prompt: string): Promise<ForwardResponse> {
    const payload = JSON.stringify({ Prompt: prompt, prompt });
    return this.forwardToServer("POST", "/api/chat", payload, {
      "Content-Type": "application/json",
    });
  }

  public pauseAgent(): Promise<ForwardResponse> {
    return this.forwardToServer("GET", "/api/pause");
  }

  public resumeAgent(): Promise<ForwardResponse> {
    return this.forwardToServer("GET", "/api/resume");
  }

  public stopAgent(): Promise<ForwardResponse> {
    return this.forwardToServer("GET", "/api/stop");
  }

  start(): void {
    this.server = createServer((req: IncomingMessage, res: ServerResponse) => {
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type");

      if (req.method === "OPTIONS") {
        res.writeHead(200);
        res.end();
        return;
      }

      if (req.method === "POST" && req.url === "/api/currentaction") {
        let body = "";

        req.on("data", (chunk) => {
          body += chunk.toString();
        });

        req.on("end", () => {
          try {
            const actionData = JSON.parse(body);
            console.log("Received current action:", actionData);

            const mainWindow = this.appState.getMainWindow();
            if (mainWindow) {
              mainWindow.webContents.send("current-action-update", actionData);
            }

            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify({ success: true, received: actionData }));
          } catch (error) {
            console.error("Error processing current action:", error);
            res.writeHead(400, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({ success: false, error: "Invalid request" })
            );
          }
        });
      } else if (req.method === "POST" && req.url === "/api/chat") {
        let body = "";

        req.on("data", (chunk) => {
          body += chunk.toString();
        });

        req.on("end", async () => {
          try {
            const response = await this.forwardToServer(
              "POST",
              "/api/chat",
              body,
              {
                "Content-Type": "application/json",
              }
            );
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(response));
          } catch (error: any) {
            console.error("Error forwarding chat to server:", error);
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                success: false,
                error: error?.message || "Unknown error",
              })
            );
          }
        });
      } else if (req.method === "GET" && req.url === "/api/stop") {
        console.log("Forwarding stop request to server");
        this.forwardToServer("GET", "/api/stop")
          .then((response) => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(response));
          })
          .catch((error: any) => {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                success: false,
                error: error?.message || "Unknown error",
              })
            );
          });
      } else if (req.method === "GET" && req.url === "/api/pause") {
        console.log("Forwarding pause request to server");
        this.forwardToServer("GET", "/api/pause")
          .then((response) => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(response));
          })
          .catch((error: any) => {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                success: false,
                error: error?.message || "Unknown error",
              })
            );
          });
      } else if (req.method === "GET" && req.url === "/api/resume") {
        console.log("Forwarding resume request to server");
        this.forwardToServer("GET", "/api/resume")
          .then((response) => {
            res.writeHead(200, { "Content-Type": "application/json" });
            res.end(JSON.stringify(response));
          })
          .catch((error: any) => {
            res.writeHead(500, { "Content-Type": "application/json" });
            res.end(
              JSON.stringify({
                success: false,
                error: error?.message || "Unknown error",
              })
            );
          });
      } else {
        res.writeHead(404, { "Content-Type": "application/json" });
        res.end(JSON.stringify({ error: "Not found" }));
      }
    });

    this.server.listen(this.listenPort, this.listenHost, () => {
      console.log(
        `API bridge listening on http://${this.listenHost}:${this.listenPort}`
      );
    });
  }

  stop(): void {
    if (this.server) {
      this.server.close();
      this.server = null;
    }
  }
}
