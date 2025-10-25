// ProcessingHelper.ts

import { AppState } from "./main"

export class ProcessingHelper {
  private appState: AppState

  constructor(appState: AppState) {
    this.appState = appState
  }

  public async processScreenshots(): Promise<void> {
    const mainWindow = this.appState.getMainWindow()
    if (!mainWindow) return

    const view = this.appState.getView()
    const screenshotHelper = this.appState.getScreenshotHelper()

    if (view === "queue") {
      const screenshotQueue = screenshotHelper.getScreenshotQueue()
      if (screenshotQueue.length === 0) {
        mainWindow.webContents.send(this.appState.PROCESSING_EVENTS.NO_SCREENSHOTS)
        return
      }

      console.warn("[ProcessingHelper] Automatic model-based processing has been removed.")
      mainWindow.webContents.send(
        this.appState.PROCESSING_EVENTS.INITIAL_SOLUTION_ERROR,
        "Automatic processing has been disabled. Send your data to the REST service instead."
      )
      return
    }

    const extraScreenshotQueue = screenshotHelper.getExtraScreenshotQueue()
    if (extraScreenshotQueue.length === 0) {
      mainWindow.webContents.send(this.appState.PROCESSING_EVENTS.NO_SCREENSHOTS)
      return
    }

    console.warn("[ProcessingHelper] Debug processing via the legacy pipeline is no longer available.")
    mainWindow.webContents.send(
      this.appState.PROCESSING_EVENTS.DEBUG_ERROR,
      "Automatic debugging has been disabled. Use the REST service for follow-up actions."
    )
  }

  public cancelOngoingRequests(): void {
    this.appState.setHasDebugged(false)
  }
}
