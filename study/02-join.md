# 조인 완전정복

> 평가 피드백 2, 8 대응 — 조인은 곱한 뒤 거르는 것이다. 행이 늘어나는지 줄어드는지를 즉답하는 감각.

---

## 조인 완전정복 — 겁먹지 말고 스키마 보면서 말하기

> **실측 환경**: `01_schema.sql` + `02_data.sql` 만 적용한 초기 상태(03의 UPDATE/DELETE 전), SQLite 3.46.1.
> 실제 행 수는 `customer` 10, `category` 10, `menu` 12, `order_header` 12(COMPLETED 9, CANCELLED 2, PENDING 1), `order_detail` 20.
> 아래 숫자는 전부 이 DB에서 직접 돌려 확인한 값이다. 발표할 때 **숫자를 근거로 말하면 자신감은 저절로 생긴다.**
>
> **⚠ 저장소에 들어 있는 `cafe.db`로는 이 숫자가 재현되지 않는다.** 그 파일은 이미 03의 Q13/Q14/Q15까지 적용된 상태다. 재현 방법은 9절을 먼저 볼 것.

| 항목 | 이 문서의 기준(01+02만) | 저장소의 `cafe.db` (03까지 적용됨) |
|---|---|---|
| `order_header` | **12행** (CANCELLED 2 포함) | 10행 (Q14가 CANCELLED 2건 삭제) |
| `order_detail` | **20행** | 18행 (CASCADE로 함께 삭제) |
| `menu` 아메리카노 가격 | **3,500원** | 4,000원 (Q13의 UPDATE) |
| 인덱스 | 자동 인덱스(UNIQUE)만 | `idx_order_header_customer_id`, `idx_order_detail_order_id` 추가 |
| `customer, order_header` 카티션 곱 | **120** | 100 |

---

## 1. 조인의 정체 — "곱하고 나서 거른다"

조인을 어렵게 느끼는 이유는 `JOIN`을 "연결하는 마법"으로 배웠기 때문이다. 개념 모델은 훨씬 단순하다.

> **조인 = 두 테이블의 모든 조합(카티션 곱)을 만든 뒤, ON 조건으로 살아남을 행만 남기는 것.**

`ON`을 빼고 실제로 돌려보면 바로 보인다.

```sql
-- ON 없음 = 카티션 곱
SELECT COUNT(*) FROM customer, order_header;   -- 실측 120
```

| 단계 | 쿼리 | 행 수 |
|---|---|---|
| 곱하기 | `FROM customer, order_header` | **120** (= 고객 10 × 주문 12) |
| 거르기 | `... JOIN order_header oh ON oh.customer_id = c.id` | **12** |

120행 중 조건을 통과한 12행만 남는다. 12는 우연이 아니라 **`order_header`의 전체 행 수**다. 모든 주문은 반드시 고객 한 명에 속하므로(`customer_id NOT NULL` + FK), 주문 12건은 각자 짝을 정확히 하나씩 찾는다.

**실제 엔진이 120행을 진짜 만드는가?** 아니다. 개념 모델일 뿐이고 실행은 다르다. Q6를 그대로(단, `ORDER BY` 없이) 돌린 SQLite의 실행계획을 보자.

```text
SCAN od
SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
SEARCH c  USING INTEGER PRIMARY KEY (rowid=?)
SEARCH m  USING INTEGER PRIMARY KEY (rowid=?)
```

`03_queries.sql`의 Q6에는 `ORDER BY oh.id, od.id`가 붙어 있으므로 **실제 계획은 다섯 줄**이다. 마지막 한 줄이 더 찍힌다.

```text
SCAN od
SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
SEARCH c  USING INTEGER PRIMARY KEY (rowid=?)
SEARCH m  USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY          -- ORDER BY를 인덱스로 못 풀어 임시 B-Tree로 정렬
```

바깥 테이블을 한 줄씩 훑으면서(`SCAN`), 그 값으로 안쪽 테이블을 인덱스로 찍어 찾는다(`SEARCH`). 이게 **중첩 루프 조인(nested loop join)** 이다. 의사코드로는 이렇다.

```python
for od in order_detail:                  # SCAN - 20번
    oh = order_header[od.order_id]       # SEARCH - PK 한 방
    c  = customer[oh.customer_id]        # SEARCH - PK 한 방
    m  = menu[od.menu_id]                # SEARCH - PK 한 방
    emit(...)
```

참고로 Q15의 인덱스가 이미 걸린 `cafe.db`에서 같은 Q6를 돌리면 **계획 자체가 바뀐다**. 바깥 루프가 인덱스 스캔으로 바뀌고 조인 순서도 재배치된다.

```text
SCAN od USING INDEX idx_order_detail_order_id
SEARCH m  USING INTEGER PRIMARY KEY (rowid=?)
SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
SEARCH c  USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY
```

> **발표 포인트**: "실행계획은 데이터와 인덱스 상태에 따라 달라집니다"는 말을 근거 없이 하면 약하다. **같은 쿼리·같은 데이터인데 인덱스 두 개 때문에 조인 순서까지 바뀐 두 계획**을 나란히 보여주면 그 말이 증거가 된다.

| DBMS | 지원하는 조인 알고리즘 |
|---|---|
| **SQLite** | 중첩 루프 **한 가지뿐**. 대신 필요하면 `AUTOMATIC (PARTIAL) COVERING INDEX`(질의 시점에 만들었다 버리는 임시 인덱스)와 `BLOOM FILTER`를 즉석에서 만들어 보완한다 — Q10 실행계획에 실제로 둘 다 찍힌다 |
| **MySQL 8** | 중첩 루프(+ 인덱스 기반). **8.0.18에서 해시 조인 도입**, **8.0.20에서 Block Nested-Loop가 제거되고 해시 조인이 그 자리를 대체**(8.0.20부터 아우터/세미/안티 조인, 인덱스가 있는 경우까지 확대). **머지 조인은 없다** |
| **PostgreSQL** | 중첩 루프 + 해시 조인 + 머지 조인, 통계 기반으로 옵티마이저가 선택. 14부터 파라미터화 중첩 루프에 `Memoize` 캐시가 추가 |

Q10(고객별 매출, LEFT JOIN 2단)의 실측 계획이 SQLite의 보완 장치를 그대로 보여준다.

```text
SCAN c
BLOOM FILTER ON oh (customer_id=? AND status=?)
SEARCH oh USING AUTOMATIC PARTIAL COVERING INDEX (customer_id=? AND status=?) LEFT-JOIN
BLOOM FILTER ON od (order_id=?)
SEARCH od USING AUTOMATIC COVERING INDEX (order_id=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```

