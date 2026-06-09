<template>
  <div
    class="draggable-panel pixel-box"
    :style="panelStyle"
    @mousedown="bringToFront"
  >
    <!-- Drag handle (header) -->
    <div
      class="panel-header drag-handle"
      @mousedown.stop="startDrag"
    >
      <h3 class="panel-title"><slot name="header">Panel</slot></h3>
      <button @click.stop="$emit('close')" class="pixel-btn close-btn">&times;</button>
    </div>

    <!-- Body -->
    <div class="panel-body">
      <slot />
    </div>

    <!-- Resize handles -->
    <div class="resize-handle resize-n" @mousedown.stop="startResize($event, 'n')"></div>
    <div class="resize-handle resize-s" @mousedown.stop="startResize($event, 's')"></div>
    <div class="resize-handle resize-w" @mousedown.stop="startResize($event, 'w')"></div>
    <div class="resize-handle resize-e" @mousedown.stop="startResize($event, 'e')"></div>
    <div class="resize-handle resize-nw" @mousedown.stop="startResize($event, 'nw')"></div>
    <div class="resize-handle resize-ne" @mousedown.stop="startResize($event, 'ne')"></div>
    <div class="resize-handle resize-sw" @mousedown.stop="startResize($event, 'sw')"></div>
    <div class="resize-handle resize-se" @mousedown.stop="startResize($event, 'se')"></div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'

const props = defineProps({
  /** The button element used to calculate default position */
  anchorEl: { type: Object, default: null },
  /** Initial width */
  initWidth: { type: Number, default: 400 },
  /** Initial height */
  initHeight: { type: Number, default: 420 },
  /** Minimum width */
  minWidth: { type: Number, default: 260 },
  /** Minimum height */
  minHeight: { type: Number, default: 200 },
})

defineEmits(['close'])

const PANEL_Z_BASE = 1000
const panelZ = ref(PANEL_Z_BASE)

// --- Position & Size ---
const x = ref(0)
const y = ref(0)
const w = ref(props.initWidth)
const h = ref(props.initHeight)
const initialized = ref(false)

const panelStyle = computed(() => ({
  left: x.value + 'px',
  top: y.value + 'px',
  width: w.value + 'px',
  height: h.value + 'px',
  zIndex: panelZ.value,
}))

/** Place panel below the anchor button on first mount */
function initPosition() {
  if (initialized.value) return
  initialized.value = true

  if (props.anchorEl) {
    const rect = props.anchorEl.getBoundingClientRect()
    const parent = props.anchorEl.closest('.chat-room-scene')
    const parentRect = parent ? parent.getBoundingClientRect() : { left: 0, top: 0 }
    // Position below the button, aligned to its right edge
    let px = rect.right - parentRect.left - props.initWidth
    let py = rect.bottom - parentRect.top + 6
    // Clamp within viewport
    px = Math.max(8, Math.min(px, window.innerWidth - props.initWidth - 8))
    py = Math.max(8, Math.min(py, window.innerHeight - props.initHeight - 8))
    x.value = px
    y.value = py
  } else {
    // Fallback: center of viewport
    x.value = Math.max(0, (window.innerWidth - props.initWidth) / 2)
    y.value = Math.max(0, (window.innerHeight - props.initHeight) / 2)
  }
}

function bringToFront() {
  panelZ.value = PANEL_Z_BASE + Date.now() % 100000
}

// --- Drag ---
let dragStartX = 0, dragStartY = 0, dragOrigX = 0, dragOrigY = 0

function startDrag(e) {
  bringToFront()
  dragStartX = e.clientX
  dragStartY = e.clientY
  dragOrigX = x.value
  dragOrigY = y.value
  window.addEventListener('mousemove', onDrag)
  window.addEventListener('mouseup', stopDrag)
  e.preventDefault()
}

function onDrag(e) {
  x.value = dragOrigX + (e.clientX - dragStartX)
  y.value = dragOrigY + (e.clientY - dragStartY)
}

