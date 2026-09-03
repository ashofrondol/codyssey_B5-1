# 주석 없이 쿼리 읽기

> 평가 피드백 2, 6, 8 대응 — 실행 순서를 읽기 절차로 바꾸고, 3초 안에 입이 열리게 만든다. 평가에서 실제로 막힌 지점.

---

## 0. 이 모듈이 고치는 것

평가 피드백 2·6·8은 전부 같은 증상 하나를 가리킨다. **쿼리를 보고 말이 나오기까지의 지연**이다. 개념을 모르는 게 아니다. README에는 `COUNT(*)`와 `COUNT(oh.id)`의 차이, ON절 필터와 WHERE절 필터의 차이까지 다 적혀 있다. 문제는 그 지식이 **주석이라는 목발**에 붙어 있어서, 주석을 떼면 접근 경로가 사라진다는 것이다.

해결책은 개념을 다시 공부하는 게 아니라 **읽는 순서를 몸에 고정시키는 것**이다. 순서가 고정되면 겁먹을 구간이 없어진다. 다음에 뭘 봐야 할지 항상 알기 때문이다.

이 문서에 나오는 모든 수치는 이 프로젝트의 DB에서 직접 실행해 확인한 값이다. 어느 상태의 DB에서 나온 값인지는 §7에서 구분해 둔다. **이게 중요한 이유는, 지금 저장소에 있는 `cafe.db`가 이미 Q13·Q14까지 적용된 사후 상태이기 때문**이다. 드릴을 시작하기 전에 §7의 재빌드 절차를 먼저 읽어라.

---

## 1. 쿼리 읽는 고정 순서 — 실행 순서를 '읽기 절차'로 바꾼다

SQL은 쓰는 순서와 실행 순서가 다르다. 학습자가 느린 이유는 **쓰는 순서대로 읽기 때문**이다. `SELECT c.id, c.name, COALESCE(SUM(...))`를 먼저 읽으면 아직 존재하지도 않는 `c`와 `od`를 해석하려다 막힌다.

| 쓰는 순서 | 실행 순서 | 읽을 때 머릿속에 그릴 것 | 행 수 변화 |
|---|---|---|---|
| 1 SELECT | 6 | 최종 출력 컬럼. **맨 나중에 본다** | 불변 |
| 2 FROM | 1 | 기준 테이블 1개. 이게 결과의 '한 행'의 정체 | 원본 행 수 |
| 3 JOIN/ON | 2 | 옆에 판을 붙인다. 1쪽이면 유지, N쪽이면 **증식** | 늘어남/유지/줄어듦 |
| 4 WHERE | 3 | 붙인 판 전체에서 행을 **잘라낸다** | 줄어듦 |
| 5 GROUP BY | 4 | 같은 키끼리 바구니로 **접는다** | 키 종류 수로 축소 |
| 6 HAVING | 5 | 바구니 단위로 잘라낸다 | 줄어듦 |
| (DISTINCT) | 6.5 | SELECT로 만든 결과에서 중복 행을 지운다 | 줄어듦/유지 |
| 7 ORDER BY | 7 | 줄 세우기. **표준상 SELECT 별칭을 쓸 수 있는 유일한 절** | 불변 |
| 8 LIMIT | 8 | 위에서 n개 자르기 | 줄어듦 |

> **DISTINCT의 위치가 중요한 이유**: 04_bonus (1-a)의 DISTINCT는 조인이 만들어 낸 중복을 *나중에* 걷어내는 것이다. 조인 단계에서 중복이 안 생기게 막는 게 아니다. 4주차 시험 문항의 핵심이 바로 이 순서다.
>
> **별칭 규칙의 실제**: "ORDER BY에서만 별칭을 쓸 수 있다"는 것은 **표준 SQL 이야기**다. 실제 DBMS는 더 관대하다.
>
> | | WHERE | GROUP BY | HAVING | ORDER BY |
> |---|---|---|---|---|
> | 표준 SQL | ✗ | ✗ | ✗ | ✓ |
> | SQLite | **✓** (확장) | ✓ | ✓ | ✓ |
> | MySQL 8 | ✗ | ✓ | ✓ | ✓ |
> | PostgreSQL | ✗ | ✓ | ✗ | ✓ |
>
> 실측: SQLite에서 `SELECT status AS s FROM order_header WHERE s = 'PENDING'` 이 그대로 실행된다. 하지만 **이식성이 없으니 쓰지 마라.** 평가장에서는 "표준상 ORDER BY에서만 되고, SQLite는 예외적으로 WHERE에서도 받아 줍니다"까지 말하면 된다.

### 각 단계에서 그려야 하는 '그림'

**FROM** — 이 쿼리 결과 한 줄이 무엇인가를 정한다. `FROM customer c`면 결과 한 줄은 "고객 한 명"이고, `FROM order_detail od`면 "주문 상세 한 줄"이다. Q6이 `FROM order_detail od`로 시작하는 이유가 바로 이것이다.

> ⚠️ **오해 주의**: FROM에 무엇을 쓰느냐가 결과 행 수를 바꾸는 것은 **아니다.** INNER JOIN으로 이어진 쿼리는 FROM 순서를 바꿔도 결과 집합이 동일하고, 옵티마이저가 실제 조인 순서를 알아서 정한다.
> 실측: Q6를 `FROM order_detail od …`로 쓴 것과 `FROM customer c …`로 쓴 것 모두 20행이고 정렬하면 완전히 같은 결과다. EXPLAIN QUERY PLAN도 두 경우 다 `SCAN od`부터 시작한다.
> 즉 "가장 세밀한 테이블을 FROM에 둔다"는 것은 **사람이 읽기 위한 규약**이지 실행 규칙이 아니다. 결과 한 행의 정체(grain)를 첫 줄에서 못 박아 두려는 것이다. 평가장에서도 이렇게 말해야 정확하다.

**JOIN** — 조인은 항상 "행이 늘어나는가, 유지되는가, 줄어드는가" 세 가지를 판단한다.

| 조인 방향 | ON절 모양 | 행 수 | 조건 |
|---|---|---|---|
| N쪽 → 1쪽 (자식이 부모를 본다) | `oh.id = od.order_id` (상대가 PK) | **유지** | 붙는 쪽이 PK/UNIQUE **이고** FK가 NOT NULL **이고** FK 검사가 켜져 있을 때 |
| N쪽 → 1쪽인데 짝이 없다 | 위와 같은 모양, 그런데 고아 행 존재 | **줄어듦** | INNER JOIN일 때. LEFT JOIN이면 유지 |
| 1쪽 → N쪽 (부모가 자식을 본다) | `oh.customer_id = c.id` (내 PK를 상대가 FK로) | **증식** | 자식이 0건인 부모는 INNER면 소멸, LEFT면 NULL로 생존 |

`INNER JOIN order_header oh ON oh.id = od.order_id` — 붙는 쪽 `oh.id`가 PK다. 주문 상세 한 줄에 헤더는 최대 하나 붙는다. `order_detail.order_id`가 NOT NULL이고 FK 검사가 켜진 상태로 데이터가 들어왔으니 반드시 딱 하나 붙는다. 행 안 늘어난다.
`LEFT JOIN order_header oh ON oh.customer_id = c.id` — 붙는 쪽이 FK다. 고객 한 명에 주문이 여러 건 붙는다. 행 늘어난다.

> **SQLite에서 "FK가 NOT NULL이니까 안전하다"고 말할 때의 함정**: SQLite는 `PRAGMA foreign_keys`가 **연결마다 기본 OFF**다. NOT NULL은 "값이 있다"만 보장하지 "그 값이 부모에 실재한다"는 보장이 아니다. 검사가 꺼진 상태로 들어간 고아 행이 있으면 INNER JOIN에서 그 행은 사라진다. 이 프로젝트는 01/02/03/04 모든 파일 첫 줄에서 `PRAGMA foreign_keys = ON`을 켜므로 안전하다.

**GROUP BY** — 바구니에 접는 동작이다. `GROUP BY c.id, c.name`이면 결과 행 수 = customer의 서로 다른 id 개수. 조인으로 20행까지 부풀었어도 여기서 10행으로 되접힌다. **집계 함수는 이 바구니 안을 훑는 도구**다.
(참고: GROUP BY 없이 집계 함수만 쓰면 테이블 전체가 바구니 하나가 되어 항상 1행이 나온다. 대상 행이 0건이어도 1행이다.)

---

## 2. 3초 스캔 → 30초 요약 → 3분 설명

평가장에서 침묵이 생기는 이유는 "완벽한 설명"을 한 번에 만들려 하기 때문이다. 세 단계로 쪼개면 3초 뒤에 이미 입이 열린다.

| 단계 | 보는 곳 | 하는 말 | 절대 하지 말 것 |
|---|---|---|---|
| **3초 스캔** | 첫 단어(SELECT/UPDATE/DELETE), FROM 줄, JOIN 개수, GROUP BY 유무 | "조회 쿼리고, customer 기준으로 테이블 두 개를 LEFT JOIN한 뒤 고객별로 묶는 집계 쿼리입니다." | SELECT 컬럼 읽기 |
| **30초 요약** | FROM/JOIN의 별칭 표 + GROUP BY 키 + SELECT의 집계 함수 하나 | "결과 한 줄은 고객 한 명이고, 값은 그 고객의 결제 완료 주문 금액 합계입니다. 주문이 없는 고객도 0원으로 남습니다." | 컬럼 하나씩 낭독 |
| **3분 설명** | 실행 순서대로 한 줄씩 + 행 수 추적 + 설계 판단 1개 | 아래 §4 대본 | 순서 뒤섞기 |

**3초 스캔에서 말할 문장의 틀**은 항상 같다.

> "이건 [조회/수정/삭제] 쿼리고, [기준 테이블] 기준으로 [조인 개수]개를 [INNER/LEFT] 조인한 뒤 [묶는다/안 묶는다] 입니다."

이 한 문장은 쿼리를 **이해하기 전에도** 말할 수 있다. 첫 3초에 이 문장을 뱉으면 그 뒤 30초 동안 뇌가 조용히 읽을 시간을 번다. 침묵은 못 읽는 것으로 보이지만, 이 문장은 "구조 파악 중"으로 보인다.

---

## 3. 별칭 해독법 — FROM/JOIN 줄만 먼저 훑는다

