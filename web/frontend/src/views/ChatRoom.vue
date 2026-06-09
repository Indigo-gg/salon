<template>
  <div class="chat-room-scene">
    <!-- Header Controls -->
    <div class="pixel-header">
      <div class="header-left">
        <router-link to="/" class="pixel-btn">&larr; {{ t('chat.back') }}</router-link>
        <h2 class="topic-title">{{ sessionStore.currentSession?.topic || t('chat.loading') }}</h2>
        <span class="pixel-badge" :class="{ 'debate-badge': isDebate }">{{ stateLabel(sessionStore.sessionState) }}</span>
        <span v-if="sessionStore.sessionState !== 'idle'" class="pixel-badge">{{ roundDisplay }}</span>
        <span v-if="isDebate" class="pixel-badge debate-phase-badge">⚔️ 辩论</span>
      </div>
      <div class="header-right">
        <button @click="autoPlayNext = !autoPlayNext" :class="['pixel-btn', { 'btn-active': autoPlayNext }]">
          AutoPlay: {{ autoPlayNext ? 'ON' : 'OFF' }}
        </button>
        <button @click="ttsEnabled = !ttsEnabled" class="pixel-btn">
          {{ ttsEnabled ? t('chat.tts_on') : t('chat.tts_off') }}
        </button>
        <button v-if="sessionStore.sessionState === 'idle'" @click="start" class="pixel-btn pixel-btn-primary" :disabled="starting">
          {{ starting ? t('chat.starting') : t('chat.start') }}
        </button>
        <button v-if="sessionStore.sessionState === 'running'" @click="pause" class="pixel-btn">{{ t('chat.pause') }}</button>
        <button v-if="sessionStore.sessionState === 'paused'" @click="resume" class="pixel-btn pixel-btn-primary">{{ t('chat.resume') }}</button>
        <button v-if="['running','paused'].includes(sessionStore.sessionState)" @click="stop" class="pixel-btn pixel-btn-danger">{{ t('chat.end') }}</button>
        <button ref="whiteboardBtn" @click="showPanel = showPanel ? null : 'whiteboard'" class="pixel-btn">{{ t('chat.whiteboard') }}</button>
        <button @click="showPanel = showPanel ? null : 'memory'" class="pixel-btn">🧠 {{ t('archive.memory') }}</button>

      </div>
    </div>

    <!-- Salon Stage -->
    <div class="salon-stage">
      <div class="salon-bg"></div>
      
      <!-- Agents (Standing right above the message panel) -->
      <div class="agents-container">
        <div v-for="(a, idx) in agents" :key="a.id" class="agent-character">
          <div class="sprite-wrapper">
            <div class="pixel-sprite" :class="getAgentActionClass(a.id)" :style="{ backgroundImage: `url(${getSpriteUrl(a.id)})` }"></div>
          </div>
          <div class="character-name">
            {{ a.name }}
            <span v-if="thinkingAgents.has(a.id)" style="color: var(--accent-gold); font-size: 10px;"> (思考中...)</span>
            <span v-if="getAgentToolCall(a.id)" style="color: var(--accent-blue); font-size: 10px;"> (🔍{{ getAgentToolCall(a.id).tool }}...)</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Message Log Panel (Bottom) -->
    <div class="message-log-panel pixel-box">
      <div class="messages-scroll" ref="messagesEl">
        <div v-if="sessionStore.messages.length === 0" class="empty-chat">{{ t('chat.empty') }}</div>
        <ChatMessage
          v-for="msg in sessionStore.messages"
          :key="msg.id"
          :msg="msg"
          :mode="sessionStore.currentSession?.mode || 'salon'"
          :factions="debateFactions"
          :show-tts="msg.agent_id !== 'human' && msg.agent_role !== 'system'"
          :tts-loading="loadingAudioMsgId === msg.id"
          :tts-playing="currentPlayingMsgId === msg.id && isPlayingAudio"
          :show-approve="sessionStore.currentSession?.mode === 'interview' && msg.speech_type === 'intent'"
          :approved="approvedMsgs.has(msg.id)"
          @tts-toggle="togglePlayMessage(msg)"
          @approve="approveAgent(msg.id, msg.agent_id, msg.agent_name)"
        />
      </div>
      
      <!-- Command Bar -->
      <div v-if="sessionStore.sessionState !== 'finished'" class="command-bar">
        <span class="cmd-prompt">&gt;</span>
        <input
          v-model="commandInput"
          @keyup.enter="sendCmd"
          :placeholder="inputPlaceholder"
          class="pixel-input cmd-input"
        />
      </div>
    </div>

    <!-- Side panel popups for whiteboard/notebook -->
    <DraggablePanel
      v-if="showPanel"
      :anchor-el="whiteboardBtn"
      :init-width="400"
      :init-height="420"
      @close="showPanel = null"
    >
      <template #header>{{ panelTitle }}</template>
      <WhiteboardPanel v-if="showPanel === 'whiteboard'" :content="sessionStore.whiteboard" />
      <MemoryPanel v-if="showPanel === 'memory'" :session-id="sessionId" />
    </DraggablePanel>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { useSessionStore } from '../stores/session'
