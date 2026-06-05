import axios from 'axios'

const api = axios.create({ baseURL: '/', timeout: 30000 })

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

export function installRequirements(projectId) { return api.post(`/api/packages/${projectId}/install-requirements`) }
export function installPackage(projectId, packageName) { return api.post(`/api/packages/${projectId}/install`, { package_name: packageName }) }
export function uninstallPackage(projectId, packageName) { return api.post(`/api/packages/${projectId}/uninstall`, { package_name: packageName }) }
export function getInstalledPackages(projectId) { return api.get(`/api/packages/${projectId}/installed`) }

export default api
