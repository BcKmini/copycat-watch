export default function Hero() {
  return (
    <section className="hero">
      <span className="hero-eyebrow">소상공인을 위한 이미지 도용 대응 도구</span>
      <h1 className="hero-title">
        내 상품 사진, 어디서<br />
        <span className="hero-highlight">무단 도용</span>되고 있을까요?
      </h1>
      <p className="hero-sub">
        사진 한 장을 올리면 AI가 인터넷 전체에서 도용 사례를 찾아내고,
        피해액 산정부터 법적 신고서 초안까지 한 번에 만들어 드려요.
      </p>
      <div className="hero-trust">
        <span className="trust-chip"><b>실측 검증</b> 오탐 제거</span>
        <span className="trust-chip"><b>3종</b> 법적 문서 자동 작성</span>
        <span className="trust-chip"><b>무료</b> 법률상담처 안내</span>
      </div>
    </section>
  )
}
