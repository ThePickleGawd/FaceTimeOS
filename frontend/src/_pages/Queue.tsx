import React, { useState, useEffect, useRef } from "react"
import { useQuery } from "react-query"
import ScreenshotQueue from "../components/Queue/ScreenshotQueue"
import {
  Toast,
  ToastTitle,
  ToastDescription,
  ToastVariant,
  ToastMessage
} from "../components/ui/toast"
import QueueCommands from "../components/Queue/QueueCommands"

interface QueueProps {
  setView: React.Dispatch<React.SetStateAction<"queue" | "solutions" | "debug">>
}

const Queue: React.FC<QueueProps> = ({ setView }) => {
  const [toastOpen, setToastOpen] = useState(false)
  const [toastMessage, setToastMessage] = useState<ToastMessage>({
    title: "",
    description: "",
    variant: "neutral"
  })

  const contentRef = useRef<HTMLDivElement>(null)

  const [chatInput, setChatInput] = useState("")
  const [originalHistory, setOriginalHistory] = useState<string[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [isChatOpen, setIsChatOpen] = useState(false)
  const chatMessagesEndRef = useRef<HTMLDivElement>(null)
  const [agentStatus, setAgentStatus] = useState<string | null>(null)
  const [isAgentRunning, setIsAgentRunning] = useState(false)

  const barRef = useRef<HTMLDivElement>(null)
  const agentTimeoutsRef = useRef<NodeJS.Timeout[]>([])
  const closeButtonRef = useRef<HTMLButtonElement>(null)

  const { data: screenshots = [], refetch } = useQuery<Array<{ path: string; preview: string }>, Error>(
    ["screenshots"],
    async () => {
      try {
        const existing = await window.electronAPI.getScreenshots()
        return existing
      } catch (error) {
        console.error("Error loading screenshots:", error)
        showToast("Error", "Failed to load existing screenshots", "error")
        return []
      }
    },
    {
      staleTime: Infinity,
      cacheTime: Infinity,
      refetchOnWindowFocus: true,
      refetchOnMount: true
    }
  )

  const showToast = (
    title: string,
    description: string,
    variant: ToastVariant
  ) => {
    setToastMessage({ title, description, variant })
    setToastOpen(true)
  }

  const handleDeleteScreenshot = async (index: number) => {
    const screenshotToDelete = screenshots[index]

    try {
      const response = await window.electronAPI.deleteScreenshot(
        screenshotToDelete.path
      )

      if (response.success) {
        refetch()
      } else {
        console.error("Failed to delete screenshot:", response.error)
        showToast("Error", "Failed to delete the screenshot file", "error")
      }
    } catch (error) {
      console.error("Error deleting screenshot:", error)
    }
  }

  const handleTogglePopup = () => { 
    setIsChatOpen(!isChatOpen)
  }

  const handleChatSubmit = async () => {
    if (!chatInput.trim()) return

    const userMessage = chatInput
    setChatInput("")

    // Stop any existing agent thread first to prevent "active thread" errors
    try {
      await window.electronAPI.stopAgent()
    } catch (err) {
      console.log('No active agent to stop, continuing...')
    }

    // Clear previous history and start fresh
    setOriginalHistory([])

    // Clear previous timeouts
    agentTimeoutsRef.current.forEach(clearTimeout)
    agentTimeoutsRef.current = []

    // Now start the new agent request
    setChatLoading(true)
    setIsAgentRunning(true)
    setAgentStatus("Agent is thinking...")

    // Send message to Agent S via POST /api/chat
    // The actual status updates will come from POST /api/currentaction
    try {
      const response = await window.electronAPI.sendChatPrompt(userMessage)
      console.log("Chat message forwarded through server:", response)
    } catch (err) {
      console.error('Error sending chat message:', err)
      setAgentStatus(null)
      setChatLoading(false)
      setIsAgentRunning(false)
      setOriginalHistory((history) => [...history, `Error: ${String(err)}`])
    }
  }

  const handlePauseAgent = async () => {
    if (isAgentRunning) {
      // Stop the agent completely (changed from pause to stop for better reliability)
      try {
        await window.electronAPI.stopAgent()
        setIsAgentRunning(false)
        setAgentStatus(null)
        setChatLoading(false)

        // Clear all pending timeouts
        agentTimeoutsRef.current.forEach(clearTimeout)
        agentTimeoutsRef.current = []

        setOriginalHistory((history) => [...history, "Agent stopped by user."])
      } catch (err) {
        console.error('Error stopping agent:', err)
      }
    }
  }

  const handleStopAgent = async () => {
    // Stop the agent completely - send stop request to Agent S
    try {
      await window.electronAPI.stopAgent()
      setIsAgentRunning(false)
      setAgentStatus(null)
      setChatLoading(false)

      // Clear all pending timeouts
      agentTimeoutsRef.current.forEach(clearTimeout)
      agentTimeoutsRef.current = []

      setOriginalHistory((history) => [...history, "Agent stopped by user."])
    } catch (err) {
      console.error('Error stopping agent:', err)
    }
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (isChatOpen && chatMessagesEndRef.current) {
      chatMessagesEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [originalHistory, isChatOpen])

  // Listen for current action updates from Flask server
  useEffect(() => {
    const unsubscribe = window.electronAPI.onCurrentActionUpdate((action) => {
      const textSummary =
        (typeof action?.text_summary === "string" && action.text_summary.trim()) ||
        (typeof action?.voice_summary === "string" && action.voice_summary.trim()) ||
        null

      const originalText =
        (typeof action?.original === "string" && action.original.trim()) ||
        null

      setAgentStatus(textSummary)
      setIsAgentRunning(true)

      // Add the original text to history (shown in expanded view)
      const historyEntry = originalText ?? textSummary
      if (historyEntry) {
        setOriginalHistory((history) => [...history, historyEntry])
      }

      // Check if this is a completion message
      const normalized = textSummary?.toLowerCase() ?? ""
      if (
        normalized.includes("completed") ||
        normalized.includes("finished") ||
        normalized.includes("done") ||
        normalized.includes("stopped")
      ) {
        // Reset state after a short delay to show the completion message
        const timeout = setTimeout(() => {
          setIsAgentRunning(false)
          setAgentStatus(null)
          setChatLoading(false)
        }, 2000)
        agentTimeoutsRef.current.push(timeout)
      }
    })

    return () => {
      unsubscribe()
    }
  }, [])


  useEffect(() => {
    const updateDimensions = () => {
      if (contentRef.current) {
        const contentHeight = contentRef.current.scrollHeight
        const contentWidth = contentRef.current.scrollWidth
        window.electronAPI.updateContentDimensions({
          width: contentWidth,
          height: contentHeight
        })
      }
    }

    const resizeObserver = new ResizeObserver(updateDimensions)
    if (contentRef.current) {
      resizeObserver.observe(contentRef.current)
    }
    updateDimensions()

    const cleanupFunctions = [
      window.electronAPI.onScreenshotTaken(() => refetch()),
      window.electronAPI.onResetView(() => refetch()),
      window.electronAPI.onSolutionError((error: string) => {
        showToast(
          "Processing Failed",
          "There was an error processing your screenshots.",
          "error"
        )
        setView("queue")
        console.error("Processing error:", error)
      }),
      window.electronAPI.onProcessingNoScreenshots(() => {
        showToast(
          "No Screenshots",
          "There are no screenshots to process.",
          "neutral"
        )
      })
    ]

    return () => {
      resizeObserver.disconnect()
      cleanupFunctions.forEach((cleanup) => cleanup())
    }
  }, [])

  const handleChatInputChange = (value: string) => {
    setChatInput(value)
  }

  // Track mouse position for close button click-through
  useEffect(() => {
    if (!isChatOpen) return

    let rafId: number | null = null

    const handleMouseMove = (e: MouseEvent) => {
      if (rafId) return

      rafId = requestAnimationFrame(() => {
        if (closeButtonRef.current) {
          const rect = closeButtonRef.current.getBoundingClientRect()
          const isOverButton =
            e.clientX >= rect.left &&
            e.clientX <= rect.right &&
            e.clientY >= rect.top &&
            e.clientY <= rect.bottom

          if (isOverButton) {
            window.electronAPI?.setWindowClickThrough(false)
          }
        }
        rafId = null
      })
    }

    document.addEventListener('mousemove', handleMouseMove)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      if (rafId) cancelAnimationFrame(rafId)
    }
  }, [isChatOpen])


  return (
    <div
      ref={barRef}
      style={{
        position: "relative",
        width: "100%",
        pointerEvents: "none"
      }}
      className="select-none"
    >
      <div className="bg-transparent w-full" style={{ pointerEvents: "none" }}>
        <div className="px-1 py-4" style={{ pointerEvents: "none" }}>
          <div style={{ pointerEvents: "auto" }}>
            <Toast
              open={toastOpen}
              onOpenChange={setToastOpen}
              variant={toastMessage.variant}
              duration={3000}
            >
              <ToastTitle>{toastMessage.title}</ToastTitle>
              <ToastDescription>{toastMessage.description}</ToastDescription>
            </Toast>
          </div>
          <div style={{ pointerEvents: "auto" }}>
            <QueueCommands
              chatInput={chatInput}
              onChatInputChange={handleChatInputChange}
              onChatSubmit={handleChatSubmit}
              chatLoading={chatLoading}
              agentStatus={agentStatus}
              isAgentRunning={isAgentRunning}
              onPauseAgent={handlePauseAgent}
              isChatOpen={isChatOpen}
              onTogglePopup={handleTogglePopup}
            />
          </div>

          {/* Conditional Text/Log View */}
          {isChatOpen && (
            <div className="mt-4 w-full max-w-2xl mx-auto liquid-glass chat-container p-4 flex flex-col" style={{ pointerEvents: "none" }}>
            {/* Close button */}
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-xs text-white/70 font-medium">
                Agent Thought Process
              </h3>
              <button
                ref={closeButtonRef}
                onClick={() => setIsChatOpen(false)}
                className="text-white/50 hover:text-white/90 transition-colors text-xs"
                style={{ pointerEvents: "auto" }}
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto max-h-64 min-h-[120px] font-mono" style={{ pointerEvents: "none" }}>
              {originalHistory.length === 0 ? (
                <div className="text-sm text-white/50 mt-8">
                  The agent's thought process and steps will appear here
                  <br />
                  <span className="text-xs text-white/30">Click the bar above and type a command to get started</span>
                </div>
              ) : (
                originalHistory.map((text, idx) => (
                  <div
                    key={idx}
                    className="text-white/80 text-xs mb-2 leading-relaxed"
                    style={{ wordBreak: "break-word", whiteSpace: "pre-wrap" }}
                  >
                    {text}
                  </div>
                ))
              )}
              {chatLoading && (
                <div className="text-white/60 text-xs mb-2">
                  <span className="inline-flex items-center">
                    <span className="animate-pulse">●</span>
                    <span className="animate-pulse animation-delay-200">●</span>
                    <span className="animate-pulse animation-delay-400">●</span>
                    <span className="ml-2">Agent is thinking...</span>
                  </span>
                </div>
              )}
              {/* Auto-scroll anchor */}
              <div ref={chatMessagesEndRef} />
            </div>
          </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Queue
