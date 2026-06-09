<template>
  <div class="agent-edit pixel-box">
    <h1 class="title">{{ isEdit ? t('edit.edit_title') : t('edit.new_title') }}</h1>

    <form @submit.prevent="save" class="form">
      <div class="row">
        <div class="field">
          <label>{{ t('edit.name') }}</label>
          <input v-model="form.name" class="pixel-input" />
          <span v-if="errors.name" class="error-msg">{{ errors.name }}</span>
        </div>
        <div class="field">
          <label>{{ t('edit.group') }}</label>
          <select v-model="form.group" class="pixel-input select">
            <option value="">{{ t('groups.no_group') }}</option>
            <option v-for="g in groups" :key="g.id" :value="g.id">{{ g.emoji ? g.emoji + ' ' : '' }}{{ g.name }}</option>
          </select>
        </div>
        <div class="field">
          <label>性别</label>
          <select v-model="form.gender" class="pixel-input select">
            <option value="">未指定</option>
            <option value="male">男性</option>
            <option value="female">女性</option>
          </select>
        </div>
        <div class="field">
          <label>预置音色</label>
          <select v-model="form.voice" class="pixel-input select">
            <option value="">MiMo-默认</option>
            <option value="苏打">苏打 (男)</option>
            <option value="白桦">白桦 (男)</option>
            <option value="冰糖">冰糖 (女)</option>
            <option value="茉莉">茉莉 (女)</option>
          </select>
        </div>
      </div>
      
      <div class="row">
        <div class="field avatar-field">
          <label>{{ t('edit.avatar') }}</label>
          <input v-model="form.avatar" class="pixel-input" />
        </div>
        <div class="field flex-2">
          <label>{{ t('edit.voice_desc') }}</label>
          <input v-model="form.voice_description" class="pixel-input" :placeholder="t('edit.voice_ph')" />
        </div>
      </div>

      <div class="soul-section">
        <div class="field flex-3">
          <label>{{ t('edit.soul') }}</label>
          <textarea v-model="form.soul_content" rows="10" class="pixel-input textarea"></textarea>
          <span v-if="errors.soul" class="error-msg">{{ errors.soul }}</span>
        </div>
        <div v-if="form.avatar" class="sprite-preview">
          <label class="preview-title">动作预览 (交互式)</label>
          <div class="sprite-wrapper"
               @mouseenter="previewAction = 'action-talk'" 
               @mouseleave="previewAction = 'action-idle'" 
               @click="previewAction = previewAction === 'action-think' ? 'action-idle' : 'action-think'">
            <div class="pixel-sprite" :class="previewAction" :style="{ backgroundImage: `url(${previewSpriteUrl})` }"></div>
          </div>
          <div class="preview-hint">悬浮说话 / 点击思考</div>
        </div>
      </div>

      <div class="actions">
        <button type="submit" class="pixel-btn pixel-btn-primary" :disabled="saving">
          {{ saving ? t('edit.updating') : t('edit.confirm') }}
        </button>
        <button type="button" @click="$router.push('/agents')" class="pixel-btn">
          {{ t('edit.cancel') }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getAgent, getAgentSoul, createAgent, updateAgent } from '../api'
import { useGroupsStore } from '../stores/groups'
import { useI18nStore } from '../stores/i18n'

const route = useRoute()
const router = useRouter()
const i18n = useI18nStore()
const groupsStore = useGroupsStore()
const t = i18n.t
const groups = computed(() => groupsStore.groups)

const isEdit = !!route.params.id && route.params.id !== 'new'
const saving = ref(false)
const errors = ref({})

const form = ref({
  name: '',
  role: 'participant',
  soul_content: '',
  avatar: '',
  group: '',
  gender: '',
  voice: '',
  voice_description: ''
})

const previewAction = ref('action-idle')

