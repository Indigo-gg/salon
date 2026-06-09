<template>
  <div class="chat-room-scene" :class="{ 'is-fullscreen': isFullscreen }">
    <!-- Header Controls -->
    <div class="pixel-header">
      <div class="header-left">
        <router-link to="/archive" class="pixel-btn">&larr; {{ t('chat.back') }}</router-link>
        <h2 class="topic-title">{{ t('play.playback') }}: {{ archive?.metadata?.topic || t('chat.loading') }}</h2>
        <span class="pixel-badge">{{ t('play.display') }} {{ visibleCount }} / {{ totalMessages }}</span>
      </div>
      <div class="header-right">
        <button @click="toggleFullscreen" class="pixel-btn">⤡ 全屏</button>
        <button ref="whiteboardBtn" @click="showPanel = showPanel ? null : 'whiteboard'" class="pixel-btn">{{ t('chat.whiteboard') }}</button>
        <button @click="showExportMenu = !showExportMenu" class="pixel-btn">📦 {{ t('archive.export') }}</button>

        <div v-if="showExportMenu" class="export-menu pixel-box">
          <button @click="doExport('md')" class="pixel-btn btn-sm">📝 {{ t('archive.export_md') }}</button>
          <button @click="doExport('html')" class="pixel-btn btn-sm">🌐 {{ t('archive.export_html') }}</button>
        </div>

        <button @click="autoPlayNext = !autoPlayNext" :class="['pixel-btn', { 'btn-active': autoPlayNext }]">
          连播: {{ autoPlayNext ? 'ON' : 'OFF' }}
        </button>
        <button @click="ttsEnabled = !ttsEnabled" class="pixel-btn">
          {{ ttsEnabled ? t('chat.tts_on') : t('chat.tts_off') }}
        </button>
      </div>
    </div>

    <!-- Playback Controls (Moved out of header to reduce crowding) -->
    <div class="playback-controls pixel-box">
      <button @click="visibleCount = 1" class="pixel-btn btn-sm">{{ t('play.reset') }}</button>
      <button @click="stepBack" class="pixel-btn btn-sm" :disabled="visibleCount <= 1">-1</button>
      
      <div class="custom-round-selector">
        <input type="range" v-model.number="visibleCount" min="1" :max="totalMessages" class="pixel-slider" :disabled="totalMessages === 0" />
        <input type="number" v-model.number="visibleCount" min="1" :max="totalMessages" class="pixel-input num-input" :disabled="totalMessages === 0" />
      </div>

      <button @click="autoPlay" class="pixel-btn btn-sm pixel-btn-primary">{{ autoPlaying ? t('play.auto_pause') : t('play.auto') }}</button>
      <button @click="stepForward" class="pixel-btn btn-sm" :disabled="visibleCount >= totalMessages">+1</button>
      <button @click="visibleCount = totalMessages" class="pixel-btn btn-sm">{{ t('play.show_all') }}</button>
    </div>

    <!-- Salon Stage -->
    <div class="salon-stage">
      <div class="salon-bg"></div>
      
      <!-- Agents (Standing right above the message panel) -->
      <div class="agents-container">
        <div v-for="agentId in participantIds" :key="agentId" class="agent-character">
          <div class="sprite-wrapper">
            <div class="pixel-sprite" :class="getAgentActionClass(agentId)" :style="{ backgroundImage: `url(${getSpriteUrl(agentId)})` }"></div>
          </div>
          <div class="character-name">{{ getAgentName(agentId) }}</div>
        </div>
      </div>
    </div>

    <!-- Message Log Panel (Bottom) -->
    <div class="message-log-panel pixel-box">
      <div class="messages-scroll" ref="messagesEl">
        <div v-if="visibleMessages.length === 0" class="empty-chat">{{ t('play.empty') }}</div>
        <ChatMessage
          v-for="msg in visibleMessages"
          :key="msg.id"
          :msg="msg"
          :mode="archive?.metadata?.mode || 'salon'"
          :factions="debateFactions"
          :show-tts="msg.agent_id !== 'human' && msg.agent_role !== 'system'"
          :tts-loading="loadingAudioMsgId === msg.id"
          :tts-playing="currentPlayingMsgId === msg.id && isPlayingAudio"
          @tts-toggle="togglePlayMessage(msg)"
        >
          <template #header-actions>
            <span v-if="isFullscreen && currentPlayingMsgId === msg.id" class="speaking-icon">🔊</span>
          </template>
        </ChatMessage>
    </div>

    <!-- Side panel popups for whiteboard/memory -->
    <DraggablePanel
      v-if="showPanel"
      :anchor-el="whiteboardBtn"
      :init-width="400"
      :init-height="420"
      @close="showPanel = null"
    >
      <template #header>{{ panelTitle }}</template>
      <WhiteboardPanel v-if="showPanel === 'whiteboard'" :content="archive?.whiteboard || ''" />
    </DraggablePanel>
    </div>

    <!-- Fullscreen Floating Toolbar (Bottom Center) -->
    <div v-if="isFullscreen" class="floating-toolbar pixel-box">
      <button @click="stepBack" class="pixel-btn btn-sm" :disabled="visibleCount <= 1">-1</button>
      
      <div class="custom-round-selector">
        <input type="range" v-model.number="visibleCount" min="1" :max="totalMessages" class="pixel-slider" :disabled="totalMessages === 0" />
        <span class="fs-count">{{ visibleCount }} / {{ totalMessages }}</span>
      </div>

      <button @click="autoPlay" class="pixel-btn btn-sm pixel-btn-primary">{{ autoPlaying ? t('play.auto_pause') : t('play.auto') }}</button>
      <button @click="stepForward" class="pixel-btn btn-sm" :disabled="visibleCount >= totalMessages">+1</button>
      <div class="toolbar-divider"></div>
      <button @click="autoPlayNext = !autoPlayNext" :class="['pixel-btn', 'btn-sm', { 'btn-active': autoPlayNext }]">
        连播: {{ autoPlayNext ? 'ON' : 'OFF' }}
      </button>
      <button @click="ttsEnabled = !ttsEnabled" class="pixel-btn btn-sm">
        {{ ttsEnabled ? t('chat.tts_on') : t('chat.tts_off') }}
      </button>
      <button @click="showPanel = showPanel ? null : 'whiteboard'" class="pixel-btn btn-sm">{{ t('chat.whiteboard') }}</button>

      <div class="toolbar-divider"></div>
      <button @click="toggleFullscreen" class="pixel-btn btn-sm btn-danger">⤡ 退出全屏 (ESC)</button>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { getArchive } from '../api'