`BLOOM FILTER`는 "안쪽에 짝이 없는 게 확실한 바깥 행"을 인덱스 탐색 전에 걸러내는 확률적 필터다(거짓 양성은 있어도 거짓 음성은 없다). `AUTOMATIC ... COVERING INDEX`는 인덱스가 없어서 SQLite가 그 자리에서 만든 임시 인덱스다 — **"인덱스를 안 만들어도 SQLite가 알아서 해 준다"가 아니라, 매 실행마다 인덱스를 새로 만드는 비용을 치르고 있다는 신호**다. Q15에서 진짜 인덱스를 만들면 이 줄들이 사라진다(위 `cafe.db` 계획 참고).

### `SEARCH ... USING INTEGER PRIMARY KEY (rowid=?)`는 왜 싼가

중첩 루프의 안쪽 탐색이 싼 이유를 자료구조로 설명할 수 있으면 질문 하나를 통째로 막는다. DBMS마다 구조가 다르므로 뭉뚱그리면 안 된다.

| DBMS | 테이블 저장 구조 | 세컨더리 인덱스 조회 비용 |
|---|---|---|
| **SQLite** | 테이블 b-tree는 **rowid를 키로 하고 데이터를 리프에만 두는 B+Tree**. `INTEGER PRIMARY KEY`는 rowid의 별칭이라 **PK = 저장 순서** | 인덱스 b-tree는 **내부 페이지에도 키를 두는 B-Tree**로, 엔트리는 (인덱스 키…, rowid). 커버링이 아니면 인덱스 하강 1번 + 테이블 하강 1번 |
| **MySQL / InnoDB** | 테이블 자체가 **PK 클러스터드 인덱스(B+Tree)**. 리프에 행 전체가 들어 있다 | 세컨더리 인덱스 리프에는 **물리 주소가 아니라 PK 값**이 들어 있다. 커버링이 아니면 **클러스터드 인덱스를 한 번 더 타야 한다**(회귀 조회). PK가 길면 모든 세컨더리 인덱스가 함께 뚱뚱해진다 |
| **PostgreSQL** | **힙(heap)** — 클러스터드 인덱스가 없다. 인덱스는 테이블과 완전히 별개 | 인덱스 리프에 **TID(물리 위치)** 가 들어 있어 힙을 한 번 더 읽는다. index-only scan이 가능하지만 **visibility map을 확인**해야 하고, VACUUM이 밀리면 결국 힙을 읽는다 |

용어 하나만 정확히 해 두면 좋다. 실무에서 인덱스로 쓰는 구조는 대부분 **B+Tree**(값은 리프에만, 리프끼리 연결되어 범위 스캔이 순차 읽기가 된다)다. 그런데 `CREATE INDEX ... USING btree`나 `USE TEMP B-TREE` 같은 **이름은 관례적으로 B-Tree**로 붙어 있다. "B-Tree라고 쓰여 있지만 실제 구현은 B+Tree인 경우가 많다"까지 말할 수 있으면 충분하다.

**말로 하는 대본**
> "조인은 개념적으로 두 테이블을 전부 곱한 다음 ON 조건으로 거르는 겁니다. 고객 10명과 주문 12건이면 ON 없이는 120행이 나오고, `oh.customer_id = c.id`를 걸면 12행이 남습니다. 실제 엔진은 120행을 만들진 않고, SQLite는 중첩 루프로 바깥 테이블을 훑으면서 안쪽을 rowid로 찍어 찾습니다. `INTEGER PRIMARY KEY`가 rowid 별칭이라 B-Tree를 한 번만 내려가면 행에 바로 닿거든요."

---

## 2. 조인 6종 — 이 스키마 기준 한 줄 예시

| 종류 | 이 스키마에서의 질문 | 결과 |
|---|---|---|
| **INNER** | "메뉴별 카테고리명" `menu m JOIN category c ON c.id = m.category_id` | **12행**. 양쪽에 짝이 있어야 남는다 |
| **LEFT** | "메뉴가 0개인 카테고리까지 포함" `category c LEFT JOIN menu m ON m.category_id = c.id` | **원시 13행** → `GROUP BY c.id` 후 **10행**. '굿즈'가 `menu_count = 0`으로 보존 |
| **RIGHT** | `FROM menu m RIGHT JOIN category c ON c.id = m.category_id` | LEFT를 뒤집은 것. **원시 13행** → 집계 후 **10행**, '굿즈' 0 보존 |
| **FULL OUTER** | "짝 없는 카테고리 + 짝 없는 메뉴를 한 번에" | **원시 13행**. 이 스키마에선 `menu.category_id NOT NULL` + FK라 부모 없는 메뉴가 없어 LEFT와 결과가 같다 |
| **CROSS** | "모든 카테고리 × 모든 고객 조합표" (리포트 격자 만들 때) | 실측 **100행** |
| **SELF** | "같은 카테고리 안의 메뉴 가격 짝비교" | **4쌍** |

> **자주 하는 실수**: LEFT JOIN을 "행 수가 유지되는 조인"으로 외우면 여기서 틀린다. 카테고리 10개에 LEFT JOIN을 걸어도 **원시 결과는 13행**이다. 10행은 `GROUP BY` 이후의 숫자다. 자세한 건 3절.

```sql
-- SELF JOIN: 같은 테이블을 별칭 두 개로 부른다
SELECT a.name AS menu_a, b.name AS menu_b, a.price AS price_a, b.price AS price_b
FROM   menu a
JOIN   menu b ON b.category_id = a.category_id AND b.id > a.id;
-- 실측 4행: 아메리카노-바닐라라떼 / 아메리카노-카페라떼 / 카페라떼-바닐라라떼 / 녹차-얼그레이
```

`b.id > a.id`가 핵심이다. 이걸 빼면 자기 자신끼리(아메리카노-아메리카노)도 붙고 (A,B)와 (B,A)가 중복으로 나온다. `b.id <> a.id`로 바꾸면 자기 자신만 빠지고 (A,B)/(B,A) 중복은 그대로 남는다 — 반드시 **부등호**여야 한다.

### DBMS 지원 차이 — 틀리게 말하면 바로 걸린다

| 문법 | SQLite | MySQL 8 | PostgreSQL |
|---|---|---|---|
| `INNER JOIN` / `LEFT JOIN` | O | O | O |
| `RIGHT JOIN` | **3.39.0(2022-06-25) 이상만 O** | O | O |
| `FULL OUTER JOIN` | **3.39.0 이상만 O** | **X (현재 버전에도 없음)** | O |
| `CROSS JOIN`에 `ON` 붙이기 | **O** (실측: 12행 = INNER JOIN과 동일) | **O** (`JOIN`/`INNER JOIN`/`CROSS JOIN`이 문법적 동의어) | **X** (표준대로 join qualification 불가) |
| `CROSS JOIN` 키워드의 부가 의미 | **SQLite 고유: 왼쪽 테이블을 반드시 바깥 루프로 고정(옵티마이저의 순서 재배치 금지)** | 없음 | 없음 |

> **주의**: "CROSS JOIN에 ON을 붙이는 건 표준 위반이니 SQLite에서 막힌다"는 흔한 오해다. **실제로 SQLite는 받아 준다.** 실측으로 `SELECT COUNT(*) FROM menu m CROSS JOIN category c ON c.id = m.category_id` → 12를 확인했다. SQLite에서 `CROSS JOIN`은 조인 순서 힌트일 뿐 결과 의미를 바꾸지 않는다. 막히는 건 PostgreSQL이다.

