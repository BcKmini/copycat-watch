import { useCallback, useRef, useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const STEPS = ['상품 등록', '스캔 결과', '신고서 초안']

const FEATURES = [
  { title: '실시간 웹 검색', desc: 'Google Vision으로 인터넷 전체에서 유사 이미지를 찾아요' },
  { title: '피해액 자동 계산', desc: '판매가 기반으로 예상 피해 규모를 산정해요' },
  { title: 'AI 신고서 3종', desc: '사유서·내용증명·손해배상 청구서를 한번에' },
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

function App() {
  const [step, setStep] = useState(1)
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [isDragging, setIsDragging] = useState(false)
  const [productName, setProductName] = useState('')
  const [sellerName, setSellerName] = useState('')
  const [matches, setMatches] = useState([])
  const [scanMode, setScanMode] = useState(null)
  const [selectedMatch, setSelectedMatch] = useState(null)
  const [report, setReport] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [copied, setCopied] = useState(false)
  const [platform, setPlatform] = useState('오픈마켓 일반')
  const [compareMatch, setCompareMatch] = useState(null)
  const [history, setHistory] = useState([])
  const [historyOpen, setHistoryOpen] = useState(false)
  const [minSimilarity, setMinSimilarity] = useState(0)
  const fileInputRef = useRef(null)

  const applyFile = (f) => {
    if (!f || !f.type.startsWith('image/')) return
    setFile(f)
    setPreviewUrl(URL.createObjectURL(f))
  }

  const handleFileChange = (e) => applyFile(e.target.files[0])

  const handleDrop = useCallback((e) => {
    e.preventDefault()
    setIsDragging(false)
    applyFile(e.dataTransfer.files[0])
  }, [])

  const runScan = async () => {
    if (!file || !productName) {
      setError('상품명과 이미지를 모두 입력해줘.')
      return
    }
    setError('')
    setLoading(true)
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(`${API_BASE}/api/scan`, { method: 'POST', body: formData })
      if (!res.ok) throw new Error('스캔 요청 실패')
      const data = await res.json()
      setMatches(data.matches)
      setScanMode(data.mode)
      setMinSimilarity(0)
      setStep(2)
      setHistory((prev) => [
        {
          id: `${Date.now()}`,
          productName,
          previewUrl,
          matches: data.matches,
          scanMode: data.mode,
          timestamp: new Date().toLocaleString('ko-KR'),
        },
        ...prev,
      ].slice(0, 10))
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  const runReport = async (match) => {
    setSelectedMatch(match)
    setError('')
    setLoading(true)
    try {
      const res = await fetch(`${API_BASE}/api/report`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          product_name: productName,
          seller_name: sellerName || '본인',
          match_shop: match.shop,
          match_note: match.note,
          similarity: match.similarity,
          platform,
          source_url: match.source_url ?? null,
          estimated_damage: match.estimated_damage ?? null,
        }),
      })
      if (!res.ok) throw new Error('신고서 생성 실패')
      const data = await res.json()
      setReport(data.report)
      setStep(3)
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
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

  const reset = () => {
    setStep(1)
    setFile(null)
    setPreviewUrl(null)
    setProductName('')
    setSellerName('')
    setMatches([])
    setScanMode(null)
    setSelectedMatch(null)
    setReport('')
    setError('')
    setPlatform('오픈마켓 일반')
    setMinSimilarity(0)
  }

  const openHistoryEntry = (entry) => {
    setProductName(entry.productName)
    setPreviewUrl(entry.previewUrl)
    setMatches(entry.matches)
    setScanMode(entry.scanMode)
    setMinSimilarity(0)
    setStep(2)
    setHistoryOpen(false)
  }

  const severity = (similarity) => (similarity >= 60 ? 'high' : 'mid')

  const resolveImageUrl = (url) => {
    if (!url) return null
    return url.startsWith('http') ? url : `${API_BASE}${url}`
  }

  const visibleMatches = matches.filter((m) => m.similarity >= minSimilarity)

  return (
    <div className="page">
      <header className="app-header">
        <div className="brand-row">
          <div className="brand">
            <span className="brand-mark">CW</span>
            <span className="brand-name">카피캣 워치</span>
          </div>
          {history.length > 0 && (
            <button className="history-toggle" onClick={() => setHistoryOpen((v) => !v)}>
              스캔 이력 ({history.length})
            </button>
          )}
        </div>
        <p className="subtitle">내 상품 사진이 무단 도용됐는지 AI가 찾아드립니다</p>
        <StepIndicator step={step} />
      </header>

      {historyOpen && (
        <div className="history-panel">
          {history.length === 0 ? (
            <p className="empty-text">아직 스캔 이력이 없어요.</p>
          ) : (
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
          )}
        </div>
      )}

      {error && <div className="error-banner">{error}</div>}

      {step === 1 && (
        <>
          <ul className="feature-row">
            {FEATURES.map((f) => (
              <li key={f.title}>
                <strong>{f.title}</strong>
                <span>{f.desc}</span>
              </li>
            ))}
          </ul>

          <section className="card">
            <h2>내 상품 정보를 입력해줘</h2>
            <p className="card-desc">사진 한 장이면 AI가 유사 이미지를 찾아 신고서까지 만들어줘요.</p>

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
                onChange={handleFileChange}
                hidden
              />
              {previewUrl ? (
                <img src={previewUrl} alt="미리보기" className="preview" />
              ) : (
                <div className="dropzone-hint">
                  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6">
                    <path d="M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" />
                    <path d="M12 3v12M12 3l4 4M12 3 8 7" strokeLinecap="round" strokeLinejoin="round" />
                  </svg>
                  <span>클릭하거나 이미지를 끌어다 놓으세요</span>
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
                <label className="field platform-field">
                  신고 대상 플랫폼
                  <select value={platform} onChange={(e) => setPlatform(e.target.value)}>
                    <option>오픈마켓 일반</option>
                    <option>스마트스토어</option>
                    <option>쿠팡</option>
                    <option>인스타그램</option>
                    <option>기타 SNS</option>
                  </select>
                </label>
                <label className="field platform-field">
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
              </div>

              {visibleMatches.length === 0 ? (
                <p className="empty-text">필터 조건에 맞는 결과가 없어요. 최소 유사도를 낮춰보세요.</p>
              ) : (
                <ul className="match-list">
                  {visibleMatches.map((m) => (
                    <li key={m.file} className="match-item">
                      {m.image_url && (
                        <img
                          className="match-thumb"
                          src={resolveImageUrl(m.image_url)}
                          alt=""
                          onClick={() => setCompareMatch(m)}
                        />
                      )}
                      <div className="match-info">
                        <span className={`badge badge-${severity(m.similarity)}`}>
                          유사도 {m.similarity}%
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
                    </li>
                  ))}
                </ul>
              )}
            </>
          )}
          <button className="ghost" onClick={reset}>처음으로</button>
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>신고서 초안</h2>
          <p className="card-desc">신고 사유서 · 내용증명 · 손해배상 청구내역서예요. 필요한 부분을 수정해서 사용하세요.</p>
          <pre className="report-box">{report}</pre>
          <div className="button-row">
            <button className="secondary" onClick={copyReport}>
              {copied ? '복사됨' : '복사하기'}
            </button>
            <button className="secondary" onClick={downloadReport}>
              다운로드
            </button>
            <button className="ghost" onClick={reset}>처음으로</button>
          </div>
        </section>
      )}

      <footer className="app-footer">K-AI 콘텐츠 공모전 · 카피캣 워치</footer>

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
          </div>
        </div>
      )}
    </div>
  )
}

export default App
