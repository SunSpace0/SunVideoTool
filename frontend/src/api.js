const request = async (path, options = {}) => {
  const isFormData = options.body instanceof FormData
  const headers = isFormData
    ? { ...(options.headers || {}) }
    : { 'Content-Type': 'application/json', ...(options.headers || {}) }
  const response = await fetch(path, {
    headers,
    ...options,
  })
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`
    try {
      const body = await response.json()
      detail = body.detail || detail
    } catch {
      // keep status text
    }
    throw new Error(detail)
  }
  return response.json()
}

export const api = {
  health: () => request('/api/health'),
  jobs: () => request('/api/jobs'),
  job: (id) => request(`/api/jobs/${id}`),
  download: (url) => request('/api/download', { method: 'POST', body: JSON.stringify({ url }) }),
  separate: (video, outputMode) =>
    request('/api/separate', { method: 'POST', body: JSON.stringify({ video, output_mode: outputMode }) }),
  pipeline: (url, outputMode) =>
    request('/api/pipeline', { method: 'POST', body: JSON.stringify({ url, output_mode: outputMode }) }),
  videos: () => request('/api/videos'),
  outputs: () => request('/api/outputs'),
  deleteVideo: (filename) =>
    request(`/api/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' }),
  clearVideos: () => request('/api/videos', { method: 'DELETE' }),
  importVideoFile: (file) => {
    const body = new FormData()
    body.append('file', file)
    return request('/api/videos/import', { method: 'POST', body })
  },
  importVideoPath: (path) =>
    request('/api/videos/import-path', { method: 'POST', body: JSON.stringify({ path }) }),
  getConfig: () => request('/api/config'),
  saveConfig: (payload) =>
    request('/api/config', { method: 'PUT', body: JSON.stringify(payload) }),
}