**`NATURAL JOIN`은 이 스키마에서 특히 위험하다.**

```sql
SELECT COUNT(*) FROM menu m NATURAL JOIN category c;   -- 실측 0행
```

`menu`와 `category`는 `id`와 `name`을 **둘 다** 갖고 있어서 NATURAL JOIN이 두 컬럼 전부를 조인 조건으로 쓴다. `m.id = c.id AND m.name = c.name`을 만족하는 행은 없으니 조용히 0행이 나온다. 에러도 안 난다. **조인 조건은 항상 `ON`으로 명시한다.**

MySQL 8에서 FULL OUTER가 필요하면 흉내를 내야 한다.

```sql
-- MySQL 8: FULL OUTER JOIN 대체 (안전한 형태)
SELECT c.name AS category_name, m.name AS menu_name
FROM   category c LEFT JOIN menu m ON m.category_id = c.id
UNION ALL
SELECT c.name, m.name
FROM   category c RIGHT JOIN menu m ON m.category_id = c.id
WHERE  c.id IS NULL;          -- 오른쪽에만 있는 행만 추가
```

흔히 보이는 `LEFT ... UNION RIGHT ...` 버전도 결과 행 수는 같지만(실측 13행으로 셋 다 일치), **`UNION`은 중복을 제거하므로 원본에 정말 존재하는 중복 행까지 함께 지워 버린다.** 이 데이터에는 중복이 없어서 우연히 맞은 것이다. `UNION ALL` + `WHERE 왼쪽PK IS NULL` 형태가 의미상 정확한 대체다.

**말로 하는 대본**
> "RIGHT JOIN과 FULL OUTER JOIN은 SQLite 3.39부터 지원됩니다. 제 환경은 3.46이라 둘 다 돌아가는 걸 확인했고요. MySQL 8은 지금도 FULL OUTER JOIN이 없어서 LEFT에 RIGHT의 '오른쪽 전용 행'만 UNION ALL로 붙여야 합니다. 그냥 UNION으로 붙이면 진짜 중복까지 지워지거든요. PostgreSQL은 넷 다 됩니다."

---

## 3. 행 수 감각 — 카디널리티만 보면 즉답이 된다

이게 평가에서 "읽는 속도"를 가르는 지점이다. 조인 한 줄을 볼 때마다 세 가지 중 하나로 즉시 분류하는 습관을 들인다.

| 붙이는 방향 | 관계 | 행 수 변화 | 이 스키마의 예 |
|---|---|---|---|
| **자식을 붙인다** (상대의 FK가 내 PK를 가리킴) | 1:N | **늘어난다** (= 매칭 개수의 합) | `order_header` → `order_detail` (12 → 20) |
| **부모를 붙인다** (내 FK가 상대의 PK를 가리킴) | N:1 | **정확히 유지** (아래 세 조건이 모두 성립할 때) | `order_detail` → `menu`, `order_detail` → `order_header` (20 → 20) |
| **짝이 없을 수 있다** | 1:0..N | INNER면 **왼쪽 행이 사라질 수 있다**, LEFT면 **사라지지는 않는다** — 다만 **짝이 2개 이상이면 여전히 늘어난다** | `category` → `menu`: INNER 12행(굿즈 소멸), LEFT **13행**(굿즈 NULL 1줄 추가) |

> **정정 포인트**: LEFT JOIN이 보장하는 것은 "**왼쪽 행이 하나도 사라지지 않는다**"이지 "**행 수가 유지된다**"가 아니다. 실측으로 `category`(10행) LEFT JOIN `menu` = **13행**이다. 굿즈만 NULL 한 줄로 보존되고, 메뉴가 3개인 '커피'는 3줄로 불어난다. `GROUP BY c.id`로 묶어야 비로소 10행이 된다.

**"부모를 붙이면 행 수 유지"가 성립하려면 세 조건이 모두 필요하다.**
1. FK 컬럼이 `NOT NULL`일 것 (NULL이면 INNER에서 그 행이 사라진다)
2. 참조 대상이 PK 또는 UNIQUE일 것 (짝이 2개면 늘어난다)
3. **FK 무결성이 실제로 지켜지고 있을 것** — SQLite는 `PRAGMA foreign_keys`가 **연결(connection)마다 기본 OFF**라, 검사 없이 들어간 고아 FK가 있으면 INNER JOIN에서 행이 조용히 줄어든다. MySQL/PostgreSQL은 기본 활성이라 이 걱정이 없다.

`customer`를 기준으로 자식·부모를 차례로 붙이며 실측한 결과다.

| 체인 | 행 수 | 판정 |
|---|---|---|
| `customer` | 10 | 시작 |
| `+ JOIN order_header` (자식, 1:N) | **12** | 늘어남 |
| `+ JOIN order_detail` (자식, 1:N) | **20** | 늘어남 |
| `+ JOIN menu` (부모, N:1) | **20** | 유지 |
| `+ JOIN category` (부모, N:1) | **20** | 유지 |

### `order_header`(12행) INNER JOIN `order_detail` → 왜 20행인가

주문 12건에 상세 라인이 총 20줄 달려 있기 때문이다. 주문별 라인 수를 뽑아보면 근거가 딱 나온다.

| order_id | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 합 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 라인 수 | 2 | 2 | 2 | 1 | 2 | 1 | 2 | 2 | 1 | 2 | 1 | 2 | **20** |

즉 조인 결과의 행 수는 왼쪽 테이블 행 수가 아니라 **"오른쪽에서 매칭된 개수의 합"** 이다. 라인이 2줄인 주문은 결과에서 2번 등장한다. 이 사실 하나가 다음 절의 모든 함정의 원인이다.

**말로 하는 대본**
> "조인 결과의 행 수는 부모 기준이 아니라 매칭된 자식 개수의 합입니다. `order_header` 12건에 `order_detail` 라인이 20줄이니까 INNER JOIN 결과는 20행입니다. 반대로 `order_detail`에 `menu`를 붙이면 `menu_id`가 NOT NULL 외래키고 참조 대상이 PK라 정확히 하나만 붙어서 20행 그대로입니다."

---

## 4. 집계 폭발(fan-out) — 학습자 Q10-B에 실제로 있는 문제

`order_detail`을 붙이는 순간 부모 행이 복제된다. 그 상태에서 부모를 세면 라인 수를 세게 된다.

```sql
-- 틀린 쿼리: 고객별 주문 건수를 세려고 했는데
SELECT c.id, c.name, COUNT(oh.id) AS order_count
FROM   customer c
JOIN   order_header oh ON oh.customer_id = c.id
JOIN   order_detail od ON od.order_id    = oh.id
GROUP  BY c.id, c.name;
```

