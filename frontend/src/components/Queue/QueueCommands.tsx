import React, { useState } from "react"

interface QueueCommandsProps {
  chatInput: string
  onChatInputChange: (value: string) => void
  onChatSubmit: () => void
  chatLoading: boolean
  agentStatus: string | null
  isAgentRunning: boolean
  onPauseAgent: () => void
  isChatOpen: boolean
  onTogglePopup: () => void
}

const QueueCommands: React.FC<QueueCommandsProps> = ({
  chatInput,
  onChatInputChange,
  onChatSubmit,
  chatLoading,
  agentStatus,
  isAgentRunning,
  onTogglePopup
}) => {
  const [isInputActive, setIsInputActive] = useState(false)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (chatInput.trim() && !chatLoading) {
      onChatSubmit()
      setIsInputActive(false)
    }
  }

  const handleBarClick = () => {
    if (isAgentRunning) {
      // If agent is running, toggle the popup
      onTogglePopup()
    } else {
      // If agent is not running, activate input
      if (!isInputActive) {
        setIsInputActive(true)
      }
    }
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="text-xs text-white/90 liquid-glass-bar draggable-area flex items-center">
        {/* Main Content Area - Clickable, Not Draggable */}
        {isInputActive && !isAgentRunning ? (
          <div className="flex-1 px-4 py-2 text-center" style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}>
            <input
              type="text"
              value={chatInput}
              onChange={(e) => onChatInputChange(e.target.value)}
              placeholder="Ask your AI agent..."
              disabled={chatLoading}
              autoFocus
              onBlur={() => !chatInput && setIsInputActive(false)}
              className="w-full px-0 py-0 bg-transparent text-white placeholder-white/50 text-xs text-center focus:outline-none focus:ring-0 border-0 transition-all duration-200 disabled:opacity-50"
            />
          </div>
        ) : (
          <div
            onClick={handleBarClick}
            className="flex-1 px-4 py-2 bg-transparent text-white text-xs cursor-pointer hover:bg-white/5 transition-all duration-200 flex items-center justify-center gap-2"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            {agentStatus ? (
              <>
                <span className="animate-pulse text-blue-400">●</span>
                <span>{agentStatus}</span>
              </>
            ) : (
              <span className="text-white/70">Agent is ready</span>
            )}
          </div>
        )}

        {/* Drag Handle - Draggable */}
        <div
          className="px-3 py-2 text-white/40 hover:text-white/60 transition-colors cursor-move flex items-center"
          title="Drag to move"
        >
          <svg width="12" height="16" viewBox="0 0 12 16" fill="currentColor">
            <circle cx="3" cy="4" r="1.5"/>
            <circle cx="9" cy="4" r="1.5"/>
            <circle cx="3" cy="8" r="1.5"/>
            <circle cx="9" cy="8" r="1.5"/>
            <circle cx="3" cy="12" r="1.5"/>
            <circle cx="9" cy="12" r="1.5"/>
          </svg>
        </div>
      </form>
    </div>
  )
}

export default QueueCommands
