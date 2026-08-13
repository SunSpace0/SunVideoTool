const request = async (path, options = {}) => {
  const response = await fetch(path, {
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) },
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
  currentJob: () => request('/api/jobs/current'),
  download: (url) => request('/api/download', { method: 'POST', body: JSON.stringify({ url }) }),
  separate: (video, outputMode) =>
    request('/api/separate', { method: 'POST', body: JSON.stringify({ video, output_mode: outputMode }) }),
  videos: () => request('/api/videos'),
  outputs: () => request('/api/outputs'),
  deleteVideo: (filename) =>
    request(`/api/videos/${encodeURIComponent(filename)}`, { method: 'DELETE' }),
  clearVideos: () => request('/api/videos', { method: 'DELETE' }),
  getConfig: () => request('/api/config'),
  saveConfig: (payload) =>
    request('/api/config', { method: 'PUT', body: JSON.stringify(payload) }),
}
