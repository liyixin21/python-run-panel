<template>
  <div>
    <div class="flex items-center gap-4 mb-6">
      <router-link to="/" class="p-2 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 transition-colors">
        <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M15 19l-7-7 7-7"/></svg>
      </router-link>
      <div>
        <h2 class="text-2xl font-bold text-gray-900 dark:text-white">{{ project?.name }}</h2>
      </div>
      <span v-if="project" class="px-2.5 py-1 text-xs font-medium rounded-full"
        :class="project.status === 'running' ? 'bg-green-100 dark:bg-green-900/30 text-green-700 dark:text-green-400' : 'bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-400'">
        {{ project.status === 'running' ? '运行中' : '已停止' }}
      </span>
    </div>

    <div v-if="project" class="space-y-5">
      <!-- 进程控制 + 项目设置 -->
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <div class="flex items-center gap-3 flex-wrap mb-3">
          <button v-if="project.status !== 'running'" @click="start"
            class="px-4 py-2 text-xs font-medium rounded-lg bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/50 border border-green-200 dark:border-green-800 transition-colors">
            <span class="flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>启动</span>
          </button>
          <button v-if="project.status === 'running'" @click="stop"
            class="px-4 py-2 text-xs font-medium rounded-lg bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/50 border border-red-200 dark:border-red-800 transition-colors">
            <span class="flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12"/></svg>停止</span>
          </button>
          <button v-if="project.status === 'running'" @click="restart"
            class="px-4 py-2 text-xs font-medium rounded-lg bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 hover:bg-yellow-100 dark:hover:bg-yellow-900/50 border border-yellow-200 dark:border-yellow-800 transition-colors">
            <span class="flex items-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>重启</span>
          </button>
          <button @click="showTerminal = !showTerminal"
            class="px-4 py-2 text-xs font-medium rounded-lg bg-gray-700 dark:bg-gray-600 text-white hover:bg-gray-800 dark:hover:bg-gray-500 transition-colors">
            {{ showTerminal ? '▾ 关闭终端' : '▸ 打开终端' }}
          </button>
          <span v-if="project.pid" class="text-xs text-gray-400">PID: {{ project.pid }}</span>
          <span v-if="project.port" class="text-xs text-blue-600 dark:text-blue-400">监听端口: {{ project.port }}</span>
          <label class="flex items-center gap-2 ml-auto cursor-pointer select-none">
            <input type="checkbox" v-model="autoRestart" @change="saveAutoRestart" class="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500" />
            <span class="text-xs text-gray-500 dark:text-gray-400">进程崩溃自动重启</span>
          </label>
        </div>

        <!-- 项目设置行 -->
        <div class="border-t border-gray-100 dark:border-gray-700 pt-3 space-y-2">
          <div class="flex items-center gap-3 flex-wrap">
            <div class="flex items-center gap-2">
              <span class="text-xs text-gray-400 flex-shrink-0">入口文件:</span>
              <input v-model="editForm.entry_file"
                class="w-32 px-2 py-1 text-xs rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-200 font-mono focus:ring-1 focus:ring-blue-500 outline-none" />
            </div>
            <span class="text-xs text-gray-400">|</span>
            <div class="flex items-center gap-2 flex-1 min-w-0">
              <span class="text-xs text-gray-400 flex-shrink-0">启动命令 (高级):</span>
              <input v-model="editForm.start_cmd"
                class="flex-1 min-w-0 px-2 py-1 text-xs rounded border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-700 dark:text-gray-200 font-mono focus:ring-1 focus:ring-blue-500 outline-none"
                placeholder="留空使用默认启动" />
            </div>
            <button @click="saveSettings" :disabled="savingSettings"
              class="px-3 py-1 text-xs font-medium rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
              {{ savingSettings ? '...' : '保存' }}
            </button>
          </div>
          <p class="text-xs text-gray-400">提示：默认启动为 <code class="text-blue-500">python 入口文件</code>，高级命令如 <code class="text-blue-500">gunicorn app:app -b 0.0.0.0:8080</code></p>
        </div>
      </div>

      <!-- 终端 -->
      <div v-if="showTerminal" class="h-[350px]">
        <WebTerminal :project-id="project.id" :project-name="project.name" @close="showTerminal = false" />
      </div>

      <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <FileManager :project-id="project.id" />

        <div class="space-y-6">
          <!-- 运行日志 -->
          <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
            <div class="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
              <h3 class="text-sm font-semibold text-gray-900 dark:text-white">
                运行日志 <span v-if="logWsConnected" class="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-green-400" title="实时连接中"></span>
              </h3>
              <button @click="clearLogs" class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">清屏</button>
            </div>
            <pre ref="logContainer" class="p-4 text-xs font-mono text-gray-300 bg-gray-900 dark:bg-black h-80 overflow-y-auto whitespace-pre-wrap break-all">{{ logText || '暂无日志' }}</pre>
          </div>

          <!-- 定时任务 -->
          <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">定时任务</h3>
            <div class="flex items-center gap-4 mb-4">
              <label class="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" v-model="scheduleEnabled" @change="onScheduleToggle" class="w-4 h-4 rounded border-gray-300 dark:border-gray-600 text-blue-600 focus:ring-blue-500" />
                <span class="text-xs text-gray-600 dark:text-gray-300">启用定时策略</span>
              </label>
            </div>
            <div v-if="scheduleEnabled" class="space-y-3">
              <div class="grid grid-cols-2 gap-3">
                <div><label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">每天启动时间</label><input type="time" v-model="scheduleForm.start_time" class="w-full px-2.5 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 outline-none" /></div>
                <div><label class="block text-xs text-gray-500 dark:text-gray-400 mb-1">每天关闭时间</label><input type="time" v-model="scheduleForm.stop_time" class="w-full px-2.5 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 outline-none" /></div>
              </div>
              <div class="flex flex-wrap gap-1.5">
                <span class="text-xs text-gray-400 py-1">快捷:</span>
                <button v-for="preset in timePresets" :key="preset.label" @click="applyPreset(preset)" class="px-2 py-0.5 text-xs rounded border border-gray-200 dark:border-gray-600 hover:bg-blue-50 dark:hover:bg-blue-900/30 text-gray-500 dark:text-gray-400 hover:text-blue-600 dark:hover:text-blue-400 transition-colors">{{ preset.label }}</button>
              </div>
              <button @click="saveSchedules" :disabled="savingSchedules" class="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">{{ savingSchedules ? '保存中...' : '保存定时配置' }}</button>
            </div>
          </div>

          <!-- 依赖管理 -->
          <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
            <h3 class="text-sm font-semibold text-gray-900 dark:text-white mb-3">依赖管理</h3>
            <div class="flex gap-2 mb-3">
              <input v-model="packageToInstall" @keyup.enter="installSinglePackage" placeholder="输入包名，如 requests"
                class="flex-1 px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 outline-none" />
              <button @click="installSinglePackage" :disabled="installingPackage" class="px-3 py-2 text-xs font-medium rounded-lg bg-green-600 text-white hover:bg-green-700 disabled:opacity-50 transition-colors">{{ installingPackage ? '...' : '安装' }}</button>
            </div>
            <div class="border-t border-gray-100 dark:border-gray-700 pt-3">
              <div class="flex items-center justify-between mb-2">
                <span class="text-xs text-gray-500 dark:text-gray-400">已安装（{{ installedPackages.length }} 个）</span>
                <button @click="refreshInstalledPackages" :disabled="loadingInstalled" class="text-xs text-blue-600 dark:text-blue-400 hover:underline">{{ loadingInstalled ? '...' : '刷新' }}</button>
              </div>
              <div v-if="loadingInstalled" class="text-center py-4"><div class="inline-block w-4 h-4 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div></div>
              <div v-else-if="installedPackages.length === 0" class="text-xs text-gray-400 text-center py-2">暂无依赖</div>
              <div v-else class="max-h-48 overflow-y-auto space-y-1">
                <div v-for="pkg in installedPackages" :key="pkg.name" class="flex items-center justify-between px-2 py-1 rounded hover:bg-gray-50 dark:hover:bg-gray-700/50 text-xs group">
                  <span class="text-gray-700 dark:text-gray-300 font-mono">{{ pkg.name }}</span>
                  <div class="flex items-center gap-2">
                    <span class="text-gray-400 dark:text-gray-500 flex-shrink-0">{{ pkg.version }}</span>
                    <button @click="removePackage(pkg.name)" :disabled="removingPackage === pkg.name" class="p-0.5 rounded text-gray-300 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all" title="卸载"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg></button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="text-center py-20">
      <div class="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed, provide, nextTick } from 'vue'
