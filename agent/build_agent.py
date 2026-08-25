"""채용공고 함정 추출 에이전트 정의를 만든다. 손으로 JSON 을 고치지 않는다.

스키마의 다섯 항목 중 넷은 표본 세 건에 라벨을 달다가 나왔다. 무엇이 왜
들어갔는지는 각 필드 옆 주석과 docs/golden/ 의 메모에 있다.
"""
import io
import json
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8", errors="replace")

CLASSES = [
    ("HIRING_NOTICE",
     "공공기관·공기업의 직원 채용 공고문. 모집분야, 응시자격, 전형절차, 제출서류가 "
     "적혀 있다. 표제가 「채용 공고」·「모집 공고」·「신규채용」 계열이다"),
    ("OTHER_REVIEW_REQUIRED",
     "채용공고문이 아닌 것. 직무기술서(NCS 기반 포함), 입사지원 서식·양식, "
     "가점 기준 안내문, 제안요청서 등. 채용과 관련 있어도 공고문 본문이 "
     "아니면 여기다"),
]

# 🔴 빈 칸 규약: 문서가 정하지 않은 것은 빈 문자열로 둔다. 추측해서 채우지 않는다.
EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        # 해양환경공단이 연령·자격·승선·운전면허로 기준일이 넷이었다. 값 하나로는 안 담긴다.
        "date_bases": {
            "type": "array",
            "description": "응시자격·가점을 언제 시점으로 판단하는지 정한 조항. 항목마다 시점이 다르면 다른 줄로 뽑는다",
            "items": {"type": "object", "properties": {
                "applies_to": {"type": "string", "description": "이 시점이 걸리는 대상. 연령·자격/면허·학력·병역·경력·가점 등 문서가 쓴 말 그대로"},
                "basis": {"type": "string", "description": "시점 원문. 예 「접수마감일 기준」 「임용예정일 기준」 「공고일 현재」"},
                "quote": {"type": "string", "description": "그 시점이 적힌 줄 전체를 그대로. 줄이지 않는다"},
                "source_page": {"type": "integer", "description": "인쇄된 쪽 번호. 확정 못 하면 0"}}}},
        # 분당서울대학교병원은 장애인이 필수 응시요건이면서 우대 사유였다. UNCLEAR 가 있어야 담긴다.
        "requirements": {
            "type": "array",
            "description": "자격 항목을 한 줄에 하나씩",
            "items": {"type": "object", "properties": {
                "item": {"type": "string", "description": "자격 조건 원문"},
                # 🔴 판정(kind)을 뺐다. 모델에게 뽑기와 판정을 같이 시키면 둘 다 나빠진다
                #    (2026-08-25: 절차를 줬더니 대조는 했는데 항목 22개를 버렸다).
                #    어느 절에서 왔는지만 받고 판정은 뒤에서 코드와 Solar 가 한다.
                "section": {"type": "string", "description": "이 항목이 적힌 절 제목 그대로. 예 「응시자격」 「우대사항」 「특전」 「가점」"},
                "quote": {"type": "string"},
                "source_page": {"type": "integer"}}}},
        # 해양환경공단은 합산에 상한 10%, 소상공인시장진흥공단은 택일이었다. 정반대라 열거값으로 둔다.
        # 🔴 최상위 속성에 object 를 못 쓴다 (API 검증 오류로 배웠다). 배열로 둔다.
        #    소상공인시장진흥공단에 「제한경쟁(장애)의 경우 장애인 가점 미적용」처럼
        #    전형별 예외가 있어서, 배열이 사실에도 더 맞다.
        "bonus_stacking": {
            "type": "array",
            "description": "가점이 여러 개 해당될 때의 처리. 전형·분야별로 규칙이 다르면 여러 줄로",
            "items": {"type": "object", "properties": {
                "applies_to": {"type": "string", "description": "이 규칙이 걸리는 전형·분야. 전체면 빈 문자열"},
                "rule": {"type": "string", "description": "SUM(합산) · CHOOSE_ONE(가장 높은 것 하나) · NONE(가점 제도 없음) · UNCLEAR(가점은 있는데 규칙이 없다) 중 하나"},
                "cap": {"type": "string", "description": "상한 원문. 예 「각 채용단계별 만점의 10% 이내」. 없으면 빈 문자열"},
                "quote": {"type": "string"},
                "source_page": {"type": "integer"}}}},
        # 소상공인시장진흥공단의 「입사지원서 내 정보입력자에 한하여 가점 인정」 — 날짜가 아니라 행위가 조건이다.
        "bonus_conditions": {
            "type": "array",
            "description": "가점을 받으려면 지원자가 해야 하는 일. 날짜가 아닌 조건만",
            "items": {"type": "object", "properties": {
                "condition": {"type": "string", "description": "예 「입사지원서에 해당 정보를 입력해야 함」 「증명서 제출처를 기관명으로 명시」"},
                "quote": {"type": "string"},
                "source_page": {"type": "integer"}}}},
        # 분당서울대학교병원은 면접 합격자만 서류를 낸다. 마감에서 역산하는 구조가 아니다.
        "documents": {
            "type": "array",
            "description": "제출서류를 한 줄에 하나씩",
            "items": {"type": "object", "properties": {
                "name": {"type": "string", "description": "서류 이름. 문서에 적힌 대로"},
                "issuer_external": {"type": "string", "description": "외부 기관에서 발급받아야 하면 YES, 자기 작성 서식이면 NO, 모르면 빈 문자열"},
                "when": {"type": "string", "description": "지원시 · 합격후 · UNCLEAR 중 하나"},
                "form_constraint": {"type": "string", "description": "발급 형식 조건. 예 「문서확인번호가 표기된 증명서」 「원본」. 없으면 빈 문자열"},
                "quote": {"type": "string"},
                "source_page": {"type": "integer"}}}},
    },
}

