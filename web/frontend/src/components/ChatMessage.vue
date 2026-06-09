<template>
  <!-- intent 消息完全隐藏 -->
  <div class="log-message" :class="{'intent-msg': msg.speech_type === 'intent', 'system-notice-msg': msg.speech_type === 'system_notice', 'streaming': msg.streaming}">
    <template v-if="msg.speech_type !== 'intent'">
      <div class="log-header">
        <span class="log-name" :class="{'human': msg.agent_id === 'human', 'system': msg.agent_role === 'system'}">
          <span v-if="mode === 'debate' && faction" class="faction-badge" :class="faction === 'affirmative' ? 'faction-aff' : 'faction-neg'">
            {{ faction === 'affirmative' ? '正方' : '反方' }}
          </span>
          [{{ displayName }}]
        </span>
        <div class="header-actions">
          <slot name="header-actions" />
          <button
            v-if="showTts && msg.agent_id !== 'human' && msg.agent_role !== 'system'"
            @click="$emit('tts-toggle')"
            :disabled="ttsLoading"
            class="pixel-btn btn-sm btn-tts"
          >
            <span v-if="ttsLoading">⏳ 生成中...</span>
            <span v-else>{{ ttsPlaying ? '🔊 停止' : '🔈 播放' }}</span>
          </button>
          <button
            v-if="showApprove"
            @click="$emit('approve')"
            :disabled="approved"
            class="pixel-btn btn-sm btn-approve"
            :class="{'btn-approved': approved}"
          >
            {{ approved ? '[已批准]' : '[批准发言]' }}
          </button>
        </div>
      </div>
      <div class="log-text markdown-body" v-html="renderedContent"></div>
      <div v-if="msg.mentions?.length" class="mentions">@{{ resolvedMentions.join(' @') }}</div>
      <!-- 工具调用 metadata（可折叠） -->
      <details v-if="msg.metadata?.tool_calls?.length" class="tool-calls-details">
        <summary class="tool-calls-summary">📎 引用来源（{{ msg.metadata.tool_calls.length }} 次工具调用）</summary>
        <div v-for="(tc, idx) in msg.metadata.tool_calls" :key="idx" class="tool-call-entry">
          <div class="tool-call-header">🔍 {{ tc.tool }}：<code>{{ formatToolInput(tc.input) }}</code></div>
          <div class="tool-call-output">{{ tc.output }}</div>
        </div>
      </details>
      <span v-if="msg.streaming" class="streaming-cursor">▍</span>
    </template>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import { useAgentsStore } from '../stores/agents'

const agentsStore = useAgentsStore()

const props = defineProps({
  msg: { type: Object, required: true },
  mode: { type: String, default: 'salon' },
  factions: { type: Object, default: () => ({}) },
  showTts: { type: Boolean, default: true },
  ttsLoading: { type: Boolean, default: false },
  ttsPlaying: { type: Boolean, default: false },
  showApprove: { type: Boolean, default: false },
  approved: { type: Boolean, default: false },
})

defineEmits(['tts-toggle', 'approve'])

const displayName = computed(() => {
  const id = props.msg.agent_id
  const agent = agentsStore.agents.find(a => a.id === id)
  return agent?.name || props.msg.agent_name || id
})

const faction = computed(() => {
  return props.msg.faction || props.factions[props.msg.agent_id] || ''
})

const resolvedMentions = computed(() => {
  return (props.msg.mentions || []).map(idOrName => {
    const agent = agentsStore.agents.find(a => a.id === idOrName)
    return agent ? agent.name : idOrName
  })
})

const renderedContent = computed(() => {
  return marked.parse(props.msg.content || '')
})

function formatToolInput(input) {
  if (!input) return ''
  if (input.queries) return input.queries.join(', ')
  return JSON.stringify(input)
}
</script>

<style scoped>
.log-message { margin-bottom: 12px; font-size: 16px; line-height: 1.6; display: flex; flex-direction: column; }
.log-header { display: flex; justify-content: space-between; align-items: center; gap: 8px; margin-bottom: 4px; }
.log-name { color: var(--accent-blue); font-weight: bold; }
.log-name.human { color: var(--accent-green); }
.log-name.system { color: var(--text-muted); font-weight: normal; }
.log-text { color: var(--text-primary); }
.mentions { font-size: 11px; color: #888; margin-top: 3px; }

.intent-msg { display: none; }
.system-notice-msg { opacity: 0.6; font-size: 12px; color: var(--text-muted); border-left: 2px dashed var(--text-muted); padding-left: 10px; margin-bottom: 6px; }

.header-actions { display: flex; align-items: center; gap: 6px; }

.btn-tts { padding: 2px 6px; font-size: 12px; }
.btn-approve { font-size: 10px; padding: 2px 6px; background: transparent; color: var(--accent-gold); border-color: var(--accent-gold); }
.btn-approve:hover:not(:disabled) { background: var(--accent-gold); color: #111; }
.btn-approved { color: var(--text-muted); border-color: var(--text-muted); cursor: not-allowed; }

/* 工具调用 metadata */
.tool-calls-details { margin-top: 6px; font-size: 12px; }
.tool-calls-summary { color: var(--text-muted); cursor: pointer; font-size: 11px; user-select: none; }
.tool-calls-summary:hover { color: var(--accent-blue); }
.tool-call-entry { margin-top: 4px; padding: 6px 8px; background: rgba(255,255,255,0.03); border-radius: 4px; border-left: 2px solid var(--text-muted); }
.tool-call-header { color: var(--text-muted); font-size: 11px; margin-bottom: 3px; }
.tool-call-header code { font-size: 10px; background: rgba(255,255,255,0.05); padding: 1px 4px; border-radius: 2px; }
.tool-call-output { color: var(--text-muted); font-size: 11px; line-height: 1.4; white-space: pre-wrap; max-height: 120px; overflow-y: auto; }

/* 流式消息 */
.streaming-cursor { display: inline-block; color: var(--accent-gold); font-weight: bold; animation: blink-cursor 0.8s steps(2) infinite; }
@keyframes blink-cursor { 0% { opacity: 1; } 100% { opacity: 0; } }
.log-message.streaming { border-left: 2px solid var(--accent-gold); padding-left: 10px; }

/* 辩论模式阵营标签 */
.faction-badge {
  display: inline-block; font-size: 10px; padding: 1px 5px;
  border: 1px solid; margin-right: 4px; font-weight: bold; vertical-align: middle;
}
.faction-badge.faction-aff { color: var(--accent-blue); border-color: var(--accent-blue); background: rgba(100, 149, 237, 0.15); }
.faction-badge.faction-neg { color: var(--accent-red); border-color: var(--accent-red); background: rgba(220, 20, 60, 0.15); }

/* Markdown body */
:deep(.markdown-body p) { margin: 0 0 8px 0; }
:deep(.markdown-body p:last-child) { margin-bottom: 0; }
:deep(.markdown-body strong) { color: var(--accent-gold); }
:deep(.markdown-body code) { background: var(--bg-color); padding: 2px 4px; border-radius: 4px; font-family: monospace; }
:deep(.markdown-body pre) { background: var(--bg-color); padding: 8px; border-radius: 4px; overflow-x: auto; margin: 8px 0; }
</style>
