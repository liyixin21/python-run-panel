/**
 * 拖拽上传 composable
 *
 * 从 FileManager.vue 中抽离出的核心难点：DataTransferItemList 是
 * 与拖拽事件生命周期绑定的实时集合，一旦在 await 后让出事件循环，
 * 浏览器可能清理 DataTransfer，导致后续 webkitGetAsEntry() 返回 null。
 *
 * 因此必须在任何 await 之前同步提取全部 FileSystemEntry，存入普通数组，
 * 断开对实时集合的依赖，之后才能安全地异步遍历目录树。
 */
import { ref } from 'vue'

export function useDragUpload({ onFiles }) {
  const dragover = ref(false)
  let dragCounter = 0

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

    // 阶段 1（同步）：把所有条目从实时集合中提取出来
    const rootEntries = []
    for (let i = 0; i < items.length; i++) {
      const item = items[i]
      if (!item || item.kind !== 'file') continue

      const getEntry = item.webkitGetAsEntry || item.getAsEntry
      const entry = getEntry ? getEntry.call(item) : null

      if (entry) {
        rootEntries.push(entry)
      } else {
        const file = item.getAsFile()
        if (file) rootEntries.push(file)
      }
    }

    // 阶段 2（异步）：此时已脱离 DataTransferItemList，可安全 await
    const fileList = []
    await processEntries(rootEntries, fileList)

    if (fileList.length > 0) {
      await onFiles(fileList)
    }
  }

  /** 处理根级条目列表（FileSystemEntry 或 File 的混合数组） */
  async function processEntries(entries, fileList) {
    for (const entry of entries) {
      if (entry instanceof File) {
        fileList.push(entry)
        continue
      }
      if (entry.isDirectory) {
        await readDirectoryEntries(entry, fileList)
      } else if (entry.isFile) {
        try {
          const file = await new Promise((resolve, reject) => entry.file(resolve, reject))
          if (file && entry.fullPath) {
            Object.defineProperty(file, '_webkit_relative_path', {
              value: entry.fullPath.replace(/^\//, ''),
              writable: false,
            })
          }
          if (file) fileList.push(file)
        } catch (err) {
          console.warn('读取文件条目失败:', err)
        }
      }
    }
  }

  /**
   * 递归读取目录。
   * 分两步：先用同步回调收集全部 FileSystemEntry，再异步读取内容。
   * readEntries 会忽略回调的 Promise 返回值，在回调里直接 await
   * 可能导致批次错乱或条目丢失。
   */
  function readDirectoryEntries(dirEntry, fileList) {
    return new Promise((resolve, reject) => {
      const reader = dirEntry.createReader()
      const allEntries = []

      const readBatch = () => {
        reader.readEntries((entries) => {
          if (entries.length === 0) {
            processDirectoryEntries(allEntries, fileList).then(resolve).catch(reject)
            return
          }
          allEntries.push(...entries)
          readBatch()
        }, reject)
      }
      readBatch()
    })
  }

  async function processDirectoryEntries(entries, fileList) {
    for (const entry of entries) {
      if (entry.isFile) {
        try {
          const file = await new Promise((res, rej) => entry.file(res, rej))
          if (file && entry.fullPath) {
            Object.defineProperty(file, '_webkit_relative_path', {
              value: entry.fullPath.replace(/^\//, ''),
              writable: false,
            })
          }
          if (file) fileList.push(file)
        } catch (err) {
          console.warn('读取文件失败:', err)
        }
      } else if (entry.isDirectory) {
        await readDirectoryEntries(entry, fileList)
      }
    }
  }

  return { dragover, onDragEnter, onDragOver, onDragLeave, onDrop }
}
