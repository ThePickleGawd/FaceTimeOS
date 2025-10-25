// ipcHandlers.ts

import { ipcMain, app } from "electron"
import { AppState } from "./main"

export function initializeIpcHandlers(appState: AppState): void {
  ipcMain.handle(
    "update-content-dimensions",
    async (event, { width, height }: { width: number; height: number }) => {
      if (width && height) {
        appState.setWindowDimensions(width, height)
      }
    }
  )

  ipcMain.handle("delete-screenshot", async (event, path: string) => {
    return appState.deleteScreenshot(path)
  })

  ipcMain.handle("server-send-chat", async (_event, prompt: string) => {
    try {
      const response = await appState.apiServerHelper.sendChat(prompt)
      return response
    } catch (error) {
      console.error("Error sending chat prompt through server:", error)
      throw error
    }
  })

  ipcMain.handle("server-pause-agent", async () => {
    try {
      const response = await appState.apiServerHelper.pauseAgent()
      return response
    } catch (error) {
      console.error("Error pausing agent via server:", error)
      throw error
    }
  })

  ipcMain.handle("server-resume-agent", async () => {
    try {
      const response = await appState.apiServerHelper.resumeAgent()
      return response
    } catch (error) {
      console.error("Error resuming agent via server:", error)
      throw error
    }
  })

  ipcMain.handle("server-stop-agent", async () => {
    try {
      const response = await appState.apiServerHelper.stopAgent()
      return response
    } catch (error) {
      console.error("Error stopping agent via server:", error)
      throw error
    }
  })

  ipcMain.handle("take-screenshot", async () => {
    try {
      const screenshotPath = await appState.takeScreenshot()
      const preview = await appState.getImagePreview(screenshotPath)
      return { path: screenshotPath, preview }
    } catch (error) {
      console.error("Error taking screenshot:", error)
      throw error
    }
  })

  ipcMain.handle("get-screenshots", async () => {
    console.log({ view: appState.getView() })
    try {
      let previews = []
      if (appState.getView() === "queue") {
        previews = await Promise.all(
          appState.getScreenshotQueue().map(async (path) => ({
            path,
            preview: await appState.getImagePreview(path)
          }))
        )
      } else {
        previews = await Promise.all(
          appState.getExtraScreenshotQueue().map(async (path) => ({
            path,
            preview: await appState.getImagePreview(path)
          }))
        )
      }
      previews.forEach((preview: any) => console.log(preview.path))
      return previews
    } catch (error) {
      console.error("Error getting screenshots:", error)
      throw error
    }
  })

  ipcMain.handle("toggle-window", async () => {
    appState.toggleMainWindow()
  })

  ipcMain.handle("reset-queues", async () => {
    try {
      appState.clearQueues()
      console.log("Screenshot queues have been cleared.")
      return { success: true }
    } catch (error: any) {
      console.error("Error resetting queues:", error)
      return { success: false, error: error.message }
    }
  })

  ipcMain.handle("quit-app", () => {
    app.quit()
  })

  ipcMain.handle("set-window-click-through", async (_, clickThrough: boolean) => {
    const mainWindow = appState.getMainWindow()
    if (mainWindow) {
      mainWindow.setIgnoreMouseEvents(clickThrough, { forward: true })
    }
  })

  // Window movement handlers
  ipcMain.handle("move-window-left", async () => {
    appState.moveWindowLeft()
  })

  ipcMain.handle("move-window-right", async () => {
    appState.moveWindowRight()
  })

  ipcMain.handle("move-window-up", async () => {
    appState.moveWindowUp()
  })

  ipcMain.handle("move-window-down", async () => {
    appState.moveWindowDown()
  })

  ipcMain.handle("center-and-show-window", async () => {
    appState.centerAndShowWindow()
  })
}
