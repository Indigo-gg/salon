<template>
  <div class="app">
    <nav class="sidebar" :class="{ 'is-collapsed': collapsed }">
      <div class="sidebar-content">
        <div class="logo">
          <img src="/logo.jpg" alt="Logo" class="logo-img" />
          {{ t('app.title') }}
        </div>
        <router-link to="/" class="nav-item">{{ t('app.nav_home') }}</router-link>
        <router-link to="/agents" class="nav-item">{{ t('app.nav_agents') }}</router-link>
        <router-link to="/archive" class="nav-item">{{ t('app.nav_archive') }}</router-link>
        <router-link to="/settings" class="nav-item">{{ t('app.nav_settings') }}</router-link>
        
        <div class="spacer"></div>
        
        <!-- Language Toggle -->
        <button class="lang-btn" @click="i18n.toggleLanguage()">
          🌐 {{ i18n.currentLang === 'zh' ? 'EN' : '中文' }}
        </button>
      </div>
      <!-- Toggle Button -->
      <button class="toggle-btn pixel-btn" @click="collapsed = !collapsed">
        {{ collapsed ? '►' : '◄' }}
      </button>
    </nav>
    <main class="content" :class="{ 'no-padding': isFullscreenView }">
      <router-view />
    </main>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { useI18nStore } from './stores/i18n'
import { useRoute } from 'vue-router'

const i18n = useI18nStore()
const t = i18n.t
const route = useRoute()

const collapsed = ref(false)
const isFullscreenView = computed(() => ['ChatRoom', 'ArchivePlay'].includes(route.name))

const updateTitle = () => {
  document.title = t('app.title')
}

watch(() => i18n.currentLang, updateTitle)
onMounted(updateTitle)
</script>

<style scoped>
.app {
  display: flex;
  height: 100vh;
}
.sidebar {
  width: 200px;
  background: var(--border-color);
  color: var(--text-primary);
  display: flex;
  flex-direction: column;
  flex-shrink: 0;
  transition: width 0.3s ease;
  position: relative;
  z-index: 50;
}
.sidebar.is-collapsed {
  width: 0;
}
.sidebar-content {
  width: 200px;
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: 16px 0;
  overflow: hidden;
  transition: opacity 0.2s;
  opacity: 1;
}
.sidebar.is-collapsed .sidebar-content {
  opacity: 0;
  pointer-events: none;
}
.toggle-btn {
  position: absolute;
  top: 50%;
  right: -24px;
  transform: translateY(-50%);
  width: 24px;
  height: 48px;
  padding: 0;
  border-radius: 0 4px 4px 0;
  border-left: none;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--accent-gold);
  background: var(--border-color);
  cursor: pointer;
  z-index: 51;
  transition: all 0.2s ease;
  overflow: hidden;
}

/* 优雅的折叠态：缩成一个小边条，悬浮时展开 */
.sidebar.is-collapsed .toggle-btn {
  width: 6px;
  right: -6px;
  color: transparent;
  opacity: 0.6;
}

.sidebar.is-collapsed .toggle-btn:hover {
  width: 24px;
  right: -24px;
  color: var(--accent-gold);
  opacity: 1;
}

.logo {
  font-size: 24px;
  font-weight: bold;
  padding: 0 20px 20px;
  border-bottom: 2px solid var(--panel-bg);
  margin-bottom: 8px;
  color: var(--accent-gold);
  display: flex;
  align-items: center;
}
.logo-img {
  width: 56px;
  height: 56px;
  border-radius: 50%;
  margin-right: 12px;
}
.nav-item {
  display: block;
  padding: 10px 20px;
  color: var(--text-muted);
  text-decoration: none;
  transition: background 0.2s;
  font-size: 18px;
}
.nav-item:hover, .nav-item.router-link-active {
  background: var(--panel-bg);
  color: var(--accent-blue);
  border-left: 4px solid var(--accent-blue);
  padding-left: 16px;
}
.spacer {
  flex: 1;
}
.lang-btn {
  margin: 20px;
  background: var(--panel-bg);
  color: var(--text-primary);
  border: 2px solid var(--text-muted);
  padding: 8px;
  cursor: pointer;
  font-family: inherit;
  font-size: 14px;
  transition: all 0.2s;
}
.lang-btn:hover {
  border-color: var(--accent-gold);
  color: var(--accent-gold);
}
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 24px;
  background: var(--bg-color);
}
.content.no-padding {
  padding: 0;
  overflow: hidden;
}
</style>
