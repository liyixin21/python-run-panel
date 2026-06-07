import axios from 'axios'

const api = axios.create({ baseURL: '/', timeout: 30000 })

// 请求拦截器：自动附加认证 token
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('auth_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// 响应拦截器：401 时跳转登录页
api.interceptors.response.use(
  (res) => res,
  (err) => {
    if (err.response?.status === 401) {
      localStorage.removeItem('auth_token')
      window.location.href = '/login'
    }
    return Promise.reject(err)
  }
)

export function listProjects() { return api.get('/api/projects/') }
export function createProject(data) { return api.post('/api/projects/', data) }
export function getProject(name) { return api.get(`/api/projects/${encodeURIComponent(name)}`) }
export function updateProject(name, data) { return api.put(`/api/projects/${encodeURIComponent(name)}`, data) }
export function deleteProject(name) { return api.delete(`/api/projects/${encodeURIComponent(name)}`) }

export function getSchedules(projectId) { return api.get(`/api/projects/${projectId}/schedules`) }
export function setSchedules(projectId, data) { return api.post(`/api/projects/${projectId}/schedules`, data) }

export function startProcess(id, data) { return api.post(`/api/processes/${id}/start`, data || {}) }
export function stopProcess(id, force = false) { return api.post(`/api/processes/${id}/stop`, null, { params: { force } }) }
export function restartProcess(id, data) { return api.post(`/api/processes/${id}/restart`, data || {}) }
export function getProcessStatus(id) { return api.get(`/api/processes/${id}/status`) }
export function getProcessLogs(id) { return api.get(`/api/processes/${id}/logs`) }
export function clearProcessLogs(id) { return api.delete(`/api/processes/${id}/logs`) }

export function listFiles(projectId, subPath = '') { return api.get(`/api/files/${projectId}/list`, { params: { sub_path: subPath } }) }

export function uploadFiles(projectId, fileList, subPath = '', onProgress) {
  const form = new FormData()
  for (const file of fileList) {
    const relPath = file._webkit_relative_path || file.webkitRelativePath || file.name
    form.append('files', file, relPath)
  }
  return api.post(`/api/files/${projectId}/upload`, form, {
    params: { sub_path: subPath },
    headers: { 'Content-Type': 'multipart/form-data' },
    onUploadProgress: onProgress,
    timeout: 300000,
  })
}

export function createDir(projectId, dirName, subPath = '') {
  return api.post(`/api/files/${projectId}/mkdir`, null, { params: { dir_name: dirName, sub_path: subPath } })
}

export function deleteFile(projectId, filePath) {
  return api.delete(`/api/files/${projectId}/delete`, { params: { file_path: filePath } })
}

export function readFile(projectId, filePath) {
  return api.get(`/api/files/${projectId}/read`, { params: { file_path: filePath } })
}

export function writeFile(projectId, filePath, content) {
  return api.put(`/api/files/${projectId}/write`, content, {
    params: { file_path: filePath }, headers: { 'Content-Type': 'text/plain' },
  })
}

export function installRequirements(projectId, onOutput, signal) {
  return streamPost(`/api/packages/${projectId}/install-requirements`, {}, onOutput, signal)
}
export function installPackage(projectId, packageName, onOutput, signal) {
  return streamPost(`/api/packages/${projectId}/install`, { package_name: packageName }, onOutput, signal)
}
export function uninstallPackage(projectId, packageName) { return api.post(`/api/packages/${projectId}/uninstall`, { package_name: packageName }) }
export function getInstalledPackages(projectId) { return api.get(`/api/packages/${projectId}/installed`) }

// 流式 POST 请求，支持 SSE 实时输出与取消
async function streamPost(url, data, onOutput, signal) {
  const headers = { 'Content-Type': 'application/json' }
  const token = localStorage.getItem('auth_token')
  if (token) headers.Authorization = `Bearer ${token}`

  const response = await fetch(url, {
    method: 'POST',
    headers,
    body: JSON.stringify(data),
    signal,  // 支持 AbortController 取消
  })

  if (!response.ok) {
    const errData = await response.json().catch(() => ({}))
    throw { response: { status: response.status, data: errData } }
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() // 保留不完整的行

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const payload = JSON.parse(line.slice(6))
        if (payload.type === 'output' && onOutput) {
          onOutput(payload.line)
        } else if (payload.type === 'done') {
          result = payload
        }
      } catch (e) { /* ignore parse errors */ }
    }
  }

  // 处理 buffer 中最后的数据
  if (buffer.startsWith('data: ')) {
    try {
      const payload = JSON.parse(buffer.slice(6))
      if (payload.type === 'done') result = payload
    } catch (e) { /* ignore */ }
  }

  return { data: result || { success: false, stderr: '未收到完成信号' } }
}

export default api