CLASSIFY_PROMPT = """이 Agent 는 공공기관 채용공고에서 지원자가 놓치기 쉬운 조항을 뽑는다.
먼저 입력 문서가 채용공고문 본문인지 가른다.

표제를 먼저 본다. 「채용 공고」·「모집 공고」·「신규채용」 계열이고 모집분야와
응시자격과 전형절차가 있으면 HIRING_NOTICE 다.

직무기술서는 채용공고문이 아니다. NCS 기반 직무기술서, 입사지원 서식, 가점 기준
안내문처럼 채용과 관련은 있으나 공고문 본문이 아닌 것은 전부 OTHER_REVIEW_REQUIRED 다.
채용 절차 전체가 아니라 한 직무의 능력단위만 서술하고 있으면 직무기술서다.

애매하면 OTHER_REVIEW_REQUIRED 로 보낸다. 아닌 문서를 채용공고로 읽으면 뒤 단계가
없는 값을 지어낸다."""

EXTRACT_PROMPT = """입력은 공공기관 채용공고문이다. 문서에 명시된 사실만 뽑는다.
요약하지 않고, 추측하지 않고, 지원 여부를 판단하지 않는다.

빈 칸 규약이 이 Agent 의 핵심이다. 문서가 정하지 않은 것은 빈 문자열로 둔다.
0 이나 그럴듯한 기본값으로 채우면 읽는 사람이 그것을 문서에 적힌 사실로 읽는다.
모르는 것을 모른다고 두는 쪽이 값이 있다.

quote 는 원문 그대로 옮긴다. 띄어쓰기가 없는 문서는 없는 대로 둔다. 다듬으면
나중에 원문과 대조할 수 없다.

date_bases 는 시점이 여러 개면 여러 줄로 뽑는다. 연령은 임용예정일 기준인데
자격·면허는 접수마감일 기준인 문서가 실제로 있다. 하나로 합치지 않는다.

requirements 에는 문서에 있는 자격 항목을 **빠짐없이** 넣는다. 응시자격·지원자격
절의 모든 줄, 우대사항·가점·특전 절의 모든 줄이 대상이다. 근무 형태 조건, 병역,
졸업 여부, 정년 같은 것도 자격 항목이다.

필수인지 우대인지는 **판정하지 마라.** 그 항목이 적힌 절 제목을 section 에 그대로
옮기면 된다. 판정은 뒤 단계가 한다. 여기서 판정까지 하려 들면 뽑기가 나빠진다.

bonus_stacking 의 rule 은 SUM 과 CHOOSE_ONE 을 헷갈리지 않는다. 「중복될 경우
합산」과 「중복될 경우 가장 높은 것 하나」는 정반대다. 가점 항목은 있는데 중복
규칙이 없으면 UNCLEAR 다. 「중복지원 불가」는 가점과 무관하니 여기 넣지 않는다.
"""


