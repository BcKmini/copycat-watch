"""API 요청 본문(pydantic) 모델. 신고서·통합 신고서·법적 가이드 요청 스키마를 모은다."""
from pydantic import BaseModel


class ReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    match_shop: str
    match_note: str
    similarity: float
    platform: str | None = None
    source_url: str | None = None
    estimated_damage: int | None = None


class BatchMatchItem(BaseModel):
    shop: str
    note: str
    similarity: float
    source_url: str | None = None
    estimated_damage: int | None = None


class BatchReportRequest(BaseModel):
    product_name: str
    seller_name: str = "본인"
    matches: list[BatchMatchItem]


class GuideMatch(BaseModel):
    shop: str = ""
    source_url: str | None = None


class LegalGuideRequest(BaseModel):
    product_name: str
    total_matches: int
    verified_matches: int
    total_damage: int = 0
    repeated_infringement: bool = False
    matches: list[GuideMatch] = []
