"""신고서·통합 신고서·법적 대응 가이드 텍스트 생성.

법적 사실(법 조항·금액·기한 등)은 전부 코드가 만드는 템플릿이 소유하고, 로컬 LLM은
문장만 다듬는다(llm.refine_document의 안전 가드가 검증). 각 함수는 (문서, AI사용여부)를
돌려준다.
"""
from core.config import ASSUMED_MONTHLY_SALES
from core.money import format_amount
from ml.llm import refine_document
from reports.platforms import PLATFORM_SUBMISSION_GUIDE, detect_platform, platform_channels
from reports.schemas import BatchReportRequest, LegalGuideRequest, ReportRequest

# 실제 절차 조사 결과(2026-07 기준):
# - 소액사건심판법 제2조: 소가 3,000만원 이하 민사 제1심 사건 대상
# - 저작권법 제125조: 손해배상 청구 시 침해자의 이익액을 손해액으로 추정
# - 한국저작권위원회 저작권 상담센터: 창작자·소상공인 대상 무료 저작권 법률 컨설팅
# - 대한법률구조공단: 국번없이 132, 경제적 어려움이 있는 국민 대상 무료 법률상담/소송대리
LEGAL_RESOURCES = (
    "한국저작권위원회 저작권 상담센터(copyright.or.kr, 무료 저작권 법률 컨설팅), "
    "대한법률구조공단(국번없이 132, 무료 법률상담 및 요건 충족 시 무료 소송대리)"
)


def build_report(req: ReportRequest) -> tuple[str, bool]:
    """단일 매치에 대한 신고 사유서·내용증명·손해배상 청구내역서(플랫폼 맞춤)."""
    platform = req.platform or detect_platform(req.match_shop, req.source_url)
    submission_guide = PLATFORM_SUBMISSION_GUIDE.get(platform)

    damage_doc = (
        f"예상 피해액: {format_amount(req.estimated_damage)}\n산정 근거: 판매가 x 월 예상판매량 {ASSUMED_MONTHLY_SALES}개(데모 가정치)\n"
        f"법적 근거: 저작권법 제125조 - 침해자가 침해행위로 얻은 이익액을 저작재산권자의 손해액으로 추정"
        if req.estimated_damage
        else "정확한 피해액 산정을 위해서는 상대방의 실제 판매 이력·매출 자료 확인이 필요합니다. "
             "플랫폼에 정보 제공을 요청하거나(저작권법 제125조 손해액 추정 규정 근거), "
             "소송상 문서제출명령으로 확보할 수 있습니다."
    )
    guide_doc = f"\n\n[신고 접수처] {submission_guide}" if submission_guide else ""
    template = (
        "---문서1---\n"
        f"[{platform} 신고 사유서]\n"
        f"본인은 '{req.product_name}' 상품 이미지의 원 판매자 겸 저작권자입니다. "
        f"'{req.match_shop}'에서 본인의 상품 이미지가 무단으로 사용되고 있음을 확인했습니다({req.match_note}). "
        f"이미지 유사도 분석 결과 {req.similarity}% 일치하여 명백한 도용으로 판단됩니다. "
        "원본 이미지, 최초 판매 게시 스크린샷, 침해 게시물 캡처를 증빙자료로 첨부하며, "
        f"해당 게시물의 판매 중지 및 이미지 삭제 조치를 요청합니다.{guide_doc}\n\n"
        "---문서2---\n"
        "[내용증명 초안]\n"
        "발신인: [본인 성명/상호/주소]\n수신인: [상대방 상호/성명/주소]\n\n"
        f"1. 발신인은 '{req.product_name}' 상품 이미지의 저작권자 겸 판매자입니다.\n"
        f"2. 수신인은 발신인의 이용 허락 없이 위 상품 이미지를 '{req.match_shop}'에서 무단 사용하여 "
        f"발신인의 저작권을 침해하고 있음을 확인하였습니다({req.match_note}, 이미지 유사도 {req.similarity}%).\n"
        "3. 본 내용증명을 수신한 날로부터 10일 이내에 해당 게시물의 판매를 중단하고 이미지를 삭제할 것과, "
        f"{('금 ' + format_amount(req.estimated_damage) if req.estimated_damage else '피해액')}"
        "의 배상을 요청합니다.\n"
        "4. 위 기한 내 이행되지 않을 경우, 저작권법 위반에 따른 민형사상 법적 조치(고소 및 손해배상 청구 소송)를 "
        "진행할 수 있음을 알려드립니다.\n\n"
        "본 내용증명은 우체국 내용증명 우편으로 발송해 발신 사실과 도달을 증명하는 것을 권장합니다 "
        "(총 3부 작성: 발신인 보관용 / 수신인 발송용 / 우체국 보관용).\n\n"
        "---문서3---\n"
        f"[손해배상 청구 내역서]\n{damage_doc}"
    )
    return refine_document(template, max_tokens=1400)