**습관 하나만 바꾼다: 쿼리를 받으면 손가락(또는 눈)으로 FROM과 JOIN이 들어간 줄만 위에서 아래로 훑어 별칭 표를 먼저 만든다.** SELECT는 아직 안 본다.

```sql
FROM    customer c
LEFT    JOIN order_header oh ON ...
LEFT    JOIN order_detail od ON ...
```

머릿속(또는 종이 귀퉁이)에 3초 안에 이렇게 적는다.

```text
c  = customer      (기준, 1쪽)
oh = order_header  (N쪽)
od = order_detail  (N쪽, oh의 자식)
```

### 이 프로젝트에서 반드시 조심할 함정

03_queries.sql에서 **`c`는 두 가지 뜻으로 쓰인다.** 파일을 직접 훑어 확인했다.

| 별칭 `c`의 정체 | 해당 쿼리 |
|---|---|
| `c` = **customer** | Q6, Q7, Q7-B, Q10, Q10-B / 04_bonus (1-a), (1-c) |
| `c` = **category** | Q5, Q8, Q8-B, Q11, Q11-B |
| 별칭 자체가 없음 | Q1~Q4-B, Q9, Q12, Q13, Q14 (단일 테이블이라 별칭이 불필요) |

이걸 모르면 Q8을 읽다가 `c.name`을 고객 이름으로 착각한다. 그래서 **별칭은 매 쿼리마다 새로 잡아야 한다**. 앞 쿼리의 별칭 기억을 끌고 오면 안 된다. 별칭 표를 3초 안에 다시 만드는 습관이 이 실수를 원천 차단한다.

특히 4주차 시험 대상인 04_bonus (1-a)는 `c = customer`인데, 바로 앞에서 Q11-B(`c = category`)를 읽었다면 뒤집어 읽기 쉽다.

고정적으로 안전한 것은 `oh = order_header`, `od = order_detail`, `m = menu` 세 개뿐이다. 이 세 개는 두 파일 전체에서 예외가 없다.

---

## 4. Q10 낭독 대본 — 한 줄씩 실제로 입으로 읽는 문장

대상 쿼리(주석 제거 상태):

```sql
SELECT c.id, c.name, COALESCE(SUM(od.quantity * od.unit_price), 0) AS total_paid
FROM customer c
LEFT JOIN order_header oh ON oh.customer_id = c.id AND oh.status = 'COMPLETED'
LEFT JOIN order_detail od ON od.order_id = oh.id
GROUP BY c.id, c.name
ORDER BY total_paid DESC, c.id;
```

### 4-1. 3초 스캔 대본 (그대로 읽는다)

> "조회 쿼리입니다. customer가 기준이고, LEFT JOIN이 두 번, GROUP BY가 있으니 고객별 집계 쿼리입니다. 먼저 FROM부터 보겠습니다."

### 4-2. 30초 요약 대본

> "결과 한 줄은 고객 한 명입니다. customer를 기준으로 order_header, order_detail을 왼쪽 조인해서 붙이고, 고객 id로 다시 묶어서 금액 합계를 냅니다. LEFT JOIN이니까 주문이 하나도 없는 고객도 결과에서 사라지지 않고, COALESCE 때문에 0원으로 표시됩니다."

### 4-3. 3분 설명 대본 — 실행 순서대로 한 줄씩

**① FROM 줄을 짚으며**

> "FROM이 customer c 니까, 이 결과의 한 행은 고객 한 명입니다. 지금 시작 시점의 행 수는 고객 10명, 10행입니다."

**② 첫 번째 LEFT JOIN 줄을 짚으며**

> "여기서 order_header를 붙입니다. ON 조건이 oh.customer_id = c.id 인데, 붙는 쪽이 FK 컬럼입니다. 즉 1쪽인 고객에서 N쪽인 주문으로 내려가는 조인이라 **행이 늘어납니다.** 그리고 LEFT니까 주문이 없는 고객도 오른쪽을 전부 NULL로 채운 채 살아남습니다."

**③ 같은 줄의 `AND oh.status = 'COMPLETED'`를 짚으며 (여기가 이 쿼리의 핵심)**

> "ON절에 AND로 상태 조건이 하나 더 붙어 있습니다. 이건 WHERE가 아니라 **조인 조건**입니다. 의미가 다릅니다.
> ON절에 있으면 '**COMPLETED인 주문만 골라서 붙여라**' 입니다. 붙일 게 없으면 안 붙이고 NULL로 두지만, 왼쪽 고객 행 자체는 남습니다.
> 만약 이 조건을 WHERE로 내리면 조인이 **다 끝난 뒤에** 행을 걸러냅니다. 그런데 주문이 없는 고객은 oh.status가 NULL이고, **NULL은 비교 연산자에 대해 절대 참이 되지 않습니다.** `NULL = 'COMPLETED'`는 거짓이 아니라 UNKNOWN이고, WHERE는 TRUE인 행만 남기므로 UNKNOWN인 행을 버립니다. 그래서 **주문 없는 고객이 통째로 탈락하고, LEFT JOIN이 사실상 INNER JOIN이 됩니다.**
> 실제로 돌려봤습니다. ON절에 두면 10행, WHERE로 내리면 7행입니다. 박지호, 윤하늘, 서지안 세 명이 사라집니다."

> ※ 꼬리질문 대비: "NULL은 어떤 비교에도 참이 안 된다"는 말은 **비교 연산자(`=`, `<>`, `<`, `>`, `LIKE`, `IN`)에 한정**된다. `IS NULL`, `IS NOT NULL`, `IS NOT DISTINCT FROM`은 NULL을 정상적으로 판정한다. 그래서 "WHERE oh.status IS NULL"로 '완료 주문 없는 고객'을 뽑는 것은 가능하다. 자세한 것은 §9.

**④ 두 번째 LEFT JOIN 줄을 짚으며**

> "이번엔 order_detail을 붙입니다. ON이 od.order_id = oh.id 니까 또 1쪽에서 N쪽으로 내려가는 조인이고, 주문 한 건에 상세가 여러 줄이니 **행이 또 늘어납니다.** 여기도 LEFT여야 합니다. 앞 단계에서 oh가 NULL인 행이 있는데 INNER로 쓰면 그 행들이 여기서 죽어버립니다."

**⑤ 여기서 행 수를 실측값으로 말한다 (평가자가 가장 좋아하는 지점)**

> "행 수를 따라가 보면 이렇습니다. 시작 10행, 첫 조인 뒤 12행, 두 번째 조인 뒤 20행, GROUP BY로 다시 10행입니다."

| 단계 | 행 수 | 내역 |
|---|---|---|
| `FROM customer c` | **10** | 고객 10명 |
| `LEFT JOIN order_header` (ON에 status 포함) | **12** | COMPLETED 주문 9건 + 짝 없는 고객 3명(NULL) |
| `LEFT JOIN order_detail` | **20** | COMPLETED 주문의 상세 17행 + NULL 3행 |
| `GROUP BY c.id, c.name` | **10** | 고객 id 종류 수만큼 접힘 |

> ※ 마지막 20행이 초기 데이터의 order_detail 전체 행 수 20과 우연히 같지만 **내용은 다르다.** order_detail 20행 중 3행은 CANCELLED·PENDING 주문 소속이라 여기 안 들어오고(취소 2건에 1행씩, 미결제 1건에 1행 — 실측), 대신 NULL 행 3개가 자리를 채운 결과다. 이 구분을 말할 수 있으면 "숫자를 외운 게 아니라 이해한 것"으로 보인다.
>
> ※ 이 10/12/20/10 추적은 Q14(CANCELLED 삭제) 실행 **전후 모두 같다**. 취소 주문은 애초에 ON절에서 걸러지기 때문이다. 실측으로 두 상태 모두 확인했다. 그래서 이 표는 §7의 어느 DB로 드릴하든 그대로 쓸 수 있다.

**⑥ GROUP BY 줄을 짚으며**

> "GROUP BY c.id, c.name 으로 고객 단위로 다시 접습니다. c.id가 PK라 c.name은 c.id에 함수적으로 종속됩니다. 그래서 c.name을 빼도 논리적으로는 문제가 없지만, DBMS마다 받아 주는 범위가 달라서 둘 다 적는 쪽이 안전합니다."

꼬리질문이 들어오면 이 표대로 답한다. **이 부분은 DBMS마다 동작이 정확히 다르므로 뭉뚱그리면 안 된다.**

| DBMS | `GROUP BY c.id` 만 쓰고 `c.name`을 SELECT하면 |
|---|---|
| SQLite | 그냥 통과. 그룹 안의 **임의의 한 행** 값을 뽑는다(어느 행인지 보장 없음). 표준에서 가장 멀다 |
| MySQL 8 | 기본 `sql_mode`에 **ONLY_FULL_GROUP_BY 포함**(5.7.5부터 기본값)이라 원칙적으로 에러. 단 `c.id`가 PK/UNIQUE NOT NULL이면 함수 종속을 인식해 **허용**한다 |
| PostgreSQL | 9.1부터 PK로 묶은 경우 함수 종속을 인식해 **허용**. 그 외 비집계 컬럼은 에러 |

> 원문 초안에 있던 "SQLite와 MySQL 8은 느슨하게 허용한다"는 서술은 정확하지 않다. MySQL 8은 오히려 기본이 엄격하고, PostgreSQL과 같은 함수 종속 예외를 갖는다. 느슨한 것은 SQLite뿐이다.

**⑦ 이제서야 SELECT 줄로 올라간다**

> "이제 SELECT를 봅니다. SUM(od.quantity * od.unit_price)는 바구니 안의 상세 줄마다 수량 곱하기 단가를 구해서 더합니다. 단가를 menu.price가 아니라 order_detail.unit_price에서 가져오는 게 중요합니다. 메뉴 가격은 나중에 바뀌지만 주문 시점 금액은 order_detail에 스냅샷으로 박혀 있어야 과거 매출이 안 흔들립니다.
> COALESCE는 SUM이 대상 행이 하나도 없거나 값이 전부 NULL일 때 0이 아니라 **NULL**을 돌려주기 때문에 씌웠습니다. 박지호처럼 완료 주문이 없는 고객은 od 컬럼이 전부 NULL이라 SUM도 NULL이 되는데, 그대로 두면 리포트에 빈칸이 찍힙니다. 0으로 바꿔줍니다."

