import { defineStore } from 'pinia'
import { ref } from 'vue'
import * as api from '../api'

export const useGroupsStore = defineStore('groups', () => {
  const groups = ref([])
  const loading = ref(false)

  async function fetchGroups() {
    loading.value = true
    try {
      const { data } = await api.getGroups()
      groups.value = data
    } finally {
      loading.value = false
    }
  }

  async function createGroup(groupData) {
    const { data } = await api.createGroup(groupData)
    groups.value.push(data)
    return data
  }

  async function updateGroup(id, groupData) {
    const { data } = await api.updateGroup(id, groupData)
    const idx = groups.value.findIndex(g => g.id === id)
    if (idx >= 0) groups.value[idx] = data
    return data
  }

  async function deleteGroup(id) {
    await api.deleteGroup(id)
    groups.value = groups.value.filter(g => g.id !== id)
  }

  return { groups, loading, fetchGroups, createGroup, updateGroup, deleteGroup }
})
