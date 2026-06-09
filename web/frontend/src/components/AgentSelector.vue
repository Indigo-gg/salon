<template>
  <div class="agent-selector">
    <div
      v-for="a in agents"
      :key="a.id"
      class="selector-item"
      :class="{ selected: modelValue.includes(a.id) }"
      @click="toggle(a.id)"
    >
      <span class="sel-avatar">{{ a.avatar || '?' }}</span>
      <span class="sel-name">{{ a.name }}</span>
      <span class="sel-role">{{ a.role }}</span>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  agents: { type: Array, default: () => [] },
  modelValue: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue'])

function toggle(id) {
  const current = [...props.modelValue]
  const idx = current.indexOf(id)
  if (idx >= 0) current.splice(idx, 1)
  else current.push(id)
  emit('update:modelValue', current)
}
</script>

<style scoped>
.agent-selector { display: flex; flex-wrap: wrap; gap: 8px; }
.selector-item { display: flex; align-items: center; gap: 8px; padding: 8px 14px; border: 2px solid #eee; border-radius: 8px; cursor: pointer; transition: all 0.15s; }
.selector-item:hover { border-color: #aaa; }
.selector-item.selected { border-color: #4a6cf7; background: #f0f4ff; }
.sel-avatar { font-size: 20px; }
.sel-name { font-weight: 500; font-size: 14px; }
.sel-role { font-size: 11px; color: #888; }
</style>
