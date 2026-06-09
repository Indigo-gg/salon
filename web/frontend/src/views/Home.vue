<template>
  <div class="home pixel-box">
    <h1 class="dashboard-title">{{ t('home.console') }}</h1>

    <div class="quick-start pixel-box">
      <h2 class="section-title">{{ t('home.start_quest') }}</h2>
      <div class="start-form">
        <input v-model="topic" :placeholder="topicPlaceholder" class="pixel-input input-full" />

        <!-- 模式选择卡片 -->
        <div class="mode-cards">
          <div
            v-for="m in modes"
            :key="m.value"
            class="mode-card pixel-box"
            :class="{ selected: mode === m.value }"
            @click="selectMode(m.value)"
          >
            <span class="mode-icon">{{ m.icon }}</span>
            <span class="mode-name">{{ m.name }}</span>
            <span class="mode-desc">{{ m.desc }}</span>
          </div>
        </div>

        <!-- 角色选择器 -->
        <AgentRoster
          v-if="mode !== 'debate'"
          :agents="selectableAgents"
          :groups="groupsStore.groups"
          :selected="selectedAgents"
          selected-title="已选角色"
          pool-title="待选角色"
          @add="toggleAgent"
          @remove="removeAgent"
        />

        <!-- 辩论模式：带正反方按钮的角色选择器 -->
        <AgentRoster
          v-else
          :agents="selectableAgents"
          :groups="groupsStore.groups"
          :selected="debateSelectedIds"
          :factions="debateFactions"
          selected-title="已分阵营"
          pool-title="待选辩手"
          @add="cycleFaction"
          @remove="removeDebateAgent"
        >
          <template #actions="{ agent, isSelected }">
            <button
              class="action-btn faction-aff"
              :class="{ 'is-active': debateFactions[agent.id] === 'affirmative' }"
              @click.stop="setFaction(agent.id, 'affirmative')"
            >
              {{ debateFactions[agent.id] === 'affirmative' ? '✓ 正方' : '正方' }}
            </button>
            <button
              class="action-btn faction-neg"
              :class="{ 'is-active': debateFactions[agent.id] === 'negative' }"
              @click.stop="setFaction(agent.id, 'negative')"
            >
              {{ debateFactions[agent.id] === 'negative' ? '✓ 反方' : '反方' }}
            </button>
          </template>
        </AgentRoster>

        <button @click="startNew" :disabled="!canStart" class="pixel-btn pixel-btn-primary start-btn">
          {{ t('home.enter_dungeon') }}
        </button>
      </div>
    </div>

    <div class="sections">
      <div class="section pixel-box">
        <h2 class="section-title">{{ t('home.active_sessions') }}</h2>
        <div v-if="newSessions.length === 0 && resumableSessions.length === 0 && finishedSessions.length === 0" class="empty">
          {{ t('home.no_active') }}
        </div>

        <div v-if="newSessions.length > 0">
          <h3 class="sub-heading">{{ t('home.pending') }}</h3>
          <div v-for="s in newSessions" :key="s.session_id" class="session-card new">
            <div class="session-top" @click="$router.push(`/chat/${s.session_id}`)">
              <div class="session-topic">{{ s.topic }}</div>
              <span class="state-badge" :class="s.mode || 'created'">{{ modeLabel(s.mode) }}</span>
            </div>
            <div class="session-meta">
              <span>{{ formatDate(s.created_at) }}</span>
            </div>
            <div class="session-agents">
              <span v-for="(name, i) in (s.agent_names || s.agent_ids)" :key="i" class="tag">{{ name }}</span>
            </div>
            <div class="session-actions">
              <button @click="$router.push(`/chat/${s.session_id}`)" class="pixel-btn btn-sm pixel-btn-primary">{{ t('home.start') }}</button>
              <button @click="deleteSession(s.session_id)" class="pixel-btn btn-sm pixel-btn-danger">{{ t('home.delete') }}</button>
            </div>
          </div>
        </div>

        <div v-if="resumableSessions.length > 0">
          <h3 class="sub-heading">{{ t('home.resumable') }}</h3>
          <div v-for="s in resumableSessions" :key="s.session_id" class="session-card resumable">
            <div class="session-top" @click="$router.push(`/chat/${s.session_id}`)">
              <div class="session-topic">{{ s.topic }}</div>
              <span class="state-badge" :class="s.state">{{ stateLabel(s.state) }}</span>
            </div>
            <div class="session-meta">
              <span>{{ t('home.round', { n: s.round_count }) }}</span>
              <span>{{ formatDate(s.created_at) }}</span>
            </div>
            <div class="session-agents">
              <span v-for="(name, i) in (s.agent_names || s.agent_ids)" :key="i" class="tag">{{ name }}</span>
            </div>
            <div class="session-actions">
              <button @click="$router.push(`/chat/${s.session_id}`)" class="pixel-btn btn-sm pixel-btn-primary">{{ t('home.resume') }}</button>
              <button @click="archiveSession(s.session_id)" class="pixel-btn btn-sm">{{ t('home.archive') }}</button>
            </div>
          </div>
        </div>

      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAgentsStore } from '../stores/agents'
