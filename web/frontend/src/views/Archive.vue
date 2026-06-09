<template>
  <div class="archive-quest-log pixel-box">
    <h1 class="quest-title">{{ t('archive.title') }}</h1>
    <p class="quest-subtitle">{{ t('archive.subtitle') }}</p>

    <div v-if="loading" class="loading">{{ t('archive.loading') }}</div>
    
    <div v-else-if="archives.length === 0" class="empty-state pixel-box">
      {{ t('archive.empty') }}
    </div>

    <div v-else class="archive-grid">
      <div v-for="arch in archives" :key="arch.session_id" class="archive-card pixel-box">
        <div class="card-header">
          <h2 class="card-title" @click="$router.push(`/archive/${arch.session_id}`)">
            {{ arch.topic || t('archive.unknown_scroll') }}
          </h2>
          <span class="date-badge">{{ formatDate(arch.created_at) }}</span>
        </div>
        
        <div class="card-body">
          <div class="stats-row">
            <span class="stat">⚔️ {{ t('archive.round', { n: arch.round_count || 0 }) }}</span>
            <span class="stat">👥 {{ t('archive.participants', { n: arch.participants?.length || 0 }) }}</span>
          </div>
          <div class="agents-list">
            <span v-for="aid in arch.participants" :key="aid" class="agent-tag">{{ getAgentName(aid) }}</span>
          </div>
        </div>
        
        <div class="card-actions">
          <button @click="$router.push(`/archive/${arch.session_id}`)" class="pixel-btn pixel-btn-primary btn-sm">
            {{ t('home.view') }}
          </button>
          <button @click="handleExport(arch.session_id, 'html')" class="pixel-btn btn-sm">
            📦 {{ t('archive.export') }}
          </button>
          <button @click="handleDelete(arch.session_id)" class="pixel-btn pixel-btn-danger btn-sm">
            {{ t('archive.destroy') }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { getArchives, deleteArchive, exportArchive } from '../api'
import { useAgentsStore } from '../stores/agents'
import { useI18nStore } from '../stores/i18n'

const archives = ref([])
const loading = ref(true)
const agentsStore = useAgentsStore()
const i18n = useI18nStore()
const t = i18n.t

function getAgentName(id) {
  if (id === 'human') return 'Human'
  const a = agentsStore.agents.find(x => x.id === id)
  return a ? a.name : id
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return `${d.getFullYear()}-${d.getMonth() + 1}-${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}

async function fetchAll() {
  loading.value = true
  try {
    const { data } = await getArchives()
    archives.value = data
  } finally {
    loading.value = false
  }
}

async function handleDelete(id) {
  if (!confirm(t('archive.destroy_confirm'))) return
  await deleteArchive(id)
  await fetchAll()
}

async function handleExport(id, format) {
  try {
    const resp = await exportArchive(id, format)
    const blob = new Blob([resp.data])
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `salon_${id}.${format === 'pdf' ? 'pdf' : format}`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  } catch (e) {
    console.error('Export failed:', e)
    alert('导出失败')
  }
}

onMounted(() => {
  agentsStore.fetchAgents()
  fetchAll()
})
</script>

<style scoped>
.archive-quest-log { max-width: 900px; margin: 20px auto; border: none; background: transparent; box-shadow: none; }
.quest-title { text-align: center; color: var(--accent-gold); margin-bottom: 8px; text-shadow: 2px 2px var(--border-color); font-size: 28px; }
.quest-subtitle { text-align: center; color: var(--text-muted); margin-bottom: 32px; font-size: 14px; }
.loading { text-align: center; color: var(--accent-blue); font-size: 20px; }
.empty-state { text-align: center; color: var(--text-muted); padding: 40px; }

.archive-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
.archive-card { padding: 16px; display: flex; flex-direction: column; gap: 12px; transition: transform 0.1s; }
.archive-card:hover { border-color: var(--accent-gold); transform: translateY(-4px); }

.card-header { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; }
.card-title { font-size: 16px; color: var(--text-primary); cursor: pointer; line-height: 1.4; text-decoration: underline; text-decoration-color: var(--border-color); }
.card-title:hover { color: var(--accent-gold); }
.date-badge { font-size: 10px; background: var(--bg-color); border: 1px solid var(--border-color); padding: 2px 6px; color: var(--text-muted); white-space: nowrap; }

.card-body { flex: 1; display: flex; flex-direction: column; gap: 8px; }
.stats-row { display: flex; gap: 12px; font-size: 12px; color: var(--accent-blue); }
.agents-list { display: flex; flex-wrap: wrap; gap: 6px; }
.agent-tag { background: var(--bg-color); border: 1px solid var(--border-color); padding: 2px 6px; font-size: 10px; color: var(--text-muted); }

.card-actions { display: flex; justify-content: flex-end; gap: 8px; margin-top: auto; border-top: 2px dashed var(--border-color); padding-top: 12px; }
</style>
