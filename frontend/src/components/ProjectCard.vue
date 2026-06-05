<template>
  <div
    class="group bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 shadow-sm hover:shadow-md transition-all duration-300 overflow-hidden"
  >
    <div class="p-5 pb-4">
      <div class="flex items-start justify-between mb-3">
        <div class="flex items-center gap-3 min-w-0">
          <span class="flex-shrink-0 w-3 h-3 rounded-full" :class="statusClass" :title="project.status === 'running' ? '运行中' : '已停止'"></span>
          <h3 class="text-base font-semibold text-gray-900 dark:text-white truncate">
            {{ project.name }}
          </h3>
        </div>
        <div class="relative" @click.stop>
          <button @click="showMenu = !showMenu"
            class="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-gray-300 hover:bg-gray-100 dark:hover:bg-gray-700 opacity-0 group-hover:opacity-100 transition-all">
            <svg class="w-5 h-5" fill="currentColor" viewBox="0 0 24 24"><path d="M12 8c1.1 0 2-.9 2-2s-.9-2-2-2-2 .9-2 2 .9 2 2 2zm0 2c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2zm0 6c-1.1 0-2 .9-2 2s.9 2 2 2 2-.9 2-2-.9-2-2-2z"/></svg>
          </button>
          <div v-if="showMenu" class="absolute right-0 top-8 z-20 w-44 bg-white dark:bg-gray-700 rounded-lg shadow-lg border border-gray-200 dark:border-gray-600 py-1">
            <button @click="handleDelete" class="w-full text-left px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-gray-100 dark:hover:bg-gray-600">删除项目</button>
          </div>
        </div>
      </div>

      <div class="flex items-center gap-2">
        <button v-if="project.status !== 'running'" @click.stop="$emit('start', project)"
          class="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-green-50 dark:bg-green-900/30 text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-900/50 border border-green-200 dark:border-green-800 transition-colors">
          <span class="flex items-center justify-center gap-1.5"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>启动</span>
        </button>
        <button v-else @click.stop="$emit('stop', project)"
          class="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-900/50 border border-red-200 dark:border-red-800 transition-colors">
          <span class="flex items-center justify-center gap-1.5"><svg class="w-3.5 h-3.5" fill="currentColor" viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12"/></svg>停止</span>
        </button>
        <button v-if="project.status === 'running'" @click.stop="$emit('restart', project)"
          class="flex-1 px-3 py-2 text-xs font-medium rounded-lg bg-yellow-50 dark:bg-yellow-900/30 text-yellow-700 dark:text-yellow-400 hover:bg-yellow-100 dark:hover:bg-yellow-900/50 border border-yellow-200 dark:border-yellow-800 transition-colors">
          <span class="flex items-center justify-center gap-1.5"><svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"/></svg>重启</span>
        </button>
      </div>
    </div>

    <div class="border-t border-gray-100 dark:border-gray-700"></div>

    <div class="px-5 py-3 flex items-center justify-between text-xs text-gray-400 dark:text-gray-500">
      <span v-if="project.port">监听端口: {{ project.port }}</span>
      <span v-else>端口: 未检测</span>
      <span>入口: {{ project.entry_file }}</span>
    </div>

    <div class="px-5 pb-4">
      <router-link :to="`/project/${project.name}`"
        class="block text-center px-3 py-2 text-xs font-medium rounded-lg bg-blue-50 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-900/50 border border-blue-200 dark:border-blue-800 transition-colors">
        进入详情
      </router-link>
    </div>

    <Teleport to="body">
      <Transition name="toast">
        <div v-if="toast.show" class="fixed bottom-6 right-6 z-50 px-4 py-3 rounded-lg shadow-lg text-sm font-medium"
          :class="toast.type === 'success' ? 'bg-green-600 text-white' : 'bg-red-600 text-white'">
          {{ toast.message }}
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, inject, onMounted, onUnmounted } from 'vue'
import { deleteProject } from '../api/index.js'

const props = defineProps({ project: { type: Object, required: true } })
const emit = defineEmits(['start', 'stop', 'restart', 'deleted', 'refresh'])
const refresh = inject('refresh')

const showMenu = ref(false)
const toast = ref({ show: false, type: 'success', message: '' })

const statusClass = computed(() => {
  switch (props.project.status) {
    case 'running': return 'bg-green-500 shadow-[0_0_6px_rgba(34,197,94,0.5)]'
    case 'error': return 'bg-red-500 shadow-[0_0_6px_rgba(239,68,68,0.5)]'
    case 'starting': return 'bg-yellow-500 animate-pulse'
    default: return 'bg-gray-300 dark:bg-gray-600'
  }
})

function showToast(type, message) {
  toast.value = { show: true, type, message }
  setTimeout(() => { toast.value.show = false }, 3000)
}

async function handleDelete() {
  showMenu.value = false
  if (!confirm(`确定删除「${props.project.name}」? 不可恢复。`)) return
  try {
    await deleteProject(props.project.name)
    showToast('success', '项目已删除')
    emit('deleted', props.project.id)
  } catch (err) {
    showToast('error', `删除失败: ${err.response?.data?.detail || err.message}`)
  }
}

function closeMenu() { showMenu.value = false }
onMounted(() => document.addEventListener('click', closeMenu))
onUnmounted(() => document.removeEventListener('click', closeMenu))
</script>

<style scoped>
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(20px); }
</style>
