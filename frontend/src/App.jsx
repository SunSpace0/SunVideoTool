import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const TABS = ['任务', '下载库', '输出库', '设置']
const OUTPUT_MODES = ['纯人声MP3', '纯伴奏MP3', '带人声原视频MP4', '带伴奏原视频MP4']

const fileUrl = (path) => `/api${path}`

function useAsyncData(loader, deps = []) {
  const [data, setData] = useState([])
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    try {
      setData(await loader())
      setError('')
    } catch (exc) {
      setError(exc.message)
    }
  }, deps)

  useEffect(() => {
    load()
  }, [load])

  return { data, error, load, setData }
}

function TaskPanel({ job, videos, outputs, onRefresh, onDownload, onSeparate, error }) {
  const [url, setUrl] = useState('')
  const [video, setVideo] = useState('')
  const [outputMode, setOutputMode] = useState(OUTPUT_MODES[0])
  const busy = job.status === 'running'

  useEffect(() => {
    if (!video && videos.length > 0) setVideo(videos[0].filename)
  }, [videos, video])

  return (
    <div className="panel">
      <div className="card">
        <label>视频链接</label>
        <input value={url} onChange={(event) => setUrl(event.target.value)} placeholder="粘贴 B 站或抖音链接" />
        <button className="action" disabled={busy} onClick={() => onDownload(url)}>下载视频</button>

        <label>本地视频</label>
        <select value={video} onChange={(event) => setVideo(event.target.value)}>
          {videos.map((item) => (
            <option key={item.filename} value={item.filename}>{item.title || item.filename}</option>
          ))}
        </select>

        <label>输出模式</label>
        <select value={outputMode} onChange={(event) => setOutputMode(event.target.value)}>
          {OUTPUT_MODES.map((mode) => <option key={mode}>{mode}</option>)}
        </select>

        <button className="action" disabled={busy || !video} onClick={() => onSeparate(video, outputMode)}>开始分离</button>
        <div>
          <small>下载记录：{videos.length} 条 · 输出任务：{outputs.length} 条</small>
        </div>
      </div>

      <div className="card">
        <label>任务状态</label>
        <div>状态：{busy ? '运行中' : job.status === 'completed' ? '已完成' : job.status === 'failed' ? '失败' : '空闲'}</div>
        {job.task_id && <div>成品：<a href={fileUrl(`/files/output/${job.task_id}`)}>打开文件</a></div>}
        {error && <div style={{ color: '#dc2626' }}>{error}</div>}
        <label>日志</label>
        <pre className="log">{job.logs.join('\n') || '等待任务开始'}</pre>
      </div>
    </div>
  )
}

