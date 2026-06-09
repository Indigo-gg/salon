<template>
  <div class="groups-manage pixel-box">
    <div class="header">
      <h1 class="title">{{ t('groups.title') }}</h1>
      <router-link to="/groups/new" class="pixel-btn pixel-btn-primary">{{ t('groups.new_group') }}</router-link>
    </div>

    <div class="group-grid">
      <div v-for="group in groupsStore.groups" :key="group.id" class="group-card pixel-box">
        <div class="card-top">
          <div class="emoji-box">{{ group.emoji || '?' }}</div>
          <div class="info">
            <h2 class="group-name">{{ group.name }}</h2>
            <p v-if="group.description" class="group-desc">{{ group.description }}</p>
            <span class="agent-count">{{ t('groups.agent_count', { n: agentCount(group.id) }) }}</span>
          </div>
        </div>
        <div class="members">
          <span v-for="a in groupMembers(group.id)" :key="a.id" class="member-chip">
            {{ a.avatar || '' }} {{ a.name }}
          </span>
        </div>
        <div class="card-actions">
          <router-link :to="`/groups/${group.id}/edit`" class="pixel-btn btn-sm">{{ t('groups.edit') }}</router-link>
          <button @click="remove(group.id)" class="pixel-btn btn-sm pixel-btn-danger">{{ t('groups.delete') }}</button>
        </div>
      </div>
    </div>

    <div v-if="ungrouped.length" class="ungrouped-section pixel-box">
      <h2 class="section-title">{{ t('groups.ungrouped') }}</h2>
      <div class="members">
        <span v-for="a in ungrouped" :key="a.id" class="member-chip">
          {{ a.avatar || '' }} {{ a.name }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useGroupsStore } from '../stores/groups'
import { useAgentsStore } from '../stores/agents'
import { useI18nStore } from '../stores/i18n'

const groupsStore = useGroupsStore()
const agentsStore = useAgentsStore()
const i18n = useI18nStore()
const t = i18n.t

function agentCount(groupId) {
  return agentsStore.agents.filter(a => a.group === groupId).length
}

function groupMembers(groupId) {
  return agentsStore.agents.filter(a => a.group === groupId)
}

const ungrouped = computed(() => agentsStore.agents.filter(a => !a.group))

async function remove(id) {
  if (confirm(t('groups.delete_confirm'))) {
    await groupsStore.deleteGroup(id)
    await agentsStore.fetchAgents()
  }
}

onMounted(() => {
  groupsStore.fetchGroups()
  agentsStore.fetchAgents()
})
</script>

<style scoped>
.groups-manage { max-width: 1000px; margin: 20px auto; border: none; background: transparent; box-shadow: none; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 2px solid var(--border-color); padding-bottom: 12px; }
.title { color: var(--accent-gold); font-size: 24px; text-shadow: 2px 2px var(--border-color); }

.group-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 20px; }
.group-card { padding: 16px; display: flex; flex-direction: column; gap: 12px; transition: transform 0.1s; }
.group-card:hover { border-color: var(--accent-blue); transform: translateY(-4px); }

.card-top { display: flex; gap: 16px; align-items: center; }
.emoji-box { width: 48px; height: 48px; background: var(--bg-color); border: 2px solid var(--border-color); display: flex; justify-content: center; align-items: center; font-size: 24px; box-shadow: inset 2px 2px 0 rgba(0,0,0,0.5); }
.info { flex: 1; }
.group-name { font-size: 18px; color: var(--text-primary); margin-bottom: 4px; }
.group-desc { font-size: 13px; color: var(--text-muted); margin: 0 0 4px; }
.agent-count { font-size: 12px; color: var(--accent-blue); border: 1px solid var(--accent-blue); padding: 1px 6px; }

.members { display: flex; flex-wrap: wrap; gap: 6px; }
.member-chip { font-size: 12px; padding: 3px 8px; background: var(--bg-color); border: 1px solid var(--border-color); color: var(--text-muted); }

.card-actions { display: flex; justify-content: flex-end; gap: 8px; border-top: 2px dashed var(--border-color); padding-top: 12px; }

.ungrouped-section { margin-top: 24px; padding: 16px; }
.section-title { font-size: 16px; color: var(--text-muted); margin-bottom: 12px; }
</style>
