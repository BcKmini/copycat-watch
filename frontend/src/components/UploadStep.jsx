import FeatureRow from './FeatureRow'
import Hero from './Hero'
import Spinner from './Spinner'

// 1단계: 상품 정보/사진 입력. 히어로·작동방식 소개 후 업로드 폼을 보여준다.
export default function UploadStep({
  productName, setProductName,
  sellerName, setSellerName,
  previewUrl, files, isDragging, setIsDragging,
  fileInputRef, onFileChange, onDrop,
  onScan, loading,
}) {
  return (
    <>
      <Hero />
      <FeatureRow />

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
          onDrop={onDrop}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            onChange={onFileChange}
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

        <button className="primary" onClick={onScan} disabled={loading}>
          {loading ? <><Spinner /> 스캔 중...</> : 'AI로 도용 스캔하기'}
        </button>
      </section>
    </>
  )
}
