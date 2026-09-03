# 서브쿼리 완전정복

> 평가 피드백 2, 8 대응 — 위치·상관 여부로 즉시 분류하고, 조인과 상호 변환한다. NOT IN의 NULL 함정까지.

---

## 0. 이 모듈이 고치려는 것

평가 피드백 2번과 8번은 "몰라서 틀렸다"가 아니라 **"읽는 데 시간이 걸린다"**는 지적이다. 서브쿼리를 만나면 안쪽부터 해석하려다 길을 잃기 때문이다. 해법은 지식이 아니라 **순서를 고정하는 것**이다. 아래 3단계를 그대로 입에 붙인다.

```text
1단계  괄호를 통째로 상자로 덮는다  → 바깥 쿼리 뼈대만 먼저 소리 내어 읽는다
2단계  그 상자가 무엇을 반환하는지 한 단어로 말한다 (값 1개 / 목록 / 표 / 존재여부)
3단계  그 다음에야 상자를 연다
```

말로 하면 이렇다.

> "바깥은 customer에서 id, name을 뽑는 쿼리고, WHERE에 상자가 하나 있습니다. 이 상자는 **고객 id 목록**을 돌려줍니다. 상자를 열어 보면 order_header, order_detail, menu를 이어서 아메리카노를 주문한 고객 id를 뽑고 있습니다."

이 문장 구조 하나면 어떤 서브쿼리도 15초 안에 설명이 시작된다. 아래는 그 상자의 종류를 즉시 분류하기 위한 내용이다.

### 0-1. 실측 전제 — 어떤 DB에서 돌린 수치인가

이 문서의 모든 결과값과 실행계획은 **`01_schema.sql` + `02_data.sql` 만 실행한 초기 상태 DB**에 SQLite 3.46.1로 직접 돌려 얻었다. 이 전제를 먼저 못 박는 이유가 있다.

저장소에 커밋되어 있는 `cafe.db` 는 **초기 상태가 아니다.** 실제로 열어 보면 이렇다.

| 항목 | 초기 상태(01+02) | 커밋된 `cafe.db` |
|---|---|---|
| order_header | 12행 (COMPLETED 9 / PENDING 1 / CANCELLED 2) | **10행** (COMPLETED 9 / PENDING 1 / CANCELLED 0) |
| order_detail | 20행 | **18행** |
| 아메리카노 price | 3500 | **4000** |
| 인덱스 | 자동 인덱스 3개(UNIQUE 유래)뿐 | **+ `idx_order_header_customer_id`, `idx_order_detail_order_id`** |

`03_queries.sql` 의 Q13(UPDATE)·Q14(DELETE)·Q15(CREATE INDEX)가 이미 반영된 상태다. 이 DB로 4번 항목을 돌리면 결과가 4행이 아니라 **3행**(박지호의 유일한 주문이 CANCELLED라 삭제됨)이 되고, 실행계획에서 `BLOOM FILTER` / `AUTOMATIC COVERING INDEX` 가 **사라진다**(실제 인덱스를 쓰므로). 재현하려면 새 파일로 다시 만든다.

```bash
# sqlite3 CLI가 있으면
rm -f fresh.db && sqlite3 fresh.db < 01_schema.sql && sqlite3 fresh.db < 02_data.sql

# CLI가 없으면 (이 문서의 실측은 이 방식으로 했다)
python3 - <<'PY'
import sqlite3
c = sqlite3.connect("fresh.db")
for f in ("01_schema.sql", "02_data.sql"):
    c.executescript(open(f, encoding="utf-8").read())
c.commit()
PY
```

자가진단: `SELECT COUNT(*) FROM order_header` 가 **12**, `order_detail` 이 **20**, 아메리카노가 **3500** 이면 초기 상태다.

---

## 1. 위치별 분류 — 서브쿼리가 앉을 수 있는 자리는 4개뿐

| 자리 | 이름 | 반드시 반환해야 하는 모양 | 이 스키마 예시 |
|---|---|---|---|
| SELECT 절 | 스칼라 서브쿼리 | **1행 1열** | 고객마다 주문 건수 |
| FROM 절 | 인라인 뷰 / 파생 테이블 | **표(N행 M열)**, 별칭 필수 | 고객별 결제합 집계 후 조인 |
| WHERE 절 | 중첩 서브쿼리 | 연산자에 따라 1행1열 / 1열 N행 | 평균가보다 비싼 메뉴 |
| HAVING 절 | 중첩 서브쿼리 | 보통 **1행 1열** | 평균 결제액을 넘는 고객 |

### 1-1. SELECT 절 — 스칼라

```sql
SELECT c.name,
       (SELECT COUNT(*) FROM order_header oh
        WHERE oh.customer_id = c.id AND oh.status = 'COMPLETED') AS completed_cnt
FROM   customer c
ORDER  BY c.id;
```

실측 결과 (초기 상태, 10행 전부):

| name | completed_cnt |
|---|---|
| 김민준 | 3 |
| 이서연 | 1 |
| 박지호 | 0 |
| 최예린 | 1 |
| 정우진 | 1 |
| 한소희 | 1 |
| 오재현 | 1 |
| 장민서 | 1 |
| 윤하늘 | 0 |
| 서지안 | 0 |

박지호는 주문이 1건 있지만 CANCELLED, 윤하늘도 1건 있지만 CANCELLED, 서지안은 주문 자체가 없다. 세 사람 모두 0인데 **이유가 다르다**는 점이 이 예제의 핵심이다.

읽는 대본:

> "SELECT 절 안의 괄호는 **값 한 개**를 만드는 상자입니다. 바깥 customer 한 행마다 그 고객의 COMPLETED 주문 수를 세서 컬럼처럼 붙입니다. 고객이 10명이면 상자는 논리적으로 10번 평가됩니다."

**LEFT JOIN으로 같은 걸 하려면 함정이 두 개 있다 — 실측으로 대조한다.**

| 방식 | 결과 |
|---|---|
| 스칼라 서브쿼리 (위) | 10행, 박지호 0 / 윤하늘 0 / 서지안 0 |
| `LEFT JOIN ... ON oh.customer_id=c.id AND oh.status='COMPLETED'` + `COUNT(oh.id)` | 10행, **동일** — 이게 올바른 조인 버전 |
| 같은 조인에서 `COUNT(*)` 로 바꿈 | 10행이지만 박지호·윤하늘·서지안이 **0이 아니라 1** |
| `status='COMPLETED'` 를 **WHERE**로 옮김 | **7행** — 박지호·윤하늘·서지안이 통째로 사라짐 |

즉 "LEFT JOIN + COUNT는 0이 안 나온다"가 아니라, **`COUNT(*)` 를 쓰면 NULL 행도 1로 세어지고, 필터를 WHERE에 두면 LEFT JOIN이 INNER JOIN으로 퇴화한다**가 정확한 서술이다. 스칼라 서브쿼리는 이 두 실수를 구조적으로 못 하게 만든다는 점이 장점이다.

포인트 — 이 자리의 서브쿼리는 **LEFT JOIN + GROUP BY의 대체재**다. 지표를 여러 개 붙일 때는 조인이, 딱 하나 붙일 때는 스칼라가 읽기 쉽다. 지표마다 스칼라를 하나씩 늘리면 그만큼 서브쿼리가 반복 평가된다는 비용은 감안한다.

### 1-2. FROM 절 — 인라인 뷰(파생 테이블)

```sql
SELECT c.name, t.total
FROM   customer c
JOIN  (SELECT oh.customer_id AS cid,
              SUM(od.quantity * od.unit_price) AS total
       FROM   order_header oh
       JOIN   order_detail od ON od.order_id = oh.id
       WHERE  oh.status = 'COMPLETED'
       GROUP  BY oh.customer_id) t
  ON   t.cid = c.id
ORDER BY t.total DESC
LIMIT 3;
```

실측: 김민준 42,500 / 한소희 18,000 / 이서연 16,000. (LIMIT을 빼면 최예린 15,000 / 장민서 14,500 / 정우진 10,500 / 오재현 9,000 까지 총 7행)