import { useGroupsStore } from '../stores/groups'
import { useSessionStore } from '../stores/session'
import { useI18nStore } from '../stores/i18n'
import AgentRoster from '../components/AgentRoster.vue'

const router = useRouter()
const agentsStore = useAgentsStore()
const groupsStore = useGroupsStore()
const sessionStore = useSessionStore()
const i18n = useI18nStore()
const t = i18n.t

const topic = ref('')
const mode = ref('salon')
const selectedAgents = ref([])
const debateFactions = ref({})  // { agent_id: 'affirmative' | 'negative' }

const modes = [
  { value: 'salon', icon: '🏰', name: '沙龙', desc: 'AI 主持人自动调度，自由探索' },
  { value: 'interview', icon: '🎤', name: '会谈', desc: '你来主持，指定发言人' },
  { value: 'debate', icon: '⚔️', name: '辩论', desc: '正反方对抗，分阶段辩论' },
]

const topicPlaceholder = computed(() => {
  if (mode.value === 'debate') return '输入辩题，如：人工智能将取代人类的工作'
  return t('home.topic_ph', '输入讨论主题...')
})

const selectableAgents = computed(() => agentsStore.agents.filter(a => a.role === 'participant'))

// 辩论模式：已选 ID 列表
const debateSelectedIds = computed(() => Object.keys(debateFactions.value))

const canStart = computed(() => {
  if (!topic.value) return false
  if (mode.value === 'debate') {
    const aff = Object.values(debateFactions.value).filter(f => f === 'affirmative').length
    const neg = Object.values(debateFactions.value).filter(f => f === 'negative').length
    return aff >= 1 && neg >= 1
  }
  return selectedAgents.value.length > 0
})

// --- 模式切换时重置选择 ---
function selectMode(m) {
  mode.value = m
}

// --- 沙龙/会谈模式 ---
function toggleAgent(id) {
  const idx = selectedAgents.value.indexOf(id)
  if (idx === -1) selectedAgents.value.push(id)
  else selectedAgents.value.splice(idx, 1)
}

function removeAgent(id) {
  const idx = selectedAgents.value.indexOf(id)
  if (idx !== -1) selectedAgents.value.splice(idx, 1)
}

// --- 辩论模式 ---
function setFaction(id, faction) {
  if (debateFactions.value[id] === faction) {
    // 已在该阵营 → 移除
    const { [id]: _, ...rest } = debateFactions.value
    debateFactions.value = rest
  } else {
    debateFactions.value = { ...debateFactions.value, [id]: faction }
  }
}

function cycleFaction(id) {
  const current = debateFactions.value[id]
  if (!current) setFaction(id, 'affirmative')
  else if (current === 'affirmative') setFaction(id, 'negative')
  else {
    const { [id]: _, ...rest } = debateFactions.value
    debateFactions.value = rest
  }
}

function removeDebateAgent(id) {
  const { [id]: _, ...rest } = debateFactions.value
  debateFactions.value = rest
}

// --- 会话列表 ---
const newSessions = computed(() =>
  sessionStore.sessions.filter(s => s.state === 'created' && s.round_count === 0)
)
const resumableSessions = computed(() =>
  sessionStore.sessions.filter(s => (s.state === 'running' || s.state === 'paused') || (s.state === 'created' && s.round_count > 0))
)
const finishedSessions = computed(() =>
  sessionStore.sessions.filter(s => s.state === 'finished' || s.state === 'unknown')
)

function stateLabel(state) {
  const key = `chat.state_${state}`
  const trans = t(key)
  return trans === key ? state.toUpperCase() : trans
}

