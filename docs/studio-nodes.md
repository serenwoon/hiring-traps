# Upstage Studio 노드 14 종 — 문서 없이 찔러서 알아낸 계약

2026-08-25. 문서를 못 찾아서 API 를 찔렀다. 빈 설정을 보내면 서버가 무엇이 빠졌는지 알려주고, 채워서 다시 보내면 다음 것을 알려준다. 재현 스크립트는 `probe/node_contracts.py` 다.

## 노드는 넷이 아니라 열넷이다

없는 종류를 넣으면 서버가 전부 나열해 준다.

    class-generate · class-update · document-classify · document-parse · export
    information-extract · instruct · instruct-generate · match · merge · review
    schema-generate · schema-update · validate

## 그런데 쓰이는 것은 넷뿐이다

내 계정 에이전트 열아홉 개가 실제로 쓴 노드를 셌다.

| 노드 | 사용 |
|---|---|
| information-extract | 34 |
| document-parse | 19 |
| document-classify | 14 |
| instruct | 8 |
| 나머지 열 종 | **0** |

`validate` · `match` · `export` · `merge` · `review` 와 `*-generate` · `*-update` 계열이 전부 0 이다.

## 안 쓰이는 쪽에 파이프라인을 닫는 것들이 몰려 있다

| 노드 | 계약 | 무엇으로 읽히나 |
|---|---|---|
| `validate` | `checks: [{name, condition}]`, condition 은 `RuleGroup` 이고 `logic` 이 필수 | 이름 붙은 검사 규칙. AND/OR 로 묶는 중첩 조건을 받는다 |
| `match` | `custom_name`, `targets: [{collection_id, ...}]` 최소 하나 | 문서끼리 대주는 것이 아니라 **미리 만든 컬렉션에 맞춰보는 것** |
| `export` | `CollectionExportDefinition` 또는 `HttpExportDefinition` | 컬렉션 저장, 또는 **HTTP 로 내보내기** |
| `merge` | split 켠 `document-classify` 가 **정확히 하나** 있어야 한다 | 쪼갠 문서를 다시 합치는 짝 |
| `review` | `next_steps: null` 강제 | 사람이 보는 자리. 반드시 파이프라인 끝 |
| `document-classify` | `split: true` 를 받는다 | 한 파일 안에 여러 서류가 섞였을 때 가르는 옵션 |

여덟 종은 `data` 를 비워도 설정이 통과한다. 값 검증을 그 시점에 안 한다는 뜻이고, 실행할 때 무엇이 일어나는지는 따로 봐야 한다.

## 이 관찰이 이 저장소에 준 것

**`split` 과 `merge` 를 몰라서 헛수고했다.** 28 쪽 문서를 PyMuPDF 로 일곱 쪽씩 쪼개고 결과를 손으로 합쳤다. 조각마다 분류를 다시 타서 다섯 중 셋이 거절됐고, 그것을 고치려고 분류 없는 설정을 따로 만들었다. Studio 안에 쪼개고 합치는 짝이 이미 있었다.

**`validate` 도 같은 자리다.** 겹침 판정을 코드로 짜서 밖에 뒀는데 파이프라인 안에 검사 노드가 있다. 다만 `match` 는 아니었다 — 컬렉션을 먼저 만들어야 해서 이 용도에 안 맞는다.

## 왜 안 쓰이는지에 대한 짐작

확인한 것이 아니라 짐작이다. `match` 는 컬렉션을 미리 만들어야 하고, `export` 는 내보낼 곳이 있어야 하고, `validate` 는 규칙 트리를 손으로 짜야 한다. 셋 다 **문서를 읽는 것 바깥에 준비가 필요하다.**

읽는 노드는 파일만 있으면 되고 나머지는 준비가 필요하다. 그래서 공개 에이전트들이 「이해」에서 멈추는 것으로 보인다.

## 캐다 만 것

`validate` 의 `RuleGroup.logic` 이 무엇을 받는지 아직 모른다. `export` 의 두 갈래도 필드까지만 봤다. `split: true` 를 켜고 실제로 돌렸을 때 출력이 어떻게 나오는지도 안 봤다.
