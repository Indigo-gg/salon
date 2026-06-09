<template>
  <div class="whiteboard-panel">
    <div v-if="!content" class="empty">暂无白板数据。</div>
    <pre v-else class="content">{{ content }}</pre>
  </div>
</template>

<script setup>
defineProps({
  content: { type: String, default: '' },
})
</script>

<style scoped>
.whiteboard-panel { font-size: 13px; height: 100%; }
.empty { color: var(--text-muted); text-align: center; padding: 20px; }
.content { 
  white-space: pre-wrap; 
  line-height: 1.6; 
  background: rgba(20, 20, 25, 0.8); 
  color: var(--text-primary); 
  padding: 12px; 
  border-radius: 4px; 
  border: 2px solid var(--border-color);
  font-family: monospace;
}
</style>
