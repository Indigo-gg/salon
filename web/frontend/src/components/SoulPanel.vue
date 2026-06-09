<template>
  <div class="soul-panel">
    <div v-if="!agent" class="empty">选择一位角色查看灵魂档案。</div>
    <template v-else>
      <div class="agent-info">
        <span class="avatar">{{ agent.avatar || '?' }}</span>
        <div>
          <div class="name">{{ agent.name }}</div>
          <div class="role">{{ roleLabel(agent.role) }} {{ agent.group ? `· ${agent.group}` : '' }}</div>
        </div>
      </div>
      <div v-if="loading" class="loading">加载灵魂档案...</div>
      <pre v-else class="soul-content">{{ soulContent }}</pre>
    </template>
  </div>
</template>

<script setup>
import { ref, watch, onMounted } from 'vue'
import { getAgentSoul } from '../api'

const props = defineProps({
  agent: { type: Object, default: null },
})

const soulContent = ref('')
const loading = ref(false)

function roleLabel(role) {
  const map = { moderator: '主持人', participant: '参与者', scribe: '记录员' }
  return map[role] || role
}

async function loadSoul() {
  if (!props.agent) return
  loading.value = true
  try {
    const { data } = await getAgentSoul(props.agent.id)
    soulContent.value = data.content
  } catch {
    soulContent.value = '（未找到灵魂档案）'
  } finally {
    loading.value = false
  }
}

watch(() => props.agent, loadSoul)
onMounted(loadSoul)
</script>

<style scoped>
.agent-info { display: flex; align-items: center; gap: 10px; margin-bottom: 12px; padding-bottom: 12px; border-bottom: 1px solid #eee; }
.avatar { font-size: 28px; }
.name { font-weight: 600; font-size: 15px; }
.role { font-size: 12px; color: #888; }
.soul-content { white-space: pre-wrap; font-size: 12px; line-height: 1.6; background: #fefefe; padding: 10px; border-radius: 6px; border: 1px solid #f0f0f0; max-height: 500px; overflow-y: auto; }
.empty, .loading { color: #999; text-align: center; padding: 20px; }
</style>
