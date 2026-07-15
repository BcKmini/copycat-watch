import { escapeHtml, resolveImageUrl } from './format'

const fileToDataUrl = (f) => new Promise((resolve, reject) => {
  const reader = new FileReader()
  reader.onload = () => resolve(reader.result)
  reader.onerror = reject
  reader.readAsDataURL(f)
})

// 원본·모든 매치·유사도·검증여부·피해액을 담은 인쇄 가능한 HTML 증거 리포트를 만들어 내려받는다.
export async function downloadEvidenceBundle({ file, productName, sellerName, scanMode, aiLabel, visibleMatches, totalDamage }) {
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
