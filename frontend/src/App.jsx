import { useCallback, useRef, useState } from 'react'
import './App.css'
import { API_BASE, apiFetch } from './api'
import HistoryPanel from './components/HistoryPanel'
import Lightbox from './components/Lightbox'
import MatchCard from './components/MatchCard'
import ReportView from './components/ReportView'
import Spinner from './components/Spinner'
import StepIndicator from './components/StepIndicator'
import UploadStep from './components/UploadStep'
import { downloadEvidenceBundle } from './lib/evidence'

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

  const visibleMatches = matches.filter((m) => m.similarity >= minSimilarity)
  const totalDamage = visibleMatches.reduce((sum, m) => sum + (m.estimated_damage ?? 0), 0)
  const attributedMatches = visibleMatches.filter((m) => m.source_url)
  const unattributedMatches = visibleMatches.filter((m) => !m.source_url)

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

  const toggleBatchSelect = (fileKey) => {
    setSelectedForBatch((prev) => {
      const next = new Set(prev)
      if (next.has(fileKey)) next.delete(fileKey)
      else next.add(fileKey)
      return next
    })
  }

  const renderMatch = (m) => (
    <MatchCard
      key={m.file}
      m={m}
      batchMode={batchMode}
      selected={selectedForBatch.has(m.file)}
      loading={loading}
      isReporting={loading && selectedMatch?.file === m.file}
      onToggle={toggleBatchSelect}
      onCompare={setCompareMatch}
      onReport={runReport}
    />
  )

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

      {dashboardOpen && <HistoryPanel history={history} onOpen={openHistoryEntry} />}

      {error && <div className="error-banner">{error}</div>}
      {loading && loadingLabel && (
        <div className="info-banner"><Spinner /> {loadingLabel}</div>
      )}

      {step === 1 && (
        <UploadStep
          productName={productName}
          setProductName={setProductName}
          sellerName={sellerName}
          setSellerName={setSellerName}
          previewUrl={previewUrl}
          files={files}
          isDragging={isDragging}
          setIsDragging={setIsDragging}
          fileInputRef={fileInputRef}
          onFileChange={handleFileChange}
          onDrop={handleDrop}
          onScan={runScan}
          loading={loading}
        />
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
                    <ul className="match-list">{attributedMatches.map(renderMatch)}</ul>
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
                        <ul className="match-list">{unattributedMatches.map(renderMatch)}</ul>
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
                <button
                  className="secondary"
                  onClick={() => downloadEvidenceBundle({ file, productName, sellerName, scanMode, aiLabel, visibleMatches, totalDamage })}
                >
                  증거 리포트 다운로드
                </button>
              )}
            </div>
          </div>
        </section>
      )}

      {step === 3 && (
        <ReportView
          reportMode={reportMode}
          report={report}
          reportAiGenerated={reportAiGenerated}
          copied={copied}
          onCopy={copyReport}
          onDownload={downloadReport}
          onBack={goBackToResults}
          onReset={reset}
        />
      )}

      <footer className="app-footer">
        카피캣 워치 · 이미지 도용 탐지 &amp; 법적 대응 자동화<br />
        생성되는 문서는 참고용 초안이며, 법적 제출 전 전문가 검토를 권장합니다.
      </footer>

      {compareMatch && (
        <Lightbox
          match={compareMatch}
          previewUrl={previewUrl}
          loading={loading}
          onClose={() => setCompareMatch(null)}
          onReport={(m) => {
            setCompareMatch(null)
            runReport(m)
          }}
        />
      )}
    </div>
  )
}

export default App
