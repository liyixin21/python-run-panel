<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden">
    <!-- 文件管理器头部 -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white">文件管理</h3>
      <div class="flex items-center gap-2">
        <!-- 新建文件夹 -->
        <button
          @click="showNewDirInput = true"
          class="px-2.5 py-1.5 text-xs rounded-lg bg-gray-100 dark:bg-gray-700 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-600 transition-colors"
        >
          新建文件夹
        </button>
        <!-- 选择文件上传 -->
        <label
          class="px-2.5 py-1.5 text-xs rounded-lg bg-blue-100 dark:bg-blue-900/30 text-blue-700 dark:text-blue-400 hover:bg-blue-200 dark:hover:bg-blue-900/50 cursor-pointer transition-colors"
          :class="{ 'opacity-50 pointer-events-none': uploading }"
        >
          {{ uploading ? '上传中...' : '选择文件' }}
          <input
            ref="fileInput"
            type="file"
            class="hidden"
            multiple
            :disabled="uploading"
            @change="onFileInputChange"
          />
        </label>
        <!-- 选择文件夹上传 -->
        <label
          class="px-2.5 py-1.5 text-xs rounded-lg bg-purple-100 dark:bg-purple-900/30 text-purple-700 dark:text-purple-400 hover:bg-purple-200 dark:hover:bg-purple-900/50 cursor-pointer transition-colors"
          :class="{ 'opacity-50 pointer-events-none': uploading }"
        >
          {{ uploading ? '上传中...' : '上传文件夹' }}
          <input
            type="file"
            class="hidden"
            webkitdirectory
            multiple
            :disabled="uploading"
            @change="onFileInputChange"
          />
        </label>
      </div>
    </div>

    <!-- 面包屑导航 -->
    <div class="px-4 py-2 text-xs text-gray-400 dark:text-gray-500 flex items-center gap-1 flex-wrap">
      <button @click="navigateTo('')" class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors">
        根目录
      </button>
      <template v-for="(part, idx) in breadcrumbs" :key="idx">
        <span>/</span>
        <button
          @click="navigateTo(part.path)"
          class="hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
          :class="{ 'text-gray-700 dark:text-gray-300 font-medium': idx === breadcrumbs.length - 1 }"
        >
          {{ part.name }}
        </button>
      </template>
    </div>

    <!-- 新建文件夹输入框 -->
    <div v-if="showNewDirInput" class="px-4 py-2 flex items-center gap-2">
      <input
        v-model="newDirName"
        @keyup.enter="createNewDir"
        @keyup.escape="showNewDirInput = false"
        placeholder="文件夹名称"
        class="flex-1 px-3 py-1.5 text-sm rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-700 text-gray-900 dark:text-white focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        ref="dirInput"
      />
      <button @click="createNewDir" class="px-3 py-1.5 text-xs font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700">创建</button>
      <button @click="showNewDirInput = false" class="px-3 py-1.5 text-xs rounded-lg border border-gray-200 dark:border-gray-600 text-gray-600 dark:text-gray-400">取消</button>
    </div>

    <!-- 拖拽上传区域 + 文件列表 -->
    <div
      class="relative"
      @dragenter.prevent="onDragEnter"
      @dragover.prevent="onDragOver"
      @dragleave.prevent="onDragLeave"
      @drop.prevent="onDrop"
    >
      <!-- 拖拽遮罩层 -->
      <Transition name="fade">
        <div
          v-if="dragover"
          class="absolute inset-0 z-10 bg-blue-500/10 dark:bg-blue-400/10 border-2 border-dashed border-blue-500 rounded-lg flex items-center justify-center pointer-events-none"
        >
          <div class="text-center">
            <svg class="w-10 h-10 mx-auto text-blue-500 mb-2" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12"/>
            </svg>
            <p class="text-sm font-medium text-blue-600 dark:text-blue-400">释放文件以上传</p>
            <p class="text-xs text-blue-400 mt-1">支持文件和文件夹</p>
          </div>
        </div>
      </Transition>

      <!-- 上传进度条 -->
      <div v-if="uploading" class="px-4 py-2">
        <div class="flex items-center gap-3">
          <div class="flex-1 h-1.5 bg-gray-200 dark:bg-gray-700 rounded-full overflow-hidden">
            <div class="h-full bg-blue-500 rounded-full transition-all duration-300" :style="{ width: uploadProgress + '%' }"></div>
          </div>
          <span class="text-xs text-gray-400 whitespace-nowrap">{{ uploadProgress }}%</span>
        </div>
      </div>

      <div class="divide-y divide-gray-50 dark:divide-gray-700/50">
        <!-- 返回上级 -->
        <div
          v-if="currentPath"
          @click="goUp"
          class="flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors"
        >
          <svg class="w-5 h-5 text-gray-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M10 19l-7-7m0 0l7-7m-7 7h18"/>
          </svg>
          <span class="text-sm text-gray-500 dark:text-gray-400">..</span>
        </div>

        <!-- 文件/目录条目 -->
        <div
          v-for="entry in files"
          :key="entry.path"
          class="flex items-center justify-between px-4 py-2.5 hover:bg-gray-50 dark:hover:bg-gray-700/50 transition-colors group"
        >
          <div
            @click="entry.is_dir ? navigateTo(entry.path) : openFileEditor(entry)"
            class="flex items-center gap-3 min-w-0 flex-1 cursor-pointer"
          >
            <svg v-if="entry.is_dir" class="w-5 h-5 text-yellow-500 flex-shrink-0" fill="currentColor" viewBox="0 0 24 24">
              <path d="M10 4H4c-1.1 0-2 .9-2 2v12c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V8c0-1.1-.9-2-2-2h-8l-2-2z"/>
            </svg>
            <svg v-else class="w-5 h-5 text-gray-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"/>
            </svg>
            <span class="text-sm text-gray-700 dark:text-gray-300 truncate">{{ entry.name }}</span>
          </div>

          <span v-if="!entry.is_dir" class="text-xs text-gray-400 dark:text-gray-500 mx-3 hidden sm:inline">
            {{ formatSize(entry.size) }}
          </span>

          <!-- requirements.txt 一键安装按钮 -->
          <button
            v-if="!entry.is_dir && entry.name.toLowerCase() === 'requirements.txt'"
            @click.stop="installReqs"
            :disabled="installingReqs"
            class="text-xs text-green-600 dark:text-green-400 hover:text-green-700 dark:hover:text-green-300 mr-2 opacity-0 group-hover:opacity-100 transition-all"
            title="一键安装依赖"
          >
            {{ installingReqs ? '安装中...' : '安装依赖' }}
          </button>

          <button
            @click.stop="handleDelete(entry)"
            class="p-1 rounded text-gray-400 hover:text-red-500 opacity-0 group-hover:opacity-100 transition-all"
            title="删除"
          >
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
            </svg>
          </button>
        </div>

        <!-- 空状态 -->
        <div v-if="!loading && files.length === 0" class="px-4 py-12 text-center">
          <svg class="w-12 h-12 mx-auto text-gray-300 dark:text-gray-600 mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" d="M5 19a2 2 0 01-2-2V7a2 2 0 012-2h4l2 2h4a2 2 0 012 2v1M5 19h14a2 2 0 002-2v-5a2 2 0 00-2-2H9a2 2 0 00-2 2v5a2 2 0 01-2 2z"/>
          </svg>
          <p class="text-sm text-gray-400 dark:text-gray-500">此目录为空</p>
          <p class="text-xs text-gray-400 dark:text-gray-500 mt-1">拖拽文件到此处即可上传</p>
        </div>
      </div>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="px-4 py-12 text-center">
      <div class="inline-block w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin"></div>
    </div>

    <!-- requirements.txt 检测弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showRequirementsDialog"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="showRequirementsDialog = false"
        >
          <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-6 w-full max-w-md mx-4 border border-gray-200 dark:border-gray-700">
            <div class="flex items-center justify-center w-12 h-12 mx-auto rounded-full bg-blue-100 dark:bg-blue-900/50 mb-4">
              <svg class="w-6 h-6 text-blue-600 dark:text-blue-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                  d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
            </div>
            <h3 class="text-lg font-semibold text-gray-900 dark:text-white text-center mb-2">
              检测到依赖文件
            </h3>
            <p class="text-sm text-gray-500 dark:text-gray-400 text-center mb-6">
              上传的文件中包含 <code class="px-1.5 py-0.5 rounded bg-gray-100 dark:bg-gray-700 text-blue-600 dark:text-blue-400 font-mono text-xs">requirements.txt</code>，是否立即安装依赖？
            </p>
            <div class="flex gap-3">
              <button
                @click="showRequirementsDialog = false"
                class="flex-1 px-4 py-2.5 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
              >
                稍后再说
              </button>
              <button
                @click="confirmInstallRequirements"
                :disabled="installingDeps"
                class="flex-1 px-4 py-2.5 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {{ installingDeps ? '安装中...' : '立即安装' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>

    <!-- 文件编辑弹窗 -->
    <Teleport to="body">
      <Transition name="modal">
        <div
          v-if="showEditor"
          class="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm"
          @click.self="closeEditor"
        >
          <div class="bg-white dark:bg-gray-800 rounded-2xl shadow-2xl p-6 w-full max-w-3xl mx-4 border border-gray-200 dark:border-gray-700 flex flex-col max-h-[85vh]">
            <div class="flex items-center justify-between mb-4">
              <h3 class="text-sm font-semibold text-gray-900 dark:text-white font-mono truncate flex-1 mr-4">
                {{ editingFile?.name }}
              </h3>
              <button @click="closeEditor" class="p-1 rounded text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">
                <svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/></svg>
              </button>
            </div>
            <textarea
              v-model="editorContent"
              class="flex-1 min-h-[400px] p-4 text-xs font-mono rounded-lg border border-gray-200 dark:border-gray-600 bg-gray-50 dark:bg-gray-900 text-gray-800 dark:text-gray-200 focus:ring-2 focus:ring-blue-500 outline-none resize-none"
              :placeholder="editorLoading ? '加载中...' : ''"
              spellcheck="false"
            ></textarea>
            <div class="flex gap-3 mt-4">
              <button @click="closeEditor" class="flex-1 px-4 py-2 text-sm font-medium rounded-lg border border-gray-200 dark:border-gray-600 text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors">取消</button>
              <button @click="saveFile" :disabled="savingFile" class="flex-1 px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors">
                {{ savingFile ? '保存中...' : '保存' }}
              </button>
            </div>
          </div>
        </div>
      </Transition>
    </Teleport>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, inject } from 'vue'