> ※ 실측 근거: `SELECT COUNT(*), SUM(v), AVG(v) FROM s WHERE v > 100` → `(0, None, None)`. COUNT만 0을 돌려주고 SUM·AVG는 NULL이다. "COUNT는 0, SUM은 NULL"이 한 세트로 나오는 대답이다.

**⑧ ORDER BY 줄**

> "ORDER BY total_paid DESC — total_paid는 SELECT에서 만든 별칭인데, ORDER BY는 SELECT 다음에 실행되므로 별칭을 쓸 수 있습니다. 표준 SQL에서 별칭을 쓸 수 있는 절은 ORDER BY뿐이고, WHERE에서는 못 씁니다. 아직 그 별칭이 만들어지기 전이기 때문입니다. 다만 SQLite는 확장으로 WHERE에서도 별칭을 받아 주는데, MySQL·PostgreSQL에서는 에러가 나므로 의존하지 않는 게 맞습니다. 뒤의 c.id는 금액이 같을 때 순서가 흔들리지 않게 하는 타이브레이커입니다."

**⑨ 실행 결과와 '0원 세 명'을 마무리로 (실측값)**

| id | 이름 | total_paid | 0원인 이유 |
|---|---|---|---|
| 1 | 김민준 | 42,500 | 완료 주문 3건 |
| 6 | 한소희 | 18,000 | |
| 2 | 이서연 | 16,000 | PENDING 주문 1건(3,500원)은 제외됨 |
| 4 | 최예린 | 15,000 | |
| 8 | 장민서 | 14,500 | |
| 5 | 정우진 | 10,500 | |
| 7 | 오재현 | 9,000 | |
| 3 | 박지호 | 0 | 주문했지만 CANCELLED |
| 9 | 윤하늘 | 0 | 주문했지만 CANCELLED |
| 10 | 서지안 | 0 | 주문 자체가 없음 |

> 이 표는 초기 상태 DB와 현재 저장소의 `cafe.db`(Q13·Q14 적용 후) **둘 다에서 동일하게 재현된다.** 금액이 `order_detail.unit_price` 스냅샷이라 Q13의 가격 인상에 영향을 받지 않고, 취소 주문은 어차피 ON절에서 걸러지기 때문이다. 실측으로 두 DB 모두 확인했다. 다만 Q14 이후에는 박지호·윤하늘의 취소 주문 자체가 삭제되어 **0원인 이유가 셋 다 '주문 이력 없음'으로 바뀐다.** 이 차이는 Q10-B로 드러난다.

> "0원이 세 명인데 성격이 다릅니다. 박지호와 윤하늘은 주문은 했지만 취소됐고, 서지안은 주문 이력 자체가 없습니다. 이 쿼리는 셋을 0원으로 뭉개기 때문에, 마케팅용으로 쓰려면 Q10-B처럼 주문 이력을 따로 세어 구분해야 합니다."

---

## 5. 스키마를 짚으며 말하는 법 — 실전 발화 문장 12개

평가자가 "스키마 테이블을 보면서 이야기해도 좋다"고 한 것은 **허락이 아니라 기술 지시**다. 스키마를 손가락으로 짚으면 세 가지가 동시에 해결된다. ① 눈이 갈 곳이 생겨 시선 처리가 안정된다 ② 다음에 말할 것이 손끝에 있어 침묵이 안 생긴다 ③ 듣는 사람도 같은 곳을 봐서 설명이 전달된다.

**짚는 방법**: 왼손 검지로 **자식 테이블의 FK 컬럼**을, 오른손 검지로 **부모 테이블의 PK**를 짚고, 두 손을 연결하듯 움직이며 말한다.

그대로 외워서 쓰는 문장 12개다. 문장마다 근거를 실측으로 확인했다.

1. > "이 조인은 order_detail의 order_id가 order_header의 id를 가리키니까, N쪽에서 1쪽으로 붙는 겁니다. 붙는 쪽이 PK라 상세 한 줄에 헤더가 최대 하나만 붙고, order_id가 NOT NULL이라 실제로는 정확히 하나 붙습니다. 행 안 늘어납니다."
2. > "반대로 이건 customer의 id를 order_header의 customer_id가 가리키는 방향이라, 1쪽에서 N쪽으로 내려갑니다. 여기서 행이 늘어납니다."
3. > "이 FK는 NOT NULL이고 PRAGMA foreign_keys가 켜져 있으니 부모 없는 자식은 없습니다. 그래서 이 조인은 INNER로 써도 행이 안 사라집니다. **SQLite는 FK 검사가 연결마다 기본 OFF라서, 이 전제는 PRAGMA를 켰다는 조건이 있어야 성립합니다.**"
    - 이 프로젝트는 01/02/03/04 네 파일 모두 첫 줄에서 `PRAGMA foreign_keys = ON`을 켠다. MySQL·PostgreSQL은 FK가 기본 활성이라 이런 스위치 자체가 없다.
4. > "order_detail의 order_id는 ON DELETE CASCADE입니다. 헤더를 지우면 상세가 같이 지워집니다. Q14에서 CANCELLED 주문 2건을 지우면 거기 딸린 상세 2행도 함께 사라져서 order_detail이 20행에서 18행이 됩니다. **다만 CASCADE도 FK 검사가 켜져 있어야 동작합니다.** 꺼진 채로 지우면 상세가 고아로 남습니다."
    - 실측 확인: `PRAGMA foreign_keys = ON` 상태로 03_queries.sql을 끝까지 돌리면 order_detail이 정확히 18행이 된다.
5. > "menu의 category_id에는 삭제 정책을 안 걸었습니다. 기본값 NO ACTION이라 메뉴가 달린 카테고리는 삭제가 막힙니다. 이게 의도한 동작입니다."
    - 실측: `DELETE FROM category WHERE id = 1` → `IntegrityError: FOREIGN KEY constraint failed`.
    - 꼬리질문 대비: 표준 SQL에서 NO ACTION과 RESTRICT는 **검사 시점**이 다르다. RESTRICT는 즉시 막고, NO ACTION은 문장이 끝날 때까지 미룬다. 둘 다 결국 거부하므로 결과는 같지만, 제약을 지연(DEFERRABLE)시킬 때 차이가 난다. SQLite는 둘 다 지원한다.
6. > "category에는 메뉴가 0개인 '굿즈'가 있습니다. 그래서 INNER JOIN으로 세면 9행, LEFT JOIN으로 세면 10행입니다. 재고 0인 카테고리를 찾으려면 INNER로는 답이 안 나옵니다."
    - 실측: Q8 = 9행, Q8-B = 10행. 카테고리 10개 중 메뉴가 달린 것이 9개다.
7. > "order_header의 status에 CHECK 제약이 걸려 있고 컬럼이 NOT NULL이라, 값이 PENDING·COMPLETED·CANCELLED 셋 중 하나로 보장됩니다. **CHECK 하나만으로는 부족합니다. CHECK는 결과가 UNKNOWN이면 통과시키기 때문에 NULL은 그냥 지나갑니다.** NOT NULL이 같이 걸려 있어서 구멍이 막힌 겁니다."
    - 실측: `CREATE TABLE t(x INTEGER CHECK (x > 0)); INSERT INTO t VALUES(NULL);` → 성공. NULL은 CHECK를 통과한다.
    - 실측 에러 메시지: `INSERT INTO order_header(customer_id, status) VALUES (1, 'DONE')` → `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')`.
    - 이식성 꼬리질문: **MySQL은 8.0.16부터 CHECK를 실제로 강제한다.** 그 이전(5.7, 8.0.15까지)은 문법만 파싱하고 조용히 무시했다. SQLite와 PostgreSQL은 오래전부터 강제한다.
    - "그래서 앱에서 검증이 필요 없다"고까지 말하면 안 된다. DB 제약은 **최후 방어선**이고, 앱은 사용자에게 이유를 보여주기 위해 여전히 검증한다. 다만 앱 검증을 우회한 경로(직접 SQL, 배치)에서도 데이터가 깨지지 않는다는 것이 DB 제약의 가치다.
8. > "unit_price가 order_detail에 따로 있는 이유는, menu.price가 나중에 바뀌어도 과거 주문 금액이 안 흔들리게 하려는 스냅샷이기 때문입니다. Q13에서 아메리카노를 3,500원에서 4,000원으로 올려도 과거 매출 합계는 그대로입니다."
    - 실측: Q13 실행 후에도 Q10의 김민준 합계는 42,500원으로 동일하다.
    - 꼬리질문 대비: "그건 정규화 위반 아닌가요?"에 대한 답 → 아니다. 파생·중복 데이터가 아니라 **시점이 다른 별개의 사실**이다. `menu.price`는 '지금 가격', `order_detail.unit_price`는 '그때 가격'이며 서로 함수 종속 관계가 아니다. 자세한 것은 §11.
9. > "customer.email에 UNIQUE가 걸려 있어서 SQLite가 sqlite_autoindex_customer_1 인덱스를 자동으로 만듭니다. 인덱스를 따로 만들 필요가 없습니다."
    - 실측: 이 DB의 인덱스는 총 5개다. `sqlite_autoindex_customer_1`(email), `sqlite_autoindex_category_1`(name), `sqlite_autoindex_menu_1`(name) 3개가 UNIQUE 때문에 자동 생성되고, Q15에서 만든 `idx_order_header_customer_id`, `idx_order_detail_order_id` 2개가 직접 생성분이다.
    - 꼬리질문 대비: PK가 5개 테이블에 다 있는데 왜 autoindex는 3개뿐인가? → **SQLite에서 `INTEGER PRIMARY KEY`는 rowid의 별칭이라 별도 인덱스가 만들어지지 않는다.** 테이블 자체가 rowid로 정렬된 B-tree라 이미 인덱스 역할을 한다. MySQL·PostgreSQL도 UNIQUE/PK에는 인덱스를 자동 생성하지만, PostgreSQL은 PK에도 별도 B-tree 인덱스를 만든다는 점이 다르다.
10. > "지금 이 쿼리는 order_detail이 가장 세밀한 단위라 이걸 FROM에 놓았습니다. 결과 한 행이 주문 상세 한 줄이라는 걸 첫 줄에서 못 박아 두려는 겁니다. **결과 집합 자체는 FROM 순서를 바꿔도 같습니다. 조인 순서는 옵티마이저가 정합니다.**"
    - 실측: Q6를 `FROM customer c`로 다시 써도 20행, 정렬 후 완전 일치. 실행계획도 두 경우 모두 `SCAN od`부터 시작한다.