이 자리의 서브쿼리는 **"이미 집계가 끝난 임시 테이블"**이다. 집계와 조인의 순서를 사람이 강제하고 싶을 때 쓴다.

**별칭 규칙의 DBMS별 경계 (자주 틀리는 부분)**

| DBMS | 파생 테이블 별칭 생략 |
|---|---|
| SQLite | 허용 — `SELECT * FROM (SELECT 1 AS a)` 가 그대로 통과 (실측) |
| MySQL 8 | **에러** — `ERROR 1248 (42000): Every derived table must have its own alias` |
| PostgreSQL 15 이하 | **에러** — `subquery in FROM must have an alias` |
| PostgreSQL 16 이상 | **허용** — 16에서 FROM 절 서브쿼리의 별칭 생략이 허용됐다 |

"PostgreSQL은 무조건 에러"는 이제 사실이 아니다. 다만 MySQL 8은 여전히 필수이고, 별칭이 있어야 바깥에서 컬럼을 참조할 수 있으므로 **항상 붙이는 습관**이 맞다.

### 1-3. WHERE 절 — 학습자의 Q12

```sql
SELECT name, price
FROM   menu
WHERE  is_available = 1
  AND  price > (SELECT AVG(price) FROM menu WHERE is_available = 1)
ORDER  BY price DESC, id;
```

실측: 기준선 `AVG(price) = 5181.818181818182`, 결과 4행 — 치킨샐러드 8500 / 티라미수 6500 / 딸기스무디 6000 / 자몽에이드 5500.

> "괄호는 **숫자 하나**, 판매중 메뉴의 평균가 약 5,181.8원을 만듭니다. 이 값은 바깥 행과 무관하니 딱 한 번만 계산됩니다. 그 다음 menu를 훑으면서 각 행의 price와 비교합니다."

"한 번만 계산된다"는 것도 실측으로 뒷받침된다. 실행계획이 이렇게 나온다.

```text
SCAN menu
SCALAR SUBQUERY 1          ← CORRELATED 가 아니다 = 바깥 행과 무관 = 1회 평가
  SCAN menu
USE TEMP B-TREE FOR ORDER BY
```

`SCALAR SUBQUERY` 와 `CORRELATED SCALAR SUBQUERY` 를 구분해서 읽는 것이 이 절의 실전 요령이다.

### 1-4. HAVING 절

```sql
SELECT c.name, SUM(od.quantity * od.unit_price) AS paid
FROM   customer c
JOIN   order_header oh ON oh.customer_id = c.id
JOIN   order_detail od ON od.order_id = oh.id
WHERE  oh.status = 'COMPLETED'
GROUP  BY c.id, c.name
HAVING SUM(od.quantity * od.unit_price) >
       (SELECT AVG(t) FROM (SELECT SUM(od2.quantity * od2.unit_price) AS t
                            FROM order_header oh2
                            JOIN order_detail od2 ON od2.order_id = oh2.id
                            WHERE oh2.status = 'COMPLETED'
                            GROUP BY oh2.customer_id))
ORDER  BY paid DESC;
```

실측: 고객 1인당 평균 결제액 17,928.571428571428원, 이를 넘는 고객은 **김민준(42,500), 한소희(18,000)** 2명.

핵심은 **WHERE와 HAVING의 서브쿼리는 시점이 다르다**는 것이다. WHERE의 서브쿼리는 묶기 **전** 개별 행과 비교되고, HAVING의 서브쿼리는 묶은 **후** 그룹 집계값과 비교된다. 여기서는 "평균의 평균"이 필요해서 서브쿼리 안에 또 파생 테이블이 들어갔다 — 이 **2중 구조**야말로 7번 항목의 CTE로 펴야 할 대상이다.

---

## 2. 상관(correlated) vs 비상관(non-correlated)

판별법은 한 문장이다.

> **"괄호 안에서 바깥 별칭을 쓰면 상관, 안 쓰면 비상관."**

| 구분 | 괄호 안 특징 | 단독 실행 | 논리적 실행 횟수 |
|---|---|---|---|
| 비상관 | 바깥 별칭 없음 | **된다** | 1회 |
| 상관 | `oh.customer_id = c.id` 처럼 바깥 `c` 참조 | **안 된다** (`no such column: c.id`) | 바깥 행 수만큼 |

면접에서 즉시 써먹을 수 있는 검증 요령: **괄호 안만 복사해서 따로 실행해 본다.** 돌아가면 비상관, `no such column` 이 뜨면 상관이다. (실측 확인: 1-1의 괄호 안만 떼어 실행하면 정확히 `no such column: c.id`)

실행 방식은 **논리적 정의**와 **실제 처리**를 구분해서 말해야 점수가 난다.

- 논리적으로는 상관 서브쿼리가 바깥 행마다 한 번씩 평가된다. customer 10행이면 10번.
- 하지만 옵티마이저가 그대로 돌린다는 보장은 없다. **다만 DBMS마다 하는 일이 다르다.**
  - **MySQL 8 / PostgreSQL**: `IN`/`EXISTS` 상관 서브쿼리를 **세미조인(semi-join)**으로 재작성하는 최적화가 있다. MySQL은 FirstMatch·LooseScan·Materialization 같은 세미조인 전략을 실행계획에 표시하고, PostgreSQL은 조인 노드를 `Semi Join` 으로 보여 준다. 세미조인은 "오른쪽에 짝이 하나라도 있으면 왼쪽 행을 통과시키고 즉시 멈추는 조인"이며, 결과 행이 불어나지 않는다는 점에서 일반 조인과 다르다.
  - **SQLite**: 일반적인 세미조인 변환기가 없다. 계획 문자열도 끝까지 `CORRELATED SCALAR SUBQUERY` 로 남는다. 대신 서브쿼리 평탄화(flattening), **자동 인덱스(automatic index)**, **블룸 필터(Bloom filter)** 로 반복 비용을 줄인다.
- SQLite 3.46.1 실측에서 4번 항목 EXISTS 쿼리의 계획에는 `BLOOM FILTER ON od` 와 `SEARCH od USING AUTOMATIC COVERING INDEX` 가 등장한다. 즉 반복 탐색을 위해 **임시 인덱스를 자동 생성**하고 블룸 필터로 헛수고를 걸러낸다. "행마다 풀스캔 10번"이 아니다.
- **다만 항상 붙는 것은 아니다.** 같은 DB에서 1-1의 상관 스칼라 서브쿼리 계획은 이게 전부다.

```text
SCAN c
CORRELATED SCALAR SUBQUERY 1
  SCAN oh                     ← 자동 인덱스도 블룸 필터도 없다
```

order_header가 12행뿐이라 임시 인덱스를 만드는 비용이 이득보다 크다고 판단한 것이다. 그리고 앞서 본 대로, `idx_order_detail_order_id` 같은 **실제 인덱스가 이미 있으면 자동 인덱스는 아예 만들지 않는다**(커밋된 `cafe.db` 로 돌리면 `SEARCH od USING INDEX idx_order_detail_order_id (order_id=?)` 로 바뀐다). 자동 인덱스는 "쓸 만한 인덱스가 없을 때의 임시방편"이지 자랑거리가 아니다.

말할 대본:

> "상관 서브쿼리는 **정의상** 바깥 행마다 평가됩니다. 다만 MySQL이나 PostgreSQL은 대부분 세미조인으로 재작성하고, SQLite는 세미조인 변환은 없지만 자동 인덱스와 블룸 필터를 붙이는 걸 EXPLAIN QUERY PLAN으로 확인했습니다. 반대로 테이블이 작으면 그냥 스캔하기도 했습니다. 그래서 '상관 서브쿼리는 느리다'는 단정은 하지 않고 계획을 떠서 판단합니다."

---

## 3. IN / EXISTS / NOT IN / NOT EXISTS / ANY / ALL