import { useAgentsStore } from '../stores/agents'
import { useI18nStore } from '../stores/i18n'
import { useConfigStore } from '../stores/config'
import WhiteboardPanel from '../components/WhiteboardPanel.vue'
import DraggablePanel from '../components/DraggablePanel.vue'
import MemoryPanel from '../components/MemoryPanel.vue'
import ChatMessage from '../components/ChatMessage.vue'

import axios from 'axios'

const route = useRoute()
const sessionStore = useSessionStore()
const agentsStore = useAgentsStore()
const configStore = useConfigStore()
const i18n = useI18nStore()
const t = i18n.t

const sessionId = route.params.sessionId
const messagesEl = ref(null)
const commandInput = ref('')
const starting = ref(false)
const showPanel = ref(null)
const ttsEnabled = ref(false)
const autoPlayNext = ref(false)

const isPlayingAudio = ref(false)
const currentAudio = ref(null)

const approvedMsgs = ref(new Set())
const thinkingAgents = ref(new Set())
const whiteboardBtn = ref(null)

const agents = computed(() => {
  const ids = sessionStore.currentSession?.agent_ids || []
  return agentsStore.agents.filter(a => ids.includes(a.id))
})

function getAgentToolCall(agentId) {
  return sessionStore.activeToolCalls.find(t => t.agent_id === agentId)
}

const isDebate = computed(() => sessionStore.currentSession?.mode === 'debate')

const inputPlaceholder = computed(() => {
  const mode = sessionStore.currentSession?.mode
  if (mode === 'interview') return '作为主持人，输入你的问题或命令...'
  if (mode === 'debate') return '辩论进行中...输入 /debate 查看状态'
  return t('chat.cmd_ph')
})

// 辩论阵营映射（从 session metadata 的 mode_config 读取）
const modeConfig = computed(() => sessionStore.currentSession?.mode_config || {})
const debateFactions = computed(() => modeConfig.value.factions || {})

const latestMessage = computed(() => {
  const msgs = sessionStore.messages
  return msgs.length ? msgs[msgs.length - 1] : null
})

const panelTitle = computed(() => {
  if (showPanel.value === 'whiteboard') return t('chat.whiteboard')
  if (showPanel.value === 'memory') return '🧠 ' + t('archive.memory')
  return ''
})

const currentlyTalkingAgent = ref(null)
const currentPlayingMsgId = ref(null)
const loadingAudioMsgId = ref(null)
const isInitialLoad = ref(true)
let talkTimeout = null

const roundDisplay = computed(() => {
  const current = sessionStore.roundCount || 0
  const mode = sessionStore.currentSession?.mode || 'salon'
  if (mode === 'interview') {
    return `Round ${current}`
  } else {
    const total = configStore.config?.discussion?.max_rounds || '?'
    return `Round ${current} / ${total}`
  }
})