import { useRoute } from 'vue-router'
import { getProject, updateProject, startProcess, stopProcess, restartProcess,
  getProcessLogs, clearProcessLogs, getSchedules, setSchedules,
  installPackage, uninstallPackage, getInstalledPackages,
} from '../api/index.js'
import FileManager from '../components/FileManager.vue'
import WebTerminal from '../components/WebTerminal.vue'

const route = useRoute()
const projectName = computed(() => route.params.name)

const project = ref(null)
const loading = ref(true)
const logText = ref('')
const logContainer = ref(null)
const showTerminal = ref(false)
const autoRestart = ref(false)

const editForm = ref({ entry_file: 'main.py', start_cmd: '' })
const savingSettings = ref(false)

const scheduleEnabled = ref(false)
const scheduleForm = ref({ start_time: '', stop_time: '' })
const existingSchedules = ref([])
const savingSchedules = ref(false)

const packageToInstall = ref('')
const installingPackage = ref(false)
const installedPackages = ref([])
const loadingInstalled = ref(false)
const removingPackage = ref(null)

let logWs = null
const logWsConnected = ref(false)

const timePresets = [
  { label: '08:00-18:00', start_time: '08:00', stop_time: '18:00' },
  { label: '09:00-17:00', start_time: '09:00', stop_time: '17:00' },
  { label: '08:00-22:00', start_time: '08:00', stop_time: '22:00' },
  { label: '全天运行', start_time: '00:00', stop_time: '23:59' },
]