import { useAgentsStore } from '../stores/agents'
import { useI18nStore } from '../stores/i18n'
import WhiteboardPanel from '../components/WhiteboardPanel.vue'
import DraggablePanel from '../components/DraggablePanel.vue'
import ChatMessage from '../components/ChatMessage.vue'
import { exportArchive } from '../api'


const route = useRoute()
const agentsStore = useAgentsStore()
const i18n = useI18nStore()
const t = i18n.t
const sessionId = route.params.sessionId

const archive = ref(null)
const visibleCount = ref(1)
const autoPlaying = ref(false)
let autoTimer = null

const showPanel = ref(null)
const whiteboardBtn = ref(null)
const showExportMenu = ref(false)
const panelTitle = computed(() => {
  if (showPanel.value === 'whiteboard') return t('chat.whiteboard')
  return ''
})

const ttsEnabled = ref(false)
const autoPlayNext = ref(false)
const isPlayingAudio = ref(false)
const currentAudio = ref(null)
const messagesEl = ref(null)

watch(ttsEnabled, (val) => {
  if (!val) {
    if (currentAudio.value) {
      currentAudio.value.pause()
      isPlayingAudio.value = false
      currentPlayingMsgId.value = null
      currentlyTalkingAgent.value = null
    }
  }
})

// 辩论模式支持
const isDebate = computed(() => archive.value?.metadata?.mode === 'debate')
const modeConfig = computed(() => archive.value?.metadata?.mode_config || {})
const debateFactions = computed(() => modeConfig.value.factions || {})

