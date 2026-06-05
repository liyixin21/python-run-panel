<template>
  <div>
    <div class="flex items-center justify-between mb-6">
      <div>
        <h2 class="text-2xl font-bold text-gray-900 dark:text-white">项目列表</h2>
        <p class="text-sm text-gray-400 dark:text-gray-500 mt-1">管理和运行你的 Python 项目</p>
      </div>
      <button @click="showCreateDialog = true"
        class="px-4 py-2 text-sm font-medium rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:from-blue-700 hover:to-purple-700 shadow-md hover:shadow-lg transition-all active:scale-95">
        <span class="flex items-center gap-1.5"><svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"/></svg>新建项目</span>
      </button>
    </div>

    <div class="grid grid-cols-3 gap-4 mb-6">
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <p class="text-2xl font-bold text-gray-900 dark:text-white">{{ projects.length }}</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">项目总数</p>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <p class="text-2xl font-bold text-green-600 dark:text-green-400">{{ runningCount }}</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">运行中</p>
      </div>
      <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 p-4">
        <p class="text-2xl font-bold text-gray-400 dark:text-gray-500">{{ stoppedCount }}</p>
        <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">已停止</p>
      </div>
    </div>

    <div v-if="projects.length > 0" class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-5">
      <ProjectCard v-for="project in projects" :key="project.id" :project="project"
        @start="handleStart" @stop="handleStop" @restart="handleRestart" @deleted="handleDeleted" />
    </div>

    <div v-else-if="!loading" class="text-center py-20">
      <div class="w-20 h-20 mx-auto mb-4 rounded-full bg-gray-100 dark:bg-gray-800 flex items-center justify-center">
        <svg class="w-10 h-10 text-gray-300 dark:text-gray-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/>
        </svg>
      </div>
      <p class="text-lg font-medium text-gray-400 dark:text-gray-500 mb-2">还没有任何项目</p>
      <p class="text-sm text-gray-400 dark:text-gray-500">点击上方「新建项目」按钮开始</p>
    </div>

    <div v-if="loading" class="text-center py-20">
      <div class="inline-block w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
      <p class="text-sm text-gray-400 mt-3">加载中...</p>
    </div>

    <Teleport to="body">
      <Transition name="modal">
        <div v-if="showCreateDialog" class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" @click.self="showCreateDialog = false">
          <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 border border-gray-200 dark:border-gray-700">
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white mb-4">新建项目</h3>
            <div>
              <label class="block text-sm font-medium text-gray-700 dark:text-gray-300 mb-1">项目名称</label>
              <input v-model="newProject.name" @keyup.enter="createNewProject" placeholder="例：my-web-app"
                class="w-full px-3 py-2 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none" />
            </div>
            <div class="flex gap-3 mt-6">
              <button @click="showCreateDialog = false" class="flex-1 px-4 py-2.5 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">取消</button>
              <button @click="createNewProject" :disabled="creating" class="flex-1 px-4 py-2.5 text-sm font-medium rounded-lg bg-gradient-to-r from-blue-600 to-purple-600 text-white hover:from-blue-700 hover:to-purple-700 disabled:opacity-50 transition-all">{{ creating ? '创建中...' : '确认创建' }}</button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, provide } from 'vue'
import { listProjects, createProject, startProcess, stopProcess, restartProcess } from '../api/index.js'
import ProjectCard from '../components/ProjectCard.vue'

const projects = ref([])
const loading = ref(true)
const showCreateDialog = ref(false)
const creating = ref(false)
const newProject = ref({ name: '' })

const runningCount = computed(() => projects.value.filter(p => p.status === 'running').length)
const stoppedCount = computed(() => projects.value.filter(p => p.status !== 'running').length)

async function fetchProjects() {
  loading.value = true
  try { projects.value = (await listProjects()).data } catch (err) { console.error(err) }
  finally { loading.value = false }
}

async function createNewProject() {
  const name = newProject.value.name.trim()
  if (!name) return
  creating.value = true
  try {
    await createProject({ name })
    showCreateDialog.value = false
    newProject.value = { name: '' }
    await fetchProjects()
  } catch (err) { alert(`创建失败: ${err.response?.data?.detail || err.message}`) }
  finally { creating.value = false }
}

async function handleStart(project) {
  try { await startProcess(project.id, { entry_file: project.entry_file, start_cmd: project.start_cmd }); await fetchProjects() }
  catch (err) { alert(`启动失败: ${err.response?.data?.detail || err.message}`) }
}

async function handleStop(project) {
  try { await stopProcess(project.id); await fetchProjects() }
  catch (err) { alert(`停止失败: ${err.response?.data?.detail || err.message}`) }
}

async function handleRestart(project) {
  try { await restartProcess(project.id, { entry_file: project.entry_file, start_cmd: project.start_cmd }); await fetchProjects() }
  catch (err) { alert(`重启失败: ${err.response?.data?.detail || err.message}`) }
}

function handleDeleted(id) { projects.value = projects.value.filter(p => p.id !== id) }

provide('refresh', fetchProjects)
onMounted(fetchProjects)
</script>
