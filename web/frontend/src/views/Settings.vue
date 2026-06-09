<template>
  <div class="settings-options pixel-box">
    <h1 class="options-title">{{ t('settings.title') }}</h1>

    <div v-if="!form" class="loading">{{ t('chat.loading') }}</div>

    <form v-else @submit.prevent="save" class="options-form">

      <!-- LLM SETTINGS -->
      <div class="option-group pixel-box">
        <h2 class="group-title" @click="toggle('llm')">
          {{ t('settings.llm_config') }}
          <span class="toggle-icon">{{ open.llm ? '▾' : '▸' }}</span>
        </h2>
        <div v-show="open.llm" class="group-body">
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.api_base') }}</label>
              <input v-model="form.llm.api_base" class="pixel-input" placeholder="https://api.openai.com/v1" />
            </div>
            <div class="field">
              <label>{{ t('settings.api_key') }}</label>
              <input v-model="form.llm.api_key" type="password" class="pixel-input" placeholder="sk-..." />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.model_name') }}</label>
              <input v-model="form.llm.model" class="pixel-input" placeholder="gpt-4o" />
            </div>
            <div class="field">
              <label>{{ t('settings.temperature') }}</label>
              <input type="number" step="0.1" min="0" max="2" v-model.number="form.llm.temperature" class="pixel-input" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.max_tokens') }}</label>
              <input type="number" v-model.number="form.llm.max_tokens" class="pixel-input" />
            </div>
            <div class="field">
              <label>{{ t('settings.timeout') }} (s)</label>
              <input type="number" v-model.number="form.llm.timeout" class="pixel-input" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.native_thinking') }}</label>
              <select v-model="form.llm.use_native_thinking" class="pixel-input select">
                <option :value="true">{{ t('settings.on') }}</option>
                <option :value="false">{{ t('settings.off') }}</option>
              </select>
            </div>
            <div class="field"></div>
          </div>
        </div>
      </div>

      <!-- DISCUSSION -->
      <div class="option-group pixel-box">
        <h2 class="group-title" @click="toggle('discussion')">
          {{ t('settings.game_rules') }}
          <span class="toggle-icon">{{ open.discussion ? '▾' : '▸' }}</span>
        </h2>
        <div v-show="open.discussion" class="group-body">
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.language') }}</label>
              <select v-model="form.discussion.language" class="pixel-input select">
                <option value="zh">中文</option>
                <option value="en">English</option>
              </select>
            </div>
            <div class="field">
              <label>{{ t('settings.participant_count') }}</label>
              <input type="number" min="2" max="8" v-model.number="form.discussion.default_participant_count" class="pixel-input" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.max_rounds') }}</label>
              <input type="number" min="3" v-model.number="form.discussion.max_rounds" class="pixel-input" />
            </div>
            <div class="field">
              <label>{{ t('settings.min_rounds') }}</label>
              <input type="number" min="1" v-model.number="form.discussion.min_rounds" class="pixel-input" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.max_speech_chars') }}</label>
              <input type="number" v-model.number="form.discussion.max_speech_chars" class="pixel-input" />
            </div>
            <div class="field">
              <label>{{ t('settings.min_speech_chars') }}</label>
              <input type="number" v-model.number="form.discussion.min_speech_chars" class="pixel-input" />
            </div>
          </div>
        </div>
      </div>

      <!-- SEARCH -->
      <div class="option-group pixel-box">
        <h2 class="group-title" @click="toggle('search')">
          {{ t('settings.search') }}
          <span class="toggle-icon">{{ open.search ? '▾' : '▸' }}</span>
        </h2>
        <div v-show="open.search" class="group-body">
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.search_enabled') }}</label>
              <select v-model="form.search.enabled" class="pixel-input select">
                <option :value="true">{{ t('settings.on') }}</option>
                <option :value="false">{{ t('settings.off') }}</option>
              </select>
            </div>
            <div class="field">
              <label>{{ t('settings.search_api_key') }}</label>
              <input v-model="form.search.api_key" type="password" class="pixel-input" placeholder="SerpAPI / Bing key" />
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.search_max_results') }}</label>
              <input type="number" min="1" max="10" v-model.number="form.search.max_results" class="pixel-input" />
            </div>
            <div class="field"></div>
          </div>
        </div>
      </div>

      <!-- MEMORY & WHITEBOARD -->
      <div class="option-group pixel-box">
        <h2 class="group-title" @click="toggle('memory')">
          {{ t('settings.memory') }}
          <span class="toggle-icon">{{ open.memory ? '▾' : '▸' }}</span>
        </h2>
        <div v-show="open.memory" class="group-body">
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.scribe_interval') }}</label>
              <input type="number" min="1" v-model.number="form.memory.whiteboard.auto_update_interval" class="pixel-input" />
              <span class="field-hint">{{ t('settings.scribe_interval_hint') }}</span>
            </div>
            <div class="field">
              <label>{{ t('settings.cold_ttl') }}</label>
              <input type="number" min="1" v-model.number="form.memory.whiteboard.cold_storage_ttl" class="pixel-input" />
              <span class="field-hint">{{ t('settings.cold_ttl_hint') }}</span>
            </div>
          </div>
        </div>
      </div>

      <!-- OUTPUT & MONITORING -->
      <div class="option-group pixel-box">
        <h2 class="group-title" @click="toggle('output')">
          {{ t('settings.output') }}
          <span class="toggle-icon">{{ open.output ? '▾' : '▸' }}</span>
        </h2>
        <div v-show="open.output" class="group-body">
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.digest_auto') }}</label>
              <select v-model="form.output.digest_auto_generate" class="pixel-input select">
                <option :value="true">{{ t('settings.on') }}</option>
                <option :value="false">{{ t('settings.off') }}</option>
              </select>
            </div>
            <div class="field">
              <label>{{ t('settings.report_auto') }}</label>
              <select v-model="form.output.report_auto_generate" class="pixel-input select">
                <option :value="true">{{ t('settings.on') }}</option>
                <option :value="false">{{ t('settings.off') }}</option>
              </select>
            </div>
          </div>
          <div class="field-row">
            <div class="field">
              <label>{{ t('settings.monitor_enabled') }}</label>
              <select v-model="form.monitor.enabled" class="pixel-input select">
                <option :value="true">{{ t('settings.on') }}</option>
                <option :value="false">{{ t('settings.off') }}</option>
              </select>
            </div>
            <div class="field">
              <label>{{ t('settings.log_level') }}</label>
              <select v-model="form.logging.level" class="pixel-input select">
                <option value="DEBUG">DEBUG</option>
                <option value="INFO">INFO</option>
                <option value="WARNING">WARNING</option>
                <option value="ERROR">ERROR</option>
              </select>
            </div>
          </div>
        </div>
      </div>

      <div class="actions">
        <button type="submit" class="pixel-btn pixel-btn-primary" :disabled="saving">
          {{ saving ? t('settings.saving') : t('settings.save') }}
        </button>
        <span v-if="saved" class="saved-msg">{{ t('settings.saved') }}</span>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useConfigStore } from '../stores/config'