11. > "인덱스를 걸기 전에는 실행계획이 SCAN order_header였는데, 인덱스를 만든 뒤에는 SEARCH order_header USING INDEX idx_order_header_customer_id (customer_id=?)로 바뀝니다. SCAN은 전부 훑는다는 뜻이고 SEARCH는 찾아 들어간다는 뜻입니다."
    - 실측 문자열이 정확히 이 형태로 나온다. `EXPLAIN QUERY PLAN`은 SQLite 전용이고, MySQL·PostgreSQL은 `EXPLAIN` / `EXPLAIN ANALYZE`를 쓴다.
    - 단, 지금 데이터는 12행짜리라 **실제 속도 차이는 없다.** "행이 많아지면 차이가 벌어지는 구조를 보여주려고 계획을 비교했습니다"라고 말해야 정직하다.
12. > "04_bonus의 JOIN 방식만 실행계획에 USE TEMP B-TREE FOR DISTINCT와 USE TEMP B-TREE FOR ORDER BY가 두 줄 뜹니다. 조인이 만든 중복을 나중에 걷어내야 해서 임시 자료구조를 두 번 만드는 겁니다."
    - 실측 실행계획: `SEARCH m USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)` → `SCAN od` → `SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)` → `SEARCH c USING INTEGER PRIMARY KEY (rowid=?)` → `USE TEMP B-TREE FOR DISTINCT` → `USE TEMP B-TREE FOR ORDER BY`.
    - 첫 줄의 `COVERING INDEX`는 "인덱스만 읽고 테이블 본체를 안 봐도 된다"는 뜻이다. 여기서는 `menu.name`이 UNIQUE 인덱스에 이미 들어 있어서 그렇다. 이 용어는 §10에서 다룬다.

---

## 6. 막혔을 때 쓰는 안전 문장

침묵 3초는 "모른다"로 읽히고, 아래 문장 한 줄은 "구조적으로 접근 중"으로 읽힌다. **답이 안 떠오를 때 생각하지 말고 반사적으로 뱉는다.** 말하는 동안 뇌가 읽는다.

| 상황 | 그대로 말할 문장 |
|---|---|
| 쿼리를 처음 봤을 때 | "먼저 FROM부터 보겠습니다." |
| 조인이 여러 개일 때 | "행이 늘어나는 조인인지부터 확인하겠습니다." |
| 별칭이 헷갈릴 때 | "별칭부터 정리하겠습니다. c가 customer인지 category인지 FROM 줄에서 확인하겠습니다." |
| ON 조건이 복잡할 때 | "ON절의 어느 쪽이 PK인지 보겠습니다." |
| 집계가 나올 때 | "GROUP BY 키가 무엇인지 보면 결과 한 행이 뭔지 정해집니다." |
| 서브쿼리가 나올 때 | "안쪽 서브쿼리가 몇 행 몇 열을 돌려주는지부터 보겠습니다." |
| NULL 이야기가 나올 때 | "이 컬럼이 NULL일 수 있는지부터 확인하겠습니다. NULL이면 판정이 UNKNOWN이 됩니다." |
| DBMS 차이를 물을 때 | "SQLite 기준으로는 이렇고, MySQL·PostgreSQL은 다를 수 있어 확인이 필요합니다." |
| 완전히 막혔을 때 | "이 쿼리 결과의 한 행이 무엇인지부터 정리하겠습니다." |
| 확신이 없을 때 | "정확히는 실행해서 확인해야 하지만, 구조상으로는 ~일 것으로 보입니다." |
| 틀린 걸 깨달았을 때 | "방금 제가 말한 건 정정하겠습니다. 여기는 ON절이라 왼쪽 행이 남습니다." |
| 시간을 벌 때 | "스키마 보면서 말씀드리겠습니다." |

마지막 두 개가 특히 중요하다. **틀린 걸 스스로 정정하는 사람은 "모르는 사람"이 아니라 "검증할 줄 아는 사람"으로 평가된다.** 틀릴까 봐 침묵하는 게 가장 나쁘다.

"DBMS 차이를 물을 때" 문장도 같은 역할을 한다. 모르는 것을 아는 척하는 것보다, **어디까지가 확인된 사실이고 어디부터가 추측인지 선을 긋는 것**이 훨씬 높게 평가된다.

---

## 7. 자가 훈련 커리큘럼 — 매일 5분 드릴

### 준비 (1회만)

**⚠️ 가장 먼저 확인할 것: 지금 저장소의 `cafe.db`는 '초기 상태'가 아니다.**

실측 결과 `/home/coder/volume/codyssey_B5-1/cafe.db`는 03_queries.sql의 Q13(UPDATE)·Q14(DELETE)까지 적용된 **사후 상태**다.

| | 초기 상태 (01+02 직후) | 현재 저장소 cafe.db |
|---|---|---|
| order_header | 12행 (COMPLETED 9 / PENDING 1 / CANCELLED 2) | **10행** (COMPLETED 9 / PENDING 1) |
| order_detail | 20행 | **18행** |
| 아메리카노 가격 | 3,500원 | **4,000원** |
| 04_bonus (1-a) DISTINCT 있음 | 4행 (김민준·이서연·박지호·정우진) | **3행** (박지호 소멸) |
| 04_bonus (1-a) DISTINCT 없음 | 5행 | **4행** |

§4의 Q10 수치(10/12/20/10, 금액표)는 두 상태에서 동일하지만, **4주차 시험 문항인 04_bonus (1)은 어느 DB로 돌리느냐에 따라 답이 달라진다.** 그러니 드릴용 DB를 따로 만든다.

```bash
# ① 드릴용 초기 상태 DB를 /tmp/drill.db 로 만든다 (저장소의 cafe.db는 건드리지 않는다)
python3 - <<'PY'
import sqlite3, pathlib
base = pathlib.Path('/home/coder/volume/codyssey_B5-1')
con = sqlite3.connect('/tmp/drill.db')
con.executescript((base / '01_schema.sql').read_text(encoding='utf-8'))
con.executescript((base / '02_data.sql').read_text(encoding='utf-8'))
con.commit()
print([con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
       for t in ('customer', 'category', 'menu', 'order_header', 'order_detail')])
PY
# 기대 출력(실측): [10, 10, 12, 12, 20]
```

주석 제거본은 **이미 저장소에 있다.** 새로 만들 필요가 없다.

```bash
ls -l /home/coder/volume/codyssey_B5-1/drill/
# 실측: 03_queries_naked.sql (206줄), 04_bonus_naked.sql (144줄)
```

직접 만들고 싶다면 이렇게 한다.

```bash
cd /home/coder/volume/codyssey_B5-1
sed 's/--.*$//' 03_queries.sql | grep -v '^[[:space:]]*$' > /tmp/03_naked.sql
sed 's/--.*$//' 04_bonus.sql   | grep -v '^[[:space:]]*$' > /tmp/04_naked.sql
wc -l /tmp/03_naked.sql /tmp/04_naked.sql
# 실측: 03 = 141줄, 04 = 101줄
```

- `sed 's/--.*$//'` 의 한계 두 가지를 알고 써야 한다. ① 문자열 리터럴 안에 `--`가 있으면 그것까지 지운다 ② `/* */` 블록 주석은 못 지운다. 지금 두 파일에는 해당 사례가 없어서 안전하다.
- **`/tmp/03_naked.sql`의 실측 내용**: 세미콜론 기준 실행 문장 **32개**. 내역은 `PRAGMA` 1개 + 라벨이 붙은 쿼리 블록 **22개**(Q1, Q2, Q3, Q4, Q4-B, Q5, Q6, Q7, Q7-B, Q8, Q8-B, Q9, Q10, Q10-B, Q11, Q11-B, Q12, Q13, Q14, Q15, Q15-A, Q15-B) + 적용 결과 확인용 SELECT 3개 + `DROP/CREATE INDEX` 4개 + `EXPLAIN QUERY PLAN` 4개다. 32개 전부 문법 오류 없이 실행되는 것을 확인했다.
- 04_bonus는 실행 문장 21개이고, 그중 4개((2-a)~(2-d))는 **일부러 실패하는 문장**이다.

### 검산 스크립트

```bash
cat > /tmp/qcheck.py <<'PY'
import os, sys, sqlite3, pathlib
DB = os.environ.get('DRILL_DB', '/tmp/drill.db')
sql = pathlib.Path(sys.argv[1]).read_text(encoding='utf-8') if len(sys.argv) > 1 else sys.stdin.read()
con = sqlite3.connect(DB)
con.execute('PRAGMA foreign_keys = ON')
for stmt in [s.strip() for s in sql.split(';') if s.strip()]:
    cur = con.execute(stmt)
    rows = cur.fetchall()
    print(f'--- {len(rows)} rows', [d[0] for d in cur.description] if cur.description else '')
    for r in rows[:20]:
        print('   ', r)
con.rollback()
PY
```

쓰는 법은 두 가지다.

```bash
echo "SELECT COUNT(*) FROM order_detail;" | python3 /tmp/qcheck.py
python3 /tmp/qcheck.py /tmp/q.sql
DRILL_DB=/home/coder/volume/codyssey_B5-1/cafe.db python3 /tmp/qcheck.py /tmp/q.sql
```

> **초안에 있던 한 줄짜리 검산 스니펫은 쓰면 안 된다.** `con.execute(open('/tmp/q.sql').read())`는 파일에 세미콜론으로 끝나는 문장이 2개 이상이면 `sqlite3.ProgrammingError: You can only execute one statement at a time.` 로 죽는다. Python의 `Cursor.execute`는 문장 하나만 받는다(여러 개를 돌리려면 `executescript`인데, 그건 결과를 못 돌려준다). 위 스크립트는 세미콜론으로 직접 쪼개서 이 문제를 피하고, `PRAGMA foreign_keys`를 켜고, 마지막에 `rollback()`으로 실험이 DB를 오염시키지 않게 한다.

### 매일 5분 드릴

| 시간 | 하는 것 | 규칙 |
|---|---|---|
| 0:00–0:30 | 무작위 쿼리 1개를 화면에 띄우고 **3초 스캔 문장**을 소리 내어 말한다 | 3초 넘기면 실패로 기록 |
| 0:30–1:30 | **30초 요약**을 소리 내어 말한다 | 녹음한다 |
| 1:30–4:00 | **행 수 추적**을 종이에 적으며 3분 설명 | FROM→JOIN→WHERE→GROUP BY 순서 고정 |
| 4:00–5:00 | `/tmp/qcheck.py`로 실제 행 수를 확인하고 자기 예측과 대조 | 틀리면 그 쿼리를 내일 다시 |