function applyPreset(p) { scheduleForm.value.start_time = p.start_time; scheduleForm.value.stop_time = p.stop_time }

function timeToCron(t) { if (!t) return null; const [h, m] = t.split(':').map(Number); return `${m} ${h} * * *` }
function cronToTime(c) { if (!c) return ''; const p = c.split(' '); return `${p[1].padStart(2,'0')}:${p[0].padStart(2,'0')}` }

function connectLogWebSocket() {
  if (!project.value?.id) return
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const token = localStorage.getItem('auth_token')
  let wsUrl = `${protocol}//${window.location.host}/ws/logs/${project.value.id}`
  if (token) {
    wsUrl += `?token=${encodeURIComponent(token)}`
  }
  logWs = new WebSocket(wsUrl)
  logWs.onopen = () => { logWsConnected.value = true }
  logWs.onmessage = (event) => {
    logText.value += (logText.value ? '\n' : '') + event.data
    nextTick(() => { if (logContainer.value) logContainer.value.scrollTop = logContainer.value.scrollHeight })
  }
  logWs.onclose = () => { logWsConnected.value = false }
}

async function clearLogs() {
  logText.value = ''
  try {
    await clearProcessLogs(project.value.id)
  } catch (err) {
    console.error('清空日志失败:', err)
  }
}

