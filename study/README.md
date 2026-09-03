# 주석 없이 읽는 SQL — 평가 피드백 대응 학습 자료

카페 주문 DB 과제(`codyssey_B5-1`)에서 받은 피드백 8개를, 같은 스키마·같은 쿼리로 되짚는다.
개념을 다시 배우는 자료가 아니라 **입이 열리는 속도**와 **원리 한 칸 아래**를 위한 자료다.

인용된 수치는 전부 이 저장소의 DB에서 실제로 실행해 확인한 값이다.

## 지금 할 일 — 하나만

지금 A4 백지 한 장에 customer·category·menu·order_header·order_detail 다섯 테이블과 FK 화살표, 그리고 각 테이블의 행 수(10/10/12/12/20)를 손으로 그려라.

## 읽는 방법

- 브라우저로 읽으려면 [`study-kit.html`](study-kit.html) 을 연다 (전체 자료 한 파일, 접었다 펼 수 있음).
- 에디터에서 읽으려면 아래 모듈 파일을 순서대로 연다.
- **한 번에 다 읽지 마라.** [`00-study-plan.md`](00-study-plan.md) 의 날짜가 가리키는 모듈만 연다.

## 피드백 8개가 어디로 갔나

| # | 평가자가 지적한 것 | 다루는 모듈 |
|---|---|---|
| 1 | 데이터베이스 사용법을 조금 더 공부했으면 좋겠다 | [07-db-selection](07-db-selection.md) |
| 2 | 쿼리 읽는 속도가 느리다. 조인과 서브쿼리가 느리다 | [01-reading-drill](01-reading-drill.md) |
| 3 | CHECK 같은 키워드가 실질적으로 어떻게 작동하는지 | [04-constraint](04-constraint.md) |
| 4 | 상황에 따라 어떤 DB를 쓸지를 학습했으면 | [07-db-selection](07-db-selection.md) |
| 5 | 인덱싱이 왜 인덱싱인지, 어떻게 저장되고 탐색되는지 | [05-index](05-index.md) |
| 6 | 쿼리에 달린 주석을 지웠으면 한다 | [01-reading-drill](01-reading-drill.md) |
| 7 | 정규화, N:M은 브릿지 테이블로 1:N + N:1 | [06-normalization](06-normalization.md) |
| 8 | 서브쿼리와 조인을 자신감 있게 설명했으면 | [03-subquery](03-subquery.md) |

## 모듈

| | 모듈 | 내용 | 분량 |
|---|---|---|---|
| `01` | [주석 없이 쿼리 읽기](01-reading-drill.md) | 실행 순서를 읽기 절차로 바꾸고, 3초 안에 입이 열리게 만든다. 평가에서 실제로 막힌 지점. | 40,146자 |
| `02` | [조인 완전정복](02-join.md) | 조인은 곱한 뒤 거르는 것이다. 행이 늘어나는지 줄어드는지를 즉답하는 감각. | 27,931자 |
| `03` | [서브쿼리 완전정복](03-subquery.md) | 위치·상관 여부로 즉시 분류하고, 조인과 상호 변환한다. NOT IN의 NULL 함정까지. | 32,594자 |
| `04` | [CHECK·제약조건의 실제 동작](04-constraint.md) | CHECK가 언제 어떻게 검사되고, 그 에러가 애플리케이션까지 어떤 경로로 올라오는가. | 38,381자 |
| `05` | [인덱스 — 왜 인덱싱인가](05-index.md) | 왜 하필 "색인"인가. 배열·해시맵·역색인에서 B+Tree까지, 실제 페이지를 따라가며. | 41,863자 |
| `06` | [정규화와 N:M 브릿지 테이블](06-normalization.md) | 1NF부터 BCNF까지 이 스키마로 유도한다. order_detail이 이미 브릿지 테이블이다. | 36,506자 |
| `07` | [DB 사용법과 상황별 선택](07-db-selection.md) | DB는 용도가 정해진 게 아니다. 접근 패턴으로 고르는 법과, 그 전에 갖출 사용법. | 51,388자 |

## 훈련 파일

주석을 전부 제거한 쿼리 모음. 원본 주석은 다 말한 뒤에만 연다.

| 파일 | 쿼리 수 | 원본 |
|---|---|---|
| [`../drill/03_queries_naked.sql`](../drill/03_queries_naked.sql) | 31 | `03_queries.sql` |
| [`../drill/04_bonus_naked.sql`](../drill/04_bonus_naked.sql) | 20 | `04_bonus.sql` |

## 훈련용 DB 만들기

저장소의 `cafe.db` 는 Q13·Q14 가 이미 반영된 사후 상태다(주문 10건 / 상세 18행 / 아메리카노 4000원).
교재의 숫자와 맞추려면 `01`+`02` 만 적용한 초기 상태를 따로 만든다.

```bash
cd /home/coder/volume/codyssey_B5-1
python3 - <<'PY'
import sqlite3, os
os.path.exists("fresh.db") and os.remove("fresh.db")
c = sqlite3.connect("fresh.db")
c.execute("PRAGMA foreign_keys=ON")
for f in ("01_schema.sql", "02_data.sql"):
    c.executescript(open(f, encoding="utf-8").read())
c.commit()
print(c.execute("SELECT COUNT(*) FROM order_header").fetchone())  # (12,) 나오면 정상
PY
```

초기 상태 기준 행 수: `customer 10 / category 10 / menu 12 / order_header 12 / order_detail 20`
