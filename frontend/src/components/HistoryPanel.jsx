export default function HistoryPanel({ history, onOpen }) {
  return (
    <div className="history-panel">
      <ul>
        {history.map((entry) => (
          <li key={entry.id}>
            <button className="history-item" onClick={() => onOpen(entry)}>
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
  )
}