watch(latestMessage, (msg) => {
  if (msg && msg.agent_id) {
    if (talkTimeout) clearTimeout(talkTimeout)
    const duration = Math.max(2000, Math.min(8000, msg.content.length * 100))
    talkTimeout = setTimeout(() => {
      if (currentlyTalkingAgent.value === msg.agent_id && !isPlayingAudio.value) {
        currentlyTalkingAgent.value = null
      }
    }, duration)
  }
}, { immediate: true })

function getSpriteUrl(agentId) {
  const agent = agentsStore.agents.find(a => a.id === agentId)
  if (agent && agent.avatar && agent.avatar.endsWith('.png')) {
    return `/src/assets/images/sprites/${agent.avatar}`
  }
  const map = {
    'ai_observer': 'ai_observer.png',
    'human': 'me.png',
    'moderator': 'moderator.png',
    'philosopher_east': 'philosopher_east.png',
    'philosopher_west': 'philosopher_west.png',
    'scientist': 'scientist.png',
    'scribe': 'scribe.png',
    'existentialist': 'existentialist.png',
    'marxist': 'marxist.png'
  }
  return `/src/assets/images/sprites/${map[agentId] || 'me.png'}`
}

function getAgentActionClass(agentId) {
  if (thinkingAgents.value.has(agentId)) {
    return 'action-think'
  }
  if (isPlayingAudio.value && currentlyTalkingAgent.value === agentId) {
    return 'action-talk'
  }
  if (!isPlayingAudio.value && currentlyTalkingAgent.value === agentId) {
    return 'action-talk'
  }
  return 'action-idle'
}

function stateLabel(state) {
  const key = `chat.state_${state}`
  const trans = t(key)
  return trans === key ? state.toUpperCase() : trans
}

async function start() {
  starting.value = true
  try {
    await sessionStore.startChat(sessionId)
  } finally {
    starting.value = false
  }
}
function pause() { sessionStore.pauseChat(sessionId) }
async function resume() {
  starting.value = true
  try {
    await sessionStore.startChat(sessionId)
    await sessionStore.resumeChat(sessionId)
  } finally {
    starting.value = false
  }
}
function stop() { sessionStore.stopChat(sessionId) }
function sendCmd() {
  if (!commandInput.value.trim()) return
  sessionStore.sendCommand(sessionId, commandInput.value.trim())
  commandInput.value = ''
}
function approveAgent(msgId, agentId, agentName) {
  if (approvedMsgs.value.has(msgId)) return
  approvedMsgs.value.add(msgId)
  thinkingAgents.value.add(agentId)
  sessionStore.sendCommand(sessionId, `/approve ${agentName}`)
}

// TTS & Audio playback
const audioQueue = ref([])
const isProcessingQueue = ref(false)
let isUnmounted = false

watch(() => ttsEnabled.value, (val) => {
  if (!val) {
    audioQueue.value = []
    if (currentAudio.value) {
      currentAudio.value.pause()
      isPlayingAudio.value = false
      currentPlayingMsgId.value = null
      currentlyTalkingAgent.value = null
    }
  }
})

