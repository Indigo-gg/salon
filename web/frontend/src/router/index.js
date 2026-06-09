import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'Home', component: () => import('../views/Home.vue') },
  { path: '/agents', name: 'Agents', component: () => import('../views/Agents.vue') },
  { path: '/agents/new', name: 'AgentNew', component: () => import('../views/AgentEdit.vue') },
  { path: '/agents/:id/edit', name: 'AgentEdit', component: () => import('../views/AgentEdit.vue') },
  { path: '/groups/new', name: 'GroupNew', component: () => import('../views/GroupEdit.vue') },
  { path: '/groups/:id/edit', name: 'GroupEdit', component: () => import('../views/GroupEdit.vue') },
  { path: '/chat/:sessionId', name: 'ChatRoom', component: () => import('../views/ChatRoom.vue') },
  { path: '/archive', name: 'Archive', component: () => import('../views/Archive.vue') },
  { path: '/archive/:sessionId', name: 'ArchivePlay', component: () => import('../views/ArchivePlay.vue') },
  { path: '/settings', name: 'Settings', component: () => import('../views/Settings.vue') },
]

export default createRouter({
  history: createWebHistory(),
  routes,
})
