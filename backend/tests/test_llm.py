"""로컬 LLM 신고서 다듬기의 '환각 차단' 검증 로직 테스트.

모델 자체(llama.cpp)는 무겁고 비결정적이라 CI에서 돌리지 않는다. 대신 안전의 핵심인
_passes_guard(모델 출력이 법적 사실을 훼손/날조했는지 판정)를 직접 검증한다. 이 가드가
통과시킨 출력만 사용자에게 나가고, 실패하면 원본 템플릿으로 폴백하므로, 이 테스트가
곧 "모델이 무슨 소리를 하든 법적 사실은 안 바뀐다"는 보장을 지킨다.
"""
from ml.llm import _passes_guard, _statutes, refine_document

TEMPLATE = (
    "---문서1---\n"
    "[내용증명 초안]\n"
    "1. 발신인은 저작권자입니다.\n"
    "2. 저작권법 제125조에 따라 손해배상을 청구합니다.\n"
    "3. 수신일로부터 10일 이내에 금 123,000원(금 십이만삼천원)의 배상을 요청합니다.\n"
    "---문서2---\n"
    "[손해배상 청구 내역서]\n"
    "예상 피해액: 123,000원\n"
)


def test_faithful_rewrite_passes():
    # 문장만 다듬고 법 조항·금액·기한·구분자를 모두 유지 → 통과
    refined = (
        "---문서1---\n"
        "[내용증명 초안]\n"
        "1. 발신인은 본 저작물의 정당한 저작권자입니다.\n"
        "2. 저작권법 제125조에 근거하여 손해배상을 청구합니다.\n"
        "3. 본 서면 수신일로부터 10일 이내에 금 123,000원(금 십이만삼천원)을 배상하여 주시기 바랍니다.\n"
        "---문서2---\n"
        "[손해배상 청구 내역서]\n"
        "예상 피해액: 123,000원\n"
    )
    assert _passes_guard(TEMPLATE, refined) is True


def test_fabricated_statute_is_rejected():
    # 템플릿에 없던 '저작권법 제136조'를 지어냄 → 거부
    refined = TEMPLATE.replace("제125조에 따라", "제125조 및 제136조에 따라")
    assert _passes_guard(TEMPLATE, refined) is False


def test_altered_amount_is_rejected():
    # 금액을 몰래 바꿈 → 거부
    refined = TEMPLATE.replace("123,000원", "999,000원")
    assert _passes_guard(TEMPLATE, refined) is False


def test_dropped_document_section_is_rejected():
    # 문서2를 통째로 빼먹음(구분자 개수 감소) → 거부
    refined = TEMPLATE.split("---문서2---")[0]
    assert _passes_guard(TEMPLATE, refined) is False


def test_dropped_deadline_is_rejected():
    # 이행 기한(10일)이 사라짐 → 거부
    refined = TEMPLATE.replace("10일 이내에 ", "")
    assert _passes_guard(TEMPLATE, refined) is False


def test_empty_output_is_rejected():
    assert _passes_guard(TEMPLATE, "") is False


def test_statutes_extraction_ignores_spacing():
    assert _statutes("제125조") == _statutes("제 125 조")


def test_refine_falls_back_to_template_without_model(monkeypatch):
    # 모델이 없는 환경에서는 원본 템플릿과 ai_generated=False를 그대로 돌려준다
    monkeypatch.setenv("LOCAL_LLM_PATH", "/nonexistent/model.gguf")
    text, ai = refine_document(TEMPLATE)
    assert text == TEMPLATE
    assert ai is False