function stopDrag() {
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', stopDrag)
  clampPosition()
}

function clampPosition() {
  x.value = Math.max(-w.value + 60, Math.min(x.value, window.innerWidth - 60))
  y.value = Math.max(0, Math.min(y.value, window.innerHeight - 40))
}

// --- Resize ---
let resizeDir = ''
let resizeStartX = 0, resizeStartY = 0
let resizeOrigX = 0, resizeOrigY = 0, resizeOrigW = 0, resizeOrigH = 0

function startResize(e, dir) {
  bringToFront()
  resizeDir = dir
  resizeStartX = e.clientX
  resizeStartY = e.clientY
  resizeOrigX = x.value
  resizeOrigY = y.value
  resizeOrigW = w.value
  resizeOrigH = h.value
  window.addEventListener('mousemove', onResize)
  window.addEventListener('mouseup', stopResize)
  e.preventDefault()
}

function onResize(e) {
  const dx = e.clientX - resizeStartX
  const dy = e.clientY - resizeStartY

  if (resizeDir.includes('e')) {
    w.value = Math.max(props.minWidth, resizeOrigW + dx)
  }
  if (resizeDir.includes('w')) {
    const newW = Math.max(props.minWidth, resizeOrigW - dx)
    x.value = resizeOrigX + (resizeOrigW - newW)
    w.value = newW
  }
  if (resizeDir.includes('s')) {
    h.value = Math.max(props.minHeight, resizeOrigH + dy)
  }
  if (resizeDir.includes('n')) {
    const newH = Math.max(props.minHeight, resizeOrigH - dy)
    y.value = resizeOrigY + (resizeOrigH - newH)
    h.value = newH
  }
}

function stopResize() {
  window.removeEventListener('mousemove', onResize)
  window.removeEventListener('mouseup', stopResize)
  clampPosition()
}

// --- Lifecycle ---
onMounted(() => {
  nextTick(initPosition)
})

onUnmounted(() => {
  window.removeEventListener('mousemove', onDrag)
  window.removeEventListener('mouseup', stopDrag)
  window.removeEventListener('mousemove', onResize)
  window.removeEventListener('mouseup', stopResize)
})
</script>

<style scoped>
.draggable-panel {
  position: absolute;
  display: flex;
  flex-direction: column;
  background: rgba(43, 43, 54, 0.95);
  border-color: var(--border-color);
  box-shadow: 4px 4px 0 rgba(0, 0, 0, 0.4);
  user-select: none;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 2px solid var(--border-color);
  cursor: grab;
  flex-shrink: 0;
}
.panel-header:active { cursor: grabbing; }

.panel-title {
  margin: 0;
  font-size: 14px;
  color: var(--accent-gold);
  pointer-events: none;
}

.close-btn {
  padding: 2px 8px;
  font-size: 16px;
  line-height: 1;
}

.panel-body {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 0;
  min-height: 0;
}

/* --- Resize handles --- */
.resize-handle {
  position: absolute;
}

/* Edge handles */
.resize-n { top: -3px; left: 8px; right: 8px; height: 6px; cursor: n-resize; }
.resize-s { bottom: -3px; left: 8px; right: 8px; height: 6px; cursor: s-resize; }
.resize-w { left: -3px; top: 8px; bottom: 8px; width: 6px; cursor: w-resize; }
.resize-e { right: -3px; top: 8px; bottom: 8px; width: 6px; cursor: e-resize; }

/* Corner handles */
.resize-nw { top: -4px; left: -4px; width: 12px; height: 12px; cursor: nw-resize; }
.resize-ne { top: -4px; right: -4px; width: 12px; height: 12px; cursor: ne-resize; }
.resize-sw { bottom: -4px; left: -4px; width: 12px; height: 12px; cursor: sw-resize; }
.resize-se { bottom: -4px; right: -4px; width: 12px; height: 12px; cursor: se-resize; }
</style>