김민준(id=1)의 조인 결과를 펼치면 왜 틀리는지가 눈에 보인다.

| customer | order_id | detail_id | menu | 비고 |
|---|---|---|---|---|
| 김민준 | 1 | 1 | 아메리카노 | order 1이 두 번 등장 |
| 김민준 | 1 | 2 | 크로와상 | ↑ |
| 김민준 | 2 | 3 | 카페라떼 | order 2가 두 번 등장 |
| 김민준 | 2 | 4 | 티라미수 | ↑ |
| 김민준 | 12 | 19 | 아메리카노 | order 12가 두 번 등장 |
| 김민준 | 12 | 20 | 티라미수 | ↑ |

`COUNT(oh.id)`는 이 6줄에서 NULL 아닌 `oh.id`를 세므로 **6**이 나온다. 실제 주문은 **3건**이다.

| customer | `COUNT(oh.id)` (틀림) | `COUNT(DISTINCT oh.id)` (정답) | 부풀림 |
|---|---|---|---|
| 김민준 | 6 | **3** | ×2 |
| 이서연 | 3 | **2** | ×1.5 |
| 최예린 | 2 | **1** | ×2 |
| 한소희 | 2 | **1** | ×2 |
| 오재현 | 2 | **1** | ×2 |
| 장민서 | 2 | **1** | ×2 |
| 박지호 / 정우진 / 윤하늘 | 1 | 1 | 라인이 1줄뿐이라 우연히 일치 |

(서지안은 주문이 없어 INNER JOIN 결과에 아예 등장하지 않는다 — 결과는 9행.)

**여기가 진짜 무서운 지점이다.** 라인이 1줄인 주문만 있는 고객은 값이 우연히 맞아서, 눈으로 검증하면 "맞는데?" 하고 넘어가게 된다. 데이터가 커지면 조용히 전부 틀린다.

`COUNT(DISTINCT oh.id)`가 답인 이유는 명확하다. **`oh.id`는 PK라 주문 한 건당 값이 유일하므로, 중복 제거하면 복제 이전의 주문 개수로 정확히 되돌아간다.** 반대로 말하면 **DISTINCT 대상이 유일하지 않은 컬럼이면 이 처방은 통하지 않는다** — 예를 들어 `COUNT(DISTINCT oh.status)`는 복원이 아니라 전혀 다른 값이 된다.

Q10-B는 `customer LEFT JOIN order_header` 한 단계만 쓰기 때문에 `DISTINCT`가 없어도 지금은 값이 같다(실측: `COUNT(oh.id)`와 `COUNT(DISTINCT oh.id)`가 다른 고객 0명). 하지만 `DISTINCT`를 써 둔 판단은 옳다. **나중에 누군가 `order_detail`을 한 줄 더 붙이는 순간 `DISTINCT` 없는 쿼리는 조용히 틀린 값을 뱉기 때문이다.**

같은 함정은 카테고리 쪽에도 있다.

```sql
-- 카테고리별 '메뉴 개수'를 주문과 함께 보려다 폭발
SELECT cat.name,
       COUNT(m.id)          AS wrong_cnt,   -- RIGHT는 3.39부터 키워드라 별칭으로 쓰지 않는다
       COUNT(DISTINCT m.id) AS right_cnt
FROM   category cat
JOIN   menu m         ON m.category_id = cat.id
JOIN   order_detail od ON od.menu_id   = m.id
GROUP  BY cat.id, cat.name;
-- 실측 '커피': wrong_cnt = 9, right_cnt = 3
--   9 = 아메리카노 5줄 + 카페라떼 2줄 + 바닐라라떼 2줄 (각 메뉴가 등장한 주문 라인 수만큼 복제)
```

**금액은 왜 안 틀렸나?** Q10의 `SUM(od.quantity * od.unit_price)`는 멀쩡하다. **집계 대상이 복제된 부모 컬럼이 아니라, 복제의 원인인 `order_detail` 자기 자신의 컬럼이기 때문이다.** 규칙으로 정리하면 이렇다.

> **집계 함수의 대상 컬럼이 "가장 잘게 쪼개진 테이블(grain)"의 것이면 안전하다. 그보다 상위 테이블의 컬럼을 세거나 더하면 반드시 DISTINCT를 쓰거나 서브쿼리로 분리해야 한다.**

**주의**: `SUM(DISTINCT ...)`는 이 문제의 해법이 **아니다**. 서로 다른 두 라인의 금액이 우연히 같으면 하나로 뭉개진다. 상위 테이블의 **금액**을 더해야 한다면(예: 주문 헤더에 배송비가 있다면) DISTINCT가 아니라 **서브쿼리로 미리 집계해서 붙이는 것**이 유일하게 안전한 방법이다.

```sql
-- 안전한 패턴: 자식을 먼저 grain 단위로 집계한 뒤 1:1로 붙인다
SELECT c.id, c.name, COALESCE(s.total_paid, 0) AS total_paid
FROM   customer c
LEFT   JOIN (
          SELECT oh.customer_id, SUM(od.quantity * od.unit_price) AS total_paid
          FROM   order_header oh
          JOIN   order_detail od ON od.order_id = oh.id
          WHERE  oh.status = 'COMPLETED'
          GROUP  BY oh.customer_id
       ) s ON s.customer_id = c.id;
-- 실측 10행, Q10과 금액 전부 일치 (김민준 42500 …)
```

**말로 하는 대본**
> "여기가 fan-out 함정입니다. `order_detail`을 붙이면 주문 한 건이 라인 수만큼 복제됩니다. 김민준은 주문 3건인데 라인이 6줄이라 `COUNT(oh.id)`가 6이 나옵니다. `oh.id`는 PK라서 `COUNT(DISTINCT oh.id)`로 세면 3으로 정확히 돌아옵니다. 반면 금액 `SUM`은 복제된 부모 컬럼이 아니라 라인 자신의 컬럼을 더하는 거라 영향이 없습니다."

---

## 5. ON vs WHERE — LEFT JOIN에서 필터 위치가 결과를 바꾼다

Q10에서 실제로 쓴 패턴이다. 논리적 실행 순서를 알면 왜 다른지가 자동으로 설명된다.

```text
FROM → JOIN(ON 평가 + LEFT의 NULL 확장) → WHERE → GROUP BY → HAVING → SELECT → ORDER BY
```

`ON`은 **NULL 확장이 일어나기 전**에 평가되고, `WHERE`는 **NULL 확장이 끝난 뒤**에 평가된다. 그래서 `WHERE oh.status = 'COMPLETED'`는 NULL로 채워진 행을 그대로 죽인다 — `NULL = 'COMPLETED'`는 참도 거짓도 아닌 **UNKNOWN**이고, WHERE는 **참인 행만** 통과시키기 때문이다.