| 연산자 | 서브쿼리에 요구하는 모양 | 의미 | NULL 안전성 |
|---|---|---|---|
| `IN` | 1열 N행 | 목록에 포함되는가 | 안전 — 일치하면 TRUE, 아니면 **FALSE가 아니라 UNKNOWN**이지만 WHERE 결과는 옳다 |
| `EXISTS` | 아무 컬럼이나 (관례상 `SELECT 1`) | 행이 하나라도 있는가 | 안전 (TRUE/FALSE만) |
| `NOT IN` | 1열 N행 | 목록에 없는가 | **위험 — NULL 하나면 전멸** |
| `NOT EXISTS` | 아무 컬럼 | 행이 하나도 없는가 | 안전 (TRUE/FALSE만) |
| `= ANY` / `> ANY` | 1열 N행 | 하나라도 만족 (`= ANY` ≡ `IN`) | **내성 있음** — 만족하는 비NULL 값이 하나라도 있으면 TRUE |
| `> ALL` / `<> ALL` | 1열 N행 | 전부 만족 (`<> ALL` ≡ `NOT IN`) | **NULL 있으면 전멸** |

**공집합일 때의 규칙**도 같이 외운다. 서브쿼리가 0행이면 `IN` = FALSE, `NOT IN` = TRUE, `ANY` = FALSE, `ALL` = **TRUE**다. `> ALL` 이 공집합에서 TRUE라는 점은 MAX 대체 시 결과가 갈리는 원인이 된다(아래).

실측 확인:

```sql
SELECT 1 IN (1, 2, NULL);   -- 1   (TRUE)
SELECT 5 IN (1, 2, NULL);   -- NULL (UNKNOWN — FALSE가 아니다)
SELECT 1 IN (SELECT id FROM menu WHERE 1=0);      -- 0 (FALSE)
SELECT 1 NOT IN (SELECT id FROM menu WHERE 1=0);  -- 1 (TRUE)
```

**DBMS 차이 (실측 포함)**

| | `IN` / `EXISTS` | `ANY` / `ALL` / `SOME` |
|---|---|---|
| SQLite 3.46.1 | 지원 | **미지원** — `> ALL (SELECT ...)` 는 `near "ALL": syntax error`, `> ANY (SELECT ...)` 는 `ANY(...)` 를 함수 호출로 파싱해 `near "SELECT": syntax error` (둘 다 직접 실행해 확인) |
| MySQL 8 | 지원 | 지원 |
| PostgreSQL | 지원 | 지원 (배열 대상 `= ANY(array)` 도 가능) |

> 참고로 MySQL 8은 `IN`/`ANY`/`ALL`/`SOME` **서브쿼리 안의 `LIMIT`** 을 아직 지원하지 않는다 — `ERROR 1235 (42000): This version of MySQL doesn't yet support 'LIMIT & IN/ALL/ANY/SOME subquery'`. SQLite와 PostgreSQL은 문제없다. 이식할 때 걸리기 쉬운 지점이다.

SQLite에서 `> ALL` 을 흉내 내려면 집계로 바꾼다.

```sql
-- MySQL8/PG:  WHERE price > ALL (SELECT price FROM menu WHERE category_id = 1)
-- SQLite 대체:
SELECT name, price
FROM   menu
WHERE  price > (SELECT MAX(price) FROM menu WHERE category_id = 1)
ORDER  BY price;
```
실측: 커피 카테고리 최고가 5000원 → 자몽에이드 5500, 딸기스무디 6000, 티라미수 6500, 에그샌드위치 6800, 치킨샐러드 8500. (`is_available` 조건을 안 걸었으므로 품절인 에그샌드위치도 포함된다.)

**단, MAX/MIN 대체는 완전한 등가가 아니다.**

| 상황 | `> ALL (서브쿼리)` | `> (SELECT MAX(...))` |
|---|---|---|
| 서브쿼리가 0행 | **TRUE** (모든 행 통과) | `MAX` 가 NULL → 비교가 UNKNOWN → **0행** |
| 서브쿼리에 NULL 포함 | UNKNOWN → 0행 | `MAX` 는 NULL을 무시 → **행이 나온다** |

그래서 대체 규칙은 이렇게 외운다 — **`> ALL` → `> MAX`, `> ANY` → `> MIN`. 단 서브쿼리가 비거나 NULL을 담을 수 있으면 결과가 갈린다.**

### 3-1. NOT IN 의 NULL 함정 — 3값 논리 진리표

SQL의 비교는 참/거짓이 아니라 **TRUE / FALSE / UNKNOWN 세 가지**다. 그리고 `WHERE` 는 **TRUE인 행만** 통과시킨다. UNKNOWN은 결과적으로 FALSE와 똑같이 버려진다.

`x NOT IN (a, b, NULL)` 은 내부적으로 `NOT (x = a OR x = b OR x = NULL)` 로 풀린다.

| x | x = 1 | x = 2 | x = NULL | OR 결합 | NOT | WHERE 통과 |
|---|---|---|---|---|---|---|
| 1 | TRUE | FALSE | UNKNOWN | TRUE | FALSE | ✗ |
| 5 | FALSE | FALSE | UNKNOWN | **UNKNOWN** | **UNKNOWN** | ✗ |

OR 진리표에서 `TRUE OR UNKNOWN = TRUE`, `FALSE OR UNKNOWN = UNKNOWN` 이기 때문에, 목록에 없는 값조차 UNKNOWN이 되어 탈락한다. **목록에 NULL이 하나라도 있으면 `NOT IN` 결과는 항상 0행이다.**

실측으로 확인:

```sql
SELECT 5 NOT IN (1, 2, NULL);          -- 결과: NULL  (TRUE 도 FALSE 도 아니다)
SELECT name FROM menu WHERE id NOT IN (1, 2, NULL);  -- 결과: 0행
```

**현실적인 사고 재현.** 여기서 중요한 전제가 하나 있다. **초기 데이터에서는 이 함정이 재현되지 않는다.** 12건의 주문 헤더 모두에 상세 라인이 최소 하나씩 있어서 LEFT JOIN이 NULL을 만들지 않기 때문이다.

```sql
-- "한 번도 팔리지 않은 메뉴" 를 뽑으려던 쿼리
SELECT m.name
FROM   menu m
WHERE  m.id NOT IN (SELECT od.menu_id
                    FROM order_header oh
                    LEFT JOIN order_detail od ON od.order_id = oh.id);
```

| 상태 | 안쪽 서브쿼리 (DISTINCT 정렬해서 본 값) | 위 `NOT IN` 쿼리 |
|---|---|---|
| 초기 상태 | `1,2,3,4,5,6,7,8,9,10,12` — **NULL 없음** | **에그샌드위치** (우연히 정답) |
| 상세 없는 주문 1건 추가 후 | `NULL,1,2,3,4,5,6,7,8,9,10,12` | **0행** (조용한 오답) |

그래서 함정을 보려면 "장바구니만 만들고 아직 메뉴를 담지 않은 주문"을 먼저 만들어야 한다. 원본 DB를 건드리지 않도록 트랜잭션으로 감싸고 ROLLBACK 한다.

```sql
BEGIN;
INSERT INTO order_header (customer_id, order_date, status)
VALUES (4, '2026-05-11 10:00:00', 'PENDING');   -- 상세 라인이 없는 주문

-- 이제 안쪽 서브쿼리에 NULL이 섞인다
SELECT DISTINCT od.menu_id
FROM   order_header oh
LEFT   JOIN order_detail od ON od.order_id = oh.id
ORDER  BY od.menu_id;      -- NULL, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12

ROLLBACK;
```

이 상태에서 세 가지를 나란히 돌린 실측 결과다.

| 실행 | 결과 |
|---|---|
| 위 `NOT IN` 쿼리 | **0행** (에그샌드위치가 사라짐 = 조용한 오답) |
| `NOT EXISTS` 로 교체 | **에그샌드위치** (정답) |
| `NOT IN (... WHERE od.menu_id IS NOT NULL)` | **에그샌드위치** (정답) |

