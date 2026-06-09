import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export const useAgentsStore = defineStore('agents', () => {
  const agents = ref([])
  const loading = ref(false)

  async function fetchAgents() {
    loading.value = true
    try {
      const { data } = await api.getAgents()
      agents.value = data
    } finally {
      loading.value = false
    }
  }

  async function createAgent(agentData) {
    const { data } = await api.createAgent(agentData)
    agents.value.push(data)
    return data
  }

  async function updateAgent(id, agentData) {
    const { data } = await api.updateAgent(id, agentData)
    const idx = agents.value.findIndex(a => a.id === id)
    if (idx >= 0) agents.value[idx] = data
    return data
  }

  async function deleteAgent(id) {
    await api.deleteAgent(id)
    agents.value = agents.value.filter(a => a.id !== id)
  }

  return { agents, loading, fetchAgents, createAgent, updateAgent, deleteAgent }
})