### 측정 지표와 합격 기준

| 지표 | 재는 법 | 합격 기준 |
|---|---|---|
| 첫 발화 지연 | 쿼리 표시 → 첫 단어까지 | **3초 이내** |
| 요약 완주 | 30초 안에 끊김 없이 | 침묵 2초 이상 0회 |
| 행 수 예측 정확도 | 예측 vs 실측 | 조인 2개 쿼리에서 **정확히 일치** |
| 별칭 오독 | c를 반대로 읽는가 | **0회** |
| "어…" 횟수 | 녹음 재생하며 카운트 | 쿼리당 **2회 이하** |
| 근거 표시 | "실측입니다 / 구조상 추정입니다"를 구분해 말하는가 | 추측을 단정하지 않기 |

### 4주 진행표

| 주차 | 대상 | 목표 |
|---|---|---|
| 1주 | Q1~Q4-B (단일 테이블) | 3초 스캔 문장 자동화 |
| 2주 | Q5~Q8-B (조인) | 행 증감 예측 100% |
| 3주 | Q9~Q11-B (집계) | GROUP BY 후 행 수를 즉답 |
| 4주 | Q10, Q12, 04_bonus (1-a/1-b/1-c) | ON vs WHERE, JOIN vs 서브쿼리를 대본 없이 설명 |

**4주차 최종 시험**: 04_bonus의 (1-a) JOIN 방식과 (1-b) IN 서브쿼리 방식을 나란히 놓고, "같은 답이 나오는데 (1-a)에만 DISTINCT가 필요한 이유"를 90초 안에 설명한다.

정답 근거는 실측이다. **`/tmp/drill.db`(초기 상태)에서** (1-a)는 DISTINCT를 빼면 **5행**, 붙이면 **4행**이다. 김민준이 아메리카노를 두 번 주문했기(주문 1번과 12번) 때문에 김민준 행이 두 번 나온다. (1-b)는 IN이 존재 여부만 보므로 customer 행이 애초에 부풀지 않아 4행 그대로다.

> ⚠️ **저장소의 `cafe.db`로 검산하면 이 숫자가 안 나온다.** Q14가 박지호의 유일한 주문(취소건)을 지웠기 때문에 (1-a)는 DISTINCT 없이 4행, 붙이면 3행이 된다. 중복되는 것은 여전히 김민준이지만 결과 인원이 한 명 줄어든다. 반드시 `/tmp/drill.db`로 돌려라.

세 방식의 대답 뼈대는 이렇다.

| 방식 | 결과가 부푸는가 | DISTINCT | 실행계획 특징(실측) |
|---|---|---|---|
| (1-a) JOIN | 부푼다 (order_detail 행 수만큼) | **필요** | `USE TEMP B-TREE FOR DISTINCT` + `USE TEMP B-TREE FOR ORDER BY` 두 줄 |
| (1-b) IN 서브쿼리 | 안 부푼다 (customer만 훑는다) | 불필요 | `LIST SUBQUERY`로 목록을 한 번 만들고 customer를 PK로 SEARCH |
| (1-c) EXISTS 상관 서브쿼리 | 안 부푼다 | 불필요 | 고객마다 존재 여부만 보고 첫 행에서 멈춘다 |

이 90초를 막힘없이 말할 수 있으면 피드백 2·6·8은 해결된 것이다.

---

## 8. 부록 A — DBMS별 차이를 물었을 때의 정확한 답

이 프로젝트는 SQLite로 만들었다. 평가자가 "MySQL이면 어떻게 되나요?"를 물으면 다음 표 안에서만 답한다. **모르는 것은 "확인이 필요합니다"로 넘기고, 아는 것은 버전 경계까지 붙여 말한다.**

| 주제 | SQLite | MySQL 8 | PostgreSQL |
|---|---|---|---|
| CHECK 제약 강제 | 3.37.0(2021)부터 완전 지원, 그 이전에도 기본 CHECK는 강제 | **8.0.16부터 강제.** 그 이전은 파싱만 하고 무시 | 오래전부터 강제 |
| RIGHT / FULL OUTER JOIN | **3.39.0(2022-06)부터 지원.** 그 이전은 문법 에러 | 지원. FULL OUTER JOIN은 미지원(UNION으로 흉내) | 둘 다 지원 |
| FK 검사 기본값 | **연결마다 기본 OFF** (`PRAGMA foreign_keys = ON` 필요) | 기본 ON | 기본 ON |
| 자동 증가 | `INTEGER PRIMARY KEY` (+ `AUTOINCREMENT` 옵션) | `AUTO_INCREMENT` | `SERIAL` / `GENERATED … AS IDENTITY` |
| 실행계획 | `EXPLAIN QUERY PLAN` | `EXPLAIN` / `EXPLAIN ANALYZE`(8.0.18+) | `EXPLAIN` / `EXPLAIN ANALYZE` |
| 인덱스 카탈로그 | `sqlite_master` | `information_schema.STATISTICS` | `pg_indexes` |
| `CREATE INDEX IF NOT EXISTS` | 지원 | **미지원** | 지원 |
| 날짜 자르기 | `DATE(x)` | `DATE(x)` | `CAST(x AS DATE)` / `date_trunc` |
| 타입 시스템 | 동적 타입 + 어피니티. `DATE`·`DATETIME`은 실제 타입이 아님 | 정적 타입, `DATE`·`DATETIME` 실재 | 정적 타입, `date`·`timestamp` 실재 |
| ORDER BY에서 NULL 위치(ASC) | NULL 먼저 | NULL 먼저 | **NULL 나중** (`NULLS FIRST`로 변경 가능) |

이 환경의 실측 버전은 SQLite **3.46.1**이다(`results/results.txt` 캡처 당시는 3.39.4). 3.46.1에서는 `RIGHT JOIN`과 `FULL OUTER JOIN`이 모두 정상 실행되는 것을 확인했다.

> 이 표에서 실수하기 가장 쉬운 곳이 **SQLite의 FK 기본 OFF**다. "FK를 걸었는데 왜 안 막히죠?"라는 질문은 대부분 PRAGMA를 안 켠 연결에서 나온다.

---

## 9. 부록 B — NULL 3값 논리, 한 장으로 정리

SQL의 논리값은 참·거짓 두 개가 아니라 **TRUE / FALSE / UNKNOWN 세 개**다. NULL이 끼면 판정이 UNKNOWN이 되고, 절마다 UNKNOWN을 처리하는 방식이 다르다.

| 절 | 남기는 것 | UNKNOWN이면 |
|---|---|---|
| WHERE | TRUE만 | **버린다** |
| ON | TRUE만 | **안 붙인다** (LEFT면 왼쪽 행은 NULL 채우고 생존) |
| HAVING | TRUE만 | **버린다** |
| **CHECK** | FALSE가 아니면 다 | **통과시킨다** ← 여기만 반대 |

**CHECK만 반대**라는 것이 핵심이다. 실측으로 확인했다.

```sql
CREATE TABLE t (x INTEGER CHECK (x > 0));
INSERT INTO t (x) VALUES (NULL);   -- 성공한다. NULL > 0 은 UNKNOWN이고 FALSE가 아니므로 통과
```

그래서 "CHECK를 걸었으니 값이 보장된다"는 말은 **NOT NULL이 같이 걸려 있을 때만** 참이다. 이 스키마의 `order_header.status`는 `NOT NULL DEFAULT 'PENDING' CHECK (status IN (...))`으로 둘 다 걸려 있어서 안전하다.

### NOT IN 함정 (실측)

```sql
SELECT COUNT(*) FROM customer WHERE id NOT IN (1, 2, NULL);   -- 0
```

고객이 10명인데 결과가 0이다. `id NOT IN (1, 2, NULL)`은 `id <> 1 AND id <> 2 AND id <> NULL`로 풀리는데, 마지막 항이 항상 UNKNOWN이라 전체가 TRUE가 될 수 없다. **서브쿼리 결과에 NULL이 하나라도 섞이면 NOT IN은 항상 빈 결과다.**

`NOT EXISTS`로 바꾸면 안전하다. 같은 조건을 `NOT EXISTS`로 쓰면 9행이 나온다(실측). 부정 조건에서는 EXISTS 계열을 쓴다는 04_bonus의 결론이 여기서 나온다.

참고로 `IN`(긍정)은 이 함정이 덜하다. 찾는 값이 목록에 있으면 NULL이 섞여 있어도 TRUE가 나온다. 없을 때만 FALSE 대신 UNKNOWN이 되어 "없음"으로 처리되므로 결과가 같다. **위험한 건 항상 `NOT IN` 쪽이다.**

### 집계 함수와 NULL

| 함수 | NULL 처리 | 대상 행이 0건일 때 |
|---|---|---|
| `COUNT(*)` | 행을 센다 (NULL 무관) | **0** |
| `COUNT(col)` | col이 NULL인 행은 안 센다 | **0** |
| `SUM(col)` | NULL은 무시하고 더한다 | **NULL** |
| `AVG(col)` | NULL은 분모에서도 빠진다 | **NULL** |
| `MIN/MAX(col)` | NULL은 무시 | **NULL** |

실측: `SELECT COUNT(*), SUM(v), AVG(v) FROM s WHERE v > 100` → `(0, None, None)`.

Q7의 `COUNT(oh.id)`와 Q10의 `COALESCE(SUM(...), 0)`이 둘 다 이 표에서 나온다. **"COUNT는 0을 주는데 SUM은 NULL을 준다"** — 이 한 문장이 두 쿼리를 동시에 설명한다.

### 그 밖에 알아 둘 것

- **UNIQUE 제약은 NULL을 여러 개 허용한다** (표준: NULL끼리는 서로 다르다고 본다). 실측: UNIQUE 컬럼에 NULL을 두 번 넣어도 성공한다. `customer.phone`이 NULL 허용인데 UNIQUE가 아니라 이 문제는 없지만, "UNIQUE니까 NULL도 하나뿐"이라고 말하면 틀린다. PostgreSQL 15부터는 `UNIQUE NULLS NOT DISTINCT`로 바꿀 수 있다.
- **GROUP BY는 NULL끼리 한 그룹으로 묶는다.** 비교에서는 서로 다르다고 하면서 그룹핑에서는 같다고 하는, 일관성 없어 보이지만 표준이 그렇다.
- `NULL = NULL` → UNKNOWN. `NULL IS NULL` → TRUE. `NULL IS NOT DISTINCT FROM NULL` → TRUE.