import { listFiles, uploadFiles, deleteFile, createDir, installRequirements, readFile, writeFile } from '../api/index.js'

const props = defineProps({
  projectId: { type: Number, required: true },
})

const refresh = inject('refresh', () => {})

const currentPath = ref('')
const files = ref([])
const loading = ref(false)
const uploading = ref(false)
const uploadProgress = ref(0)
const dragover = ref(false)
const showNewDirInput = ref(false)
const newDirName = ref('')
const dirInput = ref(null)
const fileInput = ref(null)

const showRequirementsDialog = ref(false)
const installingDeps = ref(false)
const installingReqs = ref(false)

// 文件编辑器
const showEditor = ref(false)
const editingFile = ref(null)
const editorContent = ref('')
const editorLoading = ref(false)
const savingFile = ref(false)

// 拖拽计数器（防止子元素触发 dragleave）
let dragCounter = 0

const breadcrumbs = computed(() => {
  if (!currentPath.value) return []
  const parts = currentPath.value.split('/').filter(Boolean)
  return parts.map((name, idx) => ({
    name,
    path: parts.slice(0, idx + 1).join('/'),
  }))
})

async function fetchFiles() {
  loading.value = true
  try {
    const res = await listFiles(props.projectId, currentPath.value)
    files.value = res.data.files
  } catch (err) {
    console.error('获取文件列表失败:', err)
  } finally {
    loading.value = false
  }
}

