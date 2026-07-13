import { useState } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

function App() {
  const [step, setStep] = useState(1)
  const [file, setFile] = useState(null)
  const [previewUrl, setPreviewUrl] = useState(null)
  const [productName, setProductName] = useState('')
  const [sellerName, setSellerName] = useState('')
  const [matches, setMatches] = useState([])
  const [selectedMatch, setSelectedMatch] = useState(null)
  const [report, setReport] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const handleFileChange = (e) => {
    const f = e.target.files[0]
    if (!f) return
    setFile(f)
    setPreviewUrl(URL.createObjectURL(f))
  }

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
      setStep(2)
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

  const reset = () => {
    setStep(1)
    setFile(null)
    setPreviewUrl(null)
    setProductName('')
    setSellerName('')
    setMatches([])
    setSelectedMatch(null)
    setReport('')
    setError('')
  }

  return (
    <div className="page">
      <header className="app-header">
        <h1>카피캣 워치</h1>
        <p className="subtitle">내 상품 사진이 무단 도용됐는지 AI가 찾아드립니다</p>
        <ol className="steps">
          <li className={step === 1 ? 'active' : step > 1 ? 'done' : ''}>1. 상품 등록</li>
          <li className={step === 2 ? 'active' : step > 2 ? 'done' : ''}>2. 스캔 결과</li>
          <li className={step === 3 ? 'active' : ''}>3. 신고서 초안</li>
        </ol>
      </header>

      {error && <div className="error-banner">{error}</div>}

      {step === 1 && (
        <section className="card">
          <h2>내 상품 정보를 입력해줘</h2>
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
            판매자명 (선택)
            <input
              type="text"
              placeholder="예: 박사장"
              value={sellerName}
              onChange={(e) => setSellerName(e.target.value)}
            />
          </label>
          <label className="field">
            상품 사진
            <input type="file" accept="image/*" onChange={handleFileChange} />
          </label>
          {previewUrl && <img src={previewUrl} alt="미리보기" className="preview" />}
          <button className="primary" onClick={runScan} disabled={loading}>
            {loading ? '스캔 중...' : 'AI로 도용 스캔하기'}
          </button>
        </section>
      )}

      {step === 2 && (
        <section className="card">
          <h2>스캔 결과</h2>
          {matches.length === 0 ? (
            <p className="empty">유사한 도용 사례가 발견되지 않았어요.</p>
          ) : (
            <ul className="match-list">
              {matches.map((m) => (
                <li key={m.file} className="match-item">
                  <div className="match-info">
                    <span className="similarity">유사도 {m.similarity}%</span>
                    <strong>{m.shop}</strong>
                    <span className="note">{m.note}</span>
                    <span className="price">판매가 {m.price}</span>
                  </div>
                  <button className="secondary" onClick={() => runReport(m)} disabled={loading}>
                    {loading && selectedMatch?.file === m.file ? '생성 중...' : '신고서 작성'}
                  </button>
                </li>
              ))}
            </ul>
          )}
          <button className="ghost" onClick={reset}>처음으로</button>
        </section>
      )}

      {step === 3 && (
        <section className="card">
          <h2>신고서 초안</h2>
          <pre className="report-box">{report}</pre>
          <button
            className="secondary"
            onClick={() => navigator.clipboard.writeText(report)}
          >
            복사하기
          </button>
          <button className="ghost" onClick={reset}>처음으로</button>
        </section>
      )}
    </div>
  )
}

export default App
