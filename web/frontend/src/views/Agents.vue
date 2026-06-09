<template>
  <div class="character-select pixel-box">
    <div class="header">
      <h1 class="title">{{ t('agents.title') }}</h1>
      <div class="header-actions">
        <router-link to="/agents/new" class="pixel-btn pixel-btn-primary">{{ t('agents.new_hero') }}</router-link>
        <router-link to="/groups/new" class="pixel-btn pixel-btn-gold">{{ t('agents.new_group') }}</router-link>
      </div>
    </div>

    <div v-for="group in groupsStore.groups" :key="group.id" class="group-section">
      <div class="group-header">
        <div class="group-info">
          <span class="group-emoji">{{ group.emoji || '?' }}</span>
          <span class="group-name">{{ group.name }}</span>
          <span class="group-count">{{ t('groups.agent_count', { n: groupMembers(group.id).length }) }}</span>
        </div>
        <div class="group-actions">
          <router-link :to="`/agents/new?group=${encodeURIComponent(group.id)}`" class="pixel-btn btn-sm" :title="t('agents.add_agent')">+</router-link>
          <router-link :to="`/groups/${group.id}/edit`" class="pixel-btn btn-sm">{{ t('groups.edit') }}</router-link>
          <button @click="removeGroup(group.id)" class="pixel-btn btn-sm pixel-btn-danger">{{ t('groups.delete') }}</button>
        </div>
      </div>
      <div class="roster-grid">
        <div v-for="agent in groupMembers(group.id)" :key="agent.id" class="agent-card pixel-box">
          <div class="card-top">
            <div class="avatar-box">{{ agent.avatar || '?' }}</div>
            <div class="info">
              <h2 class="agent-name">{{ agent.name }}</h2>
              <div class="agent-meta">
                <span class="role-badge" :class="agent.role">{{ roleLabel(agent.role) }}</span>
              </div>
            </div>
          </div>
          <div class="card-actions">
            <router-link :to="`/agents/${agent.id}/edit`" class="pixel-btn btn-sm">{{ t('agents.stats') }}</router-link>
            <button @click="banish(agent.id)" class="pixel-btn btn-sm pixel-btn-danger">{{ t('agents.banish') }}</button>
          </div>
        </div>
      </div>
    </div>

    <div v-if="ungrouped.length" class="group-section">
      <div class="group-header">
        <div class="group-info">
          <span class="group-name">{{ t('groups.ungrouped') }}</span>
          <span class="group-count">{{ t('groups.agent_count', { n: ungrouped.length }) }}</span>
        </div>
      </div>
      <div class="roster-grid">
        <div v-for="agent in ungrouped" :key="agent.id" class="agent-card pixel-box">
          <div class="card-top">
            <div class="avatar-box">{{ agent.avatar || '?' }}</div>
            <div class="info">
              <h2 class="agent-name">{{ agent.name }}</h2>
              <div class="agent-meta">
                <span class="role-badge" :class="agent.role">{{ roleLabel(agent.role) }}</span>
              </div>
            </div>
          </div>
          <div class="card-actions">
            <router-link :to="`/agents/${agent.id}/edit`" class="pixel-btn btn-sm">{{ t('agents.stats') }}</router-link>
            <button @click="banish(agent.id)" class="pixel-btn btn-sm pixel-btn-danger">{{ t('agents.banish') }}</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useAgentsStore } from '../stores/agents'
import { useGroupsStore } from '../stores/groups'
import { useI18nStore } from '../stores/i18n'

const agentsStore = useAgentsStore()
const groupsStore = useGroupsStore()
const i18n = useI18nStore()
const t = i18n.t

function groupMembers(groupId) {
  return agentsStore.agents.filter(a => a.group === groupId)
}

const ungrouped = computed(() => agentsStore.agents.filter(a => !a.group))

function roleLabel(role) {
  const map = { moderator: 'mod', participant: 'ftr', scribe: 'mag' }
  const r = map[role] || role
  return t(`agents.${r}`)
}

async function banish(id) {
  if (confirm(t('agents.banish_confirm'))) {
    await agentsStore.deleteAgent(id)
  }
}

async function removeGroup(id) {
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
.character-select { max-width: 1000px; margin: 20px auto; border: none; background: transparent; box-shadow: none; }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; border-bottom: 2px solid var(--border-color); padding-bottom: 12px; }
.title { color: var(--accent-gold); font-size: 24px; text-shadow: 2px 2px var(--border-color); }
.header-actions { display: flex; gap: 10px; }

.group-section { margin-bottom: 28px; }
.group-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-bottom: 8px; border-bottom: 1px dashed var(--border-color); }
.group-info { display: flex; align-items: center; gap: 10px; }
.group-emoji { font-size: 20px; }
.group-name { font-size: 18px; color: var(--text-primary); }
.group-count { font-size: 12px; color: var(--accent-blue); border: 1px solid var(--accent-blue); padding: 1px 6px; }
.group-actions { display: flex; gap: 6px; }

.roster-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 16px; }
.agent-card { padding: 16px; display: flex; flex-direction: column; gap: 16px; transition: transform 0.1s; }
.agent-card:hover { border-color: var(--accent-blue); transform: translateY(-4px); }

.card-top { display: flex; gap: 16px; align-items: center; }
.avatar-box { width: 64px; height: 64px; background: var(--bg-color); border: 2px solid var(--border-color); display: flex; justify-content: center; align-items: center; font-size: 32px; box-shadow: inset 2px 2px 0 rgba(0,0,0,0.5); }
.info { flex: 1; }
.agent-name { font-size: 18px; color: var(--text-primary); margin-bottom: 8px; }
.agent-meta { display: flex; gap: 8px; }
.role-badge { font-size: 10px; padding: 2px 6px; border: 1px solid; }
.role-badge.moderator { color: var(--accent-red); border-color: var(--accent-red); }
.role-badge.participant { color: var(--accent-blue); border-color: var(--accent-blue); }
.role-badge.scribe { color: var(--accent-gold); border-color: var(--accent-gold); }

.card-actions { display: flex; justify-content: flex-end; gap: 8px; border-top: 2px dashed var(--border-color); padding-top: 12px; }
</style>
