import React from "react"
import { IoLogOutOutline } from "react-icons/io5"

interface QueueCommandsProps {
  chatInput: string
  onChatInputChange: (value: string) => void
  onChatSubmit: () => void
  chatLoading: boolean
  agentStatus: string | null
  onBarClick: () => void
  isAgentRunning: boolean
  onPauseAgent: () => void
  isFirstUse: boolean
  isChatOpen: boolean
}

const QueueCommands: React.FC<QueueCommandsProps> = ({
  chatInput,
  onChatInputChange,
  onChatSubmit,
  chatLoading,
  agentStatus,
  onBarClick,
  isAgentRunning,
  onPauseAgent,
  isFirstUse,
  isChatOpen
}) => {
  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (chatInput.trim() && !chatLoading) {
      onChatSubmit()
    }
  }

  const handleBarClick = () => {
    onBarClick()
  }

  return (
    <div className="w-full max-w-2xl mx-auto">
      <form onSubmit={handleSubmit} className="text-xs text-white/90 liquid-glass-bar py-2 px-4 flex items-center justify-center gap-3 draggable-area">
        {/* Chat Input Field or Status Display */}
        {isFirstUse && !agentStatus ? (
          <input
            type="text"
            value={chatInput}
            onChange={(e) => onChatInputChange(e.target.value)}
            placeholder="Ask your AI agent..."
            disabled={chatLoading}
            className="flex-1 rounded-lg px-3 py-1.5 bg-white/10 backdrop-blur-md text-white placeholder-white/50 text-xs focus:outline-none focus:ring-1 focus:ring-white/30 border border-white/20 transition-all duration-200 disabled:opacity-50"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          />
        ) : (
          <div
            onClick={handleBarClick}
            className="flex-1 rounded-lg px-3 py-1.5 bg-white/10 backdrop-blur-md text-white text-xs border border-white/20 cursor-pointer hover:bg-white/15 transition-all duration-200 flex items-center gap-2"
            style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
          >
            {agentStatus ? (
              <>
                <span className="animate-pulse text-blue-400">●</span>
                <span>{agentStatus}</span>
              </>
            ) : (
              <span className="text-white/60">
                {isChatOpen ? 'Click to close chat' : 'Click to open chat'}
              </span>
            )}
          </div>
        )}

        {/* Start/Pause Button */}
        <button
          className={`transition-colors rounded-md px-3 py-1.5 text-[11px] leading-none flex items-center gap-1 whitespace-nowrap ${
            isAgentRunning
              ? 'bg-yellow-500/70 hover:bg-yellow-500/90 text-white/90'
              : 'bg-green-500/70 hover:bg-green-500/90 text-white/90'
          }`}
          onClick={onPauseAgent}
          type="button"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          {isAgentRunning ? '⏸ Pause' : '▶ Start'}
        </button>

        {/* Separator */}
        <div className="h-4 w-px bg-white/20" />

        {/* Exit Button */}
        <button
          className="text-red-500/70 hover:text-red-500/90 transition-colors hover:cursor-pointer"
          title="Exit"
          onClick={() => window.electronAPI.quitApp()}
          type="button"
          style={{ WebkitAppRegion: 'no-drag' } as React.CSSProperties}
        >
          <IoLogOutOutline className="w-4 h-4" />
        </button>
      </form>
    </div>
  )
}

export default QueueCommands
