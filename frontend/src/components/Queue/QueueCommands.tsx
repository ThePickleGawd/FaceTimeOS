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
  onPauseAgent,
  onTogglePopup
}) => {
  const [isInputActive, setIsInputActive] = useState(false)
  const [isGlowing, setIsGlowing] = useState(false)
  const [showPersistentGlow, setShowPersistentGlow] = useState(false)
  const formRef = React.useRef<HTMLFormElement>(null)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (chatInput.trim() && !chatLoading) {
      // Trigger glow animation when submitting
      setIsGlowing(true)
      setTimeout(() => {
        setIsGlowing(false)
        setShowPersistentGlow(true)
      }, 1500)

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

  // Trigger glow animation when agent starts running (for iMessage)
  // and remove persistent glow when agent stops
  React.useEffect(() => {
    if (isAgentRunning) {
      // Agent just started - trigger the animation
      setIsGlowing(true)
      const timeout = setTimeout(() => {
        setIsGlowing(false)
        setShowPersistentGlow(true)
      }, 1500)
      return () => clearTimeout(timeout)
    } else {
      // Agent stopped - remove persistent glow
      setShowPersistentGlow(false)
    }
  }, [isAgentRunning])

  // Track mouse position to enable/disable click-through
  React.useEffect(() => {
    let rafId: number | null = null

    const handleMouseMove = (e: MouseEvent) => {
      if (rafId) return // Debounce using requestAnimationFrame

      rafId = requestAnimationFrame(() => {
        if (formRef.current) {
          const rect = formRef.current.getBoundingClientRect()
          const isOverBar =
            e.clientX >= rect.left &&
            e.clientX <= rect.right &&
            e.clientY >= rect.top &&
            e.clientY <= rect.bottom

          window.electronAPI?.setWindowClickThrough(!isOverBar)
        }
        rafId = null
      })
    }

    document.addEventListener('mousemove', handleMouseMove)

    // Enable click-through initially
    window.electronAPI?.setWindowClickThrough(true)

    return () => {
      document.removeEventListener('mousemove', handleMouseMove)
      if (rafId) cancelAnimationFrame(rafId)
    }
  }, [])

  return (
    <div className="w-full max-w-2xl mx-auto py-1">
      <form
        ref={formRef}
        onSubmit={handleSubmit}
        className={`text-xs text-slate-300 liquid-glass-bar draggable-area flex items-center ${isGlowing ? 'glowing' : ''} ${showPersistentGlow ? 'glowing-persistent' : ''}`}
      >
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
              className="w-full px-0 py-0 bg-transparent text-slate-300 placeholder-slate-400 text-xs text-center focus:outline-none focus:ring-0 border-0 transition-all duration-200 disabled:opacity-50"
            />
          </div>
        ) : (
          <div
            onClick={handleBarClick}
            className="flex-1 px-4 py-2 bg-transparent text-slate-300 text-xs cursor-pointer hover:bg-slate-700/30 transition-all duration-200 flex items-center justify-center gap-2"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            {agentStatus ? (
              <>
                <span className="animate-pulse text-blue-400">●</span>
                <span>{agentStatus}</span>
              </>
            ) : (
              <span className="text-slate-400">Agent is ready</span>
            )}
          </div>
        )}

        {/* Stop Button - Only show when agent is running */}
        {isAgentRunning && (
          <button
            onClick={onPauseAgent}
            className="px-2 py-2 text-slate-400 hover:text-red-400 transition-colors flex items-center"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
            title="Stop Agent"
            type="button"
          >
            <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
              <rect x="3" y="3" width="8" height="8" rx="1"/>
            </svg>
          </button>
        )}

        {/* Drag Handle - Draggable */}
        <div
          className="px-3 py-2 text-slate-500 hover:text-slate-400 transition-colors cursor-move flex items-center"
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