| 단계 | ① `ON`에 필터 (Q10 원본) | ② `WHERE`로 옮김 |
|---|---|---|
| 1차 조인 직후 행 수 | **12행** (매칭 9 + NULL 확장 3) | **13행** (매칭 12 + NULL 확장 1) |
| WHERE 적용 후 | — (WHERE 없음) | **9행** |
| 최종 GROUP BY 결과 | **10행** | **7행** |
| 사라진 고객 | 없음 | 박지호·윤하늘·서지안 |
| 실질적 의미 | 진짜 LEFT JOIN | **사실상 INNER JOIN** |

최종 결과를 나란히 놓으면 이렇다.

| id | 고객 | ① ON 절 | ② WHERE 절 |
|---|---|---|---|
| 1 | 김민준 | 42,500 | 42,500 |
| 2 | 이서연 | 16,000 | 16,000 |
| **3** | **박지호** (취소 1건) | **0** | *행 자체가 없음* |
| 4 | 최예린 | 15,000 | 15,000 |
| 5 | 정우진 | 10,500 | 10,500 |
| 6 | 한소희 | 18,000 | 18,000 |
| 7 | 오재현 | 9,000 | 9,000 |
| 8 | 장민서 | 14,500 | 14,500 |
| **9** | **윤하늘** (취소 1건) | **0** | *행 자체가 없음* |
| **10** | **서지안** (주문 없음) | **0** | *행 자체가 없음* |

**의미 차이를 한 문장으로**
- `ON`의 조건 = **"어떤 오른쪽 행을 붙일 것인가"** — 못 붙여도 왼쪽 행은 산다.
- `WHERE`의 조건 = **"조인이 끝난 결과 중 어떤 행을 남길 것인가"** — 못 붙은 행은 죽는다.

**예외 규칙**: INNER JOIN에서는 `ON`이든 `WHERE`든 결과가 같다. NULL 확장 자체가 없기 때문이다. 그래서 "ON과 WHERE는 같다"는 오해가 생긴다. **다른 건 OUTER JOIN일 때뿐이고, 세 DBMS(SQLite/MySQL 8/PostgreSQL) 모두 이 동작은 표준대로 동일하다.**

**단, 예외의 예외**: `WHERE oh.status IS NULL`처럼 **NULL 확장된 행만 골라내는 조건**을 WHERE에 두는 건 의도된 사용이다. 바로 다음의 안티 조인이 그 경우다.

### 안티 조인 3형제 — 그리고 `NOT IN`의 NULL 함정

`WHERE`가 NULL 확장 행을 잡아낸다는 성질을 일부러 쓰면 **안티 조인**이 된다.

```sql
-- ① LEFT JOIN + IS NULL  (실측 1행: 서지안)
SELECT c.id, c.name
FROM   customer c
LEFT   JOIN order_header oh ON oh.customer_id = c.id
WHERE  oh.id IS NULL;

-- ② NOT EXISTS  (실측 1행: 서지안) — 가장 안전하다
SELECT c.id, c.name
FROM   customer c
WHERE  NOT EXISTS (SELECT 1 FROM order_header oh WHERE oh.customer_id = c.id);

-- ③ NOT IN  (실측 1행: 서지안) — 지금은 맞지만 조건부다
SELECT c.id, c.name
FROM   customer c
WHERE  c.id NOT IN (SELECT customer_id FROM order_header);
```

③이 지금 맞는 이유는 `order_header.customer_id`가 `NOT NULL`이기 때문이다. **목록에 NULL이 단 하나만 섞이면 결과가 통째로 0행이 된다.**

```sql
-- NULL 하나를 섞어 재현
SELECT c.id, c.name
FROM   customer c
WHERE  c.id NOT IN (SELECT customer_id FROM order_header UNION ALL SELECT NULL);
-- 실측 0행 (서지안조차 사라진다)
```

이유는 3값 논리다. `x NOT IN (a, b, NULL)`은 `x <> a AND x <> b AND x <> NULL`로 풀리는데, 마지막 항이 **항상 UNKNOWN**이라 AND 전체가 절대 TRUE가 될 수 없다(`TRUE AND UNKNOWN = UNKNOWN`). 결과는 언제나 빈 결과다. **에러도 경고도 없다.**

> **규칙: 서브쿼리 대상 컬럼이 NULL 가능이면 `NOT IN`을 쓰지 않는다. `NOT EXISTS` 또는 `LEFT JOIN ... IS NULL`을 쓴다.** 이 셋은 NULL이 없을 때만 결과가 같다.

### 덤: `CHECK` 제약도 같은 3값 논리를 따른다

`CHECK`는 조건이 **FALSE일 때만** 위반이다. **UNKNOWN이면 통과**한다. 즉 NULL 허용 컬럼에 `CHECK (v > 0)`를 걸어도 NULL은 그대로 들어간다.

```sql
CREATE TEMP TABLE t (v INTEGER CHECK (v > 0));
INSERT INTO t VALUES (1);      -- OK
INSERT INTO t VALUES (NULL);   -- ★ OK (NULL > 0 은 UNKNOWN → 통과)
INSERT INTO t VALUES (-1);     -- CHECK constraint failed: v > 0
-- 실측 결과 테이블에는 (1), (NULL) 두 행이 남는다
```

이 스키마의 `CHECK`가 안전한 건 대상 컬럼(`price`, `quantity`, `unit_price`, `is_available`, `status`)이 **전부 `NOT NULL`이기 때문**이다. `CHECK`는 `NOT NULL`을 대신하지 못한다 — 항상 짝으로 건다.

참고로 `CHECK` 제약의 DBMS 사정은 이렇다.

| DBMS | `CHECK` 강제 여부 |
|---|---|
| **SQLite** | 처음부터 강제 |
| **MySQL** | **8.0.16부터 강제.** 그 이전(5.7, 8.0.15 이하)은 **문법만 파싱하고 조용히 무시**했다 |
| **PostgreSQL** | 처음부터 강제 |

**말로 하는 대본**
> "`ON`은 조인 단계에서, `WHERE`는 조인이 끝난 뒤에 평가됩니다. LEFT JOIN은 짝이 없으면 오른쪽을 NULL로 채우는데, `NULL = 'COMPLETED'`는 거짓이 아니라 UNKNOWN이라 WHERE에서 그 행이 탈락합니다. 그래서 필터를 WHERE로 옮기면 10행이 7행으로 줄어서 사실상 INNER JOIN이 됩니다. 실측으로 박지호·윤하늘·서지안 세 명이 사라졌습니다. 같은 3값 논리 때문에 `NOT IN`은 목록에 NULL이 하나만 있어도 결과가 0행이 되고, `CHECK`는 NULL이면 UNKNOWN이라 통과합니다."

---

## 6. COUNT(*) vs COUNT(컬럼) — 0건이 1건으로 둔갑하는 이유

| 함수 | 세는 대상 |
|---|---|
| `COUNT(*)` | **행**을 센다. 컬럼이 전부 NULL이어도 행은 행이다 |
| `COUNT(oh.id)` | **`oh.id`가 NULL이 아닌 경우**만 센다 |
| `COUNT(DISTINCT oh.id)` | NULL 아닌 값 중 **중복 제거 후** 센다 |