---

## 10. 부록 C — 인덱스 자료구조를 정확히 말하는 법

Q15에서 인덱스를 만들었으니 "인덱스가 왜 빠른가요?"가 따라 나온다. 여기서 흔히 퍼지는 오개념 세 가지를 피해야 한다.

### B-Tree와 B+Tree는 다르다

| | B-Tree | B+Tree |
|---|---|---|
| 데이터(값)의 위치 | 내부 노드에도 있다 | **리프에만 있다** |
| 리프끼리 연결 | 없다 | **연결 리스트로 이어져 있다** |
| 범위 스캔 | 트리를 오르내려야 한다 | 리프를 옆으로 따라가면 된다 |
| 내부 노드 한 페이지에 담기는 키 개수 | 적다(값이 같이 있어서) | **많다**(키만 있어서) → 트리가 낮아진다 |

관계형 DB가 "B-Tree 인덱스"라고 부르는 것은 실제로는 **대부분 B+Tree 계열**이다. InnoDB, PostgreSQL의 btree 인덱스가 그렇다. 범위 조회(`BETWEEN`, `>`, `ORDER BY`)가 빠른 이유가 바로 리프 연결이다.

SQLite는 두 가지를 구분해서 쓴다. 파일 포맷 문서 기준으로 **테이블 b-tree는 B+tree 구조**(레코드 본문이 리프에만 있다)이고, **인덱스 b-tree는 B-tree 구조**(키가 내부 페이지에도 있다)다. 이 정도까지 말하면 충분하다.

### 클러스터드 인덱스 — DBMS마다 완전히 다르다

| | 테이블 저장 방식 | 세컨더리 인덱스의 리프에 든 것 |
|---|---|---|
| **SQLite** | rowid 기준 B+tree. `INTEGER PRIMARY KEY`는 rowid의 별칭 (`WITHOUT ROWID` 테이블이면 PK 기준 클러스터) | (인덱스 키, **rowid**) |
| **InnoDB (MySQL)** | **PK 기준 클러스터드 인덱스가 곧 테이블**. PK가 없으면 UNIQUE NOT NULL, 그것도 없으면 숨은 6바이트 row id | (인덱스 키, **PK 값**) |
| **PostgreSQL** | **힙(heap).** 정렬 없이 쌓는다. 클러스터드 인덱스가 **없다** | (인덱스 키, **TID = 물리 위치**) |

여기서 나오는 실전 결론 세 가지.

1. **InnoDB의 세컨더리 인덱스 조회는 트리를 두 번 탄다.** 세컨더리에서 PK를 찾고, 그 PK로 클러스터드 인덱스를 다시 탄다. 이걸 covering index(필요한 컬럼이 인덱스에 다 있어서 두 번째 탐색이 생략되는 경우)로 피한다. "InnoDB에서 PK를 길게 잡으면 안 된다"는 조언이 여기서 나온다. 모든 세컨더리 인덱스가 PK 값을 복사해 갖기 때문이다.
2. **PostgreSQL의 `CLUSTER` 명령은 클러스터드 인덱스를 만드는 게 아니다.** 그 시점에 테이블을 한 번 재정렬할 뿐이고, 이후 갱신하면 순서가 다시 흐트러진다.
3. **PostgreSQL은 인덱스만 읽어서 답을 낼 수 없는 경우가 있다.** 힙에 가야 그 행이 현재 트랜잭션에 보이는지(가시성)를 알 수 있기 때문이다. visibility map이 깨끗한 페이지에 한해서만 index-only scan이 된다.

실측 예: 04_bonus (1-a)의 실행계획 첫 줄이 `SEARCH m USING COVERING INDEX sqlite_autoindex_menu_1 (name=?)`이다. `menu.name`이 UNIQUE 인덱스에 들어 있어서 테이블 본체를 안 봐도 되는 경우다. 이게 covering index다.

### 해시 인덱스와 LSM은 여기 없다

- **해시 인덱스**는 등치 비교(`=`)만 되고 범위·정렬은 못 한다. SQLite에는 아예 없다. MySQL은 MEMORY 엔진에서 지원하고, InnoDB는 사용자가 만드는 게 아니라 내부적으로 **adaptive hash index**를 자동으로 붙였다 뗀다. PostgreSQL의 hash 인덱스는 10 이전에는 WAL 기록이 안 돼 크래시에 취약했고 10부터 안전해졌다.
- **LSM 트리**(쓰기를 메모리 버퍼에 모았다가 정렬해서 순차로 flush하고, 나중에 compaction으로 병합)는 RocksDB·LevelDB·Cassandra 같은 시스템의 구조다. **SQLite도, InnoDB도, PostgreSQL도 LSM이 아니다.** (MySQL에 MyRocks 엔진을 붙이면 LSM이 되지만 기본이 아니다.) "쓰기가 많으면 LSM이 유리하고 읽기 증폭이 대가"라는 트레이드오프까지만 말하고, 이 프로젝트와는 무관하다고 선을 그으면 된다.

### 지금 이 DB에서 인덱스 이야기를 할 때의 정직한 태도

데이터가 12행짜리라 **인덱스로 인한 실제 속도 차이는 없다.** `EXPLAIN QUERY PLAN`이 `SCAN`에서 `SEARCH`로 바뀌는 것을 보여주는 것이 목적이고, 그 이상을 주장하면 과장이다. 오히려 "행이 적을 때는 옵티마이저가 인덱스를 무시하고 풀스캔을 고르는 게 정상이고 더 빠릅니다"라고 말할 수 있으면 이해도가 높아 보인다.

---

## 11. 부록 D — 정규화를 한 문장씩 정확히

"이 스키마 정규화 몇 차까지 됐나요?"에 답하려면 정의부터 정확해야 한다. **모든 정의는 함수 종속(FD)과 후보키 위에 세워진다.**

- **함수 종속 X → Y**: X 값이 같으면 Y 값도 반드시 같다. 예: `menu.id → menu.name`.
- **후보키**: 모든 속성을 결정하면서 더 줄일 수 없는(극소) 속성 집합. 슈퍼키에서 군더더기를 뺀 것.
- **기본 속성(prime attribute)**: 어떤 후보키에든 속한 속성.

| 정규형 | 정의 | 한 문장 |
|---|---|---|
| 1NF | 모든 속성값이 원자적. 반복 그룹·다중값 없음 | "한 칸에 값 하나" |
| 2NF | 1NF + **비기본 속성이 후보키의 진부분집합에 종속되지 않는다**(부분 함수 종속 제거) | "복합키의 일부만 보고 정해지는 컬럼이 없다" |
| 3NF | 2NF + 모든 FD `X → A`(비자명)에 대해 **X가 슈퍼키이거나 A가 기본 속성**(이행 종속 제거) | "키가 아닌 것이 키가 아닌 것을 정하지 않는다" |
| BCNF | 모든 비자명 FD `X → A`에 대해 **X가 슈퍼키**(3NF의 예외 조항까지 없앤 것) | "결정자는 무조건 키" |

여기서 자주 틀리는 지점 세 개.

1. **2NF는 복합 후보키가 있을 때만 의미가 있다.** 후보키가 단일 속성이면 진부분집합이 공집합뿐이라 부분 종속이 성립할 수 없고, 1NF를 만족하면 자동으로 2NF다. 이 스키마는 다섯 테이블 모두 단일 컬럼 대리키 PK라 **2NF는 공짜로 만족**한다. "대리키를 썼기 때문에 2NF는 자동입니다"라고 말하면 정확하다.
2. **3NF와 BCNF의 차이는 "A가 기본 속성이면 봐준다"는 예외 조항 하나뿐이다.** 3NF는 봐주고 BCNF는 안 봐준다. 그래서 BCNF가 더 엄격하다.
3. **BCNF는 항상 무손실 분해가 가능하지만 종속성 보존은 보장되지 않는다.** 3NF는 무손실 분해와 종속성 보존을 둘 다 보장한다. 그래서 실무에서 3NF에서 멈추는 경우가 있다.

### 이 스키마를 판정하면

| 테이블 | 후보키 | 판정 |
|---|---|---|
| customer | `{id}`, `{email}` (UNIQUE) | 모든 FD의 결정자가 후보키 → **BCNF** |
| category | `{id}`, `{name}` (UNIQUE) | **BCNF** |
| menu | `{id}`, `{name}` (UNIQUE) | **BCNF** |
| order_header | `{id}` | **BCNF** |
| order_detail | `{id}` | **BCNF** |

즉 **다섯 테이블 모두 BCNF**다. `menu`나 `customer`처럼 UNIQUE 때문에 후보키가 두 개인 테이블도, 두 후보키 모두 나머지 전부를 결정하므로 문제가 없다.

`order_detail.unit_price`가 걸린다면 이렇게 답한다. **정규화 위반이 아니다.** `menu.price`(지금 가격)와 `unit_price`(그때 가격)는 서로 다른 시점의 사실이라 함수 종속 관계가 없다. `menu_id → unit_price`가 성립하지 않으므로 애초에 이행 종속이 아니다. 값이 우연히 같을 수는 있어도 논리적으로 같은 데이터가 아니다.

반대로 **진짜 비정규화였다면** 이렇게 생겼을 것이다. `order_detail`에 `menu_name`이나 `line_total`(= quantity × unit_price)을 컬럼으로 저장하는 경우다. 이건 각각 `menu_id → menu_name`, `(quantity, unit_price) → line_total`이라 실제 중복이고, 갱신 이상이 생긴다. 이 스키마는 `line_total`을 저장하지 않고 Q6에서 계산해서 쓴다(`(od.quantity * od.unit_price) AS line_total`). 그 선택이 정규화 관점에서 맞다.

---

## 12. 부록 E — 제약 위반을 코드에서 다루는 법

04_bonus (2)에서 일부러 네 가지 제약을 깨뜨린다. "그럼 애플리케이션에서는 이걸 어떻게 받나요?"가 자연스러운 꼬리질문이다.

### SQLite 실측 에러

아래는 이 DB에서 실제로 발생시킨 결과다. 네 가지 모두 파이썬에서는 **`sqlite3.IntegrityError` 하나로 올라온다.** 종류 구분은 예외 클래스가 아니라 에러 코드로 한다.