async function togglePlayMessage(msg) {
  if (!msg || msg.speech_type === 'intent') return
  
  if (loadingAudioMsgId.value === msg.id) {
    // User wants to cancel while loading
    loadingAudioMsgId.value = null
    audioQueue.value = []
    return
  }
  
  if (currentPlayingMsgId.value === msg.id && isPlayingAudio.value && currentAudio.value) {
    currentAudio.value.pause()
    isPlayingAudio.value = false
    currentPlayingMsgId.value = null
    currentlyTalkingAgent.value = null
    audioQueue.value = [] // Clear queue on manual stop
    return
  }
  
  // Clear queue when user manually starts a different message
  audioQueue.value = []
  if (currentAudio.value) {
    currentAudio.value.pause()
  }

  const agent = agentsStore.agents.find(a => a.id === msg.agent_id)
  if (!agent) return
  
  try {
    loadingAudioMsgId.value = msg.id
    const res = await axios.post('/api/tts/generate', {
      session_id: sessionId,
      message_id: msg.id,
      text: msg.content,
      voice_description: agent.voice_description || '',
      voice_name: agent.voice || ''
    })
    
    // If user cancelled during loading, loadingAudioMsgId would be null
    if (loadingAudioMsgId.value !== msg.id) return
    
    loadingAudioMsgId.value = null
    
    if (res.data.audio_url) {
      if (currentAudio.value) {
        currentAudio.value.pause()
      }
      currentAudio.value = new Audio(res.data.audio_url)
      isPlayingAudio.value = true
      currentPlayingMsgId.value = msg.id
      currentlyTalkingAgent.value = msg.agent_id
      
      currentAudio.value.addEventListener('ended', () => {
        isPlayingAudio.value = false
        currentPlayingMsgId.value = null
        currentlyTalkingAgent.value = null
        
        if (autoPlayNext.value) {
          const msgs = sessionStore.messages
          const idx = msgs.findIndex(m => m.id === msg.id)
          if (idx !== -1) {
            for (let i = idx + 1; i < msgs.length; i++) {
              const nextMsg = msgs[i]
              if (nextMsg.speech_type !== 'intent' && nextMsg.agent_id !== 'human') {
                togglePlayMessage(nextMsg)
                break
              }
            }
          }
        }
      })
      currentAudio.value.play().catch(e => {
        console.warn('Audio play failed:', e)
        isPlayingAudio.value = false
        currentPlayingMsgId.value = null
        currentlyTalkingAgent.value = null
      })

      // 连播开启时，预加载下一条音频（利用当前播放时间完成生成）
      if (autoPlayNext.value) {
        preloadNextAudio(msg, sessionStore.messages)
      }
    }
  } catch (err) {
    loadingAudioMsgId.value = null
    console.error('TTS error', err)
  }
}

/** 预加载：找到下一条可播放消息，如果音频不存在则触发生成（fire-and-forget） */
function preloadNextAudio(currentMsg, allMsgs) {
  const idx = allMsgs.findIndex(m => m.id === currentMsg.id)
  if (idx === -1) return
  for (let i = idx + 1; i < allMsgs.length; i++) {
    const nextMsg = allMsgs[i]
    if (nextMsg.speech_type !== 'intent' && nextMsg.agent_id !== 'human') {
      const agent = agentsStore.agents.find(a => a.id === nextMsg.agent_id)
      if (!agent) return
      // fire-and-forget：不阻塞当前播放，后端已有文件缓存，命中则秒回
      axios.post('/api/tts/generate', {
        session_id: sessionId,
        message_id: nextMsg.id,
        text: nextMsg.content,
        voice_description: agent.voice_description || '',
        voice_name: agent.voice || ''
      }).catch(() => {}) // 静默失败，不影响播放
      break
    }
  }
}

async function playMessage(msg) {
  if (!ttsEnabled.value) return
  if (msg.speech_type === 'intent' || msg.agent_id === 'human') return
  
  audioQueue.value.push(msg)
  processAudioQueue()
}