def build_batch_report(req: BatchReportRequest) -> tuple[str, bool]:
    """여러 매치를 묶은 통합 신고 사유서·내용증명 + 플랫폼별 접수처."""
    total_damage = sum(m.estimated_damage or 0 for m in req.matches)
    # 각 침해 건에 발견된 플랫폼을 함께 표기한다(같은 상품이라도 플랫폼마다 접수처가 다름).
    listing = "\n".join(
        f"  - {m.shop} [{detect_platform(m.shop, m.source_url)}] (유사도 {m.similarity}%)"
        for m in req.matches
    )
    platform_block = platform_channels([(m.shop, m.source_url) for m in req.matches])
    damage_text = format_amount(total_damage) if total_damage else "산정 불가(판매 이력 확인 필요)"
    template = (
        "---문서1---\n"
        f"[통합 신고 사유서]\n"
        f"본인은 '{req.product_name}' 상품 이미지의 원 판매자 겸 저작권자입니다. "
        f"아래 {len(req.matches)}곳에서 본인의 상품 이미지가 무단으로 사용되고 있음을 확인했습니다:\n{listing}\n\n"
        f"총 예상 피해액은 {damage_text}으로 산정되며, 각 게시물의 원본 이미지·침해 게시물 캡처를 "
        "증빙자료로 첨부하여 판매 중지 및 이미지 삭제 조치를 일괄 요청합니다.\n\n"
        "---문서2---\n"
        "[통합 내용증명 초안]\n"
        "발신인: [본인 성명/상호/주소]\n수신인: [각 상호/성명/주소]\n\n"
        f"1. 발신인은 '{req.product_name}' 상품 이미지의 저작권자 겸 판매자입니다.\n"
        f"2. 수신인들은 발신인의 이용 허락 없이 위 상품 이미지를 아래와 같이 무단 사용하여 "
        f"저작권을 침해하고 있음을 확인하였습니다:\n{listing}\n"
        f"3. 본 내용증명을 수신한 날로부터 10일 이내에 전 게시물의 판매를 중단하고 이미지를 삭제할 것과, "
        f"금 {damage_text}의 배상을 요청합니다.\n"
        "4. 위 기한 내 이행되지 않을 경우, 저작권법 위반에 따른 민형사상 법적 조치(고소 및 손해배상 청구 소송)를 "
        "진행할 수 있음을 알려드립니다.\n\n"
        "본 내용증명은 우체국 내용증명 우편으로 발송해 발신 사실과 도달을 증명하는 것을 권장합니다 "
        "(총 3부 작성: 발신인 보관용 / 수신인 발송용 / 우체국 보관용).\n\n"
        "---문서3---\n"
        f"[플랫폼별 신고 접수처]\n발견된 각 플랫폼의 신고 채널이 다르므로 아래 절차에 따라 개별 접수합니다.\n{platform_block}"
    )
    return refine_document(template, max_tokens=2000)


def build_legal_guide(req: LegalGuideRequest) -> tuple[str, bool]:
    """발견 건수·피해액·발견 플랫폼에 맞춘 법적 대응 가이드."""
    is_small_claim = req.total_damage <= 30_000_000
    claim_line = (
        f"예상 피해액이 {format_amount(req.total_damage)}으로 소가 3,000만원 이하 기준에 해당해, "
        "소액사건심판법 제2조에 따른 소액사건심판(1회 변론기일 원칙의 신속 절차)을 활용할 수 있습니다."
        if req.total_damage and is_small_claim
        else "예상 피해액이 3,000만원을 초과하거나 산정되지 않아, 일반 민사소송 절차 검토가 필요합니다."
    )
    lawsuit_note = (
        "\n반복적/조직적 도용 정황이 확인되어 손해액이 커질 수 있으므로 정식 소송도 함께 검토해볼 만합니다."
        if req.repeated_infringement else ""
    )

    # 이 상품이 발견된 플랫폼별 신고 채널(있을 때만). 상품·플랫폼에 따라 절차가 달라진다.
    platform_block = platform_channels([(m.shop, m.source_url) for m in req.matches])

    intro = (
        f"'{req.product_name}' 상품 이미지 도용 건에 대한 맞춤 대응 가이드입니다. "
        f"현재까지 총 {req.total_matches}곳에서 도용이 의심되며, 이 중 {req.verified_matches}곳은 "
        "서버 실측 검증을 통과했습니다.\n\n"
    )

    # 섹션을 순서대로 구성하고 자동으로 번호를 매긴다(플랫폼 섹션 유무에 따라 번호가 바뀜).
    sections = [
        ("우선순위 대응 순서",
         "게시물 삭제가 급하다면 플랫폼 신고를 먼저 진행하고, 공식적인 경고와 증거 확보를 위해 "
         "내용증명을 함께 발송하는 것이 일반적입니다. 이후에도 해결되지 않으면 민형사 절차를 검토합니다."),
        ("민사/형사 대응 가능성",
         "저작권법 제125조에 따라 침해자가 그 침해행위로 얻은 이익액을 저작재산권자의 손해액으로 "
         "추정하여 손해배상을 청구할 수 있습니다. 사안에 따라 저작권법 위반으로 형사 고소도 가능합니다."),
        ("소송 형태 판단", f"{claim_line}{lawsuit_note}"),
    ]
    if platform_block:
        sections.append((
            "발견된 플랫폼별 신고 채널",
            "이 상품이 도용된 플랫폼마다 접수처·절차가 다릅니다. 아래를 참고해 각각 접수하세요.\n"
            + platform_block,
        ))
    sections.append(("무료 법률 지원 연결처", LEGAL_RESOURCES))
    sections.append((
        "유의사항",
        "본 가이드는 일반적인 절차 안내이며 구체적인 법률 자문이 아닙니다. "
        "실제 진행 전 위 상담처를 통해 전문가 확인을 받으시길 권장합니다.",
    ))

    body = "\n\n".join(f"{i + 1}. {title}\n{content}" for i, (title, content) in enumerate(sections))
    template = intro + body
    return refine_document(template, max_tokens=1400)