| 깨뜨린 것 | 메시지 | `sqlite_errorname` | `sqlite_errorcode` |
|---|---|---|---|
| FK (2-a) | `FOREIGN KEY constraint failed` | `SQLITE_CONSTRAINT_FOREIGNKEY` | 787 |
| UNIQUE (2-b) | `UNIQUE constraint failed: customer.email` | `SQLITE_CONSTRAINT_UNIQUE` | 2067 |
| CHECK (2-c) | `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')` | `SQLITE_CONSTRAINT_CHECK` | 275 |
| NOT NULL (2-d) | `NOT NULL constraint failed: customer.email` | `SQLITE_CONSTRAINT_NOTNULL` | 1299 |

`sqlite_errorname` / `sqlite_errorcode` 속성은 **Python 3.11부터** 쓸 수 있다. 그 이전 버전에서는 메시지 문자열을 봐야 한다.

```python
import sqlite3

con = sqlite3.connect("/tmp/drill.db")
con.execute("PRAGMA foreign_keys = ON")

CONSTRAINT_MESSAGES = {
    "SQLITE_CONSTRAINT_UNIQUE":     "이미 가입된 이메일입니다.",
    "SQLITE_CONSTRAINT_NOTNULL":    "필수 항목이 비었습니다.",
    "SQLITE_CONSTRAINT_FOREIGNKEY": "참조 대상이 존재하지 않습니다.",
    "SQLITE_CONSTRAINT_CHECK":      "허용되지 않는 값입니다.",
}

def add_customer(name, email):
    try:
        with con:                       # 성공하면 commit, 예외가 나면 자동 rollback
            con.execute(
                "INSERT INTO customer (name, email) VALUES (?, ?)",
                (name, email),          # ← 문자열 포매팅 금지. 반드시 파라미터 바인딩
            )
        return "OK"
    except sqlite3.IntegrityError as e:
        name_ = getattr(e, "sqlite_errorname", "")      # Python 3.11+
        if not name_:                                   # 3.10 이하 폴백
            msg = str(e)
            name_ = ("SQLITE_CONSTRAINT_UNIQUE"     if msg.startswith("UNIQUE")   else
                     "SQLITE_CONSTRAINT_NOTNULL"    if msg.startswith("NOT NULL") else
                     "SQLITE_CONSTRAINT_FOREIGNKEY" if msg.startswith("FOREIGN")  else
                     "SQLITE_CONSTRAINT_CHECK"      if msg.startswith("CHECK")    else "")
        if name_ in CONSTRAINT_MESSAGES:
            return CONSTRAINT_MESSAGES[name_]
        raise
```

실행하면 이렇게 나온다(실측).

```text
add_customer("새고객", "new@example.com")        -> OK
add_customer("중복이", "minjun@example.com")     -> 이미 가입된 이메일입니다.
add_customer("이메일없음", None)                  -> 필수 항목이 비었습니다.
```

말할 때 강조할 지점 세 개다.

- **`with con:` 이 트랜잭션 경계다.** 블록을 정상적으로 빠져나가면 커밋, 예외가 터지면 롤백된다. 04_bonus (2-e)의 `BEGIN ~ ROLLBACK`을 코드로 옮긴 것이 이것이다.
- **파라미터 바인딩은 SQL 인젝션 방지이자 타입 안전장치다.** 문자열 포매팅으로 값을 끼워 넣으면 안 된다.
- **제약 위반은 버그가 아니라 정상 흐름이다.** 사용자 입력에서 나오는 UNIQUE 위반은 "예상되는 실패"이므로 잡아서 메시지로 바꾸고, 그 밖의 것은 `raise`로 올려 보낸다. 전부 삼키는 `except: pass`가 최악이다.

### 다른 DBMS로 옮기면

SQLite에는 **SQLSTATE가 없다.** 표준 SQLSTATE는 MySQL과 PostgreSQL에 있다.

| 위반 | SQLSTATE | MySQL 에러 번호 | PostgreSQL 조건 이름 |
|---|---|---|---|
| UNIQUE / PK 중복 | `23000`(MySQL) / `23505`(PG) | **1062** `ER_DUP_ENTRY` | `unique_violation` |
| FK 위반 | `23000`(MySQL) / `23503`(PG) | **1452** (자식 추가) / **1451** (부모 삭제) | `foreign_key_violation` |
| NOT NULL 위반 | `23000`(MySQL) / `23502`(PG) | **1048** `ER_BAD_NULL_ERROR` | `not_null_violation` |
| CHECK 위반 | `HY000`(MySQL) / `23514`(PG) | **3819** `ER_CHECK_CONSTRAINT_VIOLATED` (8.0.16+) | `check_violation` |

MySQL은 무결성 위반 대부분을 SQLSTATE `23000` 하나로 뭉뚱그리므로 **세부 구분은 errno로 해야 한다.** PostgreSQL은 SQLSTATE가 위반 종류별로 나뉘어 있어(`235xx`) 코드만으로 구분되고, psycopg에서는 `psycopg.errors.UniqueViolation` 같은 전용 예외 클래스로도 잡을 수 있다. 이 차이 때문에 이식성 있는 코드에서는 **드라이버별 매핑 계층을 한 겹 두는 것**이 보통이다.

이 답변까지 준비되어 있으면, "DB에서 막았으니 끝"이 아니라 "막힌 것을 사용자에게 어떻게 돌려주는가"까지 설계한 사람으로 보인다.

---

## 보강 — 평가 피드백 재점검에서 추가된 것


### 8. 속도는 측정해야 는다 — 3회전 드릴 프로토콜

읽는 순서를 아는 것과 3초 안에 입이 열리는 것은 다른 능력이다. 아래는 측정 가능한 훈련이다. 대상은 `drill/03_queries_naked.sql`의 Q6, Q7, Q8, Q10, Q11-B, Q12 여섯 개와 `drill/04_bonus_naked.sql`의 (1-a)(1-b)(1-c) 세 개, 총 9개.

| 지표 | 이름 | 1회전 목표 | 2회전 목표 | 3회전(합격선) |
|---|---|---|---|---|
| 쿼리를 본 순간부터 **첫 문장이 나오기까지** | TTF(time to first word) | 10초 | 5초 | **3초 이내** |
| 설명을 끝낼 때까지 | 총 소요 | 90초 | 60초 | **40초 이내** |
| 말하다 3초 이상 멈춘 횟수 | 정지 | 3회 | 1회 | **0회** |

실행 방법은 단순하다. 휴대폰 녹음을 켜고, 쿼리 하나를 열고, 스톱워치를 누르고, 아래 다섯 문장 틀을 채워 말한다.

```text
① "이 쿼리 결과 한 줄은 ___ 하나입니다."                  (FROM)
② "거기에 ___를 붙이는데, 붙는 쪽이 ___라서 행이 ___합니다." (JOIN/ON)
③ "그중 ___인 행만 남깁니다."                              (WHERE)
④ "___ 기준으로 묶어서 ___를 셉니다/더합니다."             (GROUP BY/집계)
⑤ "결과는 ___행이고, ___ 때문에 ___가 빠집니다/남습니다."   (실측 근거)
```

⑤가 이 드릴의 핵심이다. 숫자를 대는 순간 말투가 바뀐다. "아마 카테고리 개수만큼 나올 것 같은데요..."와 "9행입니다, 카테고리는 10개인데 메뉴가 0개인 굿즈가 INNER JOIN에서 탈락하기 때문입니다"는 같은 지식이지만 평가에서는 다른 점수를 받는다.

녹음은 반드시 되돌려 듣는다. 자기 목소리에서 잡을 것은 딱 두 가지다. **(a) 문장 끝을 흐리는가**("~인 것 같습니다", "~겠죠?") **(b) 침묵 구간이 어디인가**. 침묵이 생긴 지점이 곧 다음에 볼 절이다. 침묵이 ②에서 났으면 조인 모듈, ④에서 났으면 집계, ⑤에서 났으면 그냥 쿼리를 안 돌려본 것이다.

### 9. 스키마 카드 — 평가자가 허락한 목발은 써라

피드백 2번의 뒷문장은 "겁먹지 말고 스키마 테이블을 보면서 이야기해도 좋습니다"다. 이건 봐도 된다는 허락이지만, **볼 물건이 준비돼 있어야** 쓸 수 있다. A4 한 장에 손으로 그린다. 인쇄물이 아니라 손으로 그려야 외워진다.

```text
  category ──1:N──> menu ──1:N──> order_detail <──N:1── order_header <──N:1── customer
   id                id            id                    id                   id
   name(U)           name(U)       order_id  FK ─────────┘                    name
                     price CK>=0   menu_id   FK                               email(U)
                     category_id FK quantity  CK>0                            phone
                     is_available  unit_price CK>=0                           joined_at
                       CK IN(0,1)                        customer_id FK
                                                         order_date DEF now
                                                         status CK IN(P/C/X)

  ON DELETE CASCADE : order_header ─> order_detail  (이 화살표 하나뿐)
  나머지 FK 3개     : NO ACTION (부모 삭제 시 거부)
  행 수(01+02 기준) : cust 10 / cat 10 / menu 12 / oh 12 / od 20
```

오른쪽 아래 구석에 행 수를 적어 두는 게 요령이다. 조인 결과 행 수를 말할 때 이 숫자에서 출발하면 즉답이 된다. 카드를 책상에 놓고 **말할 때 손가락으로 짚어라.** 짚는 동작이 시선을 고정시켜서 시선이 헤매는 동안 생기는 침묵이 사라진다. 평가장에 이 카드를 가져갈 수 없다면, 시험 직전 백지에 90초 안에 다시 그리는 연습을 세 번 한다.

### 10. 세 방향 드릴 — 읽기만으로는 목발이 안 떨어진다

주석 제거본을 읽는 것은 **인식(recognition)** 훈련이다. 인식은 회상(recall)보다 훨씬 쉬워서, 읽을 수 있어도 못 쓰는 상태가 그대로 남는다. 방향을 세 개로 늘린다.

| 방향 | 입력 | 출력 | 잡아내는 것 |
|---|---|---|---|
| **A. 순방향(읽기)** | `drill/03_queries_naked.sql`의 쿼리 | 말로 하는 설명 | 읽는 속도 |
| **B. 역방향(쓰기)** | 한국어 요구사항 한 줄 | 백지에 쓴 쿼리 | 실제 회상 능력 |
| **C. 복원 대조** | A에서 내가 말한 설명 | 주석으로 옮겨 적고 원본 주석과 대조 | 내 설명에서 빠진 근거 |

