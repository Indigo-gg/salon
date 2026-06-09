import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export const useConfigStore = defineStore('config', () => {
  const config = ref(null)
  const loading = ref(false)

  async function fetchConfig() {
    loading.value = true
    try {
      const { data } = await api.getConfig()
      config.value = data
    } finally {
      loading.value = false
    }
  }

  async function updateConfig(updates) {
    await api.updateConfig(updates)
    await fetchConfig()
  }

  return { config, loading, fetchConfig, updateConfig }
})
