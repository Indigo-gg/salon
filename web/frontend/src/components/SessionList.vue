<template>
  <div class="session-list">
    <div v-if="sessions.length === 0" class="empty">No sessions</div>
    <div
      v-for="s in sessions"
      :key="s.session_id"
      class="session-item"
      :class="{ active: s.session_id === activeId }"
      @click="$emit('select', s.session_id)"
    >
      <div class="item-topic">{{ s.topic }}</div>
      <div class="item-meta">
        <span class="state">{{ s.state }}</span>
        <span>R{{ s.round_count }}</span>
      </div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  sessions: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
})
defineEmits(['select'])
</script>

<style scoped>
.session-list { display: flex; flex-direction: column; gap: 4px; }
.session-item { padding: 10px 12px; border: 1px solid #eee; border-radius: 6px; cursor: pointer; transition: all 0.15s; }
.session-item:hover { border-color: #4a6cf7; }
.session-item.active { border-color: #4a6cf7; background: #f0f4ff; }
.item-topic { font-weight: 500; font-size: 14px; margin-bottom: 2px; }
.item-meta { font-size: 11px; color: #888; display: flex; gap: 8px; }
.state { text-transform: capitalize; }
.empty { color: #999; font-size: 13px; text-align: center; padding: 16px; }
</style>
