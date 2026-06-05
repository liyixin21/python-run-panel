<template>
  <div class="bg-white dark:bg-gray-800 rounded-xl border border-gray-200 dark:border-gray-700 overflow-hidden flex flex-col">
    <!-- 终端头部（与运行日志等卡片头部风格一致） -->
    <div class="flex items-center justify-between px-4 py-3 border-b border-gray-100 dark:border-gray-700">
      <h3 class="text-sm font-semibold text-gray-900 dark:text-white">
        终端
        <span v-if="connected" class="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-green-400" title="已连接"></span>
        <span v-if="connecting" class="ml-2 inline-block w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" title="连接中"></span>
      </h3>
      <div class="flex items-center gap-2">
        <span class="text-xs font-mono text-gray-400">{{ projectName }}</span>
        <button
          v-if="!connected && !connecting"
          @click="initTerminal"
          class="text-xs text-blue-600 dark:text-blue-400 hover:underline"
        >
          重连
        </button>
        <button @click="$emit('close')" class="text-xs text-gray-400 hover:text-gray-600 dark:hover:text-gray-300">关闭</button>
      </div>
    </div>

    <!-- xterm.js 终端容器（暗色内部） -->
    <div ref="terminalContainer" class="h-80 bg-gray-900 relative overflow-hidden rounded-b-xl">
      <div v-if="connecting" class="absolute inset-0 flex items-center justify-center bg-gray-900 z-10 rounded-b-xl">
        <div class="text-center">
          <div class="inline-block w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mb-2"></div>
          <p class="text-xs text-gray-400">正在连接终端...</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { Terminal } from '@xterm/xterm'
import { FitAddon } from '@xterm/addon-fit'
import { WebLinksAddon } from '@xterm/addon-web-links'
import '@xterm/xterm/css/xterm.css'

const props = defineProps({
  projectId: { type: Number, required: true },
  projectName: { type: String, required: true },
})

const emit = defineEmits(['close'])

const terminalContainer = ref(null)
const connected = ref(false)
const connecting = ref(false)

let terminal = null
let fitAddon = null
let ws = null
let resizeObserver = null

async function initTerminal() {
  if (terminal) {
    terminal.dispose()
  }

  connecting.value = true

  terminal = new Terminal({
    cursorBlink: true,
    cursorStyle: 'bar',
    fontSize: 13,
    fontFamily: 'Menlo, Monaco, "Courier New", monospace',
    theme: {
      background: '#1a1b26',
      foreground: '#c0caf5',
      cursor: '#c0caf5',
      selectionBackground: '#364a82',
    },
    allowProposedApi: true,
  })

  fitAddon = new FitAddon()
  terminal.loadAddon(fitAddon)
  terminal.loadAddon(new WebLinksAddon())

  await nextTick()
  terminal.open(terminalContainer.value)
  fitAddon.fit()

  resizeObserver = new ResizeObserver(() => {
    fitAddon.fit()
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
    }
  })
  resizeObserver.observe(terminalContainer.value)

  connectWebSocket()
}

function connectWebSocket() {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${window.location.host}/ws/terminal/${props.projectId}`

  ws = new WebSocket(wsUrl)
  ws.binaryType = 'arraybuffer'

  ws.onopen = () => {
    connected.value = true
    connecting.value = false
    ws.send(JSON.stringify({ type: 'resize', cols: terminal.cols, rows: terminal.rows }))
  }

  ws.onmessage = (event) => {
    if (!terminal) return
    if (event.data instanceof ArrayBuffer) {
      terminal.write(new Uint8Array(event.data))
    } else if (typeof event.data === 'string') {
      terminal.write(event.data)
    }
  }

  ws.onclose = () => {
    connected.value = false
    connecting.value = false
    if (terminal) terminal.write('\r\n\x1b[31m[连接已断开]\x1b[0m\r\n')
  }

  ws.onerror = () => {
    connecting.value = false
    connected.value = false
    if (terminal) terminal.write('\r\n\x1b[31m[连接失败]\x1b[0m\r\n')
  }

  terminal.onData((data) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify({ type: 'input', data }))
    }
  })
}

function closeTerminal() {
  if (ws) { ws.close(); ws = null }
  if (resizeObserver) { resizeObserver.disconnect(); resizeObserver = null }
  if (terminal) { terminal.dispose(); terminal = null }
  connected.value = false
}

onMounted(async () => { await initTerminal() })
onBeforeUnmount(() => { closeTerminal() })
</script>