```sql
-- 안전한 버전
SELECT m.name
FROM   menu m
WHERE  NOT EXISTS (SELECT 1 FROM order_detail od WHERE od.menu_id = m.id);
```

이 버전은 애초에 `order_header` 를 끌어들이지 않으므로 NULL이 생길 여지 자체가 없다. **"NOT IN이 위험하다"보다 먼저 나와야 할 교훈은 "LEFT JOIN 결과를 그대로 IN/NOT IN 목록으로 쓰지 마라"** 다.

**왜 NOT EXISTS는 안전한가.** `EXISTS` 는 값을 비교하지 않고 **행이 하나라도 반환되는지 아닌지만** 본다. 그 판정은 절대 UNKNOWN이 될 수 없으므로 3값 논리에 발을 담그지 않는다. 그래서 `NOT EXISTS` 는 항상 TRUE 아니면 FALSE다. (서브쿼리가 `SELECT NULL` 을 돌려줘도 `EXISTS` 는 TRUE다 — 값이 아니라 행의 유무를 보기 때문이다.)

한 줄 암기: **"부정 조건에는 NOT EXISTS. NOT IN을 쓸 거면 서브쿼리 컬럼이 NOT NULL인지 스키마로 확인한 뒤에."**

이 스키마에서 `order_header.customer_id` 는 `NOT NULL` 이고 LEFT JOIN도 끼지 않으므로 아래는 안전하다 — 실측 결과 서지안 1명.

```sql
SELECT name FROM customer
WHERE  id NOT IN (SELECT customer_id FROM order_header);
```

---

## 4. 04_bonus.sql 의 세 쿼리 나란히 읽기 — "아메리카노를 주문한 고객"

세 쿼리 모두 결과는 동일하다. **초기 상태 실측 4행: 김민준(1), 이서연(2), 박지호(3), 정우진(5).**
(커밋된 `cafe.db` 로 돌리면 Q14가 박지호의 CANCELLED 주문을 지운 뒤라 **3행**이 나온다. 4행을 보려면 0-1의 절차로 DB를 다시 만든다.)

| | (1-a) JOIN + DISTINCT | (1-b) IN 서브쿼리 | (1-c) EXISTS |
|---|---|---|---|
| 사고방식 | 4개 테이블을 이어 붙여 **행을 만든다** | 조건 맞는 **id 목록**을 먼저 만든다 | 고객마다 **있냐/없냐**를 묻는다 |
| 상관 여부 | 해당 없음 | 비상관 | **상관** (`oh.customer_id = c.id`) |
| 중복 | **발생** — DISTINCT 없으면 5행 (김민준 2회: 주문 1번·12번) | 없음 | 없음 |
| 자식 컬럼 출력 | 가능 | 불가 | 불가 |

**실측 EXPLAIN QUERY PLAN (초기 상태 DB, SQLite 3.46.1)**

```text
(1-a) JOIN + DISTINCT
  SEARCH m USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)
  SCAN od
  SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
  SEARCH c  USING INTEGER PRIMARY KEY (rowid=?)
  USE TEMP B-TREE FOR DISTINCT      ← 임시 자료구조 1
  USE TEMP B-TREE FOR ORDER BY      ← 임시 자료구조 2

(1-b) IN
  SEARCH customer USING INTEGER PRIMARY KEY (rowid=?)
  LIST SUBQUERY 1
    SEARCH m USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)
    SCAN od
    SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
                                     ← 임시 자료구조 0개

(1-c) EXISTS
  SCAN c
  CORRELATED SCALAR SUBQUERY 1
    SEARCH m USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)
    SCAN oh
    BLOOM FILTER ON od (order_id=? AND menu_id=?)
    SEARCH od USING AUTOMATIC COVERING INDEX (order_id=? AND menu_id=?)
                                     ← 임시 자료구조 0개
```

읽어낼 것 세 가지.

1. **JOIN 방식만 TEMP B-TREE를 두 번 만든다.** 다만 두 개의 원인은 서로 다르다. 여기가 흔히 잘못 설명되는 지점이다.
   - `FOR DISTINCT` — 조인이 김민준을 두 번 만들어 놓고 걷어내야 하므로 생긴다. DISTINCT 때문이 맞다.
   - `FOR ORDER BY` — **DISTINCT 때문이 아니다.** 실제로 DISTINCT만 빼고 돌려 보면 계획이 이렇게 나온다.
     ```text
     SEARCH m ... / SCAN od / SEARCH oh ... / SEARCH c ...
     USE TEMP B-TREE FOR ORDER BY      ← 그대로 남아 있다
     ```
     원인은 **구동 테이블이 customer가 아니라 menu·order_detail** 이라 결과가 `c.id` 순으로 나오지 않기 때문이다. 즉 DISTINCT는 임시 B-트리를 **하나** 추가할 뿐이다.
2. **IN은 `LIST SUBQUERY`** — 목록을 한 번 만들고 끝난다. 목록 단계에서 중복이 흡수되므로 DISTINCT가 필요 없다. 그 뒤 customer는 PK로 `SEARCH`. 여기서 **정렬용 임시 B-트리가 아예 없다**는 점이 눈에 띄는데, SQLite가 IN 목록을 정렬된 임시 인덱스로 만들어 두고 그 순서대로 rowid를 찾아가므로 `ORDER BY id` 가 공짜로 만족되기 때문이다.
3. **EXISTS는 `CORRELATED SCALAR SUBQUERY`** 로 표시되지만 순진하게 반복하지 않는다. `BLOOM FILTER` + `AUTOMATIC COVERING INDEX` 가 붙는다. 그리고 조건에 맞는 행을 하나 찾는 순간 멈춘다(short-circuit) — 같은 고객이 아메리카노를 100번 주문해도 첫 행에서 종료. 정렬용 임시 B-트리가 없는 이유는 바깥이 `SCAN c` 라 이미 `c.id` 순이기 때문이다.

**주의: 이 계획은 인덱스 상태에 따라 바뀐다.** 같은 (1-c)를 `idx_order_header_customer_id`·`idx_order_detail_order_id` 가 있는 `cafe.db` 로 돌리면 이렇게 된다.

```text
SCAN c
CORRELATED SCALAR SUBQUERY 1
  SEARCH m  USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)
  SEARCH oh USING COVERING INDEX idx_order_header_customer_id (customer_id=?)
  SEARCH od USING INDEX idx_order_detail_order_id (order_id=?)
```

`SCAN oh` 가 인덱스 `SEARCH` 로 바뀌고 자동 인덱스와 블룸 필터가 사라진다. **자동 인덱스가 붙었다는 것은 "쓸 인덱스가 없어서 매번 임시로 만들고 있다"는 신호**이므로, 실무에서는 자랑이 아니라 인덱스를 만들라는 힌트로 읽는다.

**선택 기준 대본:**

> "결과에 주문일시나 수량 같은 **자식 테이블 컬럼을 함께 보여줘야 하면 JOIN 말고 선택지가 없습니다.** 고객 컬럼만 필요하고 존재 여부로 거르는 게 목적이면 IN이나 EXISTS가 의도를 더 정확히 드러냅니다. 자식 테이블이 아주 크면 조기 종료하는 EXISTS가 유리하고, 부정 조건이면 NULL 안전성 때문에 NOT EXISTS를 씁니다."

---

## 5. 스칼라 서브쿼리가 2행 이상을 반환하면

```sql
SELECT c.name, (SELECT price FROM menu) FROM category c LIMIT 3;
```

> 별칭 `c` 를 빼먹고 `FROM category` 로 쓰면 실행 전에 `no such column: c.name` 으로 죽는다. 스칼라 서브쿼리 실험을 하려다 엉뚱한 에러를 보는 흔한 실수라 명시한다.

| DBMS | 동작 |
|---|---|
| **SQLite 3.46.1** | **에러 없이 첫 행을 쓴다.** 실측: 커피/논커피/티 모두 `3500` (menu id 1의 price). 이것은 버그가 아니라 문서화된 동작이지만, ORDER BY가 없으므로 어느 행이 "첫 행"인지는 보장되지 않는다 |
| **PostgreSQL** | 실행 시 에러 — `ERROR: more than one row returned by a subquery used as an expression` (SQLSTATE 21000, cardinality_violation) |
| **MySQL 8** | 실행 시 에러 — `ERROR 1242 (21000): Subquery returns more than 1 row` |

