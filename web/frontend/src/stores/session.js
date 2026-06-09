import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import * as api from '../api'

export const useSessionStore = defineStore('session', () => {
  const sessions = ref([])
  const currentSession = ref(null)
  const messages = ref([])
  const whiteboard = ref('')

  const sessionState = ref('idle') // idle | running | paused | finished
  const roundCount = ref(0)
  const loading = ref(false)
  const activeToolCalls = ref([])  // 当前正在进行的工具调用
  let eventSource = null

  async function fetchSessions() {
    loading.value = true
    try {
      const { data } = await api.getSessions()
      sessions.value = data
    } finally {
      loading.value = false
    }
  }

  async function createSession(topic, agentIds, mode = 'salon', modeConfig = null) {
    const body = { topic, agent_ids: agentIds, mode }
    if (modeConfig) body.mode_config = modeConfig
    const { data } = await api.createSession(body)
    sessions.value.unshift(data)
    return data
  }

  async function loadSession(sessionId) {
    const { data } = await api.getSession(sessionId)
    currentSession.value = data
    const msgRes = await api.getSessionMessages(sessionId)
    messages.value = msgRes.data
    
    // Resume round count from messages
    if (messages.value.length > 0) {
      roundCount.value = Math.max(...messages.value.map(m => m.round || 0))
    } else {
      roundCount.value = 0
    }
    
    const wbRes = await api.getSessionWhiteboard(sessionId)
    whiteboard.value = wbRes.data.content || ''

  }

  function connectSSE(sessionId) {
    if (eventSource) eventSource.close()
    eventSource = new EventSource(`/api/chat/${sessionId}/stream`)

    // 完整消息事件（向后兼容：intent 消息及其他一次性完整消息仍走此通道）
    eventSource.addEventListener('message', (e) => {
      const data = JSON.parse(e.data)
      messages.value.push(data)
    })

    // 流式消息开始：创建占位消息，content 为空，后续由 chunk 填充
    eventSource.addEventListener('speech_start', (e) => {
      const data = JSON.parse(e.data)
      messages.value.push({
        ...data,
        content: '',
        streaming: true,
        thinking: false,
      })
    })

    // 思考开始：标记该消息正在思考中（不显示内容）
    eventSource.addEventListener('thought_start', (e) => {
      const data = JSON.parse(e.data)
      const msg = messages.value.find(m => m.id === data.id)
      if (msg) {
        msg.thinking = true
      }
    })

    // 思考结束：取消思考标记
    eventSource.addEventListener('thought_end', (e) => {
      const data = JSON.parse(e.data)
      const msg = messages.value.find(m => m.id === data.id)
      if (msg) {
        msg.thinking = false
      }
    })

    // 流式消息片段：将 chunk 追加到对应消息的 content 中
    eventSource.addEventListener('speech_chunk', (e) => {
      const data = JSON.parse(e.data)
      const msg = messages.value.find(m => m.id === data.id)
      if (msg) {
        msg.content += data.chunk
      }
    })

    // 流式消息结束：标记该消息已完成流式传输
    eventSource.addEventListener('speech_end', (e) => {
      const data = JSON.parse(e.data)
      const msg = messages.value.find(m => m.id === data.id)
      if (msg) {
        msg.streaming = false
      }
    })

    // 接收 mentions 提取事件
    eventSource.addEventListener('mentions', (e) => {
      const data = JSON.parse(e.data)
      const msg = messages.value.find(m => m.id === data.id)
      if (msg) {
        msg.mentions = data.mentions
      }
    })

    eventSource.addEventListener('status', (e) => {
      const data = JSON.parse(e.data)
      sessionState.value = data.state
      roundCount.value = data.round || roundCount.value
    })

    eventSource.addEventListener('whiteboard', (e) => {
      const data = JSON.parse(e.data)
      whiteboard.value = data.content
    })

    // 工具调用事件：实时显示 agent 的搜索等工具调用状态
    eventSource.addEventListener('tool_call', (e) => {
      const data = JSON.parse(e.data)
      if (data.status === 'calling') {
        // 工具调用开始：添加到活跃工具列表
        activeToolCalls.value.push({
          id: `${data.agent_id}_${data.tool}_${Date.now()}`,
          agent_id: data.agent_id,
          agent_name: data.agent_name,
          tool: data.tool,
          input: data.input,
          status: 'calling',
        })
      } else if (data.status === 'done') {
        // 工具调用完成：从活跃列表移除
        const idx = activeToolCalls.value.findIndex(
          t => t.agent_id === data.agent_id && t.tool === data.tool && t.status === 'calling'
        )
        if (idx !== -1) activeToolCalls.value.splice(idx, 1)
      }
    })



    eventSource.addEventListener('done', () => {
      sessionState.value = 'finished'
      disconnectSSE()
    })

    eventSource.addEventListener('error', (e) => {
      // SSE auto-reconnects, but if the stream ends, close
      if (eventSource.readyState === EventSource.CLOSED) {
        sessionState.value = 'finished'
      }
    })

    sessionState.value = 'running'
  }

  function disconnectSSE() {
    if (eventSource) {
      eventSource.close()
      eventSource = null
    }
  }

  async function startChat(sessionId) {
    await api.startChat(sessionId)
    connectSSE(sessionId)
  }

  async function sendCommand(sessionId, command) {
    await api.sendCommand(sessionId, command)
  }

  async function pauseChat(sessionId) {
    await api.pauseChat(sessionId)
    sessionState.value = 'paused'
  }

  async function resumeChat(sessionId) {
    await api.resumeChat(sessionId)
    sessionState.value = 'running'
  }

  async function stopChat(sessionId) {
    await api.stopChat(sessionId)
    disconnectSSE()
    sessionState.value = 'finished'
  }

  async function archiveSession(sessionId) {
    await api.archiveSession(sessionId)
    sessions.value = sessions.value.filter(s => s.session_id !== sessionId)
  }

  async function deleteSession(sessionId) {
    await api.deleteSession(sessionId)
    sessions.value = sessions.value.filter(s => s.session_id !== sessionId)
  }

  return {
    sessions, currentSession, messages, whiteboard,
    sessionState, roundCount, loading, activeToolCalls,
    fetchSessions, createSession, loadSession,
    connectSSE, disconnectSSE, startChat, sendCommand, stopChat,
    pauseChat, resumeChat, archiveSession, deleteSession,
  }
})
