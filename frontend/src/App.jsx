import { useCallback, useRef, useState } from 'react'
import './App.css'

// 기본값은 same-origin('') — Cloud Run/k8s/compose는 nginx가 같은 주소로 /api를 프록시한다.
// 로컬 vite dev(:5173)는 backend(:8000)가 다른 포트라 .env.local의 VITE_API_BASE로 덮어쓴다.
const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// 프로덕션용 견고한 fetch 래퍼: 타임아웃(무한 대기 방지) + 일시적 실패(콜드스타트 5xx·네트워크
// 순단) 자동 재시도 + 사용자 친화 에러 메시지. 신고서/스캔이 오래 걸려도 안전하게 끝나거나
// 명확히 실패를 알린다.
async function apiFetch(url, options = {}, { timeoutMs = 180000, retries = 2, label = '요청' } = {}) {
  let lastErr
  for (let attempt = 0; attempt <= retries; attempt++) {
    const controller = new AbortController()
    const timer = setTimeout(() => controller.abort(), timeoutMs)
    try {
      const res = await fetch(url, { ...options, signal: controller.signal })
      clearTimeout(timer)
      // 5xx(콜드스타트 직후 등 일시적)면 잠깐 쉬고 재시도한다.
      if (res.status >= 500) {
        if (attempt < retries) {
          await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)))
          continue
        }
        throw new Error(`${label}에 실패했어요(서버 오류 ${res.status}). 잠시 후 다시 시도해 주세요.`)
      }
      if (!res.ok) throw new Error(`${label}에 실패했어요(오류 ${res.status}).`)
      return res
    } catch (err) {
      clearTimeout(timer)
      lastErr = err
      if (err.name === 'AbortError') {
        throw new Error(`${label}이(가) 너무 오래 걸려 중단됐어요. 잠시 후 다시 시도해 주세요.`)
      }
      // 네트워크 순단이면 재시도, 아니면 그대로 던진다.
      const networkish = /Failed to fetch|NetworkError|network/i.test(err.message)
      if (attempt < retries && networkish) {
        await new Promise((r) => setTimeout(r, 1500 * (attempt + 1)))
        continue
      }
      if (networkish) throw new Error(`${label} 중 연결에 문제가 생겼어요. 네트워크를 확인하고 다시 시도해 주세요.`)
      throw err
    }
  }
  throw lastErr
}

const STEPS = ['상품 등록', '스캔 결과', '신고서 초안']

const FEATURES = [
  { title: '사진 업로드', desc: '상품 사진 한 장이면 충분해요 (여러 각도도 OK)' },
  { title: 'AI가 웹 전체 스캔', desc: '도용 이미지를 찾아 서버가 직접 실측 대조해요' },
  { title: '신고서 자동 작성', desc: '사유서·내용증명·손해배상 청구서를 즉시 생성해요' },
]

function Spinner() {
  return <span className="spinner" aria-hidden="true" />
}

function StepIndicator({ step }) {
  return (
    <ol className="steps">
      {STEPS.map((label, i) => {
        const n = i + 1
        const state = n === step ? 'active' : n < step ? 'done' : ''
        return (
          <li key={label} className={state}>
            <span className="step-dot">{n < step ? '✓' : n}</span>
            <span className="step-label">{label}</span>
          </li>
        )
      })}
    </ol>
  )
}

function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}

