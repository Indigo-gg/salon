<template>
  <div class="memory-panel">
    <div class="agent-tabs">
      <button
        v-for="(mem, aid) in memories" :key="aid"
        :class="['tab-btn', { active: activeAgent === aid }]"
        @click="activeAgent = aid"
      >
        {{ mem.name || aid }}
      </button>
    </div>

    <div v-if="!activeAgent || !memories[activeAgent]" class="empty">
      暂无记忆数据
    </div>

    <div v-else class="mem-body">
      <div class="mem-section">
        <h4>已表达立场 <span class="badge">{{ memories[activeAgent].expressed_stances.length }}</span></h4>
        <ul v-if="memories[activeAgent].expressed_stances.length">
          <li v-for="(s, i) in memories[activeAgent].expressed_stances" :key="i">{{ s }}</li>
        </ul>
        <p v-else class="empty-hint">暂无</p>
      </div>

      <div class="mem-section">
        <h4>独特贡献 <span class="badge">{{ memories[activeAgent].unique_contributions.length }}</span></h4>
        <ul v-if="memories[activeAgent].unique_contributions.length">
          <li v-for="(c, i) in memories[activeAgent].unique_contributions" :key="i">{{ c }}</li>
        </ul>
        <p v-else class="empty-hint">暂无</p>
      </div>

      <div class="mem-section">
        <h4>活跃分歧 <span class="badge">{{ memories[activeAgent].active_disagreements.length }}</span></h4>
        <ul v-if="memories[activeAgent].active_disagreements.length">
          <li v-for="(d, i) in memories[activeAgent].active_disagreements" :key="i">{{ d }}</li>
        </ul>
        <p v-else class="empty-hint">暂无</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { getArchiveMemory } from '../api'

const props = defineProps({
  sessionId: { type: String, required: true },
})

const memories = ref({})
const activeAgent = ref(null)
let timer = null

async function load() {
  try {
    const { data } = await getArchiveMemory(props.sessionId)
    memories.value = data
    const ids = Object.keys(data)
    if (ids.length && !activeAgent.value) {
      activeAgent.value = ids[0]
    }
  } catch (e) {
    console.error('Failed to load memory:', e)
  }
}

onMounted(() => {
  load()
  timer = setInterval(load, 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.memory-panel {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 200px;
}
.agent-tabs {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}
.tab-btn {
  padding: 3px 10px;
  font-size: 11px;
  border-radius: 10px;
  cursor: pointer;
  border: 1px solid var(--border-color);
  background: transparent;
  color: var(--text-primary);
  transition: all 0.15s;
}
.tab-btn:hover { background: var(--border-color); }
.tab-btn.active {
  background: var(--accent-blue);
  color: #fff;
  border-color: var(--accent-blue);
}
.mem-body { display: flex; flex-direction: column; gap: 14px; }
.mem-section h4 {
  font-size: 11px;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 4px;
  display: flex;
  align-items: center;
  gap: 6px;
}
.badge {
  background: var(--accent-blue);
  color: #fff;
  font-size: 10px;
  padding: 0 5px;
  border-radius: 8px;
}
.mem-section ul {
  list-style: none;
  padding: 0;
  margin: 0;
}
.mem-section li {
  font-size: 12px;
  padding: 4px 0;
  border-bottom: 1px dashed var(--border-color);
  line-height: 1.5;
  color: var(--text-primary);
}
.mem-section li:last-child { border-bottom: none; }
.empty-hint { font-size: 11px; color: var(--text-muted); font-style: italic; }
.empty { text-align: center; color: var(--text-muted); padding: 20px; font-size: 13px; }
</style>