Q7-B 실측 결과에서 차이가 나는 고객은 딱 한 명이다.

| id | 고객 | `COUNT(*)` | `COUNT(oh.id)` |
|---|---|---|---|
| 1 | 김민준 | 3 | 3 |
| 2 | 이서연 | 2 | 2 |
| 3~9 | 박지호·최예린·정우진·한소희·오재현·장민서·윤하늘 | 각 1 | 각 1 |
| **10** | **서지안** | **1** | **0** |

서지안은 주문이 0건이지만 LEFT JOIN이 `(서지안, NULL, NULL, NULL)` 한 줄을 만들어 준다. `COUNT(*)`는 그 줄을 1로 센다. **"주문 0건 고객"을 찾는 게 목적인 쿼리에서 0건 고객만 정확히 1로 나온다는 건, 그 쿼리가 목적을 정면으로 배신했다는 뜻이다.**

> **암기 규칙: LEFT JOIN + COUNT 조합에서는 절대 `COUNT(*)`를 쓰지 않는다. 반드시 오른쪽 테이블의 컬럼을 지정하고, 그 컬럼은 NULL이 될 수 없는 것(대개 PK)을 고른다.**

마지막 단서가 중요하다. `COUNT(oh.status)`처럼 NULL 가능 컬럼을 고르면 "짝은 있는데 그 컬럼만 NULL인 행"까지 빠져 또 다른 오답이 된다. `oh.id`가 정답인 이유는 PK라 **매칭된 행에서는 절대 NULL이 아님**이 보장되기 때문이다.

`SUM`도 같은 함정이 있다. 대상 행이 하나도 없으면 0이 아니라 **NULL**을 반환한다(값이 전부 NULL일 때도 NULL이다). 그래서 Q10에 `COALESCE(SUM(...), 0)`이 필요하다.

- `AVG`도 대상 행이 0개면 NULL이다. 게다가 `AVG(col)`은 **NULL인 행을 분모에서 아예 뺀다.** "0을 평균에 포함시키고 싶다"면 `SUM(COALESCE(col,0)) * 1.0 / COUNT(*)`로 직접 계산해야 한다.
- 반대로 `COUNT`만은 대상 행이 0개일 때 NULL이 아니라 **0**을 반환한다. 집계 함수 중 유일한 예외라 헷갈리지 않도록 따로 외운다.

이 동작은 SQLite/MySQL 8/PostgreSQL이 모두 동일하다(표준 SQL 규정). 다만 `GROUP BY`가 **없는** 집계 쿼리는 대상 행이 0개여도 **결과 1행**을 돌려주고, `GROUP BY`가 **있으면 0행**을 돌려준다 — 이것도 세 DBMS 공통이다.

---

## 7. 4테이블 체인 읽는 법 — 화이트보드 3단계

Q6를 예로 든다. 겁먹지 않는 유일한 방법은 **읽는 순서를 고정하는 것**이다.

```sql
FROM    order_detail od
INNER   JOIN order_header oh ON oh.id = od.order_id
INNER   JOIN customer     c  ON c.id  = oh.customer_id
INNER   JOIN menu         m  ON m.id  = od.menu_id
```

### 1단계 — FROM만 보고 "결과 한 행이 무엇인지" 선언한다

> "기준 테이블이 `order_detail`이니까 **결과 한 행은 주문 상세 한 줄**입니다."

이 한 문장을 먼저 말하면 나머지는 전부 그 문장의 부연이 된다. 조인은 **행을 만드는 게 아니라 컬럼을 붙이는 작업**으로 바뀐다.

### 2단계 — 화살표를 그린다 (FK가 어디를 가리키는지)

```text
              customer
                 ▲ (c.id = oh.customer_id)   N:1  행 유지
                 │
  order_detail ──┴─▶ order_header      (oh.id = od.order_id)  N:1  행 유지
       │
       └──────────▶ menu               (m.id = od.menu_id)    N:1  행 유지
                      │
                      └──▶ category    (N:1)  행 유지
```

화살표는 **자식 → 부모** 방향, 즉 FK가 PK를 가리키는 방향으로만 그린다. 그리고 나면 즉답할 수 있다.

> "붙이는 게 전부 부모 방향이고 FK가 전부 NOT NULL이니까 **행 수는 20행 그대로 유지**됩니다. 실측도 20행입니다."

### 3단계 — ON 조건을 "PK쪽 = FK쪽" 순서로 소리 내어 읽는다

`ON oh.id = od.order_id`를 **"주문 헤더의 아이디가 주문 상세의 주문 아이디와 같을 때"** 로 읽는다. 좌변에 항상 PK, 우변에 항상 FK를 두는 습관을 들이면 어느 쪽이 부모인지 한눈에 보이고, 읽는 속도가 눈에 띄게 빨라진다.

### 왜 `order_detail`이 FROM에 와야 하는가

`customer`부터 시작해도 결과는 같지만, **가장 잘게 쪼개진 테이블을 기준으로 잡으면 "이 조인이 행을 부풀리는가"를 고민할 일 자체가 없어진다.** 반대로 `customer`에서 시작하면 아래로 내려갈 때마다 10 → 12 → 20으로 부풀고, 그때부터 `DISTINCT`를 어디에 써야 하는지 계속 신경 써야 한다.

이건 **작성자의 가독성 원칙이지 성능 지시가 아니다.** SQLite·MySQL·PostgreSQL 모두 옵티마이저가 조인 순서를 알아서 재배치하므로, `FROM`에 무엇을 쓰든 실행계획은 같을 수 있다(1절에서 인덱스 유무만으로 순서가 바뀌는 걸 확인했다). 순서를 강제로 고정하고 싶을 때만 SQLite의 `CROSS JOIN` 힌트를 쓴다.

> **원칙: 결과 한 행의 정의(grain)를 먼저 정하고, 그 grain의 테이블을 FROM에 둔다. 나머지는 전부 부모를 붙이는 작업으로만 남긴다.**

**말로 하는 대본 (Q6 통으로 30초)**
> "`order_detail`을 기준으로 잡았으니 결과 한 행은 주문 상세 한 줄입니다. 거기에 `order_id`로 주문 헤더를 붙이고, 그 헤더의 `customer_id`로 고객을 붙이고, 상세의 `menu_id`로 메뉴를 붙였습니다. 셋 다 자식에서 부모로 올라가는 N:1이라 행이 부풀지 않고 20행 그대로입니다. 마지막 `quantity * unit_price`는 라인별 금액인데, `menu.price`를 조인해서 쓰지 않고 `order_detail.unit_price`를 쓴 이유는 주문 시점 단가 스냅샷이라 가격이 바뀌어도 과거 매출이 소급 변경되지 않게 하려는 겁니다. 실제로 Q13에서 아메리카노를 3,500원에서 4,000원으로 올려도 과거 주문 합계는 3,500원 기준 그대로입니다."

---

## 8. 예상 질문 8개 + 30초 대본