import { useI18nStore } from '../stores/i18n'

const configStore = useConfigStore()
const i18n = useI18nStore()
const t = i18n.t

const form = ref(null)
const saving = ref(false)
const saved = ref(false)

const open = reactive({
  llm: true,
  discussion: true,
  search: false,
  memory: false,
  output: false,
})

function toggle(group) {
  open[group] = !open[group]
}

onMounted(async () => {
  await configStore.fetchConfig()
  // deep clone + ensure nested objects exist
  const raw = JSON.parse(JSON.stringify(configStore.config))
  // fill defaults for missing nested sections
  raw.search = raw.search || {}
  raw.memory = raw.memory || {}
  raw.memory.whiteboard = raw.memory.whiteboard || {}
  raw.output = raw.output || {}
  raw.logging = raw.logging || {}
  raw.monitor = raw.monitor || {}
  form.value = raw
})

async function save() {
  saving.value = true
  saved.value = false
  try {
    await configStore.updateConfig(form.value)
    saved.value = true
    setTimeout(() => { saved.value = false }, 2000)
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.settings-options { max-width: 800px; margin: 20px auto; border: none; background: transparent; box-shadow: none; }
.options-title { color: var(--accent-gold); margin-bottom: 24px; text-shadow: 2px 2px var(--border-color); text-align: center; }

.loading { text-align: center; color: var(--accent-blue); font-size: 20px; }

.options-form { display: flex; flex-direction: column; gap: 24px; }

.option-group { display: flex; flex-direction: column; border-color: var(--border-color); }
.group-title {
  font-size: 18px; color: var(--accent-blue); border-bottom: 2px dashed var(--border-color);
  padding-bottom: 8px; margin-bottom: 0; cursor: pointer; user-select: none;
  display: flex; justify-content: space-between; align-items: center;
}
.group-title:hover { color: var(--accent-gold); }
.toggle-icon { font-size: 14px; opacity: 0.6; }
.group-body { display: flex; flex-direction: column; gap: 16px; padding-top: 16px; }

.field-row { display: flex; gap: 20px; }
.field { display: flex; flex-direction: column; gap: 8px; flex: 1; }
.field-hint { font-size: 12px; color: var(--text-secondary); opacity: 0.7; margin-top: -4px; }

label { color: var(--text-primary); font-size: 14px; }
.select { appearance: none; cursor: pointer; }

.actions { display: flex; align-items: center; gap: 16px; margin-top: 8px; }
.saved-msg { color: var(--accent-green); font-weight: bold; animation: pop 0.2s; }
@keyframes pop { 0% { transform: scale(0.8); } 100% { transform: scale(1); } }
</style>
