<template>
  <div class="agent-avatar" :class="{ active }" :title="agent.name">
    <span class="emoji">{{ agent.avatar || '?' }}</span>
    <span v-if="showName" class="name">{{ agent.name }}</span>
  </div>
</template>

<script setup>
defineProps({
  agent: { type: Object, required: true },
  active: { type: Boolean, default: false },
  showName: { type: Boolean, default: false },
})
</script>

<style scoped>
.agent-avatar { display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
.emoji { font-size: 24px; }
.agent-avatar.active .emoji { filter: drop-shadow(0 0 4px #4a6cf7); }
.name { font-size: 13px; font-weight: 500; }
</style>
