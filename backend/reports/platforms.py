"""발견된 게시물의 플랫폼(쿠팡·네이버 등)을 자동 인식하고, 플랫폼별 실제 신고 채널을
안내한다. 같은 상품이라도 발견된 플랫폼마다 접수처·절차가 다르므로 나눠서 안내한다.
"""

PLATFORM_DOMAIN_HINTS = [
    (("coupang.com",), "쿠팡"),
    (("smartstore.naver.com", "shopping.naver.com", "brand.naver.com"), "네이버 스마트스토어"),
    (("instagram.com",), "인스타그램"),
    (("11st.co.kr",), "11번가"),
    (("gmarket.co.kr",), "지마켓"),
    (("auction.co.kr",), "옥션"),
    (("wemakeprice.com",), "위메프"),
    (("tmon.co.kr",), "티몬"),
    (("daangn.com", "karrotmarket.com"), "당근마켓"),
    (("bunjang.co.kr", "m.bunjang"), "번개장터"),
    (("aliexpress.", "ko.aliexpress"), "알리익스프레스"),
    (("tiktok.com",), "틱톡"),
    (("facebook.com", "fbsbx.com", "fb.com"), "페이스북"),
    (("pinterest.", "pinimg.com"), "핀터레스트"),
    (("youtube.com", "youtu.be"), "유튜브"),
    (("threads.net",), "스레드"),
    (("x.com", "twitter.com"), "X(트위터)"),
]

# 실제 플랫폼 신고 절차 조사 결과(2026-07 기준)를 반영한 안내 문구.
PLATFORM_SUBMISSION_GUIDE = {
    "쿠팡": "쿠팡 판매자신고센터(신뢰관리센터)에 상표등록증/저작권 등록증 등 권리 증명자료와 상세페이지 캡처를 첨부해 접수. 처리에 통상 12일~12주 소요.",
    "네이버 스마트스토어": "네이버 스마트스토어 고객센터의 지식재산권 침해 신고센터를 통해 접수, 원 저작물 증빙과 침해 게시물 URL 필요.",
    "인스타그램": "Instagram 도움말 센터의 저작권 신고 양식(저작권자 본인 확인 필요)으로 접수.",
    "11번가": "11번가 고객센터 지식재산권 침해 신고 메뉴로 접수.",
    "지마켓": "지마켓 고객센터 지식재산권 침해 신고 페이지로 접수.",
    "옥션": "옥션 고객센터 지식재산권 침해 신고 페이지로 접수.",
    "위메프": "위메프 고객센터 지식재산권 침해 신고로 접수, 권리 증명자료와 침해 게시물 URL 첨부.",
    "티몬": "티몬 고객센터 지식재산권 침해 신고로 접수, 권리 증명자료와 침해 게시물 URL 첨부.",
    "당근마켓": "당근마켓 앱 내 해당 판매글의 '신고하기'로 지식재산권 침해 사유를 선택해 접수(증빙 첨부). 미해결 시 고객센터로 문의.",
    "번개장터": "번개장터 고객센터의 지식재산권 침해 신고로 해당 상품글 URL과 권리 증빙을 첨부해 접수.",
    "알리익스프레스": "AliExpress 지식재산권 보호 플랫폼(IPP Center)에 권리자 등록 후 침해 상품을 신고.",
    "틱톡": "TikTok의 지식재산권 침해 신고(저작권 신고) 양식으로 침해 영상/게시물 URL과 권리 증빙을 제출.",
    "페이스북": "Meta(페이스북) 저작권 신고 양식으로 접수, 권리자 본인 확인 필요.",
    "핀터레스트": "Pinterest 저작권 침해 신고(DMCA) 양식으로 접수.",
    "유튜브": "YouTube 저작권 침해 신고(웹 양식) 또는 저작권 관리 도구로 접수.",
    "스레드": "Threads(Meta) 저작권 신고 양식으로 접수, 권리자 본인 확인 필요.",
    "X(트위터)": "X(트위터) 저작권(DMCA) 신고 양식으로 침해 게시물 URL과 권리 증빙을 제출.",
}


def detect_platform(shop: str, source_url: str | None) -> str:
    """매치의 판매처/URL에서 플랫폼을 자동으로 추정한다. 사용자가 매번 수동으로
    고르게 하는 대신, 실제로 어디서 발견됐는지 기반으로 신고서 문구를 맞춘다."""
    haystack = f"{shop} {source_url or ''}".lower()
    for domains, name in PLATFORM_DOMAIN_HINTS:
        if any(d in haystack for d in domains):
            return name
    return "오픈마켓/SNS 일반"


def platform_channels(pairs) -> str:
    """(shop, source_url) 목록에서 감지된 플랫폼별 신고 채널을 건수와 함께 요약한다."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for shop, url in pairs:
        plat = detect_platform(shop, url)
        if plat not in counts:
            counts[plat] = 0
            order.append(plat)
        counts[plat] += 1
    lines = []
    for plat in order:
        guide = PLATFORM_SUBMISSION_GUIDE.get(
            plat,
            "해당 사이트 고객센터의 지식재산권·저작권 침해 신고 절차로 접수하고, "
            "미해결 시 내용증명 발송 후 민형사 절차를 검토합니다.",
        )
        lines.append(f"- {plat} ({counts[plat]}건): {guide}")
    return "\n".join(lines)
