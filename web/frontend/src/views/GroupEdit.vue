<template>
  <div class="group-edit pixel-box">
    <h1 class="title">{{ isEdit ? t('groups.edit_title') : t('groups.new_title') }}</h1>

    <form @submit.prevent="save" class="form">
      <div class="row">
        <div class="field flex-2">
          <label>{{ t('groups.name') }}</label>
          <input v-model="form.name" class="pixel-input" />
          <span v-if="errors.name" class="error-msg">{{ errors.name }}</span>
        </div>
        <div class="field emoji-field">
          <label>{{ t('groups.emoji') }}</label>
          <input v-model="form.emoji" class="pixel-input" maxlength="4" />
        </div>
      </div>

      <div class="field">
        <label>{{ t('groups.description') }}</label>
        <textarea v-model="form.description" rows="3" class="pixel-input textarea"></textarea>
      </div>

      <div class="actions">
        <button type="submit" class="pixel-btn pixel-btn-primary" :disabled="saving">
          {{ saving ? t('groups.updating') : t('groups.confirm') }}
        </button>
        <button type="button" @click="$router.push('/agents')" class="pixel-btn">
          {{ t('groups.cancel') }}
        </button>
      </div>
    </form>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getGroup, createGroup, updateGroup } from '../api'
import { useI18nStore } from '../stores/i18n'

const route = useRoute()
const router = useRouter()
const i18n = useI18nStore()
const t = i18n.t

const isEdit = !!route.params.id && route.params.id !== 'new'
const saving = ref(false)
const errors = ref({})

const form = ref({
  name: '',
  emoji: '',
  description: ''
})

onMounted(async () => {
  if (isEdit) {
    const { data } = await getGroup(route.params.id)
    form.value = { ...form.value, ...data }
  }
})

function validate() {
  errors.value = {}
  if (!form.value.name.trim()) errors.value.name = t('groups.name_required')
  return Object.keys(errors.value).length === 0
}

async function save() {
  if (!validate()) return
  saving.value = true
  try {
    if (isEdit) {
      await updateGroup(route.params.id, form.value)
    } else {
      await createGroup(form.value)
    }
    router.push('/agents')
  } finally {
    saving.value = false
  }
}
</script>

<style scoped>
.group-edit { max-width: 800px; margin: 20px auto; }
.title { color: var(--accent-gold); margin-bottom: 24px; text-shadow: 2px 2px var(--border-color); border-bottom: 2px solid var(--border-color); padding-bottom: 8px; }

.form { display: flex; flex-direction: column; gap: 20px; }
.row { display: flex; gap: 16px; }
.field { display: flex; flex-direction: column; gap: 8px; flex: 1; }
.flex-2 { flex: 2; }
.emoji-field { max-width: 120px; }

label { color: var(--accent-blue); font-size: 14px; }
.textarea { resize: vertical; line-height: 1.5; }
.error-msg { color: var(--accent-red); font-size: 12px; }

.actions { display: flex; gap: 16px; margin-top: 16px; border-top: 2px dashed var(--border-color); padding-top: 20px; }
</style>