각 답은 **① 한 줄 정의 → ② 이 스키마의 숫자 → ③ 실무적 의미** 순서로 짜여 있다. 이 세 박자를 지키면 30초에 정확히 맞고, 중간에 막혀도 다음 박자로 넘어가면 된다.

**Q1. 조인이 뭔지 설명해 보세요.**
> "조인은 개념적으로 두 테이블을 전부 곱한 다음 ON 조건으로 거르는 겁니다. 제 DB에서 고객 10명과 주문 12건을 ON 없이 곱하면 120행이 나오는데, `oh.customer_id = c.id`를 걸면 12행이 남습니다. 실제 엔진은 120행을 다 만들지는 않고, SQLite는 중첩 루프로 바깥을 훑으면서 안쪽을 rowid로 찍어 찾습니다. 정규화로 테이블을 나눈 대가를 조인으로 치르는 셈입니다."

**Q2. `order_header`가 12행인데 `order_detail`과 INNER JOIN하면 몇 행이 나오나요?**
> "20행입니다. 조인 결과 행 수는 왼쪽 행 수가 아니라 오른쪽에서 매칭된 개수의 합이거든요. 주문 12건에 상세 라인이 총 20줄 달려 있어서 라인이 2줄인 주문은 결과에 두 번 등장합니다. 그래서 이 상태에서 주문 건수를 세면 실제보다 부풀려집니다."

**Q3. INNER JOIN과 LEFT JOIN을 언제 나눠 쓰나요?**
> "'없는 것'을 찾아야 하면 LEFT입니다. 제 DB에서 카테고리별 메뉴 수를 INNER JOIN으로 뽑으면 9행이 나오는데, 메뉴가 0개인 '굿즈'가 통째로 사라집니다. LEFT JOIN이면 10행이고 굿즈가 0으로 남습니다. '재고가 0인 카테고리를 찾아라' 같은 요구는 INNER로는 아예 답이 안 나옵니다. 참고로 LEFT JOIN의 원시 결과는 13행이고, 10행은 GROUP BY로 묶은 뒤의 숫자입니다."

**Q4. LEFT JOIN에서 조건을 ON에 쓸 때와 WHERE에 쓸 때 뭐가 다른가요?**
> "ON은 조인 단계에서, WHERE는 조인이 끝난 뒤에 평가됩니다. LEFT JOIN은 짝이 없으면 오른쪽을 NULL로 채우는데, `NULL = 'COMPLETED'`는 거짓이 아니라 UNKNOWN이라 WHERE에서 탈락합니다. 제 Q10에서 status 필터를 ON에 두면 10행, WHERE로 옮기면 7행이 되고 박지호·윤하늘·서지안이 사라집니다. WHERE로 옮기는 순간 사실상 INNER JOIN이 되는 거죠. 참고로 INNER JOIN에서는 둘이 결과가 같고, 이 동작은 SQLite·MySQL·PostgreSQL이 표준대로 동일합니다."

**Q5. `COUNT(*)`와 `COUNT(컬럼)`은 언제 달라지나요?**
> "NULL이 있을 때 달라지고, LEFT JOIN이 바로 그 NULL을 만들어냅니다. `COUNT(*)`는 행을 세고 `COUNT(oh.id)`는 NULL 아닌 값을 셉니다. 제 DB에서 주문이 0건인 서지안만 두 값이 1과 0으로 갈립니다. 주문 0건 고객을 찾는 쿼리인데 정작 그 고객만 틀리는 거라, LEFT JOIN + COUNT 조합에서는 반드시 오른쪽 테이블의 PK를 지정합니다."

**Q6. `COUNT(DISTINCT oh.id)`는 왜 필요한가요?**
> "fan-out 때문입니다. 고객-주문-주문상세를 이어 붙이면 주문 한 건이 라인 수만큼 복제됩니다. 김민준은 주문 3건인데 라인이 6줄이라 `COUNT(oh.id)`가 6이 나옵니다. `oh.id`는 PK라 주문당 값이 유일하니까 DISTINCT를 걸면 3으로 정확히 돌아옵니다. 무서운 건 라인이 1줄뿐인 고객은 값이 우연히 맞아서 눈으로 검증하면 못 잡는다는 점입니다."

**Q7. 그런데 Q10의 금액 SUM은 왜 안 틀렸나요?**
> "집계 대상 컬럼의 레벨이 다르기 때문입니다. 복제의 원인이 `order_detail`인데 `quantity * unit_price`도 `order_detail` 자신의 컬럼이라, 복제된 행 하나하나가 각자 다른 라인이고 중복이 아닙니다. 반대로 `oh.id`처럼 상위 테이블 컬럼을 세면 복제된 만큼 뻥튀기됩니다. 규칙으로는 '집계 대상이 가장 잘게 쪼개진 테이블의 컬럼이면 안전하다'로 기억하고 있습니다. 상위 테이블의 금액을 더해야 한다면 `SUM(DISTINCT)`가 아니라 서브쿼리로 미리 집계해서 붙여야 합니다 — 금액은 우연히 같을 수 있으니까요."

**Q8. RIGHT JOIN이나 FULL OUTER JOIN은 왜 안 썼나요?**
> "RIGHT JOIN은 LEFT를 뒤집은 것뿐이라 테이블 순서만 바꾸면 되는데, 사람이 읽을 때 왼쪽이 기준이라는 게 직관적이라 LEFT로 통일했습니다. 지원 여부도 다른데, SQLite는 3.39부터 RIGHT와 FULL OUTER를 지원해서 제 3.46 환경에서는 둘 다 돌아가는 걸 확인했고, MySQL 8은 지금도 FULL OUTER가 없어서 LEFT에 RIGHT의 오른쪽 전용 행만 UNION ALL로 붙여야 합니다. PostgreSQL은 넷 다 됩니다. 그리고 이 스키마는 `menu.category_id`가 NOT NULL이고 FK가 걸려 있어서 부모 없는 메뉴가 존재할 수 없으니, FULL OUTER를 써도 LEFT와 결과가 13행으로 같습니다."

**보너스 Q9. `NOT IN`으로 안티 조인을 쓰면 안 되나요?**
> "이 스키마에서는 `customer_id`가 NOT NULL이라 지금은 맞습니다. 실측으로 서지안 1행이 나옵니다. 다만 서브쿼리 결과에 NULL이 하나라도 섞이면 `x <> NULL`이 UNKNOWN이 되면서 AND 전체가 절대 참이 못 돼 결과가 0행이 됩니다. 에러도 안 나고요. 그래서 저는 `NOT EXISTS`나 `LEFT JOIN ... IS NULL`을 기본으로 씁니다."

---

## 9. 발표 전 3분 셀프 드릴

주석 없는 상태로 `03_queries.sql`을 열고, **쿼리마다 아래 네 문장을 소리 내어 말한 뒤** 실제로 실행해 답을 맞춰 본다. 이걸 다섯 번만 반복하면 읽는 속도 문제는 사라진다.

