"""로컬 오픈소스 LLM(Qwen2.5-1.5B-Instruct GGUF, Apache-2.0)으로 신고서 '문장만'
다듬는 모듈. llama.cpp(CPU)로 구동한다.

핵심 원칙 — 모델은 법적 사실의 주인이 아니다:
- 법 조항 번호·금액·날짜·기한·URL·상호·유사도 수치 같은 법적 사실은 전부 코드가
  만든 템플릿(main.py)이 소유한다.
- 모델은 그 완성본 텍스트를 더 자연스러운 한국어로 '다시 쓰기'만 한다.
- 모델 출력은 반드시 아래 검증(_passes_guard)을 통과해야 채택되고, 하나라도 어긋나면
  원본 템플릿을 그대로 돌려준다. 따라서 모델이 법 조항을 지어내거나 금액을 바꾸는
  환각은 최종 결과에 반영되지 않는다.

성능/크기:
- 모델은 신고서/가이드 요청이 처음 들어올 때 지연 로딩된다(스캔 경로는 모델을 전혀
  건드리지 않으므로 콜드스타트 영향 없음).
- 모델 파일이 없거나(llama_cpp 미설치, 파일 부재) 로드에 실패하면 조용히 템플릿
  폴백으로 동작한다 → 로컬 개발/쿠버네티스(모델 미포함)에서도 그대로 돌아간다.
"""
import os
import re
import sys
import threading

_lock = threading.Lock()
_llm = None
_load_failed = False

_SYSTEM_PROMPT = (
    "너는 한국어 법률 문서 교정 전문가야. 사용자가 준 문서를 더 자연스럽고 정중하며 "
    "전문적인 한국어 문장으로 다시 써. 단, 다음은 절대 바꾸거나, 새로 추가하거나, "
    "삭제하지 마: 법 조항 번호(예: 저작권법 제125조), 모든 금액과 숫자, 날짜·기한(예: 10일), "
    "URL, 상호·플랫폼 이름, 유사도 퍼센트, '---문서N---' 구분자, '[ ]' 로 표시된 빈칸. "
    "문서에 없는 법 조항이나 사실을 새로 지어내지 마. 문장 흐름과 격식만 다듬어. "
    "서론이나 설명 없이, 다듬은 문서 본문만 그대로 출력해."
)

_STATUTE_RE = re.compile(r"제\s*\d+\s*조")
_SECTION_RE = re.compile(r"---문서\d+---")
_AMOUNT_RE = re.compile(r"[0-9][0-9,]*원")
_HANGUL_AMOUNT_RE = re.compile(r"금\s*[가-힣]+원")


def _get_llm():
    global _llm, _load_failed
    if _llm is not None or _load_failed:
        return _llm
    with _lock:
        if _llm is not None or _load_failed:
            return _llm
        model_path = os.environ.get("LOCAL_LLM_PATH", "/models/model.gguf")
        if not os.path.exists(model_path):
            _load_failed = True
            return None
        try:
            from llama_cpp import Llama

            _llm = Llama(
                model_path=model_path,
                n_ctx=4096,
                n_threads=int(os.environ.get("LOCAL_LLM_THREADS", os.cpu_count() or 4)),
                verbose=False,
            )
        except Exception as e:
            _load_failed = True
            print(f"[llm] 모델 로드 실패({type(e).__name__}): {e} → 템플릿 폴백", file=sys.stderr)
    return _llm


def _statutes(text: str) -> set[str]:
    return {re.sub(r"\s+", "", s) for s in _STATUTE_RE.findall(text)}


def _required_tokens(template: str) -> set[str]:
    """다듬은 결과에 반드시 그대로 남아 있어야 하는 안전 필수 문자열."""
    toks: set[str] = set()
    toks |= set(_AMOUNT_RE.findall(template))          # 123,000원
    toks |= {re.sub(r"\s+", "", t) for t in _HANGUL_AMOUNT_RE.findall(template)}  # 금 십이만삼천원
    if "10일" in template:
        toks.add("10일")
    return toks


def _passes_guard(template: str, refined: str) -> bool:
    """모델 출력이 법적 사실을 훼손/날조하지 않았는지 검증한다."""
    if not refined or len(refined) < len(template) * 0.5:
        return False
    # 1) 새 법 조항 인용 금지: 출력의 조항 집합이 템플릿 조항 집합의 부분집합이어야 함
    if not _statutes(refined) <= _statutes(template):
        return False
    # 2) 문서 구분자 개수 유지(문서를 통째로 빼먹지 않았는지)
    if len(_SECTION_RE.findall(refined)) != len(_SECTION_RE.findall(template)):
        return False
    # 3) 금액·기한 등 핵심 문자열이 그대로 살아있는지(공백 제거 후 비교)
    refined_flat = re.sub(r"\s+", "", refined)
    for token in _required_tokens(template):
        if re.sub(r"\s+", "", token) not in refined_flat:
            return False
    return True


def refine_document(template_text: str, max_tokens: int = 1400) -> tuple[str, bool]:
    """템플릿 문서를 로컬 LLM으로 다듬는다. (다듬은 문서, AI사용여부)를 반환하며,
    모델이 없거나 검증에 실패하면 (원본 템플릿, False)을 반환한다."""
    llm = _get_llm()
    if llm is None:
        return template_text, False
    try:
        out = llm.create_chat_completion(
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": template_text},
            ],
            temperature=0.3,
            max_tokens=max_tokens,
        )
        refined = out["choices"][0]["message"]["content"].strip()
    except Exception:
        return template_text, False

    if _passes_guard(template_text, refined):
        return refined, True
    return template_text, False