세 DBMS 모두 **파싱 단계가 아니라 실행 중에** 판정한다. 즉 데이터가 우연히 1행일 때는 통과하고, 나중에 데이터가 늘면 그때 터진다. "테스트에서는 됐는데요"의 전형이다.

이게 왜 중요한가: **SQLite에서만 테스트한 쿼리는 조용히 틀린 값을 뱉고 통과할 수 있다.** 나중에 PostgreSQL로 옮기면 그때서야 터진다. 그래서 스칼라 자리에 서브쿼리를 넣을 때는 반드시 다음 중 하나로 1행을 **보장**한다.

- **집계 함수를 쓴다** — `(SELECT AVG(price) ...)`, `(SELECT COUNT(*) ...)` 는 GROUP BY가 없으면 항상 정확히 1행
- **UNIQUE / PK로 거른다** — `menu.name` 에 UNIQUE가 있으니 `(SELECT price FROM menu WHERE name='아메리카노')` 는 최대 1행 보장 (실측 3500)
- **`ORDER BY ... LIMIT 1` 을 명시한다** — 실측 `(SELECT price FROM menu ORDER BY price DESC LIMIT 1)` → 8500

세 번째 방식은 SQLite/MySQL 8/PostgreSQL 모두 동일하게 동작한다.

**0행일 때의 차이도 같이 외운다.** 실측 `SELECT COUNT(*), AVG(price), MAX(price) FROM menu WHERE 1=0` → `0, NULL, NULL`.

| 함수 | 대상 행이 0개일 때 |
|---|---|
| `COUNT(*)`, `COUNT(col)` | **0** |
| `SUM`, `AVG`, `MAX`, `MIN` | **NULL** |

그리고 스칼라 서브쿼리 자체가 0행을 반환하면 세 DBMS 모두 **에러가 아니라 NULL**을 돌려준다. 그래서 `WHERE price > (SELECT MAX(price) FROM menu WHERE category_id = 999)` 는 0행이 되지 에러가 나지 않는다 — 3번 항목의 MAX 대체 함정과 같은 뿌리다. 금액 합계를 0으로 보이고 싶으면 `COALESCE(SUM(...), 0)` 을 쓴다.

---

## 6. 서브쿼리 ↔ 조인 상호 변환 규칙표

| 원래 형태 | 조인으로 변환 | 조건 / 주의 |
|---|---|---|
| `WHERE x IN (SELECT ...)` | **가능** — INNER JOIN | 서브쿼리 쪽에 중복이 있으면 **DISTINCT 필요**. 04_bonus의 김민준이 정확히 이 케이스(실측 5행 → DISTINCT 4행) |
| `WHERE EXISTS (...)` | **가능** — INNER JOIN + DISTINCT (세미조인) | 위와 동일. EXISTS의 조기 종료 성질은 잃는다 |
| `WHERE NOT EXISTS (...)` | **가능하지만 형태가 다름** — `LEFT JOIN ... WHERE 우측키 IS NULL` (안티조인) | 반드시 **NOT NULL인 조인 키나 PK 컬럼**을 IS NULL로 검사. 원래 NULL이 들어갈 수 있는 컬럼(예: `customer.phone`)을 검사하면 오답 |
| `WHERE NOT IN (...)` | LEFT JOIN 안티조인 | **등가 변환이 아니다.** 서브쿼리에 NULL이 섞이면 원래 NOT IN은 0행, 안티조인은 정상 결과라 답이 달라진다. NOT IN 쪽 동작도 SQL 표준이 정한 정상 동작이므로 "원본이 버그"가 아니라 "두 쿼리의 의미가 다르다"가 맞다. 서브쿼리 컬럼이 **NOT NULL임이 보장될 때만** 등가 |
| `SELECT` 절 스칼라 상관 서브쿼리 | 조건부 — LEFT JOIN + GROUP BY | 지표 1개면 그냥 두는 게 낫다. 여러 지표를 붙이면 GROUP BY가 비대해진다. 변환 시 1-1의 `COUNT(*)` / WHERE-vs-ON 함정을 그대로 밟는다 |
| `FROM` 절 파생 테이블 (집계) | **불가에 가깝다** | 집계 후 조인이라는 순서 자체가 목적이다. 억지로 펴면 GROUP BY 단위가 깨진다 |
| `WHERE price > (SELECT AVG(...))` | **불가** | 전체 집합의 요약값을 기준선으로 쓰는 구조는 조인으로 표현되지 않는다 (CROSS JOIN + 집계로는 가능하나 가독성이 크게 나빠진다). 윈도우 함수 `AVG(price) OVER ()` 가 더 자연스러운 대안이다 |

**NOT EXISTS → 안티조인 실제 변환:**

```sql
-- 서브쿼리 버전
SELECT c.name FROM customer c
WHERE  NOT EXISTS (SELECT 1 FROM order_header oh WHERE oh.customer_id = c.id);

-- 조인 버전 (동일 결과: 서지안)
SELECT c.name
FROM   customer c
LEFT   JOIN order_header oh ON oh.customer_id = c.id
WHERE  oh.id IS NULL;          -- ← 조인 키/PK를 검사해야 한다
```

> 참고로 SQLite는 **3.39.0(2022-06-25)부터 `RIGHT JOIN` 과 `FULL OUTER JOIN` 을 지원한다.** 그 이전 버전은 LEFT JOIN으로 뒤집어 쓰는 우회가 필요했다. 3.46.1에서 `... order_header oh RIGHT JOIN customer c ON ... WHERE oh.id IS NULL` 도 서지안 1명을 정상 반환하는 것을 확인했다. MySQL 8은 RIGHT JOIN은 되지만 **FULL OUTER JOIN은 여전히 미지원**이라 `UNION` 으로 흉내 내야 하고, PostgreSQL은 둘 다 오래전부터 지원한다.

**판단 기준 한 문장:**

> **"결과에 서브쿼리 쪽 컬럼이 필요하면 조인, 필터링만 하면 서브쿼리."**

여기에 하나 덧붙인다 — **부정(없는 것 찾기)은 조인으로 쓰면 안티조인이 되고, 안티조인은 `IS NULL` 검사 대상을 틀리기 쉽다.** 그래서 부정 조건은 `NOT EXISTS` 로 쓰는 편이 실수가 적다.

---

## 7. CTE(WITH)로 평평하게 펴기

2중 중첩된 HAVING 쿼리(1-4)는 이렇게 펴진다.

```sql
WITH order_total AS (
    SELECT oh.customer_id AS cid,
           SUM(od.quantity * od.unit_price) AS total
    FROM   order_header oh
    JOIN   order_detail od ON od.order_id = oh.id
    WHERE  oh.status = 'COMPLETED'
    GROUP  BY oh.customer_id
),
avg_total AS (
    SELECT AVG(total) AS avg_paid FROM order_total
)
SELECT c.name, t.total
FROM   order_total t
JOIN   customer c ON c.id = t.cid
WHERE  t.total > (SELECT avg_paid FROM avg_total)
ORDER  BY t.total DESC;
```

결과는 1-4와 동일한 김민준 42,500 / 한소희 18,000이다. 읽는 순서가 **위에서 아래로** 바뀐다. "고객별 결제합을 만들고 → 그 평균을 내고 → 평균을 넘는 사람만 남긴다." 이 세 문장이 그대로 코드 순서다. 면접에서 중첩 서브쿼리를 설명하다 막히면 **"이건 CTE로 펴면 이렇게 읽힙니다"** 라고 말하고 다시 설명하는 것이 좋은 회복 전략이다.

### 7-1. 성능은 어떤가 — 실측 (여기가 흔히 잘못 알려져 있다)

