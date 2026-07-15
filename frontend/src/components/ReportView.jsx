// 3단계: 생성된 신고서/통합 신고서/법적 가이드 표시 + 복사·다운로드.
const TITLES = { batch: '통합 신고서 초안', legal: 'AI 법적 대응 가이드', single: '신고서 초안' }
const DESCS = {
  batch: '선택한 모든 도용 사례를 묶은 통합 신고 사유서 · 내용증명이에요.',
  legal: '지금 상황(발견 건수·피해액)에 맞춘 대응 순서와 무료 법률상담처 안내예요. 일반적인 절차 안내이며 구체적 법률 자문이 아니에요.',
  single: '신고 사유서 · 내용증명 · 손해배상 청구내역서예요.',
}

export default function ReportView({ reportMode, report, reportAiGenerated, copied, onCopy, onDownload, onBack, onReset }) {
  return (
    <section className="card">
      <h2>{TITLES[reportMode] ?? TITLES.single}</h2>
      <p className="card-desc">{DESCS[reportMode] ?? DESCS.single} 필요한 부분을 수정해서 사용하세요.</p>
      {!reportAiGenerated && (
        <p className="ai-fallback-notice">
          검증된 템플릿으로 생성됐어요. AI 문장 다듬기가 안전 검증(법 조항·금액 보존)을
          통과하지 못하면, 법적 정확성을 위해 원본 템플릿을 그대로 사용해요 — 내용과 효력은 동일해요.
        </p>
      )}
      <pre className="report-box">{report}</pre>
      <div className="button-row">
        <button className="secondary" onClick={onCopy}>{copied ? '복사됨' : '복사하기'}</button>
        <button className="secondary" onClick={onDownload}>다운로드</button>
        <button className="ghost" onClick={onBack}>← 결과로 돌아가기</button>
        <button className="ghost" onClick={onReset}>처음으로</button>
      </div>
    </section>
  )
}
