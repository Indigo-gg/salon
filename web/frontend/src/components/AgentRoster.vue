<template>
  <div class="agent-roster">
    <!-- 已选区 -->
    <div v-if="selected.length > 0" class="selected-zone pixel-box">
      <div class="zone-header">
        <span class="zone-title">{{ selectedTitle }}</span>
        <span class="zone-count">{{ selected.length }}</span>
      </div>
      <div class="selected-list">
        <div v-for="sid in selected" :key="sid" class="selected-chip">
          <span class="chip-avatar">{{ getAgent(sid).avatar || '?' }}</span>
          <span class="chip-name">{{ getAgent(sid).name }}</span>
          <span v-if="getFactionTag(sid)" class="chip-faction" :class="getFactionTag(sid).cls">{{ getFactionTag(sid).label }}</span>
          <button class="chip-remove" @click.stop="$emit('remove', sid)">×</button>
        </div>
      </div>
    </div>

    <!-- 待选区 -->
    <div class="pool-zone">
      <div class="zone-header">
        <span class="zone-title">{{ poolTitle }}</span>
      </div>

      <div v-for="g in groupedAgents" :key="g.key" class="agent-group">
        <div class="group-header" @click="toggleExpand(g.key)">
          <span class="group-arrow" :class="{ open: expanded.has(g.key) }">▶</span>
          <span class="group-emoji">{{ g.emoji }}</span>
          <span class="group-name">{{ g.name }}</span>
          <span class="group-count">{{ g.agents.filter(a => selected.includes(a.id)).length }}/{{ g.agents.length }}</span>
        </div>
        <div v-show="expanded.has(g.key)" class="group-body">
          <div
            v-for="a in g.agents"
            :key="a.id"
            class="agent-row"
            :class="{ 'is-selected': selected.includes(a.id) }"
          >
            <span class="row-avatar">{{ a.avatar || '?' }}</span>
            <span class="row-name">{{ a.name }}</span>
            <div class="row-actions">
              <!-- 默认按钮插槽：可以被父组件覆盖 -->
              <slot name="actions" :agent="a" :is-selected="selected.includes(a.id)">
                <button
                  class="action-btn default-action"
                  :class="{ 'is-added': selected.includes(a.id) }"
                  @click.stop="$emit('add', a.id)"
                >
                  {{ selected.includes(a.id) ? '✓ 已选' : '+ 参与' }}
                </button>
              </slot>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'

const props = defineProps({
  agents: { type: Array, default: () => [] },           // 所有可选 agent 对象
  groups: { type: Array, default: () => [] },            // 分组元数据 [{id, name, emoji}]
  selected: { type: Array, default: () => [] },           // 已选 agent IDs
  selectedTitle: { type: String, default: '已选角色' },
  poolTitle: { type: String, default: '待选角色' },
  factions: { type: Object, default: () => ({}) },       // {agent_id: 'affirmative'|'negative'} 辩论模式用
})

const emit = defineEmits(['add', 'remove'])

const expanded = ref(new Set())

const agentMap = computed(() => {
  const map = {}
  for (const a of props.agents) map[a.id] = a
  return map
})

function getAgent(id) {
  return agentMap.value[id] || { id, name: id, avatar: '?' }
}

function getFactionTag(id) {
  const f = props.factions[id]
  if (f === 'affirmative') return { label: '正方', cls: 'aff' }
  if (f === 'negative') return { label: '反方', cls: 'neg' }
  return null
}

const groupedAgents = computed(() => {
  const groupMap = new Map()
  const groupMeta = new Map(props.groups.map(g => [g.id, g]))

  for (const a of props.agents) {
    const key = a.group || ''
    if (!groupMap.has(key)) {
      const meta = groupMeta.get(key)
      groupMap.set(key, {
        key,
        name: meta?.name || key || '未分组',
        emoji: meta?.emoji || '📋',
        agents: [],
      })
    }
    groupMap.get(key).agents.push(a)
  }

  const result = [...groupMap.values()]
  if (expanded.value.size === 0 && result.length > 0) {
    expanded.value = new Set(result.map(g => g.key))
  }
  return result
})