"CTE는 가독성만 바꾸고 실행계획은 똑같다"는 말은 **조건부로만 참**이다. 실제로 떠 보면 갈린다.

**(가) CTE를 한 번만 참조하면 파생 테이블과 계획이 글자까지 같다.** 1-2의 파생 테이블 버전과, 같은 것을 CTE로 쓴 버전의 계획이다.

```text
CO-ROUTINE t
  SCAN od
  SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
  USE TEMP B-TREE FOR GROUP BY
SCAN t
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY
```

두 버전이 완전히 동일했다. 이 경우에 한해 **CTE는 순수한 가독성 도구**다.

**(나) 그러나 위 7번의 CTE는 `order_total` 을 두 번 참조한다.** 그러면 계획이 달라진다.

```text
-- CTE 버전 (order_total 을 avg_total 과 본문에서 각각 참조)
MATERIALIZE order_total          ← 한 번 계산해서 임시 테이블에 담아 재사용
  SCAN od
  SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
  USE TEMP B-TREE FOR GROUP BY
SCAN t
SCALAR SUBQUERY 3
  CO-ROUTINE avg_total
    SCAN order_total             ← 담아 둔 결과를 다시 훑는다 (재계산 없음)
  SCAN avg_total
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY
```

같은 뜻을 파생 테이블로만 쓰면 이렇게 된다.

```text
-- 파생 테이블 버전 (같은 집계를 두 군데에 각각 써야 한다)
CO-ROUTINE t
  SCAN od / SEARCH oh ... / USE TEMP B-TREE FOR GROUP BY
SCALAR SUBQUERY 3
  CO-ROUTINE (subquery-2)
    SCAN od2 / SEARCH oh2 ... / USE TEMP B-TREE FOR GROUP BY   ← 같은 집계 재계산
  SCAN (subquery-2)
SCAN t
SCALAR SUBQUERY 3
  CO-ROUTINE (subquery-2)
    SEARCH oh2 USING AUTOMATIC PARTIAL COVERING INDEX (status=?)
    BLOOM FILTER ON od2 (order_id=?)
    SEARCH od2 USING AUTOMATIC COVERING INDEX (order_id=?)
    USE TEMP B-TREE FOR GROUP BY                               ← 또 재계산
  SCAN (subquery-2)
SEARCH c USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR ORDER BY
```

**결론: 같은 집계를 두 번 이상 쓰는 쿼리에서는 CTE가 가독성뿐 아니라 실행 측면에서도 낫다.** SQLite가 `MATERIALIZE` 를 선택해 한 번만 계산해 주기 때문이다. 반대로 `AS NOT MATERIALIZED` 를 강제하면 계획이 `CO-ROUTINE order_total` 두 벌로 갈라져 파생 테이블 버전과 비슷해지는 것도 확인했다.

정확한 한 문장은 이렇다 — **"1회 참조 CTE는 파생 테이블과 계획이 동일하고, 다회 참조 CTE는 SQLite가 구체화해서 재계산을 없애 준다."**

DBMS별 정책은 이렇게 다르다.

| DBMS | CTE 처리 |
|---|---|
| SQLite | 참조 횟수·형태를 보고 코루틴(인라인)/구체화를 선택. **3.35.0(2021)부터** `AS MATERIALIZED` / `AS NOT MATERIALIZED` 로 강제 가능 |
| MySQL 8 | 파생 테이블과 같은 규칙으로 바깥 쿼리에 병합(merge)하거나 구체화(materialize). **강제 수단이 있다** — `/*+ MERGE(cte명) */`, `/*+ NO_MERGE(cte명) */` 옵티마이저 힌트(8.0.16+)와 `SET optimizer_switch='derived_merge=off'` |
| PostgreSQL 12+ | 기본적으로 **인라인(병합)**. 단 조건이 있다 — 비재귀 + 부작용 없음(휘발성 함수·데이터 변경문 없음) + **정확히 1회 참조**. 이 중 하나라도 어긋나면 구체화된다 |
| PostgreSQL 11 이하 | **항상 구체화** — 이른바 **최적화 방벽(optimization fence)**. 12+에서 예전처럼 막으려면 `WITH x AS MATERIALIZED (...)` |

이 표는 "CTE가 항상 느리다/빠르다" 같은 잘못된 일반화를 막아 준다. 재귀 CTE(`WITH RECURSIVE`)는 SQLite(3.8.3+)·MySQL 8.0+·PostgreSQL(8.4+) 셋 다 지원한다.

---

## 8. 면접 예상 질문 8개 + 30초 대본

각 답변은 실제로 입 밖에 내는 문장이다. 소리 내어 읽어서 30초 안에 끝나는지 재 본다.

**Q1. 서브쿼리를 위치별로 분류해 보세요.**
> "네 자리입니다. SELECT 절은 스칼라 서브쿼리로 값 한 개를 만들어 컬럼처럼 붙입니다. FROM 절은 인라인 뷰라고 하고 표를 반환하며 별칭이 필요합니다. WHERE 절은 필터 조건으로 쓰이고, HAVING 절은 그룹 집계값과 비교할 때 씁니다. 저희 스키마로 예를 들면, SELECT 절에는 고객별 주문 건수를, WHERE 절에는 판매중 메뉴 평균가 5,181원을 기준선으로 넣었습니다."

**Q2. 상관 서브쿼리와 비상관 서브쿼리를 어떻게 구분합니까?**
> "괄호 안에서 바깥 쿼리의 별칭을 참조하면 상관입니다. 확인 방법은 간단합니다. 괄호 안만 떼어서 단독 실행해 봐서 돌아가면 비상관, `no such column` 에러가 나면 상관입니다. 실행계획에서도 `SCALAR SUBQUERY` 와 `CORRELATED SCALAR SUBQUERY` 로 구분돼서 찍힙니다."

**Q3. 상관 서브쿼리는 느리지 않나요?**
> "논리적으로는 바깥 행마다 한 번씩 평가되는 게 맞습니다. 다만 MySQL이나 PostgreSQL은 IN·EXISTS를 세미조인으로 재작성하는 최적화가 있습니다. SQLite에는 세미조인 변환이 없지만 EXPLAIN QUERY PLAN을 떠 보니 `BLOOM FILTER` 와 `AUTOMATIC COVERING INDEX` 가 붙어서 행마다 풀스캔을 반복하지는 않았습니다. 다만 테이블이 작을 때는 그냥 스캔하기도 했고, 실제 인덱스를 만들어 두면 자동 인덱스가 사라지고 그 인덱스를 탔습니다. 그래서 상관이라는 이유만으로 느리다고 단정하지 않고 계획을 확인합니다."

**Q4. IN과 EXISTS의 차이는?**
> "IN은 값 목록을 만들어 놓고 포함 여부를 봅니다. EXISTS는 목록을 만들지 않고 행이 하나라도 있는지만 보고 찾는 순간 멈춥니다. 그래서 자식 테이블이 크면 EXISTS가 유리합니다. 실행계획에서도 IN은 `LIST SUBQUERY`, EXISTS는 `CORRELATED SCALAR SUBQUERY` 로 다르게 잡혔습니다."

**Q5. NOT IN을 쓰면 안 되는 이유가 있나요?**
> "서브쿼리 결과에 NULL이 하나라도 있으면 결과가 통째로 0행이 됩니다. `x NOT IN (a, b, NULL)` 은 `NOT (x=a OR x=b OR x=NULL)` 로 풀리는데, `x=NULL` 이 UNKNOWN이라 OR 결합이 UNKNOWN이 되고, NOT UNKNOWN도 UNKNOWN이라 WHERE를 통과하지 못합니다. 실제로 상세가 없는 주문을 하나 넣어 LEFT JOIN 목록에 NULL이 끼게 만들었더니 정답인 에그샌드위치가 사라졌고, NOT EXISTS로 바꾸니 정상적으로 나왔습니다."