def steps():
    return [
        {"name": "step_1_parse", "type": "document-parse", "is_first": True,
         "data": {"model": "document-parse", "mode": "auto", "ocr": "auto",
                  "chart_recognition": False, "coordinates": True,
                  "merge_multipage_tables": True, "output_formats": ["html", "text"],
                  "base64_encoding": ["figure"]},
         "next_steps": [{"step_name": "step_2_classify", "condition": None}]},
        {"name": "step_2_classify", "type": "document-classify", "is_first": False,
         "data": {"text": {"format": {"name": "document-classify", "type": "json_schema",
                                      "schema": {"type": "string", "oneOf": [
                                          {"const": c, "description": d} for c, d in CLASSES]}}},
                  "user_system_prompt": CLASSIFY_PROMPT},
         "next_steps": [{"step_name": "step_3_extract_traps",
                         "condition": {"field": "text", "operator": "==", "value": "HIRING_NOTICE"}}]},
        {"name": "step_3_extract_traps", "type": "information-extract", "is_first": False,
         "data": {"custom_name": "extract_hiring_traps",
                  "text": {"format": {"name": "document-schema", "type": "json_schema",
                                      "schema": EXTRACT_SCHEMA}},
                  "schema_layout": {"version": 1, "columns": [
                      {"name": k, "source": "root"} for k in EXTRACT_SCHEMA["properties"]]},
                  # 🔴 기존 에이전트는 location 이 false 라 필드마다 쪽 번호가 안 왔다. 켠다.
                  "location": True, "location_granularity": "all", "confidence": True,
                  "many_rows": True, "many_rows_threshold": 20,
                  "many_rows_max_rows_per_batch": 40, "many_rows_max_concurrent": 5,
                  "user_system_prompt": EXTRACT_PROMPT},
         "next_steps": []},
    ]


def steps_extract_only(parse_fixed=True):
    """분류 없는 판. parse -> extract 만.

    🔴 조각내서 넣을 때 필요하다. 조각마다 분류를 다시 태우면 표제와 모집분야가
    없는 뒷조각이 전부 OTHER_REVIEW_REQUIRED 로 거절된다 (2026-08-25: 다섯 조각
    중 셋이 그렇게 죽었다). 분류는 원본으로 한 번만 하고 조각은 추출만 태운다.
    """
    s = steps()
    parse, extract = s[0], s[2]
    parse["next_steps"] = [{"step_name": extract["name"], "condition": None}]
    if parse_fixed:
        # ② 에서 토큰 편차를 34% 에서 2% 로 줄인 설정
        parse["data"].update({"ocr": "skip", "merge_multipage_tables": False})
    return [parse, extract]


if __name__ == "__main__":
    doc = {"name": "hiring-traps", "description": "공공기관 채용공고에서 놓치기 쉬운 조항을 뽑는다",
           "steps": steps()}
    io.open("agent/hiring-traps.json", "w", encoding="utf-8", newline="\n").write(
        json.dumps(doc, ensure_ascii=False, indent=1))
    print("agent/hiring-traps.json 갱신")