function toggleExpand(key) {
  const next = new Set(expanded.value)
  if (next.has(key)) next.delete(key)
  else next.add(key)
  expanded.value = next
}
</script>

<style scoped>
.agent-roster { display: flex; flex-direction: column; gap: 12px; }

/* 已选区 */
.selected-zone { background: var(--panel-bg); border-color: var(--accent-gold); }
.zone-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 8px; }
.zone-title { font-weight: bold; color: var(--accent-blue); font-size: 14px; }
.zone-count { font-size: 11px; color: var(--text-muted); border: 1px solid var(--border-color); padding: 1px 6px; }

.selected-list { display: flex; flex-wrap: wrap; gap: 6px; }
.selected-chip {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  background: var(--bg-color);
  border: 1px solid var(--border-color);
  font-size: 13px;
}
.chip-avatar { font-size: 16px; }
.chip-name { color: var(--text-primary); font-weight: bold; }
.chip-faction {
  font-size: 10px;
  padding: 1px 5px;
  border: 1px solid;
}
.chip-faction.aff { color: var(--accent-blue); border-color: var(--accent-blue); background: rgba(100, 149, 237, 0.15); }
.chip-faction.neg { color: var(--accent-red); border-color: var(--accent-red); background: rgba(220, 20, 60, 0.15); }
.chip-remove {
  background: none;
  border: none;
  color: var(--text-muted);
  cursor: pointer;
  font-size: 14px;
  padding: 0 2px;
  line-height: 1;
}
.chip-remove:hover { color: var(--accent-red); }

/* 待选区 */
.pool-zone { }
.agent-group { border: 1px solid var(--border-color); margin-bottom: 4px; }
.group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  background: var(--panel-bg);
  cursor: pointer;
  user-select: none;
  transition: background 0.1s;
}
.group-header:hover { background: var(--bg-color); }
.group-arrow { font-size: 10px; color: var(--text-muted); transition: transform 0.2s; display: inline-block; }
.group-arrow.open { transform: rotate(90deg); }
.group-emoji { font-size: 18px; }
.group-name { font-weight: bold; color: var(--accent-blue); font-size: 14px; flex: 1; }
.group-count { font-size: 11px; color: var(--text-muted); border: 1px solid var(--border-color); padding: 1px 6px; }
.group-body { display: flex; flex-direction: column; gap: 2px; padding: 4px; }

.agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  background: var(--bg-color);
  border: 1px solid transparent;
  transition: all 0.1s;
}
.agent-row:hover { border-color: var(--border-color); }
.agent-row.is-selected { border-color: var(--accent-green); background: rgba(80, 200, 120, 0.08); }

.row-avatar { font-size: 22px; }
.row-name { font-weight: bold; color: var(--text-primary); font-size: 14px; flex: 1; }
.row-actions { display: flex; gap: 4px; }

.action-btn {
  font-size: 11px;
  padding: 3px 10px;
  border: 2px solid var(--border-color);
  background: var(--panel-bg);
  color: var(--text-primary);
  cursor: pointer;
  transition: all 0.1s;
  font-family: inherit;
  box-shadow: 2px 2px 0 var(--border-color);
}
.action-btn:hover { border-color: var(--accent-blue); transform: translate(-1px, -1px); box-shadow: 3px 3px 0 var(--border-color); }
.action-btn:active { transform: translate(1px, 1px); box-shadow: 1px 1px 0 var(--border-color); }
.action-btn.default-action.is-added { background: var(--accent-green); color: #111; border-color: #111; box-shadow: 2px 2px 0 #111; }
.action-btn.faction-aff { border-color: var(--accent-blue); color: var(--accent-blue); }
.action-btn.faction-aff:hover { background: rgba(100, 149, 237, 0.15); }
.action-btn.faction-aff.is-active { background: var(--accent-blue); color: #111; border-color: #111; box-shadow: 2px 2px 0 #111; font-weight: bold; }
.action-btn.faction-neg { border-color: var(--accent-red); color: var(--accent-red); }
.action-btn.faction-neg:hover { background: rgba(220, 20, 60, 0.15); }
.action-btn.faction-neg.is-active { background: var(--accent-red); color: #fff; border-color: #111; box-shadow: 2px 2px 0 #111; font-weight: bold; }
</style>
