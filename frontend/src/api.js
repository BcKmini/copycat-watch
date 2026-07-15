// 기본값은 same-origin('') — Cloud Run/k8s/compose는 nginx가 같은 주소로 /api를 프록시한다.
// 로컬 vite dev(:5173)는 backend(:8000)가 다른 포트라 .env.local의 VITE_API_BASE로 덮어쓴다.
export const API_BASE = import.meta.env.VITE_API_BASE ?? ''

// 프로덕션용 견고한 fetch 래퍼: 타임아웃(무한 대기 방지) + 일시적 실패(콜드스타트 5xx·네트워크
// 순단) 자동 재시도 + 사용자 친화 에러 메시지. 신고서/스캔이 오래 걸려도 안전하게 끝나거나
// 명확히 실패를 알린다.
export async function apiFetch(url, options = {}, { timeoutMs = 180000, retries = 2, label = '요청' } = {}) {
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