async function processAudioQueue() {
  if (isProcessingQueue.value) return
  isProcessingQueue.value = true

  while (audioQueue.value.length > 0) {
    if (!ttsEnabled.value || isUnmounted) {
      audioQueue.value = []
      break
    }
    const msg = audioQueue.value[0]
    
    await new Promise(async (resolve) => {
      if (!audioQueue.value.includes(msg)) {
         resolve()
         return
      }

      const agent = agentsStore.agents.find(a => a.id === msg.agent_id)
      if (!agent) {
        resolve()
        return
      }
      
      try {
        loadingAudioMsgId.value = msg.id
        const res = await axios.post('/api/tts/generate', {
          session_id: sessionId,
          message_id: msg.id,
          text: msg.content,
          voice_description: agent.voice_description || '',
          voice_name: agent.voice || ''
        })
        loadingAudioMsgId.value = null

        if (!audioQueue.value.includes(msg) || !ttsEnabled.value || isUnmounted) {
          resolve()
          return
        }

        if (res.data.audio_url) {
          if (currentAudio.value) currentAudio.value.pause()
          currentAudio.value = new Audio(res.data.audio_url)
          isPlayingAudio.value = true
          currentPlayingMsgId.value = msg.id
          currentlyTalkingAgent.value = msg.agent_id
          
          currentAudio.value.onended = () => {
            isPlayingAudio.value = false
            currentPlayingMsgId.value = null
            currentlyTalkingAgent.value = null
            resolve()
          }
          currentAudio.value.onerror = () => {
            isPlayingAudio.value = false
            currentPlayingMsgId.value = null
            currentlyTalkingAgent.value = null
            resolve()
          }
          
          try {
            await currentAudio.value.play()
          } catch (e) {
             isPlayingAudio.value = false
             currentPlayingMsgId.value = null
             currentlyTalkingAgent.value = null
             resolve()
          }
        } else {
          resolve()
        }
      } catch (err) {
        loadingAudioMsgId.value = null
        resolve()
      }
    })
    
    const idx = audioQueue.value.indexOf(msg)
    if (idx > -1) {
      audioQueue.value.splice(idx, 1)
    }
  }

  isProcessingQueue.value = false
}

// --- 智能滚动逻辑 ---
const isNearBottom = ref(true)

/** 检测用户是否在滚动容器的底部附近 */
function checkScrollPosition() {
  const el = messagesEl.value
  if (!el) return
  const threshold = 80
  isNearBottom.value = (el.scrollHeight - el.scrollTop - el.clientHeight) < threshold
}

/** 平滑滚动到底部 */
function scrollToBottom() {
  nextTick(() => {
    if (messagesEl.value) {
      messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    }
  })
}

// 监听新消息到达（messages.length 变化）
watch(() => sessionStore.messages.length, (newLen, oldLen) => {
  // 仅在用户处于底部附近时自动滚动
  if (isNearBottom.value) {
    scrollToBottom()
  }
  if (newLen > oldLen) {
    const newMsg = sessionStore.messages[newLen - 1]
    if (newMsg && newMsg.agent_id) {
      thinkingAgents.value.delete(newMsg.agent_id)
    }
    if (!isInitialLoad.value) {
      playMessage(newMsg)
    }
  }
})

// 监听流式 chunk 更新：深度追踪最后一条消息的 content 长度变化
const lastMsgContentLen = computed(() => {
  const msgs = sessionStore.messages
  if (!msgs.length) return 0
  const last = msgs[msgs.length - 1]
  return last.streaming ? (last.content || '').length : -1
})

watch(lastMsgContentLen, () => {
  // 流式 chunk 到达时，如果用户在底部附近则滚动
  if (isNearBottom.value) {
    scrollToBottom()
  }
})

onMounted(async () => {
  agentsStore.fetchAgents()
  configStore.fetchConfig()
  await sessionStore.loadSession(sessionId)
  isInitialLoad.value = false
  const state = sessionStore.currentSession?.state
  if (state === 'paused') sessionStore.sessionState = 'paused'
  else if (state === 'finished') sessionStore.sessionState = 'finished'
  else if (state === 'running') {
    sessionStore.sessionState = 'running'
    sessionStore.connectSSE(sessionId)
  }
  else if (state === 'created') sessionStore.sessionState = 'idle'

  // 绑定滚动事件以检测用户是否在底部附近
  if (messagesEl.value) {
    messagesEl.value.addEventListener('scroll', checkScrollPosition)
  }
  // 初始加载完成后滚动到底部
  scrollToBottom()
})

onUnmounted(async () => {
  isUnmounted = true
  audioQueue.value = []
  if (currentAudio.value) currentAudio.value.pause()
  // 移除滚动事件监听
  if (messagesEl.value) {
    messagesEl.value.removeEventListener('scroll', checkScrollPosition)
  }
  if (sessionStore.sessionState === 'running') {
    try { await sessionStore.pauseChat(sessionId) } catch {}
  }
  sessionStore.disconnectSSE()
})
</script>