const participantIds = computed(() => archive.value?.metadata?.participants || [])
const participatingAgents = computed(() => {
  return agentsStore.agents.filter(a => participantIds.value.includes(a.id))
})
const totalMessages = computed(() => archive.value?.messages?.length || 0)
const visibleMessages = computed(() => (archive.value?.messages || []).slice(0, visibleCount.value))

const isFullscreen = ref(false)
function toggleFullscreen() {
  isFullscreen.value = !isFullscreen.value
}

const latestMessage = computed(() => {
  const msgs = visibleMessages.value
  return msgs.length ? msgs[msgs.length - 1] : null
})

function getAgentName(agentId) {
  const a = agentsStore.agents.find(x => x.id === agentId)
  return a?.name || agentId
}

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

const currentlyTalkingAgent = ref(null)
const currentPlayingMsgId = ref(null)
const loadingAudioMsgId = ref(null)
let talkTimeout = null

watch(latestMessage, (msg) => {
  if (msg && msg.agent_id) {
    if (talkTimeout) clearTimeout(talkTimeout)
    const duration = Math.max(2000, Math.min(8000, msg.content.length * 100))
    talkTimeout = setTimeout(() => {
      // Fallback timeout only if no audio is playing
      if (currentlyTalkingAgent.value === msg.agent_id && !isPlayingAudio.value) {
        currentlyTalkingAgent.value = null
      }
    }, duration)
  }
}, { immediate: true })

function getAgentActionClass(agentId) {
  if (isPlayingAudio.value && currentlyTalkingAgent.value === agentId) {
    return 'action-talk'
  }
  if (!isPlayingAudio.value && currentlyTalkingAgent.value === agentId) {
    return 'action-talk'
  }
  return 'action-idle'
}