function App() {
  const [step, setStep] = useState(1)
  const [file, setFile] = useState(null)
  const [files, setFiles] = useState([])
  const [previewUrl, setPreviewUrl] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [productName, setProductName] = useState('')
  const [sellerName, setSellerName] = useState('')
  const [matches, setMatches] = useState([])
  const [scanMode, setScanMode] = useState(null)
  const [aiLabel, setAiLabel] = useState(null)
  const [selectedMatch, setSelectedMatch] = useState(null)
  const [report, setReport] = useState('')
  const [reportMode, setReportMode] = useState('single')
  const [reportAiGenerated, setReportAiGenerated] = useState(true)
  const [loading, setLoading] = useState(false)
  const [loadingLabel, setLoadingLabel] = useState('')
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [compareMatch, setCompareMatch] = useState(null)
  const [history, setHistory] = useState([])
  const [dashboardOpen, setDashboardOpen] = useState(false)
  const [minSimilarity, setMinSimilarity] = useState(0)
  const [batchMode, setBatchMode] = useState(false)
  const [selectedForBatch, setSelectedForBatch] = useState(new Set())
  const [showUnattributed, setShowUnattributed] = useState(false)
  const fileInputRef = useRef(null)

  // 여러 장을 올리면 같은 상품의 다른 각도/배경까지 대조해 재현율이 오른다(최대 5장).
  const applyFiles = (fileList) => {
    const imgs = Array.from(fileList || []).filter((f) => f.type.startsWith('image/')).slice(0, 5)
    if (imgs.length === 0) return
    setFiles(imgs)
    setFile(imgs[0])
    setPreviewUrl(URL.createObjectURL(imgs[0]))
  }

  const handleFileChange = (e) => applyFiles(e.target.files)

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
    applyFiles(e.dataTransfer.files)
  }, [])

  const runScan = async () => {
    if (!file || !productName) {
      setError('상품명과 이미지를 모두 입력해줘.')
      return
    }
    setError('')
    setLoadingLabel('이미지를 분석하고 웹에서 대조하는 중이에요 · 최대 1분 정도 걸릴 수 있어요')
    setLoading(true)
    try {
      const formData = new FormData()
      const toSend = files.length > 0 ? files : [file]
      toSend.forEach((f) => formData.append('file', f))
      const res = await apiFetch(`${API_BASE}/api/scan`, { method: 'POST', body: formData },
        { timeoutMs: 180000, label: '스캔' })
      const data = await res.json()
      setMatches(data.matches)
      setScanMode(data.mode)
      setAiLabel(data.label ?? null)
      setMinSimilarity(0)
      setBatchMode(false)
      setSelectedForBatch(new Set())
      setShowUnattributed(false)
      setStep(2)
      setHistory((prev) => [
        {
          id: `${Date.now()}`,
          productName,
          previewUrl,
          matches: data.matches,
          scanMode: data.mode,
          aiLabel: data.label ?? null,
          timestamp: new Date().toLocaleString('ko-KR'),
        },
        ...prev,
      ].slice(0, 10))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
      setLoadingLabel('')
    }
  }

  const runReport = async (match) => {
    setSelectedMatch(match)
    setError('')
    setLoadingLabel('AI가 신고서를 작성하는 중이에요 · 최대 1~2분 걸릴 수 있어요')
    setLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/api/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_name: productName,
          seller_name: sellerName || '본인',
          match_shop: match.shop,
          match_note: match.note,
          similarity: match.similarity,
          source_url: match.source_url ?? null,
          estimated_damage: match.estimated_damage ?? null,
        }),
      }, { timeoutMs: 300000, label: '신고서 생성' })
      const data = await res.json()
      setReport(data.report)
      setReportMode('single')
      setReportAiGenerated(data.ai_generated ?? true)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
      setLoadingLabel('')
    }
  }

  const runBatchReport = async () => {
    const selected = matches.filter((m) => selectedForBatch.has(m.file))
    if (selected.length === 0) return
    setError('')
    setLoadingLabel('AI가 통합 신고서를 작성하는 중이에요 · 최대 2~3분 걸릴 수 있어요')
    setLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/api/report/batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_name: productName,
          seller_name: sellerName || '본인',
          matches: selected.map((m) => ({
            shop: m.shop,
            note: m.note,
            similarity: m.similarity,
            source_url: m.source_url ?? null,
            estimated_damage: m.estimated_damage ?? null,
          })),
        }),
      }, { timeoutMs: 300000, label: '통합 신고서 생성' })
      const data = await res.json()
      setReport(data.report)
      setReportMode('batch')
      setReportAiGenerated(data.ai_generated ?? true)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
      setLoadingLabel('')
    }
  }

  const runLegalGuide = async () => {
    if (visibleMatches.length === 0) return
    setError('')
    setLoadingLabel('AI가 법적 대응 가이드를 작성하는 중이에요 · 최대 1~2분 걸릴 수 있어요')
    setLoading(true)
    try {
      const res = await apiFetch(`${API_BASE}/api/legal-guide`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_name: productName,
          total_matches: visibleMatches.length,
          verified_matches: visibleMatches.filter((m) => m.verified).length,
          total_damage: totalDamage,
          repeated_infringement: visibleMatches.length >= 5,
          matches: visibleMatches.map((m) => ({ shop: m.shop, source_url: m.source_url ?? null })),
        }),
      }, { timeoutMs: 300000, label: '법적 대응 가이드 생성' })
      const data = await res.json()
      setReport(data.report)
      setReportMode('legal')
      setReportAiGenerated(data.ai_generated ?? true)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
      setLoadingLabel('')
    }
  }

  const copyReport = () => {
    navigator.clipboard.writeText(report)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }

  const downloadReport = () => {
    const blob = new Blob([report], { type: 'text/plain;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${productName || '신고서'}_카피캣워치.txt`
    a.click()
    URL.revokeObjectURL(url)
  }

  const fileToDataUrl = (f) => new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = reject
    reader.readAsDataURL(f)
  })

  const downloadEvidenceBundle = async () => {
    const originalDataUrl = file ? await fileToDataUrl(file).catch(() => null) : null
    const generatedAt = new Date()

    const rows = visibleMatches.map((m, i) => `
      <tr>
        <td>${i + 1}</td>
        <td>${m.image_url ? `<img src="${escapeHtml(resolveImageUrl(m.image_url))}" />` : '이미지 없음'}</td>
        <td>${escapeHtml(m.shop)}</td>
        <td>${m.similarity}%</td>
        <td class="${m.verified ? 'ok' : 'warn'}">${m.verified ? '실측 검증(직접 대조)' : '미검증(추정치, 사이트 차단)'}</td>
        <td>${escapeHtml(m.note)}</td>
        <td>${m.source_url ? `<a href="${escapeHtml(m.source_url)}">${escapeHtml(m.source_url)}</a>` : '게시 페이지 미확인'}</td>
        <td>${m.estimated_damage != null ? m.estimated_damage.toLocaleString() + '원' : '-'}</td>
      </tr>`).join('')

    const verifiedCount = visibleMatches.filter((m) => m.verified).length

    const html = `<!doctype html><html><head><meta charset="utf-8">
<title>증거 리포트 - ${escapeHtml(productName)}</title>
<style>
  body{font-family:-apple-system,'Malgun Gothic',sans-serif;max-width:1000px;margin:40px auto;padding:0 20px;color:#14141a;line-height:1.5}
  h1{font-size:22px;margin-bottom:4px}
  h2{font-size:16px;margin-top:32px;border-bottom:2px solid #14141a;padding-bottom:6px}
  .meta{color:#444;font-size:13px;margin:3px 0}
  .original{display:flex;gap:16px;align-items:flex-start;margin-top:12px;padding:16px;background:#f8f8fb;border-radius:10px}
  .original img{width:160px;height:160px;object-fit:cover;border-radius:8px;border:1px solid #ddd}
  table{width:100%;border-collapse:collapse;margin-top:12px}
  th,td{border:1px solid #ddd;padding:8px;text-align:left;font-size:12.5px;vertical-align:middle;word-break:break-all}
  th{background:#f4f4f8}
  img{width:56px;height:56px;object-fit:cover;border-radius:6px}
  .ok{color:#1e8a4c;font-weight:700}
  .warn{color:#a15c00;font-weight:700}
  .disclaimer{margin-top:28px;padding:14px;background:#fdecea;border-radius:8px;color:#7a1f1f;font-size:12.5px}
  .footer{color:#999;font-size:11.5px;margin-top:20px}
  @media print{ body{margin:0} }
</style></head><body>
  <h1>이미지 도용 탐지 증거 리포트</h1>
  <p class="meta">문서 생성 일시: ${generatedAt.toLocaleString('ko-KR', { dateStyle: 'long', timeStyle: 'medium' })} (KST)</p>
  <p class="meta">상품명: ${escapeHtml(productName)}${sellerName ? ` · 판매자: ${escapeHtml(sellerName)}` : ''}</p>
  <p class="meta">탐지 방식: ${scanMode === 'web' ? 'Google Vision 실시간 웹 검색 + 서버 실측 이미지 대조' : '데모 데이터셋 매칭'} · AI 인식 상품 종류: ${escapeHtml(aiLabel || '확인되지 않음')}</p>
  <p class="meta">발견 건수: ${visibleMatches.length}건 (이 중 실측 검증 ${verifiedCount}건) · 예상 피해액 합계: ${totalDamage.toLocaleString()}원</p>

  <h2>1. 제출 원본 이미지</h2>
  <div class="original">
    ${originalDataUrl ? `<img src="${originalDataUrl}" alt="원본 이미지" />` : '<p>원본 이미지를 첨부할 수 없습니다.</p>'}
    <div>
      <p class="meta">이 리포트에 포함된 모든 비교는 위 이미지를 기준으로 수행되었습니다.</p>
      <p class="meta">파일명: ${file ? escapeHtml(file.name) : '-'}</p>
    </div>
  </div>

  <h2>2. 발견된 도용 의심 사례 (${visibleMatches.length}건)</h2>
  <table>
    <thead><tr><th>#</th><th>이미지</th><th>발견 위치</th><th>유사도</th><th>검증 방식</th><th>정황</th><th>게시물 URL</th><th>예상 피해액</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>

  <p class="disclaimer">
    ⚠ "실측 검증" 항목은 서버가 해당 이미지를 직접 다운로드하여 프로덕션 유사도 알고리즘(perceptual
    hash + color hash)으로 대조한 결과입니다. "미검증(추정치)" 항목은 게시 사이트가 이미지 직접
    다운로드를 차단해 Google Vision의 등급 분류만으로 추정한 값이므로, 신고·법적 조치 전 해당
    URL을 직접 방문해 육안으로 재확인하시기 바랍니다. 본 리포트는 자동 생성된 참고자료이며 법적
    증거로 제출 시 변호사·전문가의 검토 및 필요시 공증·전자문서 타임스탬프 등록을 권장합니다.
  </p>
  <p class="footer">카피캣 워치(Copycat Watch)로 자동 생성된 증거 리포트입니다.</p>
</body></html>`

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${productName || '증거리포트'}_카피캣워치_${generatedAt.toISOString().slice(0, 10)}.html`
    a.click()
    URL.revokeObjectURL(url)
  }

  const goBackToResults = () => {
    setStep(2)
    setReport('')
    setError('')
  }

  const reset = () => {
    setStep(1)
    setFile(null)
    setFiles([])
    setPreviewUrl(null)
    setProductName('')
    setSellerName('')
    setMatches([])
    setScanMode(null)
    setAiLabel(null)
    setSelectedMatch(null)
    setReport('')
    setError('')
    setMinSimilarity(0)
    setBatchMode(false)
    setSelectedForBatch(new Set())
  }

  const openHistoryEntry = (entry) => {
    setProductName(entry.productName)
    setPreviewUrl(entry.previewUrl)
    setMatches(entry.matches)
    setScanMode(entry.scanMode)
    setAiLabel(entry.aiLabel ?? null)
    setMinSimilarity(0)
    setBatchMode(false)
    setSelectedForBatch(new Set())
    setStep(2)
    setDashboardOpen(false)
  }

  const toggleBatchSelect = (file) => {
    setSelectedForBatch((prev) => {
      const next = new Set(prev)
      if (next.has(file)) next.delete(file)
      else next.add(file)
      return next
    })
  }

  const severity = (similarity) => (similarity >= 60 ? 'high' : 'mid')

  const renderMatchCard = (m) => (
    <li key={m.file} className={`match-item ${selectedForBatch.has(m.file) ? 'selected' : ''}`}>
      {batchMode && (
        <input
          type="checkbox"
          className="match-checkbox"
          checked={selectedForBatch.has(m.file)}
          onChange={() => toggleBatchSelect(m.file)}
        />
      )}
      {m.image_url && (
        <img
          className="match-thumb"
          src={resolveImageUrl(m.image_url)}
          alt=""
          onClick={() => setCompareMatch(m)}
        />
      )}
      <div className="match-info">
        <span className="badge-row">
          <span className={`badge badge-${severity(m.similarity)}`}>
            유사도 {m.similarity}%
          </span>
          {m.verified && <span className="badge badge-verified">실측 검증</span>}
        </span>
        <strong>{m.shop}</strong>
        <span className="note">{m.note}</span>
        {m.price !== '-' && <span className="price">판매가 {m.price}</span>}
        {m.estimated_damage != null && (
          <span className="damage">예상 피해액 {m.estimated_damage.toLocaleString()}원</span>
        )}
        {m.source_url && (
          <a
            className="source-link"
            href={m.source_url}
            target="_blank"
            rel="noopener noreferrer"
          >
            게시물 바로가기 ↗
          </a>
        )}
      </div>
      {!batchMode && (
        <div className="match-actions">
          {m.image_url && (
            <button className="ghost small" onClick={() => setCompareMatch(m)}>
              비교하기
            </button>
          )}
          <button className="secondary" onClick={() => runReport(m)} disabled={loading}>
            {loading && selectedMatch?.file === m.file ? <Spinner /> : '신고서 작성'}
          </button>
        </div>
      )}
    </li>
  )

  const resolveImageUrl = (url) => {
    if (!url) return null
    return url.startsWith('http') ? url : `${API_BASE}${url}`
  }

  const visibleMatches = matches.filter((m) => m.similarity >= minSimilarity)
  const totalDamage = visibleMatches.reduce((sum, m) => sum + (m.estimated_damage ?? 0), 0)
  const attributedMatches = visibleMatches.filter((m) => m.source_url)
  const unattributedMatches = visibleMatches.filter((m) => !m.source_url)

  return (
    <div className="page">
      <header className="app-header">
        <div className="brand-row">
          <div className="brand">
            <span className="brand-mark">CW</span>
            <span className="brand-name">카피캣 워치</span>
          </div>
          {history.length > 0 && (
            <button className="history-toggle" onClick={() => setDashboardOpen((v) => !v)}>
              스캔 이력 ({history.length})
            </button>
          )}
        </div>
        <p className="subtitle">내 상품 사진이 무단 도용됐는지 AI가 찾아드립니다</p>
        <StepIndicator step={step} />
      </header>

      {dashboardOpen && (
        <div className="history-panel">
          <ul>
            {history.map((entry) => (
              <li key={entry.id}>
                <button className="history-item" onClick={() => openHistoryEntry(entry)}>
                  {entry.previewUrl && <img src={entry.previewUrl} alt="" />}
                  <span className="history-item-info">
                    <strong>{entry.productName}</strong>
                    <span>{entry.matches.length}건 발견 · {entry.timestamp}</span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}
      {loading && loadingLabel && (
        <div className="info-banner"><Spinner /> {loadingLabel}</div>
      )}

      {step === 1 && (
        <>
          <section className="hero">
            <span className="hero-eyebrow">소상공인을 위한 이미지 도용 대응 도구</span>
            <h1 className="hero-title">
              내 상품 사진, 어디서<br />
              <span className="hero-highlight">무단 도용</span>되고 있을까요?
            </h1>
            <p className="hero-sub">
              사진 한 장을 올리면 AI가 인터넷 전체에서 도용 사례를 찾아내고,
              피해액 산정부터 법적 신고서 초안까지 한 번에 만들어 드려요.
            </p>
            <div className="hero-trust">
              <span className="trust-chip"><b>실측 검증</b> 오탐 제거</span>
              <span className="trust-chip"><b>3종</b> 법적 문서 자동 작성</span>
              <span className="trust-chip"><b>무료</b> 법률상담처 안내</span>
            </div>
          </section>

          <ul className="feature-row">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <div className="feat-text">
                  <strong>{f.title}</strong>
                  <span>{f.desc}</span>
                </div>
              </li>
            ))}
          </ul>

          <section className="card">
            <h2>내 상품 정보 입력</h2>
            <p className="card-desc">상품명과 사진만 있으면 바로 시작할 수 있어요.</p>

            <label className="field">
              상품명
              <input
                type="text"
                placeholder="예: 핸드메이드 라벤더 비누"
                value={productName}
                onChange={(e) => setProductName(e.target.value)}
              />
            </label>
            <label className="field">
              판매자명 <span className="optional">(선택)</span>
              <input
                type="text"
                placeholder="예: 박사장"
                value={sellerName}
                onChange={(e) => setSellerName(e.target.value)}
              />
            </label>

            <span className="field-label">상품 사진</span>
            <div
              className={`dropzone ${isDragging ? 'dragging' : ''} ${previewUrl ? 'has-file' : ''}`}
              onClick={() => fileInputRef.current?.click()}
              onDragOver={(e) => {
                e.preventDefault()
                setIsDragging(true)
              }}
              onDragLeave={() => setIsDragging(false)}
              onDrop={handleDrop}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept="image/*"
                multiple
                onChange={handleFileChange}
                hidden
              />
              {previewUrl ? (
                <>
                  <img src={previewUrl} alt="미리보기" className="preview" />
                  {files.length > 1 && (
                    <span className="multi-badge">외 {files.length - 1}장 · 총 {files.length}장</span>
                  )}
                </>
              ) : (
                <div className="dropzone-hint">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
                    <path d="M12 3v12M12 3l4 4M12 3 8 7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>클릭하거나 이미지를 끌어다 놓으세요 (여러 장 가능)</span>
                </div>
              )}
            </div>

            <button className="primary" onClick={runScan} disabled={loading}>
              {loading ? <><Spinner /> 스캔 중...</> : 'AI로 도용 스캔하기'}
            </button>
          </section>
        </>
      )}

      {step === 2 && (
        <section className="card">
          <div className="card-header-row">
            <h2>스캔 결과</h2>
            {scanMode && (
              <span className={`mode-badge mode-${scanMode}`}>
                {scanMode === 'web' ? '실시간 웹 검색' : '데모 데이터 검색'}
              </span>
            )}
          </div>
          {scanMode === 'demo' && (
            <p className="card-desc">
              Google Vision API 키가 설정되지 않아 데모 데이터셋 안에서만 찾은 결과예요.
              실제 웹 검색을 켜려면 백엔드에 GOOGLE_VISION_API_KEY를 설정하세요.
            </p>
          )}
          {aiLabel && (
            <p className="card-desc">AI가 인식한 상품 종류: <strong>{aiLabel}</strong></p>
          )}
          {visibleMatches.length > 0 && (
            <div className="stats-bar">
              <div className="stat">
                <span className="stat-value">{visibleMatches.length}건</span>
                <span className="stat-label">발견된 도용 의심</span>
              </div>
              <div className="stat">
                <span className="stat-value">{Math.round(visibleMatches[0]?.similarity ?? 0)}%</span>
                <span className="stat-label">최고 유사도</span>
              </div>
              {totalDamage > 0 && (
                <div className="stat">
                  <span className="stat-value">{totalDamage.toLocaleString()}원</span>
                  <span className="stat-label">예상 피해액 합계</span>
                </div>
              )}
            </div>
          )}
          {matches.length === 0 ? (
            <div className="empty">
              <svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                <path d="M9 12l2 2 4-4" strokeLinecap="round" strokeLinejoin="round" />
                <circle cx="12" cy="12" r="9" />
              </svg>
              <p>유사한 도용 사례가 발견되지 않았어요.</p>
            </div>
          ) : (
            <>
              <div className="result-controls">
                <label className="field slider-field">
                  최소 유사도 {minSimilarity}%
                  <input
                    type="range"
                    min="0"
                    max="90"
                    step="5"
                    value={minSimilarity}
                    onChange={(e) => setMinSimilarity(Number(e.target.value))}
                  />
                </label>
                <button
                  className={`ghost small toggle ${batchMode ? 'active' : ''}`}
                  onClick={() => {
                    setBatchMode((v) => !v)
                    setSelectedForBatch(new Set())
                  }}
                >
                  {batchMode ? '일괄 선택 취소' : '여러 건 선택'}
                </button>
              </div>

              {visibleMatches.length === 0 ? (
                <p className="empty-text">필터 조건에 맞는 결과가 없어요. 최소 유사도를 낮춰보세요.</p>
              ) : (
                <>
                  {attributedMatches.length > 0 && (
                    <ul className="match-list">{attributedMatches.map(renderMatchCard)}</ul>
                  )}
                  {unattributedMatches.length > 0 && (
                    <div className="unattributed-section">
                      <button
                        className="ghost small unattributed-toggle"
                        onClick={() => setShowUnattributed((v) => !v)}
                      >
                        {showUnattributed
                          ? '접기 ▲'
                          : `게시 페이지가 확인되지 않은 동일/유사 이미지 ${unattributedMatches.length}건 더보기 ▼`}
                      </button>
                      {showUnattributed && (
                        <ul className="match-list">{unattributedMatches.map(renderMatchCard)}</ul>
                      )}
                    </div>
                  )}
                </>
              )}
            </>
          )}

          <div className="result-footer">
            <button className="ghost" onClick={reset}>← 새로 스캔하기</button>
            <div className="result-footer-actions">
              {batchMode && (
                <button
                  className="primary"
                  onClick={runBatchReport}
                  disabled={loading || selectedForBatch.size === 0}
                >
                  {loading ? <Spinner /> : `선택 ${selectedForBatch.size}건 통합 신고서 생성`}
                </button>
              )}
              {visibleMatches.length > 0 && (
                <button className="secondary" onClick={runLegalGuide} disabled={loading}>
                  AI 법적 대응 가이드
                </button>
              )}
              {visibleMatches.length > 0 && (
                <button className="secondary" onClick={downloadEvidenceBundle}>
                  증거 리포트 다운로드
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>{reportMode === 'batch' ? '통합 신고서 초안' : reportMode === 'legal' ? 'AI 법적 대응 가이드' : '신고서 초안'}</h2>
          <p className="card-desc">
            {reportMode === 'batch'
              ? '선택한 모든 도용 사례를 묶은 통합 신고 사유서 · 내용증명이에요.'
              : reportMode === 'legal'
                ? '지금 상황(발견 건수·피해액)에 맞춘 대응 순서와 무료 법률상담처 안내예요. 일반적인 절차 안내이며 구체적 법률 자문이 아니에요.'
                : '신고 사유서 · 내용증명 · 손해배상 청구내역서예요.'} 필요한 부분을 수정해서 사용하세요.
          </p>
          {!reportAiGenerated && (
            <p className="ai-fallback-notice">
              검증된 템플릿으로 생성됐어요. AI 문장 다듬기가 안전 검증(법 조항·금액 보존)을
              통과하지 못하면, 법적 정확성을 위해 원본 템플릿을 그대로 사용해요 — 내용과 효력은 동일해요.
            </p>
          )}
          <pre className="report-box">{report}</pre>
          <div className="button-row">
            <button className="secondary" onClick={copyReport}>
              {copied ? '복사됨' : '복사하기'}
            </button>
            <button className="secondary" onClick={downloadReport}>
              다운로드
            </button>
            <button className="ghost" onClick={goBackToResults}>← 결과로 돌아가기</button>
            <button className="ghost" onClick={reset}>처음으로</button>
          </div>
        </section>
      )}

      <footer className="app-footer">
        카피캣 워치 · 이미지 도용 탐지 &amp; 법적 대응 자동화<br />
        생성되는 문서는 참고용 초안이며, 법적 제출 전 전문가 검토를 권장합니다.
      </footer>

      {compareMatch && (
        <div className="lightbox" onClick={() => setCompareMatch(null)}>
          <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
            <div className="lightbox-header">
              <h3>이미지 비교</h3>
              <button className="ghost small" onClick={() => setCompareMatch(null)}>닫기</button>
            </div>
            <div className="lightbox-images">
              <div className="lightbox-col">
                <span>내 원본</span>
                {previewUrl ? <img src={previewUrl} alt="내 원본" /> : <p className="empty-text">미리보기 없음</p>}
              </div>
              <div className="lightbox-col">
                <span>발견된 이미지</span>
                {compareMatch.image_url ? (
                  <img src={resolveImageUrl(compareMatch.image_url)} alt="발견된 이미지" />
                ) : (
                  <p className="empty-text">미리보기 없음 · 링크로 확인</p>
                )}
              </div>
            </div>
            <button
              className="primary"
              onClick={() => {
                const match = compareMatch
                setCompareMatch(null)
                runReport(match)
              }}
              disabled={loading}
            >
              이 결과로 신고서 작성
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default App
