import { defineStore } from 'pinia'
import { ref } from 'vue'

const dict = {
  zh: {
    app: {
      title: '沙龙',
      nav_home: '首页',
      nav_agents: '角色管理',
      nav_archive: '档案馆',
      nav_settings: '设置',
    },
    home: {
      console: '沙龙控制台',
      start_quest: '发起新讨论',
      topic_ph: '输入讨论主题...',
      mod: '主持人',
      scribe: '记录员',
      always_party: '(自动参与)',
      enter_dungeon: '开始讨论',
      active_sessions: '活跃会话',
      no_active: '暂无活跃会话',
      pending: '待启动',
      resumable: '可恢复',
      finished: '已完成',
      start: '开始',
      resume: '恢复',
      archive: '归档',
      view: '查看',
      delete: '删除',
      round: '第 {n} 轮',
      hero_roster: '角色列表',
      manage_heroes: '管理角色',
      banish_confirm: '确定要删除该会话吗？此操作不可恢复。',
      select_hint: '（点击右侧角色卡片选择出战角色）'
    },
    chat: {
      back: '返回',
      loading: '加载中...',
      tts_on: '🔊 语音: 开',
      tts_off: '🔇 语音: 关',
      start: '开始讨论',
      starting: '启动中...',
      pause: '暂停',
      resume: '恢复',
      end: '结束',
      whiteboard: '白板',

      empty: '暂无对话。',
      cmd_ph: '输入命令: /pause /resume /end /ask @名称 问题',
      state_idle: '待启动',
      state_running: '进行中',
      state_paused: '已暂停',
      state_finished: '已完成'
    },
    archive: {
      title: '档案记录',
      subtitle: '-- 已完成的会话记录 --',
      loading: '正在翻阅记录...',
      empty: '手札中空空如也。',
      unknown_scroll: '未知卷轴',
      destroy: '销毁',
      destroy_confirm: '确定销毁该卷轴？此操作不可逆。',
      round: '{n} 轮',
      participants: '{n} 参与者',
      export: '导出',
      export_md: 'Markdown',
      export_html: 'HTML',
      memory: '记忆',
    },
    play: {
      playback: '回放',
      display: '显示',
      reset: '重置',
      show_all: '全显',
      auto: '自动',
      auto_pause: '暂停',
      empty: '暂无记录'
    },
    agents: {
      title: '角色管理',
      new_hero: '+ 新建角色',
      banish: '删除',
      banish_confirm: '确定要删除该角色吗？',
      stats: '编辑',
      mod: '主持人',
      ftr: '参与者',
      mag: '记录员',
      new_group: '+ 新建分组',
      add_agent: '+'
    },
    edit: {
      new_title: '新建角色',
      edit_title: '编辑角色',
      name: '名称',
      role: '职责',
      group: '分组',
      avatar: '头像(Emoji)',
      voice_desc: '音色描述 (TTS)',
      voice_ph: '例如：年轻女性，温柔',
      soul: '灵魂档案 (Markdown)',
      confirm: '保存',
      updating: '保存中...',
      cancel: '取消',
      name_required: '请输入名称',
      soul_required: '请输入灵魂档案内容'
    },
    groups: {
      title: '分组管理',
      new_group: '+ 新建分组',
      edit: '编辑',
      delete: '删除',
      delete_confirm: '确定要删除该分组吗？组内角色将变为无分组状态。',
      no_group: '无分组',
      ungrouped: '未分组',
      agent_count: '{n} 个角色',
      new_title: '新建分组',
      edit_title: '编辑分组',
      name: '名称',
      description: '描述',
      emoji: '图标(Emoji)',
      confirm: '保存',
      updating: '保存中...',
      cancel: '取消',
      name_required: '请输入分组名称'
    },
    settings: {
      title: '系统设置',
      // LLM
      llm_config: '大模型配置',
      api_base: 'API 地址',
      api_key: 'API Key',
      model_name: '模型',
      temperature: '温度',
      max_tokens: '最大 Token',
      timeout: '超时时间',
      native_thinking: '原生思考模式',
      // Discussion
      game_rules: '讨论参数',
      language: '语言 (Language)',
      max_rounds: '最大轮次',
      min_rounds: '最小轮次',
      max_speech_chars: '发言字数上限',
      min_speech_chars: '发言字数下限',
      participant_count: '参与人数',
      // Search
      search: '联网搜索',
      search_enabled: '启用搜索',
      search_api_key: '搜索 API Key',
      search_max_results: '每次搜索结果数',
      // Memory
      memory: '记忆与白板',
      scribe_interval: '记录员同步频率（每N轮）',
      scribe_interval_hint: '记录员每隔几轮同步一次白板',
      cold_ttl: '白板条目过期轮次',
      cold_ttl_hint: '超过此轮次未更新的条目将被归档',
      archive_enabled: '启用跨会话记忆',
      archive_top_k: '记忆检索条数',
      // Output
      output: '输出与监控',
      digest_auto: '自动生成讨论纪要',
      report_auto: '自动生成报告',
      monitor_enabled: '启用信号监测系统',
      log_level: '日志级别',
      // Common
      on: '开启',
      off: '关闭',
      save: '保存更改',
      saving: '保存中...',
      saved: '已保存!',
      scheduler: '调度器',
      mode: '调度模式',
      mode_weighted: '加权随机',
      mode_rr: '轮流发言',
    }
  },
  en: {
    app: {
      title: 'Salon',
      nav_home: 'Dashboard',
      nav_agents: 'Heroes',
      nav_archive: 'Archives',
      nav_settings: 'Settings',
    },
    home: {
      console: 'SALON CONSOLE',
      start_quest: 'START NEW QUEST',
      topic_ph: 'ENTER QUEST TOPIC...',
      mod: 'MODERATOR',
      scribe: 'SCRIBE',
      always_party: '(Always in party)',
      enter_dungeon: 'ENTER DUNGEON',
      active_sessions: 'ACTIVE SESSIONS',
      no_active: 'NO ACTIVE SESSIONS',
      pending: 'PENDING',
      resumable: 'RESUMABLE',
      finished: 'FINISHED',
      start: 'START',
      resume: 'RESUME',
      archive: 'ARCHIVE',
      view: 'VIEW',
      delete: 'DELETE',
      round: 'ROUND {n}',
      hero_roster: 'HERO ROSTER',
      manage_heroes: 'MANAGE HEROES',
      banish_confirm: 'Banish this session forever?',
      select_hint: '(Click hero cards on the right to add to party)'
    },
    chat: {
      back: 'BACK',
      loading: 'LOADING...',
      tts_on: '🔊 TTS: ON',
      tts_off: '🔇 TTS: OFF',
      start: 'START',
      starting: 'STARTING...',
      pause: 'PAUSE',
      resume: 'RESUME',
      end: 'END',
      whiteboard: 'BOARD',

      empty: 'NO MESSAGES.',
      cmd_ph: 'Enter cmd: /pause /resume /end /ask @name question',
      state_idle: 'IDLE',
      state_running: 'RUNNING',
      state_paused: 'PAUSED',
      state_finished: 'FINISHED'
    },
    archive: {
      title: 'QUEST LOG',
      subtitle: '-- COMPLETED SESSIONS --',
      loading: 'READING SCROLLS...',
      empty: 'THE LOG IS EMPTY.',
      unknown_scroll: 'UNKNOWN SCROLL',
      destroy: 'DESTROY',
      destroy_confirm: 'Destroy this scroll permanently?',
      round: '{n} ROUNDS',
      participants: '{n} PARTICIPANTS',
      export: 'EXPORT',
      export_md: 'Markdown',
      export_html: 'HTML',
      memory: 'MEMORY',
    },
    play: {
      playback: 'REPLAY',
      display: 'DISPLAY',
      reset: 'RESET',
      show_all: 'SHOW ALL',
      auto: 'AUTO',
      auto_pause: 'PAUSE',
      empty: 'NO LOGS'
    },
    agents: {
      title: 'CHOOSE YOUR HEROES',
      new_hero: '+ NEW HERO',
      banish: 'BANISH',
      banish_confirm: 'Banish this hero forever?',
      stats: 'STATS',
      mod: 'MOD',
      ftr: 'FIGHTER',
      mag: 'MAGE',
      new_group: '+ NEW GROUP',
      add_agent: '+'
    },
    edit: {
      new_title: 'NEW HERO',
      edit_title: 'HERO STATS',
      name: 'NAME',
      role: 'CLASS',
      group: 'GROUP',
      avatar: 'AVATAR (EMOJI)',
      voice_desc: 'VOICE DESCRIPTION (TTS)',
      voice_ph: 'e.g. young male, confident and calm',
      soul: 'SOUL ARCHIVE (LORE)',
      confirm: 'CONFIRM',
      updating: 'UPDATING...',
      cancel: 'CANCEL',
      name_required: 'Name is required',
      soul_required: 'Soul content is required'
    },
    groups: {
      title: 'GROUPS',
      new_group: '+ NEW GROUP',
      edit: 'EDIT',
      delete: 'DELETE',
      delete_confirm: 'Delete this group? Agents in it will become ungrouped.',
      no_group: 'No Group',
      ungrouped: 'UNGROUPED',
      agent_count: '{n} AGENTS',
      new_title: 'NEW GROUP',
      edit_title: 'EDIT GROUP',
      name: 'NAME',
      description: 'DESCRIPTION',
      emoji: 'EMOJI',
      confirm: 'CONFIRM',
      updating: 'UPDATING...',
      cancel: 'CANCEL',
      name_required: 'Group name is required'
    },
    settings: {
      title: 'SYSTEM OPTIONS',
      // LLM
      llm_config: 'LLM CONFIG',
      api_base: 'API BASE URL',
      api_key: 'API KEY',
      model_name: 'MODEL NAME',
      temperature: 'TEMPERATURE',
      max_tokens: 'MAX TOKENS',
      timeout: 'TIMEOUT',
      native_thinking: 'NATIVE THINKING',
      // Discussion
      game_rules: 'DISCUSSION',
      language: 'LANGUAGE',
      max_rounds: 'MAX ROUNDS',
      min_rounds: 'MIN ROUNDS',
      max_speech_chars: 'MAX SPEECH CHARS',
      min_speech_chars: 'MIN SPEECH CHARS',
      participant_count: 'PARTICIPANT COUNT',
      // Search
      search: 'WEB SEARCH',
      search_enabled: 'ENABLE SEARCH',
      search_api_key: 'SEARCH API KEY',
      search_max_results: 'MAX RESULTS PER SEARCH',
      // Memory
      memory: 'MEMORY & WHITEBOARD',
      scribe_interval: 'SCRIBE SYNC INTERVAL (EVERY N ROUNDS)',
      scribe_interval_hint: 'How often the scribe syncs the whiteboard',
      cold_ttl: 'WHITEBOARD ENTRY TTL (ROUNDS)',
      cold_ttl_hint: 'Entries older than this are archived',
      archive_enabled: 'ENABLE CROSS-SESSION MEMORY',
      archive_top_k: 'MEMORY RETRIEVAL TOP K',
      // Output
      output: 'OUTPUT & MONITORING',
      digest_auto: 'AUTO-GENERATE DIGEST',
      report_auto: 'AUTO-GENERATE REPORT',
      monitor_enabled: 'ENABLE SIGNAL MONITOR',
      log_level: 'LOG LEVEL',
      // Common
      on: 'ON',
      off: 'OFF',
      save: 'SAVE CHANGES',
      saving: 'SAVING...',
      saved: 'SAVED!',
      scheduler: 'SCHEDULER',
      mode: 'MODE',
      mode_weighted: 'WEIGHTED RANDOM',
      mode_rr: 'ROUND ROBIN',
    }
  }
}

export const useI18nStore = defineStore('i18n', () => {
  const currentLang = ref(localStorage.getItem('salon_lang') || 'zh')

  function setLanguage(lang) {
    currentLang.value = lang
    localStorage.setItem('salon_lang', lang)
  }

  function toggleLanguage() {
    setLanguage(currentLang.value === 'zh' ? 'en' : 'zh')
  }

  function t(key, params = {}) {
    const keys = key.split('.')
    let val = dict[currentLang.value]
    for (const k of keys) {
      if (val === undefined) break
      val = val[k]
    }
    if (val === undefined) return key
    
    let result = val
    for (const [k, v] of Object.entries(params)) {
      result = result.replace(`{${k}}`, v)
    }
    return result
  }

  return { currentLang, setLanguage, toggleLanguage, t }
})
