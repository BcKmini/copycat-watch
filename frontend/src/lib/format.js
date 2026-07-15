import { API_BASE } from '../api'

// 데모 이미지(상대 경로)는 API_BASE를 붙이고, 외부 이미지(http)는 그대로 쓴다.
export function resolveImageUrl(url) {
  if (!url) return null
  return url.startsWith('http') ? url : `${API_BASE}${url}`
}

export function escapeHtml(str) {
  return String(str ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[c])
}

// 유사도 60% 이상은 강한(high) 배지, 그 미만은 중간(mid) 배지.
export const severity = (similarity) => (similarity >= 60 ? 'high' : 'mid')
