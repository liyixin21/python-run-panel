<template>
  <div class="max-w-lg mx-auto space-y-6">
    <div>
      <h2 class="text-2xl font-bold text-gray-900 dark:text-white">面板设置</h2>
      <p class="text-sm text-gray-500 dark:text-gray-400 mt-1">修改登录凭据</p>
    </div>

    <!-- 修改用户名和密码 -->
    <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white">登录凭据</h3>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">当前用户名</label>
        <input
          :value="currentUsername"
          disabled
          class="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-100 dark:bg-gray-700 text-gray-500 dark:text-gray-400"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">新用户名（留空不修改）</label>
        <input
          v-model="form.newUsername"
          type="text"
          placeholder="留空保持不变"
          class="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">新密码（留空不修改）</label>
        <input
          v-model="form.newPassword"
          type="password"
          placeholder="留空保持不变"
          class="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        />
      </div>

      <div>
        <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1.5">当前密码（必填，用于验证身份）</label>
        <input
          v-model="form.currentPassword"
          type="password"
          placeholder="请输入当前密码"
          class="w-full px-3 py-2.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        />
      </div>

      <p v-if="message" class="text-xs" :class="success ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'">
        {{ message }}
      </p>

      <button
        @click="saveCredentials"
        :disabled="saving || !form.currentPassword || (!form.newUsername && !form.newPassword)"
        class="px-5 py-2.5 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
      >
        <span v-if="!saving">保存修改</span>
        <span v-else class="flex items-center gap-2"><span class="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></span>保存中...</span>
      </button>
    </div>

    <!-- 提示 -->
    <p class="text-xs text-gray-400 dark:text-gray-500">
      修改用户名或密码后，当前登录不会失效。重新登录时请使用新凭据。
    </p>

    <!-- 防火墙设置 -->
    <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-6 space-y-4">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white">防火墙自动放行</h3>
      <p class="text-xs text-gray-400 dark:text-gray-500">通过 1Panel API 自动管理端口放行规则</p>

      <!-- 连接状态 -->
      <div v-if="connected" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-green-50 dark:bg-green-900/20 text-green-700 dark:text-green-400 text-xs">
        <span class="w-1.5 h-1.5 rounded-full bg-green-500"></span> 1Panel API 已连接
      </div>
      <div v-else-if="connected === false" class="flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-700 dark:text-red-400 text-xs">
        <span class="w-1.5 h-1.5 rounded-full bg-red-500"></span> 未连接 1Panel API，自动放行功能不可用
      </div>

      <div class="space-y-3">
        <div>
          <label class="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">1Panel 地址</label>
          <input v-model="fwSettings.base_url" type="text" placeholder="http://127.0.0.1:55555"
            class="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-blue-500 outline-none" />
        </div>
        <div>
          <label class="block text-xs font-medium text-gray-600 dark:text-gray-400 mb-1">API Key</label>
          <input v-model="fwSettings.api_key" type="password" placeholder="1Panel 的 API 密钥"
            class="w-full px-3 py-2 text-xs rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-1 focus:ring-blue-500 outline-none" />
        </div>
        <div class="flex gap-2">
          <button @click="testAndSave"
            :disabled="testing || savingFw"
            class="px-4 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
            <span v-if="testing">测试中...</span>
            <span v-else-if="savingFw">保存中...</span>
            <span v-else>测试并保存</span>
          </button>
          <button @click="testConnection"
            :disabled="testing || savingFw"
            class="px-4 py-1.5 text-xs font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors disabled:opacity-50">
            <span v-if="!testing">仅测试连接</span>
            <span v-else class="flex items-center gap-1"><span class="w-3 h-3 border-2 border-gray-400 border-t-transparent rounded-full animate-spin"></span>测试中</span>
          </button>
        </div>
      </div>

      <div class="border-t border-gray-100 dark:border-gray-700 pt-3 space-y-2">
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-900 dark:text-white">自动放行端口</p>
            <p class="text-xs text-gray-400 dark:text-gray-500">检测到端口后自动调用 1Panel API 放行</p>
          </div>
          <button @click="toggleFirewall('auto_open')"
            :disabled="!connected"
            :class="connected ? (fwSettings.auto_open ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600') : 'bg-gray-200 dark:bg-gray-700 cursor-not-allowed'"
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0">
            <span :class="fwSettings.auto_open ? 'translate-x-6' : 'translate-x-1'"
              class="inline-block h-4 w-4 rounded-full bg-white transition-transform shadow-sm" />
          </button>
        </div>
        <div class="flex items-center justify-between">
          <div>
            <p class="text-sm text-gray-900 dark:text-white">保留已放行规则</p>
            <p class="text-xs text-gray-400 dark:text-gray-500">进程停止后保留防火墙规则</p>
          </div>
          <button @click="toggleFirewall('keep_rules')"
            :disabled="!connected"
            :class="connected ? (fwSettings.keep_rules ? 'bg-blue-600' : 'bg-gray-300 dark:bg-gray-600') : 'bg-gray-200 dark:bg-gray-700 cursor-not-allowed'"
            class="relative inline-flex h-6 w-11 items-center rounded-full transition-colors flex-shrink-0">
            <span :class="fwSettings.keep_rules ? 'translate-x-6' : 'translate-x-1'"
              class="inline-block h-4 w-4 rounded-full bg-white transition-transform shadow-sm" />
          </button>
        </div>
      </div>

      <p v-if="fwMsg" class="text-xs" :class="fwOk ? 'text-green-600 dark:text-green-400' : 'text-red-500 dark:text-red-400'">
        {{ fwMsg }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import api from '../api/index.js'

const currentUsername = ref('admin')
const form = ref({ newUsername: '', newPassword: '', currentPassword: '' })
const saving = ref(false)
const message = ref('')
const success = ref(false)

// 防火墙设置
const fwSettings = ref({ auto_open: true, keep_rules: false, api_key: '', base_url: 'http://127.0.0.1:55555' })
const fwMsg = ref('')
const fwOk = ref(false)
const testing = ref(false)
const savingFw = ref(false)
const connected = ref(null) // null=未知, true=已连接, false=未连接

onMounted(async () => {
  try {
    const res = await api.get('/api/auth/info')
    currentUsername.value = res.data.username
  } catch (e) { /* ignore */ }
  try {
    const res = await api.get('/api/firewall/settings')
    fwSettings.value = res.data
    if (res.data.api_key === '***') fwSettings.value.api_key = ''
    // 如果有 api_key，尝试测试连接
    if (res.data.api_key && res.data.api_key !== '***') {
      connected.value = null // 待验证
    }
  } catch (e) { /* ignore */ }
})

async function doTest() {
  testing.value = true
  try {
    const res = await api.post('/api/firewall/test-connection', { ...fwSettings.value })
    const ok = res.data.success
    connected.value = ok
    fwOk.value = ok
    fwMsg.value = res.data.message
    if (!ok && fwSettings.value.auto_open) {
      fwSettings.value.auto_open = false
      await saveFwSettingsSilent(fwSettings.value)
    }
    return ok
  } catch (err) {
    connected.value = false
    fwOk.value = false
    fwMsg.value = err.response?.data?.detail || '连接测试异常'
    return false
  } finally {
    testing.value = false
    setTimeout(() => { fwMsg.value = '' }, 5000)
  }
}

async function testConnection() {
  fwMsg.value = ''
  await doTest()
}

async function testAndSave() {
  fwMsg.value = ''
  savingFw.value = true
  // 先测试连接
  const ok = await doTest()
  if (!ok) {
    savingFw.value = false
    return // 连接失败不保存
  }
  // 连接成功，保存配置
  try {
    const originalApiKey = fwSettings.value.api_key
    const res = await api.put('/api/firewall/settings', { ...fwSettings.value })
    fwSettings.value = res.data.config
    if (res.data.config.api_key === '***') fwSettings.value.api_key = originalApiKey
    fwOk.value = true
    fwMsg.value = '已保存'
    setTimeout(() => { fwMsg.value = '' }, 2000)
  } catch (err) {
    fwOk.value = false
    fwMsg.value = err.response?.data?.detail || '保存失败'
  } finally {
    savingFw.value = false
  }
}

async function toggleFirewall(key) {
  fwMsg.value = ''
  const newVal = !fwSettings.value[key]
  const payload = { ...fwSettings.value, [key]: newVal }
  saveFwSettings(payload)
}

async function saveFwSettings(payload) {
  try {
    const res = await api.put('/api/firewall/settings', payload)
    fwSettings.value = res.data.config
    if (res.data.config.api_key === '***') fwSettings.value.api_key = payload.api_key
    fwOk.value = true
    fwMsg.value = '已更新'
    setTimeout(() => { fwMsg.value = '' }, 2000)
  } catch (err) {
    fwOk.value = false
    fwMsg.value = err.response?.data?.detail || '保存失败'
  }
}

async function saveFwSettingsSilent(payload) {
  try {
    await api.put('/api/firewall/settings', payload)
  } catch (e) { /* silent */ }
}

async function saveCredentials() {
  saving.value = true
  message.value = ''
  try {
    const res = await api.put('/api/settings/credentials', {
      current_password: form.value.currentPassword,
      new_username: form.value.newUsername || undefined,
      new_password: form.value.newPassword || undefined,
    })
    success.value = true
    message.value = res.data.message
    form.value = { newUsername: '', newPassword: '', currentPassword: '' }
    // 更新本地缓存的用户名
    if (res.data.username) {
      currentUsername.value = res.data.username
      localStorage.setItem('auth_username', res.data.username)
    }
  } catch (err) {
    success.value = false
    message.value = err.response?.data?.detail || '保存失败'
  } finally {
    saving.value = false
  }
}
</script>
