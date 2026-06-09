import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

// Agents
export const getAgents = () => api.get('/agents')
export const getAgent = (id) => api.get(`/agents/${id}`)
export const getAgentSoul = (id) => api.get(`/agents/${id}/soul`)
export const createAgent = (data) => api.post('/agents', data)
export const updateAgent = (id, data) => api.put(`/agents/${id}`, data)
export const deleteAgent = (id) => api.delete(`/agents/${id}`)

// Groups
export const getGroups = () => api.get('/groups')
export const getGroup = (id) => api.get(`/groups/${id}`)
export const createGroup = (data) => api.post('/groups', data)
export const updateGroup = (id, data) => api.put(`/groups/${id}`, data)
export const deleteGroup = (id) => api.delete(`/groups/${id}`)

// Sessions
export const getSessions = () => api.get('/sessions')
export const getSession = (id) => api.get(`/sessions/${id}`)
export const createSession = (data) => api.post('/sessions', data)
export const getSessionMessages = (id) => api.get(`/sessions/${id}/messages`)
export const getSessionWhiteboard = (id) => api.get(`/sessions/${id}/whiteboard`)
export const getSessionDigest = (id) => api.get(`/sessions/${id}/digest`)

export const archiveSession = (id) => api.put(`/sessions/${id}/archive`)
export const deleteSession = (id) => api.delete(`/sessions/${id}`)

// Chat
export const startChat = (id) => api.post(`/chat/${id}/start`)
export const sendCommand = (id, command) => api.post(`/chat/${id}/command`, { command })
export const pauseChat = (id) => api.post(`/chat/${id}/pause`)
export const resumeChat = (id) => api.post(`/chat/${id}/resume`)
export const stopChat = (id) => api.post(`/chat/${id}/stop`)

// Config
export const getConfig = () => api.get('/config')
export const updateConfig = (data) => api.put('/config', data)

// Archives
export const getArchives = () => api.get('/archives')
export const getArchive = (id) => api.get(`/archives/${id}`)
export const deleteArchive = (id) => api.delete(`/archives/${id}`)
export const getArchiveMemory = (id) => api.get(`/archives/${id}/memory`)
export const exportArchive = (id, format, includeReasoning = false) =>
  api.get(`/archives/${id}/export`, {
    params: { format, include_reasoning: includeReasoning },
    responseType: 'blob',
  })
