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

onMounted(async () => {
  try {
    const res = await api.get('/api/auth/info')
    currentUsername.value = res.data.username
  } catch (e) { /* ignore */ }
})

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