1. "결과 한 행은 ○○○ 하나다." (FROM 절만 보고)
2. "조인은 ○○ 방향이라 행이 늘어난다 / 유지된다 / 줄어든다."
3. "그래서 최종 행 수는 대략 ○행이다."
4. "여기서 틀리기 쉬운 건 ○○다." (`COUNT(*)` / `DISTINCT` 누락 / `WHERE` 위치 / `SUM`의 NULL)

| 쿼리 | 답 (틀리면 위 절로 돌아간다) |
|---|---|
| Q5 | menu 12행 기준, category는 부모 → **12행 유지** |
| Q6 | order_detail 20행 기준, 부모 3개 → **20행 유지** |
| Q7 | customer 10행 LEFT JOIN → 원시 13행, GROUP BY로 **10행**, 서지안 0 |
| Q8 / Q8-B | INNER **9행**(굿즈 소멸) / LEFT **10행**(굿즈 0) |
| Q10 | LEFT 2단, 필터는 ON → **10행**, 0원 3명(박지호·윤하늘·서지안) |
| Q10-B | LEFT 1단이라 지금은 DISTINCT 유무로 값이 같지만, **DISTINCT를 뺀 쿼리**는 od를 한 줄 더 붙이는 순간 김민준이 3 → 6으로 깨진다 |

### 실측 재현 방법 — `cafe.db`를 그대로 쓰면 숫자가 안 맞는다

이 환경에는 `sqlite3` CLI가 없어 Python 표준 라이브러리로 확인했다(Python 3.14, `sqlite3.sqlite_version` = 3.46.1).

**저장소의 `cafe.db`는 이미 03의 Q13/Q14/Q15까지 적용된 상태**라 이 문서의 숫자(120, 20, ...)가 나오지 않는다. 실측으로 확인한 차이는 문서 맨 위 표와 같다. 재현하려면 **01+02만으로 새 파일을 빌드**해야 한다. 아래 스크립트는 실제로 돌려서 결과를 확인한 것이다.

```python
import sqlite3, pathlib

SRC = pathlib.Path('/home/coder/volume/codyssey_B5-1')
db  = SRC / 'fresh_check.db'          # cafe.db 를 건드리지 않는다
if db.exists():
    db.unlink()

con = sqlite3.connect(db)
con.execute("PRAGMA foreign_keys = ON")          # 연결마다 켜야 한다
con.executescript((SRC / '01_schema.sql').read_text(encoding='utf-8'))
con.executescript((SRC / '02_data.sql').read_text(encoding='utf-8'))
con.commit()

for t in ('customer', 'category', 'menu', 'order_header', 'order_detail'):
    print(t, con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
# 실측 출력: customer 10 / category 10 / menu 12 / order_header 12 / order_detail 20

for row in con.execute("""
    EXPLAIN QUERY PLAN
    SELECT oh.id, c.name, m.name
    FROM   order_detail od
    JOIN   order_header oh ON oh.id = od.order_id
    JOIN   customer     c  ON c.id  = oh.customer_id
    JOIN   menu         m  ON m.id  = od.menu_id
"""):
    print(row[3])
# 실측 출력: SCAN od / SEARCH oh USING INTEGER PRIMARY KEY (rowid=?) / SEARCH c ... / SEARCH m ...
con.close()
```

`EXPLAIN QUERY PLAN`의 결과 튜플은 `(id, parent, notused, detail)`이므로 사람이 읽을 문자열은 **`row[3]`** 이다.

### 파괴적 DML을 안전하게 시험하는 법

Q13/Q14 같은 것을 실험할 때는 `SAVEPOINT`로 감싸고 되돌린다. 파일을 복사해 두는 것도 좋다.

```python
con.execute("SAVEPOINT probe")
try:
    con.execute("DELETE FROM order_header WHERE status = 'CANCELLED'")
    print(con.execute("SELECT COUNT(*) FROM order_detail").fetchone())  # 18 (CASCADE)
finally:
    con.execute("ROLLBACK TO probe")   # 원상복구
    con.execute("RELEASE probe")
print(con.execute("SELECT COUNT(*) FROM order_detail").fetchone())      # 20 으로 되돌아옴
```

### 제약 위반을 코드에서 구분하는 법

`sqlite3`에서 FK·UNIQUE·CHECK 위반은 **전부 `sqlite3.IntegrityError`** (→ `DatabaseError` → `Error`)로 올라온다. 셋을 구분하려면 **Python 3.11+의 `e.sqlite_errorname`** 을 본다. 아래는 실제로 돌려서 얻은 값이다.

```python
import sqlite3
try:
    con.execute("INSERT INTO menu(name, price, category_id) VALUES('X', 1000, 999)")
except sqlite3.IntegrityError as e:
    print(e)                    # FOREIGN KEY constraint failed
    print(e.sqlite_errorname)   # SQLITE_CONSTRAINT_FOREIGNKEY
```

| 위반 | 예외 클래스 | 메시지(실측) | `sqlite_errorname`(실측) |
|---|---|---|---|
| FK | `sqlite3.IntegrityError` | `FOREIGN KEY constraint failed` | `SQLITE_CONSTRAINT_FOREIGNKEY` |
| UNIQUE | `sqlite3.IntegrityError` | `UNIQUE constraint failed: menu.name` | `SQLITE_CONSTRAINT_UNIQUE` |
| CHECK | `sqlite3.IntegrityError` | `CHECK constraint failed: status IN (...)` | `SQLITE_CONSTRAINT_CHECK` |

**SQLite에는 SQLSTATE가 없다.** 표준 SQLSTATE로 구분하는 건 다른 DBMS 이야기다.

| 위반 | 표준 SQLSTATE | MySQL 에러번호 | PostgreSQL |
|---|---|---|---|
| FK 위반 | `23503` | 1452 (자식 추가) / 1451 (부모 삭제) | `foreign_key_violation` (23503) |
| UNIQUE 위반 | `23505` | 1062 (`ER_DUP_ENTRY`) | `unique_violation` (23505) |
| CHECK 위반 | `23514` | 3819 (`ER_CHECK_CONSTRAINT_VIOLATED`, **8.0.16+**) | `check_violation` (23514) |
| NOT NULL 위반 | `23502` | 1048 | `not_null_violation` (23502) |

드라이버로 옮기면 `psycopg`는 `e.sqlstate`, `mysql-connector-python`은 `e.errno`/`e.sqlstate`로 같은 정보를 읽는다. **"FK인지 UNIQUE인지 메시지 문자열로 판별한다"는 코드는 로케일·버전에 따라 깨지므로 쓰지 않는다.**

**PRAGMA를 빠뜨리면 FK 실험 자체가 무의미하다.** SQLite는 `PRAGMA foreign_keys`가 **연결마다 기본 OFF**라, 이 줄이 없으면 위의 FK 위반이 아무 소리 없이 성공한다. MySQL/PostgreSQL은 기본 활성이라 이 스위치가 없다.