**Q6. 그럼 NOT EXISTS는 왜 안전합니까?**
> "EXISTS는 값을 비교하지 않고 행이 하나라도 반환되는지만 보기 때문입니다. 그 판정은 UNKNOWN이 될 수 없으니 3값 논리에 걸리지 않고 항상 TRUE 아니면 FALSE입니다. 서브쿼리가 `SELECT NULL` 을 돌려줘도 행이 있으므로 TRUE입니다. 그래서 부정 조건은 NOT EXISTS를 기본으로 씁니다."

**Q7. 스칼라 서브쿼리가 두 행 이상을 반환하면 어떻게 됩니까?**
> "DBMS마다 다릅니다. PostgreSQL은 `more than one row returned by a subquery`, MySQL 8은 에러 1242로 실행 중에 에러가 납니다. 파싱이 아니라 실행 중이라 데이터가 우연히 1행이면 통과합니다. 반면 SQLite는 에러 없이 첫 행을 씁니다. 실제로 돌려 보니 조용히 3500이 나왔습니다. 그래서 SQLite에서만 테스트하면 이식했을 때 터질 수 있어서, 스칼라 자리에는 집계 함수를 쓰거나 UNIQUE 컬럼으로 거르거나 `ORDER BY ... LIMIT 1` 로 1행을 보장합니다."

**Q8. 서브쿼리와 조인 중 무엇을 언제 씁니까?**
> "기준은 하나입니다. 결과에 서브쿼리 쪽 컬럼이 필요하면 조인, 필터링만 하면 서브쿼리입니다. 같은 요구를 세 가지로 짜서 실행계획을 비교해 봤는데, JOIN + DISTINCT 버전만 임시 B-트리를 두 번 만들었습니다. 하나는 중복 제거용이고, 나머지 하나는 구동 테이블이 customer가 아니어서 생긴 정렬용이었습니다. DISTINCT를 빼고 다시 떠 보니 정렬용은 그대로 남아 있어서 원인이 둘로 나뉜다는 걸 확인했습니다. 주문일시나 수량 같은 자식 컬럼을 함께 보여줘야 한다면 그래도 조인을 씁니다."

---

## 9. 보강 — 3값 논리는 WHERE 밖에서도 작동한다 (CHECK 제약)

3-1에서 본 UNKNOWN 규칙은 `WHERE` 전용이 아니다. **`CHECK` 제약은 판정이 UNKNOWN이면 위반이 아니라 통과**로 처리한다. 표준이 그렇게 정의되어 있다 — 제약은 "FALSE가 아니면 만족"이다. `WHERE`(TRUE만 통과)와 정반대 기준이라는 점이 핵심이다.

SQLite 3.46.1에서 직접 확인했다.

```sql
CREATE TABLE s (x TEXT CHECK (x IN ('A','B')));
INSERT INTO s VALUES (NULL);   -- 통과한다. NULL IN ('A','B') 는 UNKNOWN
INSERT INTO s VALUES ('Z');    -- IntegrityError: CHECK constraint failed: x IN ('A','B')
```

| 판정 결과 | `WHERE` | `CHECK` |
|---|---|---|
| TRUE | 통과 | 통과 |
| FALSE | 탈락 | **위반** |
| UNKNOWN | 탈락 | **통과** |

그래서 이 스키마의 `menu.is_available INTEGER NOT NULL ... CHECK (is_available IN (0,1))` 에서 **`NOT NULL` 이 진짜 일을 하고 있다.** CHECK만 걸어 두면 NULL이 그대로 들어간다. `order_header.status` 의 화이트리스트 CHECK도 마찬가지다.

**DBMS별 CHECK 지원 경계** — 자주 묻는 함정이다.

| DBMS | CHECK 강제 여부 |
|---|---|
| SQLite | 오래전부터 강제 |
| MySQL 5.7 이하 ~ **8.0.15** | **문법은 받아들이지만 조용히 무시한다.** `CREATE TABLE` 은 성공하고 제약은 없는 것과 같다 |
| **MySQL 8.0.16 이상** | 실제로 강제 — 위반 시 `ERROR 3819 (HY000): Check constraint 'xxx' is violated` |
| PostgreSQL | 오래전부터 강제 (SQLSTATE 23514 check_violation) |

"MySQL은 CHECK를 지원하지 않는다"는 흔한 서술은 **8.0.15 이하 기준**이다. 8.0.16이 경계다.

---

## 10. 보강 — 실행계획 용어를 정확히 읽기

이 문서에는 `TEMP B-TREE`, `COVERING INDEX`, `AUTOMATIC COVERING INDEX` 가 계속 나온다. 면접에서 이 단어들을 되물으면 답이 갈리므로 정리해 둔다.

**B-트리와 B+트리.** 둘 다 다분기 균형 트리지만, **레코드(값)를 어디에 두느냐**가 다르다.

| | B-트리 | B+트리 |
|---|---|---|
| 값의 위치 | 내부 노드에도 값이 있다 | **리프에만** 값이 있다 |
| 리프 연결 | 없음 | 보통 **리프끼리 연결 리스트**로 이어져 범위 스캔이 빠르다 |
| 범위 조회 | 트리를 오르내려야 한다 | 리프를 옆으로 훑으면 끝 |

SQLite 문서 기준으로 **테이블(rowid 테이블)은 B+트리**(레코드가 리프에만 있다)이고, **인덱스는 B-트리**(키가 내부 페이지에도 있다)다. 계획의 `USE TEMP B-TREE FOR ORDER BY / GROUP BY / DISTINCT` 는 "정렬·중복제거를 위해 디스크나 메모리에 임시 트리 구조를 하나 만들었다"는 뜻이며, **없앨 수 있으면 없애는 게 이득**인 항목이다(적절한 인덱스나 조인 순서로 사라지기도 한다).

**커버링 인덱스(covering index).** 쿼리가 필요한 컬럼이 전부 인덱스 안에 있어서 **테이블 본체를 읽지 않아도 되는** 경우다. 계획에 `USING COVERING INDEX sqlite_autoindex_menu_1` 이 뜬 것은 `menu.name` UNIQUE 인덱스만으로 `WHERE m.name='아메리카노'` 와 `m.id`(rowid) 확보가 끝났다는 뜻이다. `AUTOMATIC COVERING INDEX` 는 여기에 "그 인덱스를 이 쿼리를 위해 즉석에서 만들었다"가 붙은 것이다.

**같은 개념이 다른 엔진에서는 이렇게 생겼다.**

- **InnoDB(MySQL)**: 테이블 자체가 **클러스터드 인덱스**다. PK B+트리의 리프에 **행 전체**가 들어 있다. 세컨더리 인덱스의 리프에는 인덱스 키와 **PK 값**이 들어 있고 물리 주소가 아니다. 따라서 세컨더리 인덱스로 찾은 뒤 다른 컬럼이 필요하면 **PK로 클러스터드 인덱스를 한 번 더 타야 한다**(이른바 두 번째 조회). 필요한 컬럼이 세컨더리 인덱스 안에 다 있으면 이 두 번째 조회가 없어지고, `EXPLAIN` 의 Extra에 `Using index` 가 뜬다. 이것이 InnoDB의 커버링 인덱스다. PK를 길게 잡으면 모든 세컨더리 인덱스가 뚱뚱해지는 이유도 여기 있다.
- **PostgreSQL**: 테이블이 **힙(heap)**이고 인덱스는 별도다. 인덱스 리프에는 힙 안의 물리 위치(TID/ctid)가 들어 있고 클러스터드 인덱스라는 개념이 없다(`CLUSTER` 명령은 일회성 물리 재배치이지 유지되는 구조가 아니다). 그래서 인덱스만으로 끝내려면 **Index Only Scan**이 필요한데, MVCC 때문에 가시성(visibility map) 확인이 추가로 걸린다. 커버링을 노리면 `CREATE INDEX ... INCLUDE (컬럼)` 을 쓴다.
- **SQLite**: `INTEGER PRIMARY KEY` 는 rowid의 별칭이므로 rowid 테이블이 곧 PK 클러스터다. 계획에 `SEARCH ... USING INTEGER PRIMARY KEY (rowid=?)` 가 뜨는 것이 그 조회다.

