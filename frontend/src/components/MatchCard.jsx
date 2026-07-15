import { resolveImageUrl, severity } from '../lib/format'
import Spinner from './Spinner'

// 발견된 도용 의심 1건 카드. 배치 모드에선 체크박스, 일반 모드에선 비교/신고서 버튼을 보여준다.
export default function MatchCard({ m, batchMode, selected, loading, isReporting, onToggle, onCompare, onReport }) {
  return (
    <li className={`match-item ${selected ? 'selected' : ''}`}>
      {batchMode && (
        <input
          type="checkbox"
          className="match-checkbox"
          checked={selected}
          onChange={() => onToggle(m.file)}
        />
      )}
      {m.image_url && (
        <img className="match-thumb" src={resolveImageUrl(m.image_url)} alt="" onClick={() => onCompare(m)} />
      )}
      <div className="match-info">
        <span className="badge-row">
          <span className={`badge badge-${severity(m.similarity)}`}>유사도 {m.similarity}%</span>
          {m.verified && <span className="badge badge-verified">실측 검증</span>}
        </span>
        <strong>{m.shop}</strong>
        <span className="note">{m.note}</span>
        {m.price !== '-' && <span className="price">판매가 {m.price}</span>}
        {m.estimated_damage != null && (
          <span className="damage">예상 피해액 {m.estimated_damage.toLocaleString()}원</span>
        )}
        {m.source_url && (
          <a className="source-link" href={m.source_url} target="_blank" rel="noopener noreferrer">
            게시물 바로가기 ↗
          </a>
        )}
      </div>
      {!batchMode && (
        <div className="match-actions">
          {m.image_url && (
            <button className="ghost small" onClick={() => onCompare(m)}>비교하기</button>
          )}
          <button className="secondary" onClick={() => onReport(m)} disabled={loading}>
            {isReporting ? <Spinner /> : '신고서 작성'}
          </button>
        </div>
      )}
    </li>
  )
}
