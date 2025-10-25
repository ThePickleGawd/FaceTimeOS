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
    setChatLoading(true)
    setChatInput("")

    // Clear previous history and start fresh
    setOriginalHistory([])

    // Start the agent
    setIsAgentRunning(true)

    // Start showing agent status
    setAgentStatus("Agent is thinking...")

    // Clear previous timeouts
    agentTimeoutsRef.current.forEach(clearTimeout)
    agentTimeoutsRef.current = []

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
      // Pause the agent - send pause request to Agent S
      try {
        await window.electronAPI.pauseAgent()
        setIsAgentRunning(false)
        setAgentStatus(null)
        setChatLoading(false)

        // Clear all pending timeouts
        agentTimeoutsRef.current.forEach(clearTimeout)
        agentTimeoutsRef.current = []

        setOriginalHistory((history) => [...history, "Agent paused by user."])
      } catch (err) {
        console.error('Error pausing agent:', err)
      }
    } else {
      // Resume the agent - send resume request to Agent S
      try {
        await window.electronAPI.resumeAgent()
        setIsAgentRunning(true)
        setAgentStatus("Resuming...")
        setOriginalHistory((history) => [...history, "Agent resumed by user."])
      } catch (err) {
        console.error('Error resuming agent:', err)
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
      // Update agent status with the message (shown in bar)
      setAgentStatus(action.message)
      setIsAgentRunning(true)

      // Add the original text to history (shown in expanded view)
      setOriginalHistory((history) => [...history, action.original])

      // Check if this is a completion message
      if (action.message.toLowerCase().includes("completed") ||
          action.message.toLowerCase().includes("finished") ||
          action.message.toLowerCase().includes("done")) {
        // Reset state after a short delay to show the completion message
        setTimeout(() => {
          setIsAgentRunning(false)
          setAgentStatus(null)
          setChatLoading(false)
        }, 2000)
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
      <div className="bg-transparent w-full">
        <div className="px-2 py-1">
          <Toast
            open={toastOpen}
            onOpenChange={setToastOpen}
            variant={toastMessage.variant}
            duration={3000}
          >
            <ToastTitle>{toastMessage.title}</ToastTitle>
            <ToastDescription>{toastMessage.description}</ToastDescription>
          </Toast>
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
            <div className="mt-4 w-full max-w-2xl mx-auto liquid-glass chat-container p-4 flex flex-col" style={{ pointerEvents: "auto" }}>
            {/* Close button */}
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-xs text-white/70 font-medium">
                Agent Thought Process
              </h3>
              <button
                onClick={() => setIsChatOpen(false)}
                className="text-white/50 hover:text-white/90 transition-colors text-xs"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto max-h-64 min-h-[120px] font-mono">
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