async function fetchProject() {
  loading.value = true
  try {
    const [projRes, schedRes, logRes] = await Promise.all([
      getProject(projectName.value),
      getSchedules(projectName.value).catch(() => ({ data: [] })),
      getProcessLogs(projectName.value).catch(() => ({ data: { logs: '' } })),
    ])
    project.value = projRes.data
    existingSchedules.value = schedRes.data
    logText.value = logRes.data.logs || ''
    autoRestart.value = project.value.auto_restart || false
    editForm.value = { entry_file: project.value.entry_file || 'main.py', start_cmd: project.value.start_cmd || '' }
    const ss = existingSchedules.value.find(s => s.job_type === 'start')
    const se = existingSchedules.value.find(s => s.job_type === 'stop')
    scheduleEnabled.value = !!(ss || se)
    scheduleForm.value.start_time = cronToTime(ss?.cron_expression)
    scheduleForm.value.stop_time = cronToTime(se?.cron_expression)
  } catch (err) { console.error(err); project.value = null }
  finally { loading.value = false }
}

async function start() {
  try {
    await startProcess(project.value.id, { entry_file: project.value.entry_file, start_cmd: project.value.start_cmd, auto_restart: autoRestart.value })
    await fetchProject(); if (logWs) logWs.close(); connectLogWebSocket()
  } catch (err) { alert(`启动失败: ${err.response?.data?.detail || err.message}`) }
}
async function stop() { try { await stopProcess(project.value.id); await fetchProject() } catch (e) { alert(e.response?.data?.detail || e.message) } }
async function restart() {
  try {
    await restartProcess(project.value.id, { entry_file: project.value.entry_file, start_cmd: project.value.start_cmd, auto_restart: autoRestart.value })
    await fetchProject(); if (logWs) logWs.close(); connectLogWebSocket()
  } catch (e) { alert(e.response?.data?.detail || e.message) }
}

async function saveSettings() {
  savingSettings.value = true
  try {
    await updateProject(projectName.value, { entry_file: editForm.value.entry_file, start_cmd: editForm.value.start_cmd })
    project.value.entry_file = editForm.value.entry_file; project.value.start_cmd = editForm.value.start_cmd
  } catch (e) { alert(e.response?.data?.detail || e.message) }
  finally { savingSettings.value = false }
}

async function saveAutoRestart() {
  try { await updateProject(projectName.value, { auto_restart: autoRestart.value }); project.value.auto_restart = autoRestart.value }
  catch (e) { alert(e.response?.data?.detail || e.message) }
}

async function onScheduleToggle() { if (!scheduleEnabled.value) await saveSchedules() }
async function saveSchedules() {
  savingSchedules.value = true
  try {
    if (!scheduleEnabled.value) await setSchedules(projectName.value, { cron_start: null, cron_stop: null })
    else await setSchedules(projectName.value, { cron_start: timeToCron(scheduleForm.value.start_time), cron_stop: timeToCron(scheduleForm.value.stop_time) })
    existingSchedules.value = (await getSchedules(projectName.value)).data
  } catch (e) { alert(e.response?.data?.detail || e.message) }
  finally { savingSchedules.value = false }
}

async function refreshInstalledPackages() {
  loadingInstalled.value = true
  try { installedPackages.value = ((await getInstalledPackages(projectName.value)).data.packages || []) }
  catch (e) { console.error(e) }
  finally { loadingInstalled.value = false }
}

async function installSinglePackage() {
  const p = packageToInstall.value.trim(); if (!p) return
  installingPackage.value = true
  try { await installPackage(projectName.value, p); packageToInstall.value = ''; await refreshInstalledPackages() }
  catch (e) { alert(e.response?.data?.detail || e.message) }
  finally { installingPackage.value = false }
}

async function removePackage(name) {
  if (!confirm(`确定卸载「${name}」?`)) return
  removingPackage.value = name
  try { await uninstallPackage(projectName.value, name); await refreshInstalledPackages() }
  catch (e) { alert(e.response?.data?.detail || e.message) }
  finally { removingPackage.value = null }
}

provide('refresh', fetchProject)
onMounted(async () => { await fetchProject(); refreshInstalledPackages(); connectLogWebSocket() })
onBeforeUnmount(() => { if (logWs) logWs.close() })
</script>