function modeLabel(m) {
  const found = modes.find(x => x.value === m)
  return found ? found.name : m || 'salon'
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

// --- 创建会话 ---
async function startNew() {
  if (mode.value === 'debate') {
    const factions = { ...debateFactions.value }
    const agentIds = Object.keys(factions)
    const modeConfig = { factions }
    const session = await sessionStore.createSession(topic.value, agentIds, 'debate', modeConfig)
    router.push(`/chat/${session.session_id}`)
  } else {
    const allAgents = [...new Set([...selectedAgents.value])]
    const session = await sessionStore.createSession(topic.value, allAgents, mode.value)
    router.push(`/chat/${session.session_id}`)
  }
}

async function archiveSession(id) {
  await sessionStore.archiveSession(id)
}

async function deleteSession(id) {
  if (!confirm(t('home.banish_confirm'))) return
  await sessionStore.deleteSession(id)
}

onMounted(() => {
  agentsStore.fetchAgents()
  groupsStore.fetchGroups()
  sessionStore.fetchSessions()
})
</script>

<style scoped>
.home { max-width: 1000px; margin: 20px auto; background: var(--bg-color); border: none; box-shadow: none; }
.dashboard-title { text-align: center; color: var(--accent-gold); margin-bottom: 24px; text-shadow: 2px 2px var(--border-color); letter-spacing: 2px; }

.quick-start { background: var(--panel-bg); margin-bottom: 24px; border-color: var(--border-color); }
.section-title { color: var(--accent-blue); margin-bottom: 16px; border-bottom: 2px solid var(--border-color); padding-bottom: 8px; font-size: 18px; display: flex; align-items: baseline; gap: 10px; }

.start-form { display: flex; flex-direction: column; gap: 16px; }
.input-full { width: 100%; font-size: 16px; padding: 12px; }
.start-btn { margin-top: 4px; }

/* 模式选择卡片 */
.mode-cards { display: flex; gap: 12px; }
.mode-card { flex: 1; display: flex; flex-direction: column; align-items: center; gap: 4px; padding: 16px 12px; cursor: pointer; transition: all 0.15s; text-align: center; border-color: var(--border-color); background: var(--bg-color); }
.mode-card:hover { border-color: var(--accent-blue); transform: translateY(-2px); }
.mode-card.selected { border-color: var(--accent-gold); background: var(--panel-bg); box-shadow: 0 0 8px rgba(255, 215, 0, 0.3); }
.mode-icon { font-size: 28px; }
.mode-name { font-weight: bold; color: var(--text-primary); font-size: 15px; }
.mode-desc { font-size: 11px; color: var(--text-muted); line-height: 1.3; }

/* 辩论按钮激活态 */
.action-btn.faction-aff.is-active { background: rgba(100, 149, 237, 0.25); font-weight: bold; }
.action-btn.faction-neg.is-active { background: rgba(220, 20, 60, 0.25); font-weight: bold; }

/* 会话列表 */
.sections { display: flex; flex-direction: column; gap: 24px; }
.section { background: var(--panel-bg); border-color: var(--border-color); }
.sub-heading { font-size: 14px; color: var(--accent-gold); margin: 16px 0 8px; }
.empty { color: var(--text-muted); font-size: 14px; text-align: center; padding: 20px 0; }

.session-card { padding: 12px; border: 2px solid var(--border-color); background: var(--bg-color); margin-bottom: 12px; cursor: pointer; transition: transform 0.1s; }
.session-card:hover { border-color: var(--accent-gold); transform: translateX(4px); }
.session-card.new { border-left-color: var(--accent-blue); }
.session-card.resumable { border-left-color: var(--accent-green); }

.session-top { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.session-topic { font-weight: bold; color: var(--text-primary); font-size: 16px; }
.state-badge { font-size: 10px; padding: 2px 6px; border: 1px solid var(--text-primary); }
.state-badge.created { background: var(--accent-blue); color: #111; border-color: var(--accent-blue); }
.state-badge.running { background: var(--accent-green); color: #111; border-color: var(--accent-green); }
.state-badge.paused { background: var(--accent-gold); color: #111; border-color: var(--accent-gold); }
.state-badge.finished { background: var(--text-muted); color: var(--text-primary); border-color: var(--text-muted); }
.state-badge.debate { background: var(--accent-red); color: #fff; border-color: var(--accent-red); }
.state-badge.salon { background: var(--accent-blue); color: #111; border-color: var(--accent-blue); }
.state-badge.interview { background: var(--accent-gold); color: #111; border-color: var(--accent-gold); }

.session-meta { font-size: 12px; color: var(--text-muted); display: flex; gap: 16px; margin-bottom: 8px; }
.session-agents { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { background: var(--border-color); border: 1px solid var(--panel-bg); padding: 2px 6px; font-size: 10px; color: var(--text-muted); }
.session-actions { margin-top: 12px; display: flex; gap: 8px; }
.btn-sm { font-size: 12px; padding: 6px 12px; }

</style>