function navigateTo(path) {
  currentPath.value = path
}

function goUp() {
  const parts = currentPath.value.split('/').filter(Boolean)
  parts.pop()
  currentPath.value = parts.join('/')
}

function onDragEnter() {
  dragCounter++
  dragover.value = true
}

function onDragOver() {
  dragover.value = true
}

function onDragLeave() {
  dragCounter--
  if (dragCounter <= 0) {
    dragCounter = 0
    dragover.value = false
  }
}

async function onDrop(e) {
  dragover.value = false
  dragCounter = 0

  const items = e.dataTransfer?.items
  if (!items) return

  const fileList = []
  await traverseFileTree(items, fileList)

  if (fileList.length > 0) {
    await doUpload(fileList)
  }
}

async function traverseFileTree(items, fileList) {
  for (const item of items) {
    if (item.kind === 'file') {
      const file = item.getAsFile()
      if (file) {
        // 保留相对路径信息用于文件夹上传
        if (item.webkitGetAsEntry && item.webkitGetAsEntry().isFile) {
          const entry = item.webkitGetAsEntry()
          // 拼接完整相对路径
          if (entry.fullPath) {
            Object.defineProperty(file, '_webkit_relative_path', {
              value: entry.fullPath.replace(/^\//, ''),
              writable: false,
            })
          }
        }
        fileList.push(file)
      }
    } else if (item.kind === 'directory' || (item.webkitGetAsEntry && item.webkitGetAsEntry().isDirectory)) {
      const entry = item.webkitGetAsEntry()
      if (entry) {
        await readDirectoryEntries(entry, fileList)
      }
    }
  }
}

function readDirectoryEntries(dirEntry, fileList) {
  return new Promise((resolve) => {
    const reader = dirEntry.createReader()
    const readBatch = () => {
      reader.readEntries(async (entries) => {
        if (entries.length === 0) {
          resolve()
          return
        }
        for (const entry of entries) {
          if (entry.isFile) {
            const file = await new Promise((res) => entry.file(res))
            Object.defineProperty(file, '_webkit_relative_path', {
              value: entry.fullPath.replace(/^\//, ''),
              writable: false,
            })
            fileList.push(file)
          } else if (entry.isDirectory) {
            await readDirectoryEntries(entry, fileList)
          }
        }
        readBatch()
      })
    }
    readBatch()
  })
}

function onFileInputChange(e) {
  const fileList = Array.from(e.target.files || [])
  if (fileList.length > 0) {
    doUpload(fileList)
    e.target.value = ''
  }
}

async function doUpload(fileList) {
  if (fileList.length === 0) return

  uploading.value = true
  uploadProgress.value = 0

  try {
    const res = await uploadFiles(props.projectId, fileList, currentPath.value, (progressEvent) => {
      if (progressEvent.total) {
        uploadProgress.value = Math.round((progressEvent.loaded * 100) / progressEvent.total)
      }
    })

    if (res.data.has_requirements) {
      showRequirementsDialog.value = true
    }

    await fetchFiles()
    refresh()
  } catch (err) {
    alert(`上传失败: ${err.response?.data?.detail || err.message}`)
  } finally {
    uploading.value = false
    uploadProgress.value = 0
    if (fileInput.value) fileInput.value.value = ''
  }
}

async function installReqs() {
  installingReqs.value = true
  try {
    const res = await installRequirements(props.projectId)
    if (res.data.success) alert('依赖安装成功')
    else alert('依赖安装失败，请查看运行日志')
  } catch (err) {
    alert(`安装失败: ${err.response?.data?.detail || err.message}`)
  } finally { installingReqs.value = false }
}

async function confirmInstallRequirements() {
  installingDeps.value = true
  try {
    const res = await installRequirements(props.projectId)
    if (res.data.success) {
      showRequirementsDialog.value = false
    } else {
      alert('依赖安装失败，请查看终端日志')
    }
  } catch (err) {
    alert(`安装失败: ${err.response?.data?.detail || err.message}`)
  } finally {
    installingDeps.value = false
    refresh()
  }
}

async function handleDelete(entry) {
  if (!confirm(`确定删除「${entry.name}」?`)) return
  try {
    await deleteFile(props.projectId, entry.path)
    await fetchFiles()
    refresh()
  } catch (err) {
    alert(`删除失败: ${err.response?.data?.detail || err.message}`)
  }
}

async function createNewDir() {
  const name = newDirName.value.trim()
  if (!name) return
  try {
    await createDir(props.projectId, name, currentPath.value)
    newDirName.value = ''
    showNewDirInput.value = false
    await fetchFiles()
    refresh()
  } catch (err) {
    alert(`创建失败: ${err.response?.data?.detail || err.message}`)
  }
}

async function openFileEditor(entry) {
  if (entry.is_dir) return
  editingFile.value = entry
  editorContent.value = ''
  editorLoading.value = true
  showEditor.value = true
  try {
    const res = await readFile(props.projectId, entry.path)
    editorContent.value = res.data.content
  } catch (err) {
    if (err.response?.status === 400) {
      alert('无法编辑此类型文件（可能是二进制文件）')
      showEditor.value = false
    } else {
      alert(`读取文件失败: ${err.response?.data?.detail || err.message}`)
    }
  } finally {
    editorLoading.value = false
  }
}

function closeEditor() {
  showEditor.value = false
  editingFile.value = null
  editorContent.value = ''
}

async function saveFile() {
  if (!editingFile.value) return
  savingFile.value = true
  try {
    await writeFile(props.projectId, editingFile.value.path, editorContent.value)
    closeEditor()
    await fetchFiles()
    refresh()
  } catch (err) {
    alert(`保存失败: ${err.response?.data?.detail || err.message}`)
  } finally {
    savingFile.value = false
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

watch(currentPath, fetchFiles)
fetchFiles()

watch(showNewDirInput, async (val) => {
  if (val) {
    await nextTick()
    dirInput.value?.focus()
  }
})
</script>

<style scoped>
.fade-enter-active, .fade-leave-active {
  transition: opacity 0.2s ease;
}
.fade-enter-from, .fade-leave-to {
  opacity: 0;
}

.modal-enter-active, .modal-leave-active {
  transition: opacity 0.25s ease;
}
.modal-enter-active > div, .modal-leave-active > div {
  transition: transform 0.25s ease;
}
.modal-enter-from, .modal-leave-to {
  opacity: 0;
}
.modal-enter-from > div {
  transform: scale(0.95) translateY(10px);
}
.modal-leave-to > div {
  transform: scale(0.95) translateY(10px);
}
</style>
