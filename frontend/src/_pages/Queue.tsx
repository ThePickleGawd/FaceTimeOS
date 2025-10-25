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
  const [chatMessages, setChatMessages] = useState<{role: "user"|"gemini", text: string}[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const [isChatOpen, setIsChatOpen] = useState(false)
  const chatInputRef = useRef<HTMLInputElement>(null)
  const chatMessagesEndRef = useRef<HTMLDivElement>(null)
  const [agentStatus, setAgentStatus] = useState<string | null>(null)
  const [isAgentRunning, setIsAgentRunning] = useState(false)
  const [isFirstUse, setIsFirstUse] = useState(true)

  const [currentModel, setCurrentModel] = useState<{ provider: string; model: string }>({ provider: "gemini", model: "gemini-2.0-flash" })

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

  const handleChatSubmit = async () => {
    if (!chatInput.trim()) return

    // Add user message to chat
    const userMessage = chatInput
    setChatMessages((msgs) => [...msgs, { role: "user", text: userMessage }])
    setChatLoading(true)
    setChatInput("")

    // Start the agent (like clicking the Start button)
    setIsAgentRunning(true)
    setIsFirstUse(false)

    // Start showing agent status (don't open popup yet)
    setAgentStatus("Agent is thinking...")

    // Add initial thinking message to chat (detailed)
    setChatMessages((msgs) => [...msgs, {
      role: "gemini",
      text: "Let me think about how to help you with that..."
    }])

    // Clear previous timeouts
    agentTimeoutsRef.current.forEach(clearTimeout)
    agentTimeoutsRef.current = []

    // Simulate agent thinking process with status updates
    // This would be replaced with actual agent status updates
    const timeout1 = setTimeout(() => {
      setAgentStatus("Agent is analyzing the task...")
      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: "First, I need to understand what you're asking. Let me break down the task: " + userMessage
      }])
    }, 1000)
    agentTimeoutsRef.current.push(timeout1)

    const timeout2 = setTimeout(() => {
      setAgentStatus("Agent is planning steps...")
      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: "Now I'm thinking about the best approach. For this task, I would need to:\n1. Understand the specific requirements\n2. Determine what tools or applications to use\n3. Execute the steps in the right order"
      }])
    }, 2500)
    agentTimeoutsRef.current.push(timeout2)

    // Send message to LLM
    try {
      const response = await window.electronAPI.invoke("gemini-chat", userMessage)

      // Simulate finding the solution
      const timeout3 = setTimeout(() => {
        setAgentStatus("Agent is executing...")
        setChatMessages((msgs) => [...msgs, {
          role: "gemini",
          text: "Perfect! I found a solution. " + response
        }])
      }, 4000)
      agentTimeoutsRef.current.push(timeout3)

      // Complete the task
      const timeout4 = setTimeout(() => {
        setAgentStatus(null)
        setChatLoading(false)
        setIsAgentRunning(false)
      }, 5500)
      agentTimeoutsRef.current.push(timeout4)
    } catch (err) {
      setChatMessages((msgs) => [...msgs, { role: "gemini", text: "Error: " + String(err) }])
      setAgentStatus(null)
      setChatLoading(false)
      setIsAgentRunning(false)
    }
  }

  const handlePauseAgent = () => {
    if (isAgentRunning) {
      // Pause the agent - stop all processing
      setIsAgentRunning(false)
      setAgentStatus(null)
      setChatLoading(false)

      // Clear all pending timeouts
      agentTimeoutsRef.current.forEach(clearTimeout)
      agentTimeoutsRef.current = []

      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: "Agent paused by user."
      }])
    }
  }

  const handleBarClick = () => {
    setIsChatOpen(!isChatOpen)
  }

  // Auto-scroll to bottom when new messages arrive
  useEffect(() => {
    if (isChatOpen && chatMessagesEndRef.current) {
      chatMessagesEndRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [chatMessages, isChatOpen])

  // Listen for current action updates from Flask server
  useEffect(() => {
    const unsubscribe = window.electronAPI.onCurrentActionUpdate((action: string) => {
      // Update agent status with the current action
      setAgentStatus(action)
      setIsAgentRunning(true)

      // Add detailed message to chat if open
      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: action
      }])
    })

    return () => {
      unsubscribe()
    }
  }, [])

  const handleChatSend = async () => {
    if (!chatInput.trim()) return

    const userMessage = chatInput
    setChatMessages((msgs) => [...msgs, { role: "user", text: userMessage }])
    setChatLoading(true)
    setChatInput("")

    // Start the agent when sending from popup
    setIsAgentRunning(true)
    setAgentStatus("Agent is thinking...")

    // Add initial thinking message
    setChatMessages((msgs) => [...msgs, {
      role: "gemini",
      text: "Let me think about how to help you with that..."
    }])

    // Clear previous timeouts
    agentTimeoutsRef.current.forEach(clearTimeout)
    agentTimeoutsRef.current = []

    // Status updates
    const timeout1 = setTimeout(() => {
      setAgentStatus("Agent is analyzing the task...")
      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: "First, I need to understand what you're asking. Let me break down the task: " + userMessage
      }])
    }, 1000)
    agentTimeoutsRef.current.push(timeout1)

    const timeout2 = setTimeout(() => {
      setAgentStatus("Agent is planning steps...")
      setChatMessages((msgs) => [...msgs, {
        role: "gemini",
        text: "Now I'm thinking about the best approach. For this task, I would need to:\n1. Understand the specific requirements\n2. Determine what tools or applications to use\n3. Execute the steps in the right order"
      }])
    }, 2500)
    agentTimeoutsRef.current.push(timeout2)

    try {
      const response = await window.electronAPI.invoke("gemini-chat", userMessage)

      const timeout3 = setTimeout(() => {
        setAgentStatus("Agent is executing...")
        setChatMessages((msgs) => [...msgs, {
          role: "gemini",
          text: "Perfect! I found a solution. " + response
        }])
      }, 4000)
      agentTimeoutsRef.current.push(timeout3)

      const timeout4 = setTimeout(() => {
        setAgentStatus(null)
        setChatLoading(false)
        setIsAgentRunning(false)
        chatInputRef.current?.focus()
      }, 5500)
      agentTimeoutsRef.current.push(timeout4)
    } catch (err) {
      setChatMessages((msgs) => [...msgs, { role: "gemini", text: "Error: " + String(err) }])
      setAgentStatus(null)
      setChatLoading(false)
      setIsAgentRunning(false)
      chatInputRef.current?.focus()
    }
  }

  // Load current model configuration on mount
  useEffect(() => {
    const loadCurrentModel = async () => {
      try {
        const config = await window.electronAPI.getCurrentLlmConfig();
        setCurrentModel({ provider: config.provider, model: config.model });
      } catch (error) {
        console.error('Error loading current model config:', error);
      }
    };
    loadCurrentModel();
  }, []);

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

  // Seamless screenshot-to-LLM flow
  useEffect(() => {
    // Listen for screenshot taken event
    const unsubscribe = window.electronAPI.onScreenshotTaken(async (data) => {
      // Refetch screenshots to update the queue
      await refetch();
      // Show loading in chat
      setChatLoading(true);
      try {
        // Get the latest screenshot path
        const latest = data?.path || (Array.isArray(data) && data.length > 0 && data[data.length - 1]?.path);
        if (latest) {
          // Call the LLM to process the screenshot
          const response = await window.electronAPI.invoke("analyze-image-file", latest);
          setChatMessages((msgs) => [...msgs, { role: "gemini", text: response.text }]);
        }
      } catch (err) {
        setChatMessages((msgs) => [...msgs, { role: "gemini", text: "Error: " + String(err) }]);
      } finally {
        setChatLoading(false);
      }
    });
    return () => {
      unsubscribe && unsubscribe();
    };
  }, [refetch]);

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
              onBarClick={handleBarClick}
              isAgentRunning={isAgentRunning}
              onPauseAgent={handlePauseAgent}
              isFirstUse={isFirstUse}
              isChatOpen={isChatOpen}
            />
          </div>

          {/* Conditional Chat Interface */}
          {isChatOpen && (
            <div className="mt-4 w-full max-w-2xl mx-auto liquid-glass chat-container p-4 flex flex-col" style={{ pointerEvents: "auto" }}>
            {/* Close button */}
            <div className="flex justify-between items-center mb-2">
              <h3 className="text-xs text-white/70 font-medium">
                {isFirstUse ? "Detailed Agent Thoughts" : "AI Agent Chat"}
              </h3>
              <button
                onClick={() => setIsChatOpen(false)}
                className="text-white/50 hover:text-white/90 transition-colors text-xs"
              >
                ✕
              </button>
            </div>
            <div className="flex-1 overflow-y-auto mb-3 p-3 rounded-lg bg-white/10 backdrop-blur-md max-h-64 min-h-[120px] glass-content border border-white/20 shadow-lg">
              {chatMessages.length === 0 ? (
                <div className="text-sm text-gray-600 text-center mt-8">
                  💬 Chat with your AI agent
                  <br />
                  <span className="text-xs text-gray-500">Ask the agent to help with tasks on your computer</span>
                </div>
              ) : (
                chatMessages.map((msg, idx) => (
                  <div
                    key={idx}
                    className={`w-full flex ${msg.role === "user" ? "justify-end" : "justify-start"} mb-3`}
                  >
                    <div
                      className={`max-w-[80%] px-3 py-1.5 rounded-xl text-xs shadow-md backdrop-blur-sm border ${
                        msg.role === "user" 
                          ? "bg-gray-700/80 text-gray-100 ml-12 border-gray-600/40" 
                          : "bg-white/85 text-gray-700 mr-12 border-gray-200/50"
                      }`}
                      style={{ wordBreak: "break-word", lineHeight: "1.4" }}
                    >
                      {msg.text}
                    </div>
                  </div>
                ))
              )}
              {chatLoading && (
                <div className="flex justify-start mb-3">
                  <div className="bg-white/85 text-gray-600 px-3 py-1.5 rounded-xl text-xs backdrop-blur-sm border border-gray-200/50 shadow-md mr-12">
                    <span className="inline-flex items-center">
                      <span className="animate-pulse text-gray-400">●</span>
                      <span className="animate-pulse animation-delay-200 text-gray-400">●</span>
                      <span className="animate-pulse animation-delay-400 text-gray-400">●</span>
                      <span className="ml-2">Agent is thinking...</span>
                    </span>
                  </div>
                </div>
              )}
              {/* Auto-scroll anchor */}
              <div ref={chatMessagesEndRef} />
            </div>
            {/* Only show chat input in popup after first use */}
            {!isFirstUse && (
              <form
                className="flex gap-2 items-center glass-content"
                onSubmit={e => {
                  e.preventDefault();
                  handleChatSend();
                }}
              >
                <input
                  ref={chatInputRef}
                  className="flex-1 rounded-lg px-3 py-2 bg-white/25 backdrop-blur-md text-gray-800 placeholder-gray-500 text-xs focus:outline-none focus:ring-1 focus:ring-gray-400/60 border border-white/40 shadow-lg transition-all duration-200"
                  placeholder="Type your message..."
                  value={chatInput}
                  onChange={e => setChatInput(e.target.value)}
                  disabled={chatLoading}
                />
                <button
                  type="submit"
                  className="p-2 rounded-lg bg-gray-600/80 hover:bg-gray-700/80 border border-gray-500/60 flex items-center justify-center transition-all duration-200 backdrop-blur-sm shadow-lg disabled:opacity-50"
                  disabled={chatLoading || !chatInput.trim()}
                  tabIndex={-1}
                  aria-label="Send"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="white" className="w-4 h-4">
                    <path strokeLinecap="round" strokeLinejoin="round" d="M4.5 19.5l15-7.5-15-7.5v6l10 1.5-10 1.5v6z" />
                  </svg>
                </button>
              </form>
            )}
          </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Queue