**B의 문제 목록** — 스키마 카드만 보고 백지에 쓴다. 답은 `03_queries.sql`에 있으니 다 쓴 뒤에만 연다.

```text
 B1. 카테고리별 등록 메뉴 개수. 단 메뉴가 0개인 카테고리도 0으로 나와야 한다.
 B2. 고객별 총 결제 금액. 취소·미결제는 매출이 아니고, 주문 없는 고객도 0원으로 나와야 한다.
 B3. 아메리카노를 한 번이라도 주문한 고객 이름. 조인 방식과 EXISTS 방식 두 개로.
 B4. 판매중인 메뉴 중, 판매중 메뉴 평균가보다 비싼 메뉴.
 B5. 메뉴를 2개 이상 가진 카테고리만. 단 4000원 이상 메뉴만 세어서.
 B6. 한 번도 주문된 적 없는 메뉴. (원본에 없는 문제 - 스스로 만들어야 한다)
 B7. 고객별로 가장 많이 시킨 메뉴 1개씩. (원본에 없는 문제 - 윈도우 함수 또는 상관 서브쿼리)
```

B1은 `LEFT JOIN`을 안 쓰면 굿즈가 사라지고, B2는 `status` 필터를 `WHERE`에 두면 고객 3명이 사라지고, B5는 `WHERE`와 `HAVING`을 둘 다 써야 한다. 즉 **각 문제가 함정을 하나씩 품고 있다.** 쓴 다음 실제로 돌려서 행 수부터 확인한다.

```bash
python3 - <<'PY'
import sqlite3
c = sqlite3.connect("fresh.db")
q = """여기에 내가 쓴 쿼리"""
rows = c.execute(q).fetchall()
print(len(rows), "행"); [print(r) for r in rows]
print(*c.execute("EXPLAIN QUERY PLAN " + q), sep="\n")
PY
```

### 11. 자기 채점 루브릭 — 설명 하나당 5칸

녹음을 되돌려 들으며 쿼리 하나에 대해 채운다. 4칸 이상이면 통과, 3칸 이하면 그 쿼리는 다음 회전에 다시 넣는다.

| # | 채점 항목 | 통과 기준 |
|---|---|---|
| 1 | **그레인** | "이 결과 한 줄은 ___ 하나다"를 첫 문장에 말했는가 |
| 2 | **행 수 변화** | 각 조인에서 늘어남/유지/줄어듦을 근거와 함께 말했는가 |
| 3 | **실측 숫자** | 결과 행 수를 숫자로 말했는가 ("9행입니다") |
| 4 | **대안 대조** | "이걸 ___로 바꾸면 ___가 된다"를 최소 한 번 말했는가 (INNER↔LEFT, ON↔WHERE, `COUNT(*)`↔`COUNT(col)`) |
| 5 | **말끝** | "~같습니다", "~겠죠", "아마"를 한 번도 쓰지 않았는가 |

4번이 가장 배점이 높다. 대안을 대조할 수 있다는 것은 그 쿼리를 **선택지 중에서 골랐다**는 증거이고, 평가자가 "자신감"이라고 부른 것의 실체가 정확히 이것이다.

### 12. 예상 꼬리질문 20개 — 답은 한 문장씩

대본은 첫 질문만 막아 준다. 점수가 갈리는 곳은 두 번째 질문이다. 각 답은 **한 문장 + 근거 숫자** 형태로 준비한다.

| # | 질문 | 답의 뼈대 |
|---|---|---|
| 1 | INNER를 LEFT로 바꾸면 몇 행이 되나 | "Q8은 9행에서 10행이 됩니다. 메뉴 0개인 굿즈가 `menu_count=0`으로 살아납니다." |
| 2 | 왜 `COUNT(*)`가 아니라 `COUNT(oh.id)`인가 | "`COUNT(*)`는 행을 세서 LEFT JOIN이 NULL로 채운 줄까지 세고, `COUNT(oh.id)`는 NULL 아닌 값만 셉니다. 서지안이 1과 0으로 갈립니다." |
| 3 | 그 필터를 WHERE로 옮기면 | "ON절은 10행, WHERE절은 7행입니다. NULL은 어떤 비교에도 참이 안 돼서 주문 없는 고객이 통째로 탈락합니다." |
| 4 | GROUP BY에 `c.id`와 `c.name`을 둘 다 쓴 이유 | "동명이인을 분리하기 위해서입니다. `c.id`만으로도 `c.name`이 함수 종속하지만, 표준 SQL과 MySQL의 `ONLY_FULL_GROUP_BY`에서는 SELECT에 쓴 비집계 컬럼을 다 넣어야 합니다. PostgreSQL은 PK가 있으면 생략을 허용합니다." |
| 5 | IN과 EXISTS 중 뭐가 빠른가 | "단정할 수 없고 실행계획으로 답합니다. IN은 목록을 한 번 만들고, EXISTS는 행마다 존재 여부만 보고 조기 종료합니다. 자식이 크면 EXISTS가 유리합니다." |
| 6 | `NOT IN`의 함정은 | "서브쿼리 결과에 NULL이 하나라도 섞이면 전체가 빈 결과가 됩니다. `NOT EXISTS`는 안전합니다." |
| 7 | 인덱스를 다 걸면 안 되나 | "쓰기가 느려집니다. 10만 행 INSERT 실측이 0.373초에서 0.888초로 2.4배, 파일은 39.2MiB에서 50.0MiB로 27.7% 늘었습니다." |
| 8 | FK를 걸면 인덱스가 자동으로 생기나 | "MySQL InnoDB만 만들어 줍니다. SQLite와 PostgreSQL은 안 만듭니다. 그래서 제 스키마도 `menu.category_id`가 풀스캔입니다." |
| 9 | `unit_price`는 중복 아닌가 | "의도한 역정규화입니다. 주문 시점 가격 스냅샷이라 Q13이 아메리카노를 4000원으로 올려도 과거 주문 금액이 안 흔들립니다." |
| 10 | 이 스키마의 약점을 하나 말해 보라 | "`order_detail`에 `UNIQUE(order_id, menu_id)`가 없어서 같은 주문에 같은 메뉴가 두 줄 들어갈 수 있습니다. 실측으로 확인했습니다." |
| 11 | CHECK는 언제 검사되나 | "문장 단위 즉시입니다. 지연은 SQLite·PostgreSQL의 FK만 가능하고 CHECK는 어느 DBMS도 지연이 안 됩니다." |
| 12 | CHECK로 NULL을 막을 수 있나 | "못 막습니다. NULL 비교는 UNKNOWN이고 CHECK는 거짓이 아니면 통과시킵니다. NOT NULL과 세트로 겁니다." |
| 13 | `AUTOINCREMENT`를 쓴 이유 | "없어도 rowid는 자동 증가하지만, `AUTOINCREMENT`는 삭제된 id를 재사용하지 않습니다. 주문 번호가 재사용되면 감사 추적이 깨집니다. 대신 `sqlite_sequence` 테이블 갱신 비용이 붙습니다." |
| 14 | 트랜잭션을 왜 `BEGIN IMMEDIATE`로 여나 | "기본 DEFERRED는 읽은 뒤 쓰기 승격에 실패하면 `database is locked`로 죽고 처음부터 다시 해야 합니다. IMMEDIATE는 아직 아무것도 읽지 않은 상태라 재시도가 깨끗합니다." |
| 15 | `DISTINCT`는 언제 사라지나 | "조인이 만든 중복이라 생깁니다. `EXISTS`로 바꾸면 애초에 중복이 안 생겨서 필요 없고, 실행계획에서 `USE TEMP B-TREE FOR DISTINCT`도 사라집니다." |
| 16 | `ON DELETE CASCADE`를 왜 하나에만 걸었나 | "주문서를 지우면 그 줄들은 존재 의미가 없지만, 고객이나 메뉴를 지운다고 주문 이력이 사라지면 안 되기 때문입니다. 나머지 3개는 NO ACTION이라 부모 삭제가 거부됩니다." |
| 17 | 이 프로젝트를 MySQL로 옮기면 뭐가 깨지나 | "`AUTOINCREMENT`가 `AUTO_INCREMENT`로, `DATE('now')`가 `CURDATE()`로, `INTEGER PRIMARY KEY`의 rowid 별칭 개념이 사라집니다. CHECK는 8.0.16부터만 실제로 시행됩니다." |
| 18 | SQLite를 쓴 이유 | "용도가 아니라 접근 패턴 때문입니다. 단일 프로세스 쓰기, 파일 하나로 재현, 조인과 트랜잭션 필요 — 이 조합이면 SQLite가 맞습니다." |
| 19 | 언제 SQLite를 버려야 하나 | "동시 쓰기가 생길 때입니다. 쓰기 트랜잭션이 파일 전체에 하나뿐이라 그때가 임계점입니다." |
| 20 | 인덱싱이 왜 인덱싱인가 | "라틴어 index가 집게손가락, 가리키는 것입니다. 본문이 아니라 위치를 가리키는 정렬된 목록이라는 뜻이 이름에 그대로 들어 있습니다." |

### 13. 모를 때 무너지지 않는 세 문장

자신감은 다 아는 상태가 아니다. **모르는 걸 모른다고 말하고 확인 방법을 아는 상태**다. 아래 세 형태를 통째로 외운다.

```text
[모를 때]
"그건 확답을 못 드리겠습니다. 다만 제 추측은 ___이고, 확인하려면
 EXPLAIN QUERY PLAN을 붙여서 인덱스를 타는지 보면 됩니다."

[틀렸다고 지적받았을 때]
"아, 맞습니다. 제가 ___로 알고 있었는데 ___가 맞네요.
 그러면 ___ 부분도 같이 바뀌겠습니다."        ← 파급까지 짚으면 실점이 회복된다

[질문을 못 알아들었을 때]
"질문을 ___로 이해했는데 맞을까요?"            ← 되묻는 건 감점이 아니다. 엉뚱한 답이 감점이다
```

두 번째 문장이 가장 중요하다. 지적을 받은 순간 얼어붙어서 그 뒤 답변이 전부 흔들리는 게 실제 실점 경로다. **정정을 즉시 받아들이고 파급을 스스로 짚으면**, 그 한 번의 오답은 오히려 이해도의 증거가 된다.