참고로 **LSM 트리**(RocksDB·LevelDB 계열)는 위 셋과 계열이 다르다. 쓰기를 메모리 테이블에 모았다가 정렬된 파일로 순차 flush하고 나중에 컴팩션으로 합치는 구조라 **쓰기에 유리하고 읽기(특히 범위 밖 점 조회)에 불리**하며, 그 불리함을 블룸 필터로 보완한다. SQLite 계획에 나온 `BLOOM FILTER` 는 LSM과 무관하게 **조인 조건에 맞을 가능성이 없는 행을 미리 걸러내는 용도**로 쓰인 것이니 둘을 섞어 말하지 않는다.

---

## 11. 보강 — 파이썬에서 다룰 때

서브쿼리 결과를 애플리케이션에서 받을 때 두 가지가 자주 문제가 된다.

**(1) 스칼라 서브쿼리는 NULL을 돌려줄 수 있다.** 0행이면 에러가 아니라 `None` 이다.

```python
import sqlite3

conn = sqlite3.connect("fresh.db")
row = conn.execute(
    "SELECT (SELECT MAX(price) FROM menu WHERE category_id = ?)", (999,)
).fetchone()
print(row[0])            # None  ← 에러가 아니다

# 금액을 다룬다면 SQL 쪽에서 막는 편이 낫다
row = conn.execute(
    "SELECT COALESCE((SELECT SUM(price) FROM menu WHERE category_id = ?), 0)", (999,)
).fetchone()
print(row[0])            # 0
```

**(2) 제약 위반 예외 매핑.** 파이썬 `sqlite3` 는 FK·UNIQUE·CHECK·NOT NULL 위반을 **모두 `sqlite3.IntegrityError` 하나로** 던진다. 어떤 제약이 깨졌는지는 메시지나 상세 에러코드로 구분한다(`sqlite_errorname` / `sqlite_errorcode` 는 파이썬 3.11+).

```python
import sqlite3

conn = sqlite3.connect("fresh.db")
conn.execute("PRAGMA foreign_keys = ON")     # SQLite는 연결마다 기본 OFF다

try:
    conn.execute("INSERT INTO menu (name, price, category_id) VALUES ('테스트', -1, 1)")
except sqlite3.IntegrityError as e:
    print(type(e).__name__)          # IntegrityError
    print(str(e))                    # CHECK constraint failed: price >= 0
    print(e.sqlite_errorname)        # SQLITE_CONSTRAINT_CHECK
    print(e.sqlite_errorcode)        # 275
finally:
    conn.rollback()
```

실행해 확인한 매핑이다.

| 위반 | SQLite 메시지 | `sqlite_errorname` / 코드 |
|---|---|---|
| CHECK | `CHECK constraint failed: <식>` | `SQLITE_CONSTRAINT_CHECK` / 275 |
| UNIQUE | `UNIQUE constraint failed: <표.컬럼>` | `SQLITE_CONSTRAINT_UNIQUE` / 2067 |
| NOT NULL | `NOT NULL constraint failed: <표.컬럼>` | `SQLITE_CONSTRAINT_NOTNULL` / 1299 |
| FK | `FOREIGN KEY constraint failed` | `SQLITE_CONSTRAINT_FOREIGNKEY` / 787 |

예외 계층은 `IntegrityError → DatabaseError → Error → Exception` 이다. 그러므로 `except sqlite3.DatabaseError` 로 잡으면 제약 위반과 문법 오류(`OperationalError`)가 섞이지 않도록 순서를 신경 써야 한다. `sqlite3.OperationalError` 는 `no such column: c.id` 같은 5번·2번 항목의 에러가 올라오는 자리다.

다른 DBMS로 옮길 때의 대응은 이렇다.

| 위반 / 상황 | SQLite | MySQL 8 (errno) | PostgreSQL (SQLSTATE) |
|---|---|---|---|
| UNIQUE | `SQLITE_CONSTRAINT_UNIQUE` | 1062 `ER_DUP_ENTRY` | `23505` unique_violation |
| FK | `SQLITE_CONSTRAINT_FOREIGNKEY` | 1452 / 1451 | `23503` foreign_key_violation |
| CHECK | `SQLITE_CONSTRAINT_CHECK` | **3819** (8.0.16+) | `23514` check_violation |
| NOT NULL | `SQLITE_CONSTRAINT_NOTNULL` | 1048 `ER_BAD_NULL_ERROR` | `23502` not_null_violation |
| 스칼라 서브쿼리 다중행 | (에러 없음) | 1242 | `21000` cardinality_violation |

드라이버에서 코드를 꺼내는 속성도 제각각이다 — `mysql.connector` 는 `e.errno` / `e.sqlstate`, `psycopg2` 는 `e.pgcode`, `psycopg`(3)는 `e.sqlstate`. **"IntegrityError로 뭉뚱그리지 말고 코드로 분기한다"** 가 이식성 있는 예외 처리의 기준이다.

---

## 부록: 60초 자가 점검

아래 문장을 보지 않고 말할 수 있으면 이 모듈은 끝난 것이다.

| 체크 | 한 문장 |
|---|---|
| □ | 서브쿼리 자리는 SELECT·FROM·WHERE·HAVING 네 곳 |
| □ | 괄호 안에서 바깥 별칭 쓰면 상관, 아니면 비상관 (계획에도 `CORRELATED` 로 찍힌다) |
| □ | 괄호가 반환하는 모양을 먼저 말한다 — 값 1개 / 목록 / 표 / 존재여부 |
| □ | 부정 조건은 NOT EXISTS. NOT IN은 목록에 NULL 하나면 0행 |
| □ | LEFT JOIN 결과를 IN/NOT IN 목록으로 그대로 쓰지 않는다 (거기서 NULL이 생긴다) |
| □ | WHERE는 TRUE만 통과, CHECK는 UNKNOWN도 통과 — 기준이 반대다 |
| □ | SQLite는 스칼라 다중행을 봐주지만 PG·MySQL은 실행 중 에러 |
| □ | SQLite에 ANY/ALL은 없다. `> ALL` → `> MAX`, `> ANY` → `> MIN` (공집합·NULL이면 결과가 갈림) |
| □ | 파생 테이블 별칭: SQLite 생략 가능, MySQL 8 필수, PG는 16부터 생략 가능 |
| □ | 1회 참조 CTE = 파생 테이블과 계획 동일 / 다회 참조 CTE = SQLite가 MATERIALIZE로 재계산 제거 |
| □ | 결과에 자식 컬럼 필요 → 조인, 필터링만 → 서브쿼리 |
| □ | `AUTOMATIC COVERING INDEX` 는 자랑이 아니라 인덱스를 만들라는 신호 |
| □ | 막히면 "CTE로 펴면 이렇게 읽힙니다" 로 회복 |

**참고 파일** — `/home/coder/volume/codyssey_B5-1/04_bonus.sql` (1-a~1-d), `/home/coder/volume/codyssey_B5-1/03_queries.sql` (Q12), `/home/coder/volume/codyssey_B5-1/01_schema.sql`, `/home/coder/volume/codyssey_B5-1/02_data.sql`.

**재현 조건** — 본문의 모든 결과값과 실행계획은 `01_schema.sql + 02_data.sql` 로 **새로 만든** DB(customer 10명, category 10개, menu 12개, order_header 12건 — COMPLETED 9 / PENDING 1 / CANCELLED 2, order_detail 20행)에 SQLite **3.46.1**로 직접 실행해 얻은 실측치다. 저장소에 커밋된 `cafe.db` 는 `03_queries.sql` 실행 후 상태(order_header 10행 / order_detail 18행 / 아메리카노 4000원 / 인덱스 2개 추가)이므로 그대로 쓰면 4번 항목이 3행이 되고 실행계획도 달라진다. 0-1의 절차로 DB를 새로 만든 뒤 확인한다. 파괴적인 실험(3-1의 빈 주문 삽입 등)은 반드시 `BEGIN` ~ `ROLLBACK` 으로 감싼다.
