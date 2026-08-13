import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from './api.js'

const PAGES = [
  { key: 'tasks', label: '任务中心', icon: '⚡' },
  { key: 'videos', label: '下载库', icon: '📥' },
  { key: 'outputs', label: '输出库', icon: '📦' },
  { key: 'settings', label: '设置', icon: '⚙️' },
]

const OUTPUT_MODES = ['纯人声MP3', '纯伴奏MP3', '带人声原视频MP4', '带伴奏原视频MP4']

const fileUrl = (path) => `/api${path}`

const ageSeconds = (iso) => {
  if (!iso) return null
  const value = Date.parse(iso)
  return Number.isFinite(value) ? Math.max(0, Math.floor((Date.now() - value) / 1000)) : null
}

const elapsedSeconds = (started) => {
  const age = ageSeconds(started)
  return age === null ? 0 : age
}

const formatDuration = (seconds) => {
  const minutes = Math.floor(seconds / 60)
  const rest = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(rest).padStart(2, '0')}`
}

const clampProgress = (value) => Math.max(0, Math.min(100, Number(value) || 0))

const inferProgress = (job) => {
  if (job.status === 'completed') return 100
  if (job.status === 'failed') return 100
  if (Number.isFinite(job.progress)) return clampProgress(job.progress)
  const text = (job.logs || []).join('\n')
  const realProgress = text.match(/下载进度\s*(\d+(?:\.\d+)?)%/)
  if (realProgress) return clampProgress(Number(realProgress[1]))
  if (job.job_type === 'download') return 45
  if (text.includes('成品已生成') || text.includes('分离任务已完成')) return 92
  if (text.includes('分离完成:')) return 80
  if (text.includes('开始音轨分离')) return 68
  if (text.includes('分离模型已就绪')) return 50
  if (text.includes('已提取分离音轨')) return 35
  if (text.includes('视频校验通过')) return 18
  return 8
}

function StatusPill({ status }) {
  const label = { running: '运行中', completed: '已完成', failed: '失败' }[status] || status
  return <span className={`status-pill ${status}`}>{label}</span>
}

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

  return { data, error, load }
}

function JobCard({ job }) {
  const running = job.status === 'running'
  const progress = inferProgress(job)
  const lastHeartbeat = ageSeconds(job.last_heartbeat_at)
  const lastLog = ageSeconds(job.last_log_at)
  const heartbeatWarning = running && lastHeartbeat !== null && lastHeartbeat > 12
  const waitingLogs = running && lastLog !== null && lastLog > 8
  const hasRealProgress = Number.isFinite(job.progress) && job.progress > 0

  return (
    <article className={`job-card ${job.status}`}>
      <div className="job-head">
        <div>
          <div className="job-title">
            {job.job_type === 'download'
              ? '视频下载'
              : job.job_type === 'download-separate'
                ? '下载并分离'
                : '音轨分离'}
            <span className="job-id">#{job.id}</span>
          </div>
          <StatusPill status={job.status} />
        </div>
        <div className="job-meta">
          <span>已运行 {formatDuration(elapsedSeconds(job.started_at))}</span>
          {running && (
            <span className={heartbeatWarning ? 'heartbeat warn' : 'heartbeat'}>
              {heartbeatWarning ? '心跳异常' : '保活正常'}
            </span>
          )}
        </div>
      </div>

      <div className="progress-track">
        <div className={`progress-bar ${running && progress < 10 ? 'indeterminate' : ''}`} style={{ width: `${progress}%` }} />
      </div>
      <div className="progress-meta">
        <span>{progress}%</span>
        {hasRealProgress && <span>yt-dlp 实时进度</span>}
        {waitingLogs && <span>当前阶段仍在执行，正在等待更多日志…</span>}
      </div>

      {job.status === 'failed' && (
        <div className="job-error">任务失败：{job.error || '请查看下方日志'}</div>
      )}
      {job.task_id && <div className="job-result"><a href={fileUrl(`/files/output/${job.task_id}`)}>查看成品</a></div>}
      <pre className="job-log">{job.logs.length ? job.logs.join('\n') : '任务已提交，等待开始…'}</pre>
    </article>
  )
}

function EmptyJobs() {
  return <div className="empty-state">暂无任务，下载或分离任务会显示在这里。</div>
}

function detectBrowser() {
  const ua = navigator.userAgent || ''
  if (/QQBrowser|MQQBrowser|QQBrowserHD|TencentTraveler|QBWebViewType/i.test(ua)) {
    return { key: 'qq', name: 'QQ浏览器', supported: false, message: 'QQ浏览器不能自动读取浏览器 Cookie，B 站等会员/登录内容可能无法下载。建议改用 Chrome、Edge 或 Safari，或在“设置”中粘贴 Cookie 字符串。' }
  }
  if (/Edg\//i.test(ua)) return { key: 'edge', name: 'Edge', supported: true, message: '' }
  if (/Firefox\//i.test(ua)) return { key: 'firefox', name: 'Firefox', supported: true, message: '' }
  if (/Chrome\//i.test(ua) && !/CriOS/i.test(ua)) return { key: 'chrome', name: 'Chrome', supported: true, message: '' }
  if (/Safari\//i.test(ua)) return { key: 'safari', name: 'Safari', supported: true, message: '' }
  return { key: 'unknown', name: '未知浏览器', supported: true, message: '未识别当前浏览器，如果下载需要登录 Cookie，请优先使用 Chrome、Edge 或 Safari。' }
}

function DownloadPanel({ onCreate, disabled }) {
  const [urls, setUrls] = useState('')
  const [browser, setBrowser] = useState(detectBrowser)
  const [qqConfirmed, setQqConfirmed] = useState(false)
  const [separateAfterDownload, setSeparateAfterDownload] = useState(false)
  const [pipelineMode, setPipelineMode] = useState(OUTPUT_MODES[0])
  const unsupported = browser.key === 'qq' && !qqConfirmed
  const canSubmit = !disabled && urls.trim().length > 0 && !unsupported

  const submit = () => {
    const currentBrowser = detectBrowser()
    setBrowser(currentBrowser)
    if (currentBrowser.key === 'qq' && !qqConfirmed) return
    const list = urls.split('\n').map((item) => item.trim()).filter(Boolean)
    if (list.length) onCreate(list, separateAfterDownload, pipelineMode)
  }

  return (
    <section className="card">
      <div className="card-title">批量下载</div>
      <p className="muted">每行一个视频链接，任务会并行创建。</p>
      <div className={`browser-bar ${browser.supported ? 'ok' : 'warn'}`}>
        <span>当前浏览器：{browser.name}</span>
        <button className="btn small ghost" onClick={() => setBrowser(detectBrowser())}>重新检测浏览器</button>
      </div>
      {browser.key === 'qq' && (
        <div className="banner warning">
          {browser.message}
          <label className="inline-check">
            <input type="checkbox" checked={qqConfirmed} onChange={(event) => setQqConfirmed(event.target.checked)} />
            我已在“设置”中粘贴 Cookie，或使用不需要登录的视频链接，继续创建下载任务
          </label>
        </div>
      )}
      {browser.key === 'unknown' && <div className="banner warning">{browser.message}</div>}
      <textarea
        rows={5}
        value={urls}
        onChange={(event) => setUrls(event.target.value)}
        placeholder="https://www.bilibili.com/video/BV...&#10;https://www.douyin.com/video/..."
      />
      <label className="inline-check pipeline-check">
        <input
          type="checkbox"
          checked={separateAfterDownload}
          onChange={(event) => setSeparateAfterDownload(event.target.checked)}
        />
        下载完成后立即分离音轨
      </label>
      {separateAfterDownload && (
        <>
          <label>分离输出模式</label>
          <select value={pipelineMode} onChange={(event) => setPipelineMode(event.target.value)}>
            {OUTPUT_MODES.map((item) => <option key={item}>{item}</option>)}
          </select>
        </>
      )}
      <button className="btn primary" disabled={!canSubmit} onClick={submit}>创建下载任务</button>
    </section>
  )
}

function SeparatePanel({ videos, onCreate, onImportFile, onImportPath, importing, importError, onRefresh }) {
  const [video, setVideo] = useState('')
  const [mode, setMode] = useState(OUTPUT_MODES[0])
  const [path, setPath] = useState('')

  useEffect(() => {
    if (!video && videos.length) setVideo(videos[0].filename)
  }, [videos, video])

  const handleFile = async (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    await onImportFile(file)
    event.target.value = ''
  }

  const handlePath = async () => {
    if (!path.trim()) return
    await onImportPath(path.trim())
    setPath('')
  }

  return (
    <section className="card">
      <div className="card-title">开始分离</div>
      <label>本地视频</label>
      <select value={video} onChange={(event) => setVideo(event.target.value)}>
        {!videos.length && <option value="">暂无本地视频，请先导入</option>}
        {videos.map((item) => <option key={item.filename} value={item.filename}>{item.title || item.filename}</option>)}
      </select>
      <div className="import-row">
        <label className="btn small ghost file-picker">
          选择视频文件
          <input type="file" accept="video/*" hidden disabled={importing} onChange={handleFile} />
        </label>
        <input
          value={path}
          onChange={(event) => setPath(event.target.value)}
          placeholder="或输入本地视频绝对路径，如 /Users/you/Movies/a.mp4"
        />
        <button className="btn small ghost" disabled={!path.trim() || importing} onClick={handlePath}>加载地址</button>
        <button className="btn small ghost" onClick={onRefresh}>刷新列表</button>
      </div>
      {importing && <div className="banner info">正在导入本地视频，请稍候…</div>}
      {importError && <div className="banner error">{importError}</div>}
      <label>输出模式</label>
      <select value={mode} onChange={(event) => setMode(event.target.value)}>
        {OUTPUT_MODES.map((item) => <option key={item}>{item}</option>)}
      </select>
      <button className="btn primary" disabled={!video || importing} onClick={() => onCreate(video, mode)}>创建分离任务</button>
    </section>
  )
}

function JobsPanel({ jobs }) {
  const running = jobs.filter((job) => job.status === 'running').length
  const completed = jobs.filter((job) => job.status === 'completed').length
  const failed = jobs.filter((job) => job.status === 'failed').length
  return (
    <section className="jobs-section">
      <div className="section-head">
        <div>
          <h2>任务进度</h2>
          <p className="muted">并行任务中心，多个任务可同时执行。</p>
        </div>
        <div className="job-stats">
          <span className="stat running">运行 {running}</span>
          <span className="stat completed">完成 {completed}</span>
          <span className="stat failed">失败 {failed}</span>
        </div>
      </div>
      {jobs.length ? (
        <div className="jobs-grid">
          {jobs.map((job) => <JobCard key={job.id} job={job} />)}
        </div>
      ) : <EmptyJobs />}
    </section>
  )
}

function VideosPage({ videos, onDelete, onClear, onRefresh }) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>下载历史</h2>
          <p className="muted">{videos.length} 条记录</p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onRefresh}>刷新</button>
          <button className="btn danger" onClick={onClear}>清空全部</button>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th></th><th>标题</th><th>作者</th><th>时长</th><th>下载时间</th><th></th></tr>
          </thead>
          <tbody>
            {videos.map((item) => (
              <tr key={item.filename}>
                <td>
                  {item.thumbnail_path ? (
                    <img className="thumb" src={fileUrl(`/files/thumbnail/${encodeURIComponent(item.filename)}`)} alt="" />
                  ) : <div className="thumb placeholder">🎬</div>}
                </td>
                <td className="title-cell">{item.title || item.filename}</td>
                <td>{item.uploader || '-'}</td>
                <td>{item.duration || '-'}</td>
                <td>{item.created_at || '-'}</td>
                <td>
                  <a className="btn small ghost" href={fileUrl(`/files/video/${encodeURIComponent(item.filename)}`)} target="_blank">播放</a>
                  <button className="btn small danger" onClick={() => onDelete(item.filename)}>删除</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function OutputsPage({ outputs }) {
  return (
    <section className="card">
      <div className="section-head">
        <div>
          <h2>输出历史</h2>
          <p className="muted">{outputs.length} 条任务</p>
        </div>
      </div>
      <div className="table-wrap">
        <table>
          <thead>
            <tr><th></th><th>任务目录</th><th>源视频</th><th>模式</th><th>状态</th><th></th></tr>
          </thead>
          <tbody>
            {outputs.map((item) => (
              <tr key={item.task_id}>
                <td>
                  {item.preview_path ? (
                    <img className="thumb" src={fileUrl(`/files/output-thumbnail/${item.task_id}`)} alt="" />
                  ) : <div className="thumb placeholder">🎵</div>}
                </td>
                <td>{item.task_id}</td>
                <td>{item.source_video}</td>
                <td>{item.output_mode}</td>
                <td><StatusPill status={item.status} /></td>
                <td>
                  {item.final_output_path && (
                    <a className="btn small primary" href={fileUrl(`/files/output/${item.task_id}`)} target="_blank">打开成品</a>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  )
}

function SettingsPage({ config, onSave, message }) {
  const [form, setForm] = useState({
    host: '127.0.0.1',
    port: 18880,
    frontendPort: 18881,
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
      port: config.runtime?.port ?? 18880,
      frontendPort: config.runtime?.frontend_port ?? 18881,
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
  const save = () => onSave({
    runtime: { host: form.host, port: Number(form.port), frontend_port: Number(form.frontendPort) },
    separator: { backend: form.backend, model_file: form.modelFile },
    yt_dlp: { cookiesfrombrowser: form.cookiesFromBrowser, cookie_header: form.cookieHeader },
    llm: { provider: form.provider, api_base: form.apiBase, api_key: form.apiKey, model: form.model },
  })

  return (
    <div className="settings-grid">
      <section className="card">
        <div className="card-title">服务与端口</div>
        <label>监听地址</label>
        <input value={form.host} onChange={update('host')} />
        <label>服务端口（避免 3000 / 5173-5176 / 7860 / 8000 / 8080）</label>
        <input type="number" value={form.port} onChange={update('port')} />
        <label>前端开发端口（避免常见开发端口）</label>
        <input type="number" value={form.frontendPort} onChange={update('frontendPort')} />

        <div className="card-title">音轨分离</div>
        <label>分离后端</label>
        <select value={form.backend} onChange={update('backend')}>
          <option value="auto">auto</option>
          <option value="audio-separator">audio-separator</option>
          <option value="custom">custom</option>
        </select>
        <label>模型文件路径</label>
        <input value={form.modelFile} onChange={update('modelFile')} />

        <div className="card-title">下载认证</div>
        <label>浏览器 Cookie 来源</label>
        <input value={form.cookiesFromBrowser} onChange={update('cookiesFromBrowser')} />
        <label>Cookie 字符串</label>
        <input type="password" value={form.cookieHeader} onChange={update('cookieHeader')} />
      </section>

      <section className="card">
        <div className="card-title">大模型（预留）</div>
        <label>服务商</label>
        <input value={form.provider} onChange={update('provider')} placeholder="openai / ollama" />
        <label>API Base URL</label>
        <input value={form.apiBase} onChange={update('apiBase')} />
        <label>API Key</label>
        <input type="password" value={form.apiKey} onChange={update('apiKey')} />
        <label>模型名称</label>
        <input value={form.model} onChange={update('model')} />
        <button className="btn primary" onClick={save}>保存配置</button>
        <div className="form-message">{message}</div>
      </section>
    </div>
  )
}

export default function App() {
  const [page, setPage] = useState('tasks')
  const [jobs, setJobs] = useState([])
  const [config, setConfig] = useState({})
  const [message, setMessage] = useState('')
  const [health, setHealth] = useState(null)
  const [notice, setNotice] = useState({ type: '', text: '' })
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState('')
  const videos = useAsyncData(api.videos)
  const outputs = useAsyncData(api.outputs)

  const flash = useCallback((type, text) => {
    setNotice({ type, text })
    if (type === 'error') setMessage(text)
  }, [])

  const loadJobs = useCallback(async () => {
    try {
      setJobs(await api.jobs())
    } catch (exc) {
      setMessage(exc.message)
    }
  }, [])

  useEffect(() => {
    api.getConfig().then(setConfig).catch((exc) => setMessage(exc.message))
    loadJobs()
  }, [loadJobs])

  useEffect(() => {
    let active = true
    const checkHealth = () => api.health()
      .then((result) => active && setHealth(result))
      .catch(() => active && setHealth({ status: 'error' }))
    checkHealth()
    const timer = window.setInterval(checkHealth, 5000)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => {
      loadJobs()
      if (page === 'videos') videos.load()
      if (page === 'outputs') outputs.load()
    }, 1500)
    return () => window.clearInterval(timer)
  }, [loadJobs, page, videos.load, outputs.load])

  const refreshAll = useCallback(() => {
    videos.load()
    outputs.load()
    loadJobs()
  }, [videos.load, outputs.load, loadJobs])

  const createDownloads = async (urls, separateAfterDownload = false, pipelineMode = OUTPUT_MODES[0]) => {
    try {
      const taskLabel = separateAfterDownload ? '下载并分离' : '下载'
      setMessage(`正在创建 ${urls.length} 个${taskLabel}任务…`)
      await Promise.all(
        urls.map((url) => separateAfterDownload ? api.pipeline(url, pipelineMode) : api.download(url)),
      )
      setMessage(`已创建 ${urls.length} 个${taskLabel}任务`)
      setNotice({ type: 'success', text: `已创建 ${urls.length} 个${taskLabel}任务，下方可查看实时进度。` })
      await loadJobs()
    } catch (exc) {
      flash('error', exc.message)
    }
  }

  const createSeparation = async (video, mode) => {
    try {
      setMessage('正在创建分离任务…')
      await api.separate(video, mode)
      setMessage('分离任务已创建')
      setNotice({ type: 'success', text: '分离任务已创建，下方可查看任务进度。' })
      await loadJobs()
    } catch (exc) {
      flash('error', exc.message)
    }
  }

  const importLocalFile = async (file) => {
    setImporting(true)
    setImportError('')
    setNotice({ type: '', text: '' })
    try {
      const record = await api.importVideoFile(file)
      await videos.load()
      setMessage(`已导入本地视频：${record.title || record.filename}`)
      setNotice({ type: 'success', text: `已导入本地视频：${record.title || record.filename}` })
    } catch (exc) {
      setImportError(exc.message)
      flash('error', exc.message)
    } finally {
      setImporting(false)
    }
  }

  const importLocalPath = async (path) => {
    setImporting(true)
    setImportError('')
    setNotice({ type: '', text: '' })
    try {
      const record = await api.importVideoPath(path)
      await videos.load()
      setMessage(`已导入本地视频：${record.title || record.filename}`)
      setNotice({ type: 'success', text: `已导入本地视频：${record.title || record.filename}` })
    } catch (exc) {
      setImportError(exc.message)
      flash('error', exc.message)
    } finally {
      setImporting(false)
    }
  }

  const deleteVideo = async (filename) => {
    try {
      await api.deleteVideo(filename)
      await refreshAll()
    } catch (exc) {
      setMessage(exc.message)
    }
  }

  const clearVideos = async () => {
    try {
      await api.clearVideos()
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

  const activePage = useMemo(() => PAGES.find((item) => item.key === page), [page])

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">SV</div>
          <div>
            <div className="brand-name">SunVideoTool</div>
            <div className="brand-sub">本地视频工作台</div>
          </div>
        </div>
        <nav>
          {PAGES.map((item) => (
            <button key={item.key} className={page === item.key ? 'nav active' : 'nav'} onClick={() => setPage(item.key)}>
              <span>{item.icon}</span>{item.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-foot">React · FastAPI</div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>{activePage.label}</h1>
            <p className="muted">{message || '下载、分离任务并行执行，实时监控运行状态。'}</p>
          </div>
          <div className="topbar-actions">
            {health && (
              <span className={`health-pill ${health.status === 'ok' ? 'online' : 'offline'}`}>
                {health.status === 'ok' ? `后端在线 · ${health.device}` : '后端离线'}
              </span>
            )}
            <button className="btn ghost" onClick={refreshAll}>刷新数据</button>
          </div>
        </header>

        {notice.text && (
          <div className={`app-notice ${notice.type}`}>
            <span>{notice.text}</span>
            <button className="notice-close" onClick={() => setNotice({ type: '', text: '' })}>×</button>
          </div>
        )}

        {page === 'tasks' && (
          <>
            <div className="two-col">
              <DownloadPanel onCreate={createDownloads} />
              <SeparatePanel
                videos={videos.data}
                onCreate={createSeparation}
                onImportFile={importLocalFile}
                onImportPath={importLocalPath}
                importing={importing}
                importError={importError}
                onRefresh={() => videos.load()}
              />
            </div>
            <JobsPanel jobs={jobs} />
          </>
        )}
        {page === 'videos' && <VideosPage videos={videos.data} onDelete={deleteVideo} onClear={clearVideos} onRefresh={refreshAll} />}
        {page === 'outputs' && <OutputsPage outputs={outputs.data} />}
        {page === 'settings' && <SettingsPage config={config} onSave={saveConfig} message={message} />}
      </main>
    </div>
  )
}