function VideosPanel({ videos, selected, onSelect, onDelete, onClear, onRefresh }) {
  return (
    <div className="card">
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <button className="action" onClick={onRefresh}>刷新</button>
        <button className="action danger" disabled={!selected} onClick={() => selected && onDelete(selected.filename)}>删除选中</button>
        <button className="action secondary" onClick={onClear}>清空下载历史</button>
      </div>
      <div className="panel">
        <table>
          <thead>
            <tr><th>标题</th><th>作者</th><th>下载时间</th></tr>
          </thead>
          <tbody>
            {videos.map((item) => (
              <tr key={item.filename} className={selected?.filename === item.filename ? 'selected' : ''} onClick={() => onSelect(item)}>
                <td>{item.title || item.filename}</td>
                <td>{item.uploader || '-'}</td>
                <td>{item.created_at || '-'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="preview">
          {selected?.thumbnail_path && <img src={fileUrl(`/files/thumbnail/${encodeURIComponent(selected.filename)}`)} alt="封面" />}
          {selected && <video src={fileUrl(`/files/video/${encodeURIComponent(selected.filename)}`)} controls />}
        </div>
      </div>
    </div>
  )
}

function OutputsPanel({ outputs, selected, onSelect }) {
  return (
    <div className="card">
      <div className="panel">
        <table>
          <thead>
            <tr><th>任务目录</th><th>源视频</th><th>模式</th><th>状态</th></tr>
          </thead>
          <tbody>
            {outputs.map((item) => (
              <tr key={item.task_id} className={selected?.task_id === item.task_id ? 'selected' : ''} onClick={() => onSelect(item)}>
                <td>{item.task_id}</td>
                <td>{item.source_video}</td>
                <td>{item.output_mode}</td>
                <td>{item.status}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <div className="preview">
          {selected?.preview_path && <img src={fileUrl(`/files/output-thumbnail/${selected.task_id}`)} alt="预览" />}
          {selected?.final_output_path?.endsWith('.mp4') && (
            <video src={fileUrl(`/files/output/${selected.task_id}`)} controls />
          )}
          {selected?.final_output_path?.endsWith('.mp3') && (
            <audio src={fileUrl(`/files/output/${selected.task_id}`)} controls />
          )}
        </div>
      </div>
    </div>
  )
}

function SettingsPanel({ config, onSave, message }) {
  const [form, setForm] = useState({
    host: '127.0.0.1',
    port: 7860,
    backend: 'auto',
    modelFile: '',
    cookiesFromBrowser: '',
    cookieHeader: '',
    provider: '',
    apiBase: '',
    apiKey: '',
    model: '',
  })

  useEffect(() => {
    setForm({
      host: config.runtime?.host || '127.0.0.1',
      port: config.runtime?.port ?? 7860,
      backend: config.separator?.backend || 'auto',
      modelFile: config.separator?.model_file || '',
      cookiesFromBrowser: config.yt_dlp?.cookiesfrombrowser || '',
      cookieHeader: config.yt_dlp?.cookie_header || '',
      provider: config.llm?.provider || '',
      apiBase: config.llm?.api_base || '',
      apiKey: config.llm?.api_key || '',
      model: config.llm?.model || '',
    })
  }, [config])

  const update = (key) => (event) => setForm((current) => ({ ...current, [key]: event.target.value }))

  const submit = () => onSave({
    runtime: { host: form.host, port: Number(form.port) },
    separator: { backend: form.backend, model_file: form.modelFile },
    yt_dlp: { cookiesfrombrowser: form.cookiesFromBrowser, cookie_header: form.cookieHeader },
    llm: { provider: form.provider, api_base: form.apiBase, api_key: form.apiKey, model: form.model },
  })

  return (
    <div className="panel">
      <div className="card">
        <h3>服务端口</h3>
        <label>监听地址</label>
        <input value={form.host} onChange={update('host')} />
        <label>服务端口（勿使用 5173 / 8000）</label>
        <input type="number" value={form.port} onChange={update('port')} />

        <h3>音轨分离</h3>
        <label>分离后端</label>
        <select value={form.backend} onChange={update('backend')}>
          <option value="auto">auto</option>
          <option value="audio-separator">audio-separator</option>
          <option value="custom">custom</option>
        </select>
        <label>模型文件路径</label>
        <input value={form.modelFile} onChange={update('modelFile')} />

        <h3>下载认证</h3>
        <label>浏览器 Cookie 来源</label>
        <input value={form.cookiesFromBrowser} onChange={update('cookiesFromBrowser')} />
        <label>Cookie 字符串</label>
        <input type="password" value={form.cookieHeader} onChange={update('cookieHeader')} />
      </div>

      <div className="card">
        <h3>大模型（预留）</h3>
        <label>服务商</label>
        <input value={form.provider} onChange={update('provider')} placeholder="openai / ollama，可留空" />
        <label>API Base URL</label>
        <input value={form.apiBase} onChange={update('apiBase')} />
        <label>API Key</label>
        <input type="password" value={form.apiKey} onChange={update('apiKey')} />
        <label>模型名称</label>
        <input value={form.model} onChange={update('model')} />

        <button className="action" onClick={submit}>保存配置</button>
        <div style={{ marginTop: 8 }}>{message}</div>
      </div>
    </div>
  )
}

export default function App() {
  const [tab, setTab] = useState('任务')
  const [job, setJob] = useState({ logs: [], status: 'idle', job_type: 'idle', output_file: null, task_id: null, error: null })
  const [message, setMessage] = useState('')
  const [selectedVideo, setSelectedVideo] = useState(null)
  const [selectedOutput, setSelectedOutput] = useState(null)
  const [taskError, setTaskError] = useState('')
  const videos = useAsyncData(api.videos)
  const outputs = useAsyncData(api.outputs)
  const [config, setConfig] = useState({})

  useEffect(() => {
    api.getConfig().then(setConfig).catch((exc) => setMessage(exc.message))
  }, [])

  const refreshAll = useCallback(() => {
    videos.load()
    outputs.load()
  }, [videos.load, outputs.load])

  useEffect(() => {
    let timer
    const poll = async () => {
      try {
        const current = await api.currentJob()
        setJob(current)
        if (current.status === 'running') {
          timer = window.setTimeout(poll, 1000)
        } else {
          refreshAll()
        }
      } catch (exc) {
        setTaskError(exc.message)
      }
    }
    poll()
    return () => window.clearTimeout(timer)
  }, [refreshAll])

  const startDownload = async (url) => {
    try {
      setTaskError('')
      await api.download(url)
      setJob({ logs: [], status: 'running', job_type: 'download', output_file: null, task_id: null, error: null })
    } catch (exc) {
      setTaskError(exc.message)
    }
  }

  const startSeparate = async (video, outputMode) => {
    try {
      setTaskError('')
      await api.separate(video, outputMode)
      setJob({ logs: [], status: 'running', job_type: 'separate', output_file: null, task_id: null, error: null })
    } catch (exc) {
      setTaskError(exc.message)
    }
  }

  const deleteVideo = async (filename) => {
    try {
      await api.deleteVideo(filename)
      setSelectedVideo(null)
      await refreshAll()
    } catch (exc) {
      setMessage(exc.message)
    }
  }

  const clearVideos = async () => {
    try {
      await api.clearVideos()
      setSelectedVideo(null)
      await refreshAll()
    } catch (exc) {
      setMessage(exc.message)
    }
  }

  const saveConfig = async (payload) => {
    try {
      const result = await api.saveConfig(payload)
      setConfig(result.config)
      setMessage(result.message)
    } catch (exc) {
      setMessage(exc.message)
    }
  }

  return (
    <div className="app">
      <h1>SunVideoTool</h1>
      <div className="tabs">
        {TABS.map((item) => (
          <button key={item} className={tab === item ? 'active' : ''} onClick={() => setTab(item)}>{item}</button>
        ))}
      </div>

      {tab === '任务' && (
        <TaskPanel
          job={job}
          videos={videos.data}
          outputs={outputs.data}
          error={taskError}
          onDownload={startDownload}
          onSeparate={startSeparate}
        />
      )}
      {tab === '下载库' && (
        <VideosPanel
          videos={videos.data}
          selected={selectedVideo}
          onSelect={setSelectedVideo}
          onDelete={deleteVideo}
          onClear={clearVideos}
          onRefresh={refreshAll}
        />
      )}
      {tab === '输出库' && (
        <OutputsPanel outputs={outputs.data} selected={selectedOutput} onSelect={setSelectedOutput} />
      )}
      {tab === '设置' && <SettingsPanel config={config} onSave={saveConfig} message={message} />}
    </div>
  )
}