<style scoped>
.chat-room-scene {
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
  position: relative;
  background: var(--bg-color);
}

.pixel-header {
  position: absolute;
  top: 0; left: 0; right: 0;
  display: flex;
  justify-content: space-between;
  padding: 16px;
  z-index: 10;
  background: rgba(43, 43, 54, 0.8);
  backdrop-filter: blur(2px);
  border-bottom: 2px solid var(--border-color);
}
.header-left, .header-right { display: flex; align-items: center; gap: 16px; }
.topic-title { font-size: 20px; color: var(--accent-gold); text-shadow: 2px 2px 0 var(--border-color); }
.pixel-badge { background: var(--accent-blue); padding: 4px 8px; border: 2px solid var(--border-color); font-size: 14px; color: #111; }

.salon-stage {
  flex: 1;
  position: relative;
}
.salon-bg {
  position: absolute;
  top: 0; left: 0; right: 0; bottom: 0;
  background: url('@/assets/images/salon-bg.png') no-repeat center bottom;
  background-size: cover;
  image-rendering: pixelated;
  opacity: 0.9;
}

/* Set agents right above the message panel (60% height) */
.agents-container { 
  position: absolute; 
  bottom: 60%; 
  left: 0; 
  right: 0; 
  height: 160px; 
  display: flex;
  justify-content: center;
  align-items: flex-end;
  gap: 30px;
}
.agent-character { 
  display: flex; 
  flex-direction: column; 
  align-items: center; 
  transform: scale(1.05);
  transform-origin: bottom center;
}

.sprite-wrapper {
  width: 140px;
  height: 140px;
  overflow: hidden;
  position: relative;
}

.pixel-sprite {
  width: 140px;
  height: 140px;
  background-size: 560px 420px; /* 4*140, 3*140 */
  background-repeat: no-repeat;
  image-rendering: pixelated;
  filter: drop-shadow(4px 4px 0px rgba(0,0,0,0.5));
}

@keyframes sprite-idle {
  from { background-position: 0 0; }
  to { background-position: -560px 0; }
}
@keyframes sprite-talk {
  from { background-position: 0 -140px; }
  to { background-position: -560px -140px; }
}
@keyframes sprite-think {
  from { background-position: 0 -280px; }
  to { background-position: -560px -280px; }
}

.pixel-sprite.action-idle { animation: sprite-idle 2.5s steps(4) infinite; }
.pixel-sprite.action-talk { animation: sprite-talk 1.8s steps(4) infinite; }
.pixel-sprite.action-think { animation: sprite-think 2.5s steps(4) infinite; }

.character-name {
  margin-top: -10px;
  background: var(--border-color);
  padding: 4px 8px;
  border: 2px solid var(--text-muted);
  font-size: 12px;
  color: var(--text-primary);
  z-index: 5;
}

.message-log-panel { 
  position: absolute; 
  bottom: 0; 
  left: 0; 
  right: 0; 
  height: 60%; 
  background: rgba(43, 43, 54, 0.95); 
  backdrop-filter: blur(4px); 
  border-top: 4px solid var(--border-color); 
  border-left: none; border-right: none; border-bottom: none; border-radius: 0; 
  display: flex; flex-direction: column; padding: 24px 16px 16px 32px; z-index: 10; 
}

.messages-scroll { flex: 1; overflow-y: auto; padding-right: 10px; }

.command-bar { display: flex; align-items: center; gap: 8px; margin-top: 10px; }
.cmd-prompt { font-size: 18px; color: var(--accent-green); font-weight: bold; }
.cmd-input { flex: 1; }
.cmd-input:focus { border-color: var(--accent-green); }

/* 辩论模式样式 */
.debate-badge { background: var(--accent-red); color: #fff; border-color: var(--accent-red); }
.debate-phase-badge { background: var(--accent-red); color: #fff; border-color: var(--accent-red); font-size: 11px; }
</style>