async function doExport(format) {
  showExportMenu.value = false
  try {
    const resp = await exportArchive(sessionId, format)
    const blob = new Blob([resp.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `salon_${sessionId}.${format === 'pdf' ? 'pdf' : format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Export failed:', e)
    alert('导出失败: ' + (e.message || '未知错误'))
  }
}

function stepForward() {
  if (visibleCount.value < totalMessages.value) visibleCount.value++
}
function stepBack() {
  if (visibleCount.value > 1) visibleCount.value--
}
function autoPlay() {
  if (autoPlaying.value) {
    clearInterval(autoTimer)
    autoPlaying.value = false
  } else {
    autoPlaying.value = true
    autoTimer = setInterval(() => {
      // If audio is currently playing, wait for it to finish before stepping
      if (ttsEnabled.value && isPlayingAudio.value) return
      
      if (visibleCount.value >= totalMessages.value) {
        clearInterval(autoTimer)
        autoPlaying.value = false
      } else {
        visibleCount.value++
      }
    }, 3000)
  }
}

const audioQueue = ref([])
const isProcessingQueue = ref(false)
let isUnmounted = false

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
    audioQueue.value = []
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
    const res = await fetch('/api/tts/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        session_id: sessionId,
        message_id: msg.id,
        text: msg.content,
        voice_description: agent.voice_description || '',
        voice_name: agent.voice || ''
      })
    })
    const data = await res.json()
    
    // If user cancelled during loading, drop the result
    if (loadingAudioMsgId.value !== msg.id) return
    
    loadingAudioMsgId.value = null
    
    if (data.audio_url) {
      if (currentAudio.value) currentAudio.value.pause()
      
      const audio = new Audio(data.audio_url)
      currentAudio.value = audio
      currentPlayingMsgId.value = msg.id
      isPlayingAudio.value = true
      currentlyTalkingAgent.value = msg.agent_id
      audio.onended = () => { 
        isPlayingAudio.value = false 
        currentPlayingMsgId.value = null
        currentlyTalkingAgent.value = null
        
        if (autoPlayNext.value) {
          const allMsgs = visibleMessages.value
          const idx = allMsgs.findIndex(m => m.id === msg.id)
          if (idx !== -1) {
            for (let i = idx + 1; i < allMsgs.length; i++) {
              const nextMsg = allMsgs[i]
              if (nextMsg.speech_type !== 'intent' && nextMsg.agent_id !== 'human' && nextMsg.agent_id !== 'host') {
                togglePlayMessage(nextMsg)
                break
              }
            }
          }
        }
      }
      audio.play().catch(e => {
        console.warn('Audio play failed:', e)
        isPlayingAudio.value = false
        currentPlayingMsgId.value = null
        currentlyTalkingAgent.value = null
      })

      // 连播开启时，预加载下一条音频（利用当前播放时间完成生成）
      if (autoPlayNext.value) {
        preloadNextAudio(msg, visibleMessages.value)
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
    if (nextMsg.speech_type !== 'intent' && nextMsg.agent_id !== 'human' && nextMsg.agent_id !== 'host') {
      const agent = agentsStore.agents.find(a => a.id === nextMsg.agent_id)
      if (!agent) return
      // fire-and-forget：不阻塞当前播放，后端已有文件缓存，命中则秒回
      fetch('/api/tts/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          session_id: sessionId,
          message_id: nextMsg.id,
          text: nextMsg.content,
          voice_description: agent.voice_description || '',
          voice_name: agent.voice || ''
        })
      }).catch(() => {}) // 静默失败，不影响播放
      break
    }
  }
}

async function playAudio(msg) {
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
        const res = await fetch('/api/tts/generate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            session_id: sessionId,
            message_id: msg.id,
            text: msg.content,
            voice_description: agent.voice_description || '',
            voice_name: agent.voice || ''
          })
        })
        const data = await res.json()
        loadingAudioMsgId.value = null

        if (!audioQueue.value.includes(msg) || !ttsEnabled.value || isUnmounted) {
          resolve()
          return
        }

        if (data.audio_url) {
          if (currentAudio.value) currentAudio.value.pause()
          currentAudio.value = new Audio(data.audio_url)
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

watch(visibleCount, (newVal, oldVal) => {
  nextTick(() => {
    if (messagesEl.value) {
      const lastChild = messagesEl.value.lastElementChild
      if (lastChild) {
        lastChild.scrollIntoView({ behavior: 'smooth', block: 'start' })
      }
    }
  })
  if (newVal > oldVal) {
    const msg = latestMessage.value
    if (msg) playAudio(msg)
  }
})

function handleKeydown(e) {
  if (e.key === 'Escape' && isFullscreen.value) {
    isFullscreen.value = false
    return
  }
  if (e.key === 'Enter') {
    e.preventDefault()
    stepForward()
  }
}

onMounted(async () => {
  window.addEventListener('keydown', handleKeydown)
  agentsStore.fetchAgents()
  const { data } = await getArchive(sessionId)
  archive.value = data
  if (totalMessages.value > 0) {
    const msg = visibleMessages.value[0]
    if (msg) playAudio(msg)
  }
})

onUnmounted(() => {
  isUnmounted = true
  window.removeEventListener('keydown', handleKeydown)
  if (autoTimer) clearInterval(autoTimer)
  audioQueue.value = []
  if (currentAudio.value) currentAudio.value.pause()
})
</script>

<style scoped>
.chat-room-scene { display: flex; flex-direction: column; height: 100vh; overflow: hidden; position: relative; background: var(--bg-color); }
.pixel-header { position: absolute; top: 0; left: 0; right: 0; display: flex; justify-content: space-between; padding: 16px; z-index: 10; background: rgba(43, 43, 54, 0.8); backdrop-filter: blur(2px); border-bottom: 2px solid var(--border-color); align-items: flex-start; }
.header-left { display: flex; align-items: center; gap: 16px; flex: 1; flex-wrap: wrap; }
.header-right { display: flex; align-items: center; gap: 8px; flex-shrink: 0; white-space: nowrap; }
.topic-title { font-size: 20px; color: var(--accent-gold); text-shadow: 2px 2px 0 var(--border-color); flex: 1; min-width: 200px; }
.pixel-badge { background: var(--accent-blue); padding: 4px 8px; border: 2px solid var(--border-color); font-size: 14px; color: #111; white-space: nowrap; }

.pixel-btn { white-space: nowrap; } /* 防止所有按钮文字竖向折行 */

.playback-controls {
  position: absolute;
  top: 90px;
  right: 16px;
  z-index: 20;
  display: flex;
  gap: 8px;
  padding: 8px;
  background: rgba(54, 54, 68, 0.9);
  flex-shrink: 0;
  white-space: nowrap;
}
.btn-sm { font-size: 12px; padding: 4px 8px; }

.salon-stage { flex: 1; position: relative; }
.salon-bg { position: absolute; top: 0; left: 0; right: 0; bottom: 0; background: url('@/assets/images/salon-bg.png') no-repeat center bottom; background-size: cover; image-rendering: pixelated; opacity: 0.9; }

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

.character-name { margin-top: -10px; background: var(--border-color); padding: 4px 8px; border: 2px solid var(--text-muted); font-size: 12px; color: var(--text-primary); z-index: 5; }

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
.messages-scroll { flex: 1; overflow-y: auto; }

.controls-overlay { position: absolute; top: 16px; right: 16px; background: rgba(0,0,0,0.6); padding: 8px; border-radius: 4px; z-index: 20; }

/* .side-panel styles moved to DraggablePanel.vue */

/* --- Fullscreen Mode Styles --- */
.chat-room-scene.is-fullscreen .pixel-header,
.chat-room-scene.is-fullscreen .playback-controls,
.chat-room-scene.is-fullscreen .salon-stage {
  display: none;
}

.chat-room-scene.is-fullscreen .message-log-panel {
  height: 100vh;
  border-top: none;
  background: var(--bg-color);
  padding-bottom: 100px;
}

/* DraggablePanel handles its own sizing; no fullscreen override needed */

.floating-toolbar {
  position: fixed;
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 12px 24px;
  background: rgba(43, 43, 54, 0.95);
  backdrop-filter: blur(8px);
  z-index: 100;
  border: 2px solid var(--border-color);
  border-radius: 8px;
  box-shadow: 0 8px 24px rgba(0,0,0,0.6);
}

.toolbar-divider {
  width: 2px;
  height: 24px;
  background: var(--border-color);
  margin: 0 8px;
}

.export-menu {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 8px;
  z-index: 50;
}

.btn-danger {
  color: #ff6b6b;
  border-color: #ff6b6b;
}
.btn-danger:hover {
  background: #ff6b6b;
  color: #111;
}

.speaking-icon {
  display: inline-block;
  margin-left: 4px;
  animation: pulse-icon 1s infinite;
}

@keyframes pulse-icon {
  0% { transform: scale(1); opacity: 0.8; }
  50% { transform: scale(1.3); opacity: 1; text-shadow: 0 0 8px var(--accent-gold); }
  100% { transform: scale(1); opacity: 0.8; }
}
.custom-round-selector {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 4px;
}
.pixel-slider {
  width: 100px;
  cursor: pointer;
  accent-color: var(--accent-blue);
}
.num-input {
  width: 60px;
  text-align: center;
  padding: 2px 4px;
  font-size: 14px;
}
.fs-count {
  font-size: 14px;
  color: var(--accent-gold);
  min-width: 60px;
  text-align: center;
}
.btn-active {
  background: var(--accent-green, #4caf50) !important;
  color: #111 !important;
  border-color: var(--accent-green, #4caf50) !important;
}

</style>