const previewSpriteUrl = computed(() => {
  if (form.value.avatar && form.value.avatar.endsWith('.png')) {
    return `/src/assets/images/sprites/${form.value.avatar}`
  }
  const id = isEdit ? route.params.id : 'me'
  const map = {
    'ai_observer': 'ai_observer.png',
    'human': 'me.png',
    'moderator': 'moderator.png',
    'philosopher_east': 'philosopher_east.png',
    'philosopher_west': 'philosopher_west.png',
    'scientist': 'scientist.png',
    'scribe': 'scribe.png',
    'existentialist': 'existentialist.png',
    'marxist': 'marxist.png'
  }
  return `/src/assets/images/sprites/${map[id] || 'me.png'}`
})

onMounted(async () => {
  await groupsStore.fetchGroups()
  if (!isEdit && route.query.group) {
    form.value.group = route.query.group
  }
  if (isEdit) {
    const { data } = await getAgent(route.params.id)
    form.value = { ...form.value, ...data }
    try {
      const { data: soul } = await getAgentSoul(route.params.id)
      form.value.soul_content = soul.content || ''
    } catch {
      // soul file may not exist yet
    }
  }
})

function validate() {
  errors.value = {}
  if (!form.value.name.trim()) errors.value.name = t('edit.name_required')
  if (!form.value.soul_content.trim()) errors.value.soul = t('edit.soul_required')
  return Object.keys(errors.value).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  try {
    if (isEdit) {
      await updateAgent(route.params.id, form.value)
    } else {
      await createAgent(form.value)
    }
    router.push('/agents')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.agent-edit { max-width: 800px; margin: 20px auto; }
.title { color: var(--accent-gold); margin-bottom: 24px; text-shadow: 2px 2px var(--border-color); border-bottom: 2px solid var(--border-color); padding-bottom: 8px; }

.form { display: flex; flex-direction: column; gap: 20px; }
.row { display: flex; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 8px; flex: 1; }
.flex-2 { flex: 2; }
.avatar-field { max-width: 150px; }

label { color: var(--accent-blue); font-size: 14px; }
.select { appearance: none; background-color: var(--border-color); cursor: pointer; }
.error-msg { color: var(--accent-red); font-size: 12px; }
.textarea { resize: vertical; line-height: 1.5; font-family: monospace; font-size: 14px; }

.actions { display: flex; gap: 16px; margin-top: 16px; border-top: 2px dashed var(--border-color); padding-top: 20px; }

.soul-section {
  display: flex;
  gap: 20px;
}
.flex-3 {
  flex: 3;
  display: flex;
  flex-direction: column;
}
.sprite-preview {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: rgba(43, 43, 54, 0.5);
  border: 2px dashed var(--border-color);
  padding: 16px;
  min-width: 180px;
}
.preview-title {
  color: var(--accent-gold);
  font-size: 12px;
  margin-bottom: 10px;
}
.preview-hint {
  font-size: 10px;
  color: var(--text-muted);
  margin-top: 10px;
}

.sprite-wrapper {
  width: 140px;
  height: 140px;
  overflow: hidden;
  position: relative;
  cursor: pointer;
}

.pixel-sprite {
  width: 140px;
  height: 140px;
  background-size: 560px 420px;
  background-repeat: no-repeat;
  image-rendering: pixelated;
  filter: drop-shadow(4px 4px 0px rgba(0,0,0,0.5));
}

@keyframes sprite-idle {
  from { background-position: 0 0; }
  to { background-position: -560px 0; }
}
@keyframes sprite-talk {
  from { background-position: 0 -140px; }
  to { background-position: -560px -140px; }
}
@keyframes sprite-think {
  from { background-position: 0 -280px; }
  to { background-position: -560px -280px; }
}

.pixel-sprite.action-idle { animation: sprite-idle 2.5s steps(4) infinite; }
.pixel-sprite.action-talk { animation: sprite-talk 1.8s steps(4) infinite; }
.pixel-sprite.action-think { animation: sprite-think 2.5s steps(4) infinite; }
</style>
