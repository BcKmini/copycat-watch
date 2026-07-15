import { resolveImageUrl } from '../lib/format'

// 내 원본 vs 발견된 이미지를 나란히 비교하는 모달. 배경 클릭으로 닫힌다.
export default function Lightbox({ match, previewUrl, loading, onClose, onReport }) {
  return (
    <div className="lightbox" onClick={onClose}>
      <div className="lightbox-content" onClick={(e) => e.stopPropagation()}>
        <div className="lightbox-header">
          <h3>이미지 비교</h3>
          <button className="ghost small" onClick={onClose}>닫기</button>
        </div>
        <div className="lightbox-images">
          <div className="lightbox-col">
            <span>내 원본</span>
            {previewUrl ? <img src={previewUrl} alt="내 원본" /> : <p className="empty-text">미리보기 없음</p>}
          </div>
          <div className="lightbox-col">
            <span>발견된 이미지</span>
            {match.image_url ? (
              <img src={resolveImageUrl(match.image_url)} alt="발견된 이미지" />
            ) : (
              <p className="empty-text">미리보기 없음 · 링크로 확인</p>
            )}
          </div>
        </div>
        <button className="primary" onClick={() => onReport(match)} disabled={loading}>
          이 결과로 신고서 작성
        </button>
      </div>
    </div>
  )
}
