# 정규화와 N:M 브릿지 테이블

> 평가 피드백 7 대응 — 1NF부터 BCNF까지 이 스키마로 유도한다. order_detail이 이미 브릿지 테이블이다.

---

## 결론부터 — 너는 이미 브릿지 테이블을 만들었다

평가자가 "브릿지 테이블을 놓아서 1:N + N:1 구조를 만드는 것"이라고 알려준 그것을, 제출한 스키마의 `order_detail`이 이미 하고 있다. 게다가 `quantity`, `unit_price`라는 **관계 자체의 속성**까지 가진 고급 형태다. 못 한 게 아니라, **한 걸 이름 붙여 말하지 못한 것**이다. 이 모듈의 목표는 그 이름을 붙여 주는 것이다.

한 문장으로 외울 것:

> "고객과 메뉴는 N:M입니다. 그걸 `order_header`와 `order_detail`로 끊어서 `order_header` 1:N `order_detail` N:1 `menu` 구조로 해소했고, `order_detail`이 브릿지 테이블입니다. 여기에 수량·단가라는 관계 속성이 붙어서 단순 연결 테이블이 아니라 독립 엔티티가 됐습니다."

> **이 문서의 실측 환경**: SQLite 3.46.1 (Python 3.14의 `sqlite3` 모듈), 대상 파일 `cafe.db`. 표기된 행 수·실행계획 문자열·에러 메시지는 모두 이 환경에서 직접 실행해 얻은 값이다. 파괴적 DML은 전부 트랜잭션 안에서 실행한 뒤 ROLLBACK 하거나 복사본에서 확인했다. SQLite는 버전에 따라 실행계획 문자열이 바뀌므로, 다른 버전에서는 문자열이 조금 다를 수 있다.

---

## 1. 정규화가 푸는 문제 — '엑셀 한 장' 카페 장부

정규화를 이론으로 설명하면 말이 막힌다. **"엑셀로 짜면 이렇게 망가진다"**로 설명하면 안 막힌다. 현재 `cafe.db`를 조인해서 엑셀 한 장으로 펴 보면 이런 모양이다(실측).

| order_id | cust | email | menu | cat | quantity | unit_price |
|---|---|---|---|---|---|---|
| 1 | 김민준 | minjun@example.com | 아메리카노 | 커피 | 2 | 3500 |
| 1 | 김민준 | minjun@example.com | 크로와상 | 베이커리 | 1 | 4500 |
| 2 | 김민준 | minjun@example.com | 카페라떼 | 커피 | 1 | 4500 |
| 3 | 이서연 | seoyeon@example.com | 바닐라라떼 | 커피 | 2 | 5000 |
| 6 | 정우진 | woojin@example.com | 아메리카노 | 커피 | 3 | 3500 |

이 한 장짜리 표에서 세 가지 이상(anomaly)이 터진다.

| 이상 | 이 표에서 벌어지는 일 | 분리된 스키마에서는 |
|---|---|---|
| **삽입 이상 (insertion)** | '굿즈' 카테고리를 새로 만들고 싶은데, 주문이 한 건도 없으면 넣을 행 자체가 없다. `menu`·`quantity`를 NULL로 채운 유령 행을 만들어야 한다. | `category`에 한 행 INSERT. 실측: `category.id=10 굿즈`는 소속 메뉴 0개인 채로 멀쩡히 존재한다 |
| **갱신 이상 (update)** | 김민준이 이메일을 바꾸면 그가 등장하는 **모든 행**을 고쳐야 한다. 하나라도 빠뜨리면 같은 사람이 두 이메일을 갖는다 | `customer` 1행만 UPDATE |
| **삭제 이상 (deletion)** | 정우진의 주문 6을 취소하면, 그 행에만 있던 정우진의 전화번호·가입일까지 같이 사라진다. 주문을 지웠는데 **고객이 증발한다** | `order_header` 삭제 → `order_detail`만 CASCADE로 정리, `customer`는 남는다 |

세 번째 칸은 실측으로 확인된다. 복사본에서 `PRAGMA foreign_keys=ON` 후 `DELETE FROM order_header WHERE id=1` → `order_detail` 18행 → 16행(주문 1의 라인 2개만 CASCADE 삭제), `customer` 10행 그대로. 반대로 `DELETE FROM customer WHERE id=1`은 `FOREIGN KEY constraint failed`로 막힌다(NO ACTION).

**말할 때 쓸 문장:**
> "정규화는 이론이 아니라 이상 현상 제거입니다. 고객 이름을 주문 행마다 반복 저장하면 갱신 이상이 생기고, 주문이 없는 카테고리는 삽입 자체가 안 되고, 주문 하나 지우면 고객 정보까지 날아갑니다. 그래서 `customer`, `category`, `menu`를 각각 독립 테이블로 뺐습니다."

---

## 2. 1NF → 2NF → 3NF → BCNF, 카페 스키마로 단계 유도

각 단계는 **"어떤 함수 종속(FD)이 문제인가 → 어떻게 쪼개는가"** 한 쌍으로 외운다. FD 표기 `A → B`는 "A가 정해지면 B가 하나로 정해진다"는 뜻이다. 여기서 중요한 건 FD가 **데이터에 우연히 성립하는 사실이 아니라 도메인 규칙**이라는 점이다. 현재 데이터에서 우연히 1:1로 대응한다고 FD가 아니고, 도메인 규칙상 항상 그래야 하는 것만 FD다. (이 구분이 §7의 `unit_price` 논증의 핵심이 된다.)

### 2-1. 0NF → 1NF : 한 칸에 값 하나 (원자성)

망가진 출발점:

```text
order(id=1, customer='김민준', menus='아메리카노,크로와상', qty='2,1')
```

문제는 감성이 아니라 기능이다.

| 하려는 일 | CSV 칸에서 | 1NF에서 |
|---|---|---|
| 아메리카노 주문 찾기 | `LIKE '%아메리카노%'` → '아이스아메리카노'도 걸린다 | `WHERE menu_id = 1` |
| 인덱스 | 선행 와일드카드 매칭이라 B-tree 인덱스를 못 탄다, 풀스캔 | `menu_id` 인덱스 사용 |
| 수량 합계 | 문자열 파싱 후 자리 맞춰 매칭 | `SUM(quantity)` |
| FK 검증 | 불가. 존재하지 않는 메뉴명이 들어가도 DB가 못 막는다 | `FOREIGN KEY (menu_id) REFERENCES menu(id)` |

정확히 말하면 "B-tree 인덱스가 무효"인 이유는 B-tree가 **키 앞부분부터 정렬된 자료구조**이기 때문이다. `LIKE 'abc%'`처럼 접두사가 고정된 패턴은 B-tree로 범위 탐색이 되지만, `LIKE '%abc%'`는 시작점을 특정할 수 없어 전체를 훑어야 한다. (PostgreSQL은 `pg_trgm` 확장 + GIN 인덱스로 중간 매칭도 색인할 수 있고, MySQL 8·SQLite는 FTS/전문 인덱스가 따로 필요하다. 어느 쪽이든 일반 B-tree로는 안 된다는 사실은 같다.)

→ **1NF 결과**: 주문 라인을 행으로 쪼갠다. 이게 `order_detail`의 출발점이다.

### 2-2. 1NF → 2NF : 부분 종속 제거

`order_detail`의 후보키를 `(order_id, menu_id)`라고 두고, 여기에 `menu_name`, `menu_price`를 넣었다고 하자.

```text
order_detail(order_id, menu_id, menu_name, quantity)
   FD1: (order_id, menu_id) → quantity      정상. 복합키 전체에 종속
   FD2: menu_id → menu_name                 문제. 복합키의 '일부'에만 종속 = 부분 종속
```

부분 종속의 실제 피해: 아메리카노 이름을 '아메리카노(HOT)'로 바꾸면 그 메뉴가 등장한 **모든 order_detail 행**을 고쳐야 한다. 실측상 아메리카노(`menu_id = 1`)는 `order_detail` 4개 행(id 1, 10, 15, 19)에 등장한다 → 4행 갱신, 갱신 이상.

참고로 2NF는 **복합키 테이블에서만** 의미가 있다. 후보키가 단일 컬럼이면 '키의 일부'라는 게 없으므로 1NF를 만족하는 순간 2NF는 자동으로 만족된다.

→ **2NF 결과**: `menu_name`을 `menu` 테이블로 보내고 `menu_id`만 남긴다. 제출 스키마의 `order_detail`이 정확히 이 모양이다.

### 2-3. 2NF → 3NF : 이행 종속 제거

`order_detail`에 `category_name`까지 넣었다고 하자.

```text
   menu_id → category_id → category_name
   즉  menu_id → category_name  (키가 아닌 속성을 거쳐서 결정됨 = 이행 종속)
```

실제 피해: '커피'를 'COFFEE'로 바꾸면 커피 카테고리 메뉴가 들어간 모든 주문 행을 고쳐야 하고, 중간에 실패하면 '커피'와 'COFFEE'가 공존한다.

3NF의 교과서적 정의는 이렇다. **모든 FD `X → A`에 대해, `X`가 슈퍼키이거나 `A`가 후보키의 일부(prime attribute)여야 한다.** 위 예에서 `menu_id`는 슈퍼키가 아니고 `category_name`도 prime이 아니므로 위반이다.

→ **3NF 결과**: `category`를 독립 테이블로 빼고 `menu.category_id`로 참조. 제출 스키마 그대로다.

### 2-4. 3NF → BCNF : 무엇이 다른가

BCNF는 3NF보다 한 칸 더 엄격하다. **"모든 (자명하지 않은) 결정자, 즉 `→`의 왼쪽은 슈퍼키여야 한다."** 3NF는 "결정되는 쪽이 후보키의 일부면 봐준다"는 예외를 남기는데, BCNF는 그 예외를 없앤다.

이 스키마에서 억지로 만들면:

```text
가정: 바리스타 배치표
  shift(barista_id, category_id, station_no)
  규칙 ① (barista_id, category_id) → station_no
  규칙 ② station_no → category_id                  -- 스테이션 하나는 한 카테고리 전용

  후보키: (barista_id, category_id) 와 (barista_id, station_no)  -- 두 개가 barista_id 를 공유
```

규칙 ②의 결정자 `station_no`는 슈퍼키가 아니다. 그런데 결정되는 `category_id`는 후보키의 일부(prime)라서 **3NF는 통과**한다. BCNF는 위반이다. 실제 피해: 스테이션 3번이 '티' 전용이라는 사실이 배치 행마다 반복 저장돼, 마지막 배치를 지우면 그 사실이 사라진다.

→ 분해: `station(station_no PK, category_id)` + `shift(barista_id, station_no)`.

여기서 같이 알아둘 것 하나. 이 분해는 **무손실 조인(lossless join)은 보장되지만 종속성 보존(dependency preservation)은 깨진다.** 규칙 ①은 두 테이블 어느 쪽에서도 단독으로 검사할 수 없다. "3NF는 무손실 + 종속성 보존을 항상 동시에 달성할 수 있지만, BCNF는 무손실만 보장되고 종속성 보존은 포기해야 할 수 있다" — 이게 실무에서 3NF까지만 밀고 BCNF는 사례별로 판단하는 이유다.

| 정규형 | 없애는 것 | 카페 스키마의 해당 조치 |
|---|---|---|
| 1NF | 다중값 칸 | 주문 라인을 `order_detail` 행으로 분리 |
| 2NF | 복합키에 대한 부분 종속 | `menu_name`을 `menu`로 |
| 3NF | 이행 종속 | `category_name`을 `category`로 |
| BCNF | 슈퍼키 아닌 결정자 | 현 스키마엔 위반 없음(모든 후보키가 단일 컬럼) |

BCNF 칸의 근거를 정확히 대면 이렇다. 어떤 테이블의 **후보키가 전부 단일 컬럼이면 3NF와 BCNF는 같다.** BCNF만 위반하려면 "슈퍼키가 아닌 X가 prime 속성 A를 결정"해야 하는데, 후보키가 전부 단일 컬럼이면 prime 속성 A 자체가 후보키라 `A → 나머지 전부`이고, 따라서 `X → A → 나머지 전부`가 되어 X도 슈퍼키가 되어 버린다(모순). 카페 스키마의 후보키는 `customer(id / email)`, `menu(id / name)`, `category(id / name)`, `order_header(id)`, `order_detail(id)` — 전부 단일 컬럼이다. 그래서 3NF = BCNF다.

**말할 때 쓸 한 줄:** "3NF는 '키가 아닌 것이 키가 아닌 것을 결정하면 안 된다', BCNF는 '아예 모든 결정자가 슈퍼키여야 한다'입니다. 차이가 드러나려면 후보키가 여러 개이면서 컬럼을 공유하는 테이블이 필요한데, 제 스키마는 후보키가 전부 단일 컬럼이라 3NF = BCNF입니다."

---

## 3. N:M은 왜 물리 테이블로 직접 표현할 수 없나

관계형 모델의 대전제: **한 칸에는 값이 하나(원자값)**. 그래서 "고객 한 명이 여러 메뉴를, 메뉴 하나가 여러 고객에게" 라는 양방향 다중성을 **두 테이블만으로는 담을 그릇이 없다**.

억지로 우회한 3가지와 그때 깨지는 것:

| 우회 방법 | SQLite | MySQL 8 | PostgreSQL | 깨지는 것 |
|---|---|---|---|---|
| `menu.customer_ids TEXT = '1,3,5'` | 가능(문자열) | 가능 | 가능 | 검색이 `LIKE '%1%'` → `1`이 `11`, `21`에 걸린다. 인덱스 무효. FK 불가 |
| 배열 컬럼 | **타입 자체가 없다** | 없음(JSON으로 대체) | `int[]` 있음 | PostgreSQL 배열조차 **원소별 FK를 걸 수 없다**. 존재하지 않는 고객 id가 들어가도 DB가 못 막는다 |
| JSON 컬럼 | JSON 함수 내장(3.38.0+, 별도 확장 불필요. 3.45.0+는 JSONB 포맷도 지원) | `JSON` 타입 있음 | `json` / `jsonb` | JSON 내부 값에 FK 불가(세 DBMS 모두). 정합성 검증이 애플리케이션 책임으로 넘어간다 |

배열/JSON에 대해 흔한 반문 두 개를 미리 막아 둔다.

- "PostgreSQL은 GIN 인덱스로 배열·jsonb를 색인할 수 있지 않나?" — 색인은 된다(`@>` 포함 연산 등). 하지만 **FK는 여전히 안 된다.** 인덱스는 성능 도구고 FK는 정합성 도구다. 다른 문제다.
- "MySQL은 JSON에 multi-valued index가 있지 않나?" — 8.0.17부터 있다(배열 원소별 색인). 역시 **참조 무결성은 못 준다.**
- "CHECK로 검증하면 되지 않나?" — CHECK는 자기 행 안에서만 평가되므로 "다른 테이블에 그 id가 존재하는가"를 물을 수 없다.

핵심은 하나다. **"컬럼 안에 값을 여러 개 우겨넣는 순간 FK·인덱스·제약이 전부 죽는다."** 그래서 다중값을 **행(row)으로 펴야** 하고, 행으로 펴는 그릇이 브릿지 테이블이다.

---

## 4. 브릿지 테이블 — `order_detail`이 바로 그것이다

### 4-1. 구조 그림

```text
   customer ──1:N──> order_header ──1:N──> order_detail <──1:N── menu
                                            └ 브릿지 테이블 ┘
                                              (관계 속성 보유:
                                               quantity, unit_price)

  개념: customer  N ────────── M  menu   "누가 무엇을 시켰나"
  물리: 1:N 두 개로 분해.  order_detail 이 두 화살표의 도착점이다.
        order_header 1 : N order_detail   (order_id  FK)
        menu         1 : N order_detail   (menu_id   FK)
```

브릿지 테이블은 항상 이 모양이다. **"N:M 관계선 하나를 지우고, 그 자리에 테이블을 하나 놓으면 관계선이 두 개의 1:N이 된다."** `order_detail`은 두 부모(`order_header`, `menu`)로부터 각각 N쪽이므로, 브릿지에서 부모 쪽으로 거꾸로 읽으면 `order_detail` N:1 `order_header`, `order_detail` N:1 `menu`다.

실측으로 N:M임을 증명할 수 있다.

```sql
-- 서로 다른 (고객, 메뉴) 조합의 개수
SELECT COUNT(*) FROM (
  SELECT DISTINCT oh.customer_id, od.menu_id
  FROM order_header oh
  JOIN order_detail od ON od.order_id = oh.id
);
-- 실측: 16
```

정확한 분모까지 같이 말해야 설득력이 생긴다. 등록된 고객은 10명, 메뉴는 12종이지만 **실제로 주문 이력이 있는 고객은 7명, 한 번이라도 팔린 메뉴는 11종**이다(에그샌드위치는 판매 0, `is_available = 0`). 그 7 × 11 안에서 서로 다른 조합이 16개 나온다. 김민준 한 명이 서로 다른 메뉴 4개를 시켰고(실측: `menu_id` 1, 2, 9, 10), 아메리카노는 김민준·정우진·이서연 3명에게 팔렸다(실측). **양쪽 모두 다(多)** → 정의상 N:M이고, 이걸 담고 있는 물리 테이블이 `order_detail`이다.

### 4-2. 왜 `customer`와 `menu`를 직접 잇지 않았나

직접 `customer_menu(customer_id, menu_id)`로 이었다면 "언제 시켰는지", "몇 잔인지", "그때 얼마였는지", "주문 단위로 취소했는지"를 담을 곳이 없다. 실제 도메인에서 N:M의 교차점은 대개 **그 자체로 이름이 있는 사건**이다. 여기서 그 사건은 '주문'이고, 주문에는 시각(`order_date`)·상태(`status`)라는 속성이 있어 `order_header`로 승격됐다. 그래서 브릿지가 2단(header/detail)이 됐다.

2단으로 나눈 것에는 정규화상의 근거도 있다. 만약 `order_date`, `status`를 `order_detail`에 그대로 뒀다면 `order_id → order_date`, `order_id → status`라는 부분 종속이 생긴다(후보키 `(order_id, menu_id)` 기준). 주문 하나를 취소할 때 라인 수만큼 UPDATE해야 하고, 일부만 갱신되면 한 주문이 두 상태를 갖는다. **header/detail 분리 = 2NF 적용**이다.

**말할 때 쓸 문장:**
> "브릿지 테이블에 관계 자체의 속성이 생기면 그건 더 이상 단순 연결 테이블이 아니라 독립 엔티티입니다. 그래서 `order_detail`은 대리키 `id`를 갖고, 주문 시각·상태처럼 주문 전체에 붙는 속성은 `order_header`로 한 단계 더 올렸습니다. 안 그러면 `order_id`에 대한 부분 종속이 생겨서 2NF 위반입니다."

### 4-3. 순수 브릿지(속성 없음)는 이렇게 생겼다 — `menu_tag`

`order_detail`은 속성이 붙은 고급형이라, 대비되는 순수형을 하나 알아두면 설명이 선명해진다. 메뉴와 태그는 N:M이다(아메리카노는 'ICE가능'+'디카페인가능', 'ICE가능'은 아메리카노·카페라떼·딸기스무디에 걸린다).

```sql
-- SQLite
PRAGMA foreign_keys = ON;   -- ★ 이 한 줄이 없으면 아래 FK는 장식이다

CREATE TABLE tag (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
);

CREATE TABLE menu_tag (
    menu_id INTEGER NOT NULL REFERENCES menu(id) ON DELETE CASCADE,
    tag_id  INTEGER NOT NULL REFERENCES tag(id)  ON DELETE CASCADE,
    PRIMARY KEY (menu_id, tag_id)
) WITHOUT ROWID;

CREATE INDEX idx_menu_tag_rev ON menu_tag (tag_id, menu_id);  -- 역방향 조회용
```

실측(메모리 DB에 위 DDL로 검증, SQLite 3.46.1):

```text
INSERT INTO menu_tag VALUES (1,1);  -- 이미 있는 조합
  → IntegrityError: UNIQUE constraint failed: menu_tag.menu_id, menu_tag.tag_id
    (확장 결과코드 SQLITE_CONSTRAINT_PRIMARYKEY = 1555. 복합 PK가 중복 태깅을 막는다)

INSERT INTO menu_tag VALUES (99,1); -- 없는 메뉴
  ㆍPRAGMA foreign_keys = OFF (SQLite 기본값!)
      → 성공. (99,1) 이 그대로 저장된다. FK 선언은 파싱만 되고 검사되지 않는다
  ㆍPRAGMA foreign_keys = ON
      → IntegrityError: FOREIGN KEY constraint failed
        (확장 결과코드 SQLITE_CONSTRAINT_FOREIGNKEY = 787)
```

#### SQLite의 FK 함정 두 개 — 반드시 외운다

이 부분은 원고에서 가장 자주 틀리는 곳이라 따로 뗀다.

1. **SQLite의 외래키 강제는 기본 OFF다.** 컴파일 옵션과 하위 호환 때문에 `PRAGMA foreign_keys`의 기본값이 `0`이다(실측: 새 연결에서 `PRAGMA foreign_keys` → `0`). 이 상태에서는 위처럼 유령 참조가 그냥 들어간다. MySQL(InnoDB)·PostgreSQL은 항상 강제하므로 이 함정이 없다.
2. **PRAGMA는 연결(connection) 단위이고, 트랜잭션 안에서는 무시된다.** 파일에 저장되는 설정이 아니라서 **연결할 때마다 매번** 실행해야 하고, 이미 트랜잭션이 열려 있으면 `PRAGMA foreign_keys=ON`이 조용히 no-op이 된다(실측: 트랜잭션 안에서 값을 바꾸려 하면 아무 에러 없이 이전 값이 유지됨). Python `sqlite3`에서는 **연결 직후, 어떤 DML보다 먼저** 실행하는 게 안전하다.

CSV 컬럼으로는 중복 방지·참조 검증 두 방어가 **둘 다 불가능**하다. 이게 브릿지 테이블을 쓰는 실질적 이유다.

#### `NOT NULL`을 직접 쓰는 이유

`NOT NULL`을 명시한 것도 그냥 습관이 아니다. **SQLite의 rowid 테이블에서는 `INTEGER PRIMARY KEY`(rowid의 별칭)를 제외한 모든 PRIMARY KEY 컬럼이 NULL을 허용한다.** 복합 PK에 국한된 이야기가 아니라 단일 `TEXT PRIMARY KEY`도 마찬가지다. 초기 버전의 버그가 하위 호환 때문에 그대로 남은 것으로, SQLite 문서에도 "알려진 표준 위반"으로 명시돼 있다.

실측:

```text
CREATE TABLE t1(x INTEGER, y INTEGER, PRIMARY KEY(x,y));      -- rowid 테이블
  INSERT INTO t1 VALUES (NULL,1);   → 성공
  INSERT INTO t1 VALUES (NULL,1);   → 또 성공 (2행!)
     ↑ UNIQUE 인덱스에서 NULL 끼리는 '서로 다른 값'으로 취급되므로
       중복 방지 장치가 통째로 무력화된다

CREATE TABLE t2(x TEXT PRIMARY KEY);                          -- 단일 PK도 동일
  INSERT INTO t2 VALUES (NULL);     → 성공

CREATE TABLE t3(x INTEGER PRIMARY KEY);                       -- rowid 별칭만 예외
  INSERT INTO t3 VALUES (NULL);     → 성공하지만 NULL 이 아니라 자동 부여된 1 이 들어간다

CREATE TABLE t4(x INTEGER, y INTEGER, PRIMARY KEY(x,y)) WITHOUT ROWID;
  INSERT INTO t4 VALUES (NULL,1);   → IntegrityError: NOT NULL constraint failed: t4.x
```

MySQL 8과 PostgreSQL은 표준대로 PK 컬럼을 자동으로 NOT NULL로 만들므로 이 문제가 없다. **SQLite에서 브릿지 테이블을 만들 땐 `WITHOUT ROWID`를 붙이고, 그와 별개로 `NOT NULL`도 반드시 직접 쓴다.** 둘 중 하나만 믿지 않는다.

### 4-4. NULL 3값 논리 — 제약을 조용히 통과시키는 값

브릿지 테이블에서 `NOT NULL`이 왜 그렇게 중요한지는 **SQL의 3값 논리(TRUE / FALSE / UNKNOWN)**를 알아야 끝까지 이해된다. NULL이 낀 비교는 TRUE도 FALSE도 아닌 **UNKNOWN**이 되고, 제약마다 UNKNOWN을 다르게 취급한다.

| 제약 | 결과가 UNKNOWN일 때 | 결론 |
|---|---|---|
| `CHECK` | **통과시킨다** (표준: FALSE일 때만 위반) | `CHECK (quantity > 0)`은 `quantity IS NULL`을 못 막는다 |
| `WHERE` / `HAVING` / `JOIN ON` | **행을 버린다** (TRUE만 통과) | 같은 조건인데 반대로 동작한다 |
| `UNIQUE` | NULL끼리는 서로 다르다고 본다 | NULL이 낀 조합은 중복 저장된다 |
| `FOREIGN KEY` (기본 MATCH SIMPLE) | 참조 컬럼에 NULL이 하나라도 있으면 **검사 자체를 건너뛴다** | 복합 FK에서 특히 위험 |

실측(SQLite 3.46.1):

```text
CREATE TABLE t(q INTEGER CHECK (q > 0));
INSERT INTO t VALUES (NULL);     → 성공.  NULL > 0 은 UNKNOWN → CHECK 통과

SELECT NULL > 0,  NULL = NULL,  NULL IS NULL;
   →   NULL,      NULL,         1

SELECT 1 IN (1, NULL),  3 IN (1, NULL),  3 NOT IN (1, NULL);
   →   1,               NULL,            NULL
```

마지막 줄이 그 유명한 **`NOT IN` 함정**이다. `3 NOT IN (1, NULL)`은 상식적으로 참이어야 할 것 같지만 UNKNOWN이라, `WHERE ... NOT IN (NULL이 섞인 서브쿼리)`는 **한 행도 반환하지 않는다.** 원리는 이렇다. `x NOT IN (a, b)`는 `x <> a AND x <> b`로 풀리는데, `3 <> NULL`이 UNKNOWN이므로 `TRUE AND UNKNOWN = UNKNOWN`이 된다. 반대로 `IN`은 `OR`로 풀려서 하나만 TRUE면 TRUE라 문제가 없다(`1 IN (1, NULL)` → 1).

그래서 "한 번도 안 팔린 메뉴 찾기" 같은 쿼리는 `NOT IN` 대신 `NOT EXISTS`나 `LEFT JOIN ... IS NULL`로 쓴다. 두 방식은 NULL에 영향받지 않는다.

```sql
-- ✕ 위험: order_detail.menu_id 가 NULL 을 허용하는 순간 결과가 0행이 된다
SELECT name FROM menu WHERE id NOT IN (SELECT menu_id FROM order_detail);

-- ○ 안전
SELECT m.name
FROM menu m
LEFT JOIN order_detail od ON od.menu_id = m.id
WHERE od.id IS NULL;
-- 실측: 에그샌드위치 (1행)

-- ○ 안전 (같은 결과)
SELECT m.name FROM menu m
WHERE NOT EXISTS (SELECT 1 FROM order_detail od WHERE od.menu_id = m.id);
```

현재 스키마는 `order_detail.menu_id`가 `NOT NULL`이라 지금은 `NOT IN`도 우연히 맞는 답을 낸다. **"지금 NULL이 없다"에 기대는 쿼리를 쓰지 않는 것**이 요점이다.

DBMS 차이 하나: PostgreSQL 15부터 `UNIQUE NULLS NOT DISTINCT`를 붙이면 NULL끼리도 같은 값으로 보게 만들 수 있다. SQLite와 MySQL 8에는 그런 옵션이 없다. 어느 쪽이든 브릿지 테이블에서는 **애초에 NOT NULL을 걸어 NULL을 들이지 않는 것**이 정답이다.

---

## 5. 브릿지 테이블의 PK 선택 — 복합 PK vs 대리키 + UNIQUE

두 가지 설계가 있고, **둘 다 정답이 될 수 있다.** 어느 쪽인지 근거를 대는 게 실력이다.

```sql
-- (A) 복합 PK
PRIMARY KEY (menu_id, tag_id)

-- (B) 대리키 + UNIQUE
id INTEGER PRIMARY KEY AUTOINCREMENT,
UNIQUE (menu_id, tag_id)
```

| 항목 | (A) 복합 PK | (B) 대리키 + UNIQUE |
|---|---|---|
| 중복 방지 | PK가 곧 방지 장치 | UNIQUE로 별도 보장 |
| 저장 공간 | 작다(단, SQLite rowid 테이블은 예외 — 아래 실측) | 인덱스가 하나 더(PK + UNIQUE) |
| 자식 테이블이 이 행을 참조할 때 | FK가 2컬럼이라 번거롭다 | `id` 하나로 참조. 편하다 |
| ORM 매핑 | 복합키 지원이 프레임워크마다 들쭉날쭉 | 단일 PK라 무난 |
| 관계 속성이 늘어날 때 | 엔티티로 승격시키기 애매 | 이미 엔티티 형태 |
| **같은 조합의 중복 라인 허용** | **불가능** | UNIQUE를 빼면 가능 |

### 5-1. SQLite에서 실측한 저장 공간 차이

재현 조건: `menu_id` 1..200 × `tag_id` 1..200 = **40,000행**, 두 정의에 동일 데이터를 `executemany`로 적재, SQLite 3.46.1, `page_size` 4096(기본값).

| 정의 | 파일 크기 | 페이지 수 | 조회 계획 (`WHERE menu_id = ?`) |
|---|---|---|---|
| `PRIMARY KEY(menu_id,tag_id)` (rowid 테이블) | 1,011,712 B | 247 | `SEARCH mt USING COVERING INDEX sqlite_autoindex_mt_1 (menu_id=?)` |
| 같은 정의 + `WITHOUT ROWID` | 405,504 B | 99 | `SEARCH mt USING PRIMARY KEY (menu_id=?)` |
| (참고) 위 두 파일을 `VACUUM` 후 | 946,176 B / 360,448 B | 231 / 88 | 동일 |

**약 60% 감소**한다(VACUUM 후 기준 61.9%). 이유는 명확하다. SQLite의 rowid 테이블은 숨은 `rowid`로 정렬된 본체 B-tree를 두고, 복합 PK를 강제하기 위해 **별도의 자동 UNIQUE 인덱스(`sqlite_autoindex_mt_1`)를 하나 더** 만든다 → PK 컬럼들이 두 벌 저장된다. `WITHOUT ROWID`는 복합 PK 자체를 클러스터 키로 삼아 본체 하나만 유지한다. 이 테이블처럼 **PK가 곧 전체 컬럼**인 순수 브릿지에서 차이가 가장 크게 벌어진다.

> 주의: 정확한 바이트 수는 키 분포·삽입 순서·`page_size`·VACUUM 여부에 따라 달라진다. 외울 것은 숫자가 아니라 **"SQLite 순수 브릿지에는 `WITHOUT ROWID`를 붙인다"**는 결론이다. 반대로 컬럼이 많은 테이블에 `WITHOUT ROWID`를 붙이면 PK가 모든 보조 인덱스에 복제되어 오히려 커질 수 있다(SQLite 문서 권고: 행이 작을 때 유리).

### 5-2. DBMS별 물리 구조

| DBMS | 복합 PK 브릿지의 물리 구조 |
|---|---|
| **SQLite** | 기본은 rowid 본체 + 자동 UNIQUE 인덱스(PK 컬럼 중복 저장). `WITHOUT ROWID`를 붙여야 PK가 클러스터 키가 된다 |
| **MySQL 8 (InnoDB)** | PK가 **항상** 클러스터 인덱스. `WITHOUT ROWID`에 해당하는 게 기본 동작이라 복합 PK가 자연스럽게 효율적. 단 보조 인덱스 리프가 PK 전체를 행 식별자로 품으므로, PK 폭이 넓으면 보조 인덱스가 다 같이 뚱뚱해진다 (PK를 선언하지 않으면 UNIQUE NOT NULL 인덱스를, 그것도 없으면 숨은 6바이트 `GEN_CLUST_INDEX`를 클러스터 키로 쓴다) |
| **PostgreSQL** | 힙(heap) 테이블 + PK는 **별도 B+tree**. 인덱스는 힙 튜플의 위치(TID)만 가리키므로 클러스터링 이득이 없다. 대신 `CREATE INDEX ... INCLUDE (...)`(11+)로 커버링 인덱스를 따로 설계한다. `CLUSTER` 명령은 그 시점 한 번 물리 정렬할 뿐 이후 갱신에는 유지되지 않는다 |

### 5-3. 잠깐 — B-tree인가 B+tree인가

위 표를 정확히 말하려면 자료구조를 구분해야 한다. 면접에서 자주 흔들리는 지점이다.

- **B-tree**: 내부 노드에도 데이터(페이로드)를 저장한다. 운 좋으면 내부 노드에서 탐색이 끝난다.
- **B+tree**: 데이터는 **리프에만** 있고 내부 노드는 키와 포인터만 갖는다. 리프끼리 연결돼 있어 **범위 스캔이 빠르다.** 내부 노드가 가벼워 팬아웃(fan-out)이 커지고 트리 높이가 낮아진다.

실제 구현은 이렇다.

| 엔진 | 구조 |
|---|---|
| **InnoDB** | 인덱스·테이블 모두 **B+tree**. 클러스터 인덱스의 리프가 곧 행 데이터다 |
| **PostgreSQL** | 인덱스는 **B+tree**(Lehman–Yao 변형, 리프가 양방향 연결). 테이블은 트리가 아니라 **힙**이라 정렬 순서 자체가 없다 |
| **SQLite** | 둘을 섞어 쓴다. **테이블 B-tree(rowid 테이블)는 페이로드를 리프에만 두어 B+tree처럼 동작**하고, **인덱스 B-tree(및 `WITHOUT ROWID` 테이블)는 내부 노드에도 키를 저장하는 고전적 B-tree**다 |

여기서 나오는 흔한 오개념 세 개를 미리 정리한다.

1. **"인덱스는 B-tree다"** → 세 DBMS 모두 인덱스 관점에서는 사실상 B+tree 계열이고, 정렬 순서를 이용한 범위 탐색·`ORDER BY` 생략이 가능한 이유가 여기 있다. 해시 인덱스는 등치 비교만 되고 범위·정렬에 못 쓴다(PostgreSQL의 `USING hash`, MySQL MEMORY 엔진. InnoDB의 adaptive hash index는 사용자가 만드는 게 아니라 엔진이 자동으로 얹는 캐시다).
2. **"InnoDB 세컨더리 인덱스는 행 주소를 가리킨다"** → 아니다. **PK 값**을 가진다. 그래서 세컨더리 인덱스로 찾은 뒤 PK로 클러스터 인덱스를 한 번 더 타는 **북마크 룩업**이 생기고, 반대로 필요한 컬럼이 (인덱스 컬럼 + PK) 안에 다 있으면 그 룩업이 사라진다.
3. **"PostgreSQL도 PK가 클러스터드다"** → 아니다. 힙이라 물리 순서가 없다. PostgreSQL의 index-only scan은 인덱스만으로 값을 얻더라도 **가시성 맵(visibility map)** 확인이 필요하고, 갱신이 잦아 맵이 더러우면 결국 힙을 읽는다.
4. **LSM 트리**(LevelDB/RocksDB/Cassandra 계열)는 쓰기를 메모리 테이블에 모았다가 순차적으로 병합 기록하는 **완전히 다른 계열**이다. SQLite·InnoDB·PostgreSQL의 기본 저장 구조는 LSM이 아니다(MySQL에 RocksDB를 얹는 MyRocks, SQLite의 `lsm1` 확장 같은 선택지가 따로 있을 뿐이다). "B-tree는 읽기, LSM은 쓰기에 유리하다"는 비교를 이 문서의 스키마에 적용하려 하지 않는다.

### 5-4. 학습자의 판단: `order_detail`에 `(order_id, menu_id)` UNIQUE를 일부러 안 건 것

이건 실수가 아니라 **도메인 판단**이고, 근거가 명확해서 방어 가능하다.

> "같은 주문에 '아메리카노 ICE 1잔 + 아메리카노 HOT 1잔'처럼 옵션이 다른 같은 메뉴가 **별도 라인**으로 들어갈 수 있어야 합니다. `(order_id, menu_id)`에 UNIQUE를 걸면 그 순간 이 케이스가 DB 레벨에서 불가능해집니다. 그래서 대리키 `id`를 PK로 두고 조합 UNIQUE는 걸지 않았습니다. 대신 집계는 전부 `SUM(quantity)` 기준이라 라인이 나뉘어도 수치는 정확합니다."

즉 표의 마지막 행 — **"같은 조합의 중복 라인을 허용해야 한다"** — 가 바로 (B)를 골라야 하는 조건이고, 이 스키마가 그 조건에 해당한다. 반대로 `menu_tag`는 "같은 메뉴에 같은 태그를 두 번"이 무의미하므로 (A) 복합 PK가 맞다. **판단 기준 한 줄: "그 조합이 두 번 나올 수 있는 도메인인가?"**

현재 데이터로도 확인된다. `SELECT order_id, menu_id, COUNT(*) FROM order_detail GROUP BY 1,2 HAVING COUNT(*) > 1` → **0행**(실측). 즉 지금은 중복이 없지만, **가능성을 열어두기 위해** 제약을 안 건 것이다. 이 구분("현재 데이터에 없다" ≠ "제약을 걸어야 한다")을 말할 수 있으면 설계자로 보인다.

다만 정직하게 덧붙일 반대편 논리도 준비해 둔다. 옵션 컬럼(`option_note` 등)이 실제로 생기면 그때는 `(order_id, menu_id, option_note)` UNIQUE로 조여서 **진짜 중복 라인은 다시 막는 것**이 더 나은 설계다. "지금은 옵션 컬럼이 과제 범위 밖이라 제약을 유보했다"까지 말하면 완성된다.

---

## 6. 복합 PK의 컬럼 순서와 역방향 인덱스

복합 인덱스 `(A, B)`는 **A로 먼저 정렬되고, A가 같은 것끼리 B로 정렬된 전화번호부**다. 그래서 `WHERE A=?`는 빠르고, `WHERE B=?` 단독은 **인덱스의 정렬 순서를 이용할 수 없다**(성 없이 이름만으로 전화번호부를 찾는 것과 같다). 이걸 좌측 선두 접두사(leftmost prefix) 규칙이라 하고, SQLite / MySQL 8 / PostgreSQL의 B-tree 인덱스에 공통으로 적용된다.

여기에 정확한 단서를 붙인다. **"인덱스를 절대 못 쓴다"는 아니다.**

- **SQLite**: 후행 컬럼 단독 조건이면 그 인덱스를 버리고 테이블을 스캔한다(실측: `SCAN`).
- **MySQL 8**: 8.0.13부터 **index skip scan**이 있다. 선두 컬럼의 distinct 값이 적으면 값마다 범위 탐색을 반복해 인덱스를 쓸 수 있다.
- **PostgreSQL**: 예전부터 후행 컬럼 조건만으로도 **인덱스 전체를 훑는** 형태로 쓸 수는 있었고(효율은 나쁘다), 18부터 B-tree **skip scan**이 들어가 선두 컬럼의 카디널리티가 낮을 때 제대로 활용된다.

그래도 결론은 같다. **skip scan은 옵티마이저의 구제책이지 설계의 대체재가 아니다.** 선두 컬럼의 distinct 값이 많으면 이득이 사라진다. 역방향 조회가 주 패턴이면 인덱스를 따로 둔다.

`menu_tag`(§4-3의 `WITHOUT ROWID` 정의)로 실측:

```text
① 정방향  SELECT * FROM menu_tag mt WHERE mt.menu_id = 1
   → SEARCH mt USING PRIMARY KEY (menu_id=?)                                   빠름

② 역방향  SELECT * FROM menu_tag mt WHERE mt.tag_id = 1        (역방향 인덱스 없음)
   → SCAN mt                                                                   전체 스캔

③ CREATE INDEX idx_menu_tag_rev ON menu_tag(tag_id, menu_id);  적용 후 ②를 재실행
   → SEARCH mt USING COVERING INDEX idx_menu_tag_rev (tag_id=?)                빠름
```

> 문자열 주의: `WITHOUT ROWID` 테이블은 PK 자체가 본체라 `USING PRIMARY KEY`로 표시된다. 같은 테이블을 **rowid 테이블**로 만들면 자동 인덱스를 타므로 `SEARCH mt USING COVERING INDEX sqlite_autoindex_mt_1 (menu_id=?)`가 나온다(둘 다 실측 확인). 실행계획 문자열을 외울 게 아니라, **어떤 구조라서 그 문자열이 나오는지**를 말할 수 있어야 한다.

그래서 **브릿지 테이블은 인덱스를 두 개 두는 게 관행**이다. `(A,B)`는 PK로, `(B,A)`는 보조 인덱스로. 두 컬럼 모두 인덱스에 있으니 테이블 본체를 안 읽는 **커버링 인덱스**가 되어 더 빠르다(실측에서 `COVERING INDEX`로 표시됨).

여기에도 DBMS 차이가 있다. **InnoDB에서는 `INDEX(tag_id)`만 만들어도 리프에 PK 값이 붙으므로 물리적으로 이미 `(tag_id, menu_id)`다.** 즉 `(B, A)`를 명시적으로 쓸 필요가 없다(써도 손해는 아니지만 중복이다). SQLite와 PostgreSQL은 그런 자동 부가가 없으므로 `(B, A)`를 직접 써야 커버링이 된다.

같은 원리가 제출 스키마에도 그대로 적용된다.

```text
SELECT * FROM order_detail WHERE order_id = 1
   → SEARCH order_detail USING INDEX idx_order_detail_order_id (order_id=?)   ← 인덱스 있음

SELECT * FROM order_detail WHERE menu_id = 1
   → SCAN order_detail                                                        ← 인덱스 없음
```

즉 **`order_detail`은 지금 "주문 → 메뉴" 방향만 인덱싱돼 있고, "메뉴 → 이 메뉴가 팔린 주문" 역방향은 풀스캔**이다. 18행이라 체감이 없을 뿐, 메뉴별 판매 집계가 늘어나면 인덱스를 추가해야 한다. 복사본에서 직접 걸어 보면 계획이 이렇게 바뀐다(실측).

```sql
CREATE INDEX idx_order_detail_menu_id ON order_detail(menu_id, order_id);
```

```text
SELECT * FROM order_detail WHERE menu_id = 1
   → SEARCH order_detail USING INDEX idx_order_detail_menu_id (menu_id=?)
SELECT order_id FROM order_detail WHERE menu_id = 1
   → SEARCH order_detail USING COVERING INDEX idx_order_detail_menu_id (menu_id=?)
SELECT menu_id, SUM(quantity) FROM order_detail GROUP BY menu_id
   → SCAN order_detail USING INDEX idx_order_detail_menu_id   (정렬 없이 그룹핑)
```

`SELECT *`는 `quantity`, `unit_price`가 인덱스에 없어 본체를 읽지만(`COVERING` 아님), 필요한 컬럼만 고르면 커버링이 된다. 이 차이를 짚으면 "인덱스를 외운 사람"이 아니라 "실행계획을 읽는 사람"이 된다.

FK 인덱스에 대한 DBMS 차이도 정확히 알아둔다.

| DBMS | 자식 FK 컬럼 인덱스 |
|---|---|
| **SQLite** | 자동 생성 **안 한다**. 직접 만들어야 한다 (그래서 위 SCAN이 나온다). `PRAGMA foreign_key_check`나 부모 삭제 시 자식 탐색이 느려진다 |
| **MySQL 8 (InnoDB)** | FK 제약을 걸면 적절한 인덱스가 없을 때 **자동 생성**한다(InnoDB가 FK 컬럼 인덱스를 요구하기 때문) |
| **PostgreSQL** | 자동 생성 **안 한다**. 부모 DELETE/UPDATE 시 자식 전체 스캔이 발생하므로 직접 만들어야 한다 |

---

## 7. 반정규화 — `unit_price` 스냅샷은 위반이 아니라 판단이다

`order_detail.unit_price`는 `menu.price`와 사실상 같은 값이라, 순진하게 보면 "메뉴 가격을 중복 저장했다 = 3NF 위반"으로 지적당하기 쉽다. **아니다.** 두 값은 **의미가 다른 별개의 사실**이다.

- `menu.price` = **지금** 이 메뉴의 판매가
- `order_detail.unit_price` = **그때** 실제로 결제된 금액

같은 값이 우연히 들어있을 뿐, `menu_id → unit_price` 라는 함수 종속이 **애초에 성립하지 않는다**(같은 메뉴가 시점에 따라 다른 값으로 팔린다). 종속이 없으면 위반도 없다. §2 서두에서 말한 "FD는 데이터에 우연히 성립하는 사실이 아니라 도메인 규칙"이라는 원칙이 여기서 그대로 쓰인다.

현재 `cafe.db`가 이걸 실증한다. Q13에서 아메리카노를 3500 → 4000으로 올린 상태다(실측: `menu.price = 4000`, `order_detail`의 아메리카노 라인 4개는 모두 `unit_price = 3500`).

| 메뉴 | 수량 | `SUM(qty × od.unit_price)` (스냅샷) | `SUM(qty × m.price)` (조인) |
|---|---|---|---|
| **아메리카노** | 8 | **28,000** | **32,000** |
| 티라미수 | 3 | 19,500 | 19,500 |
| 크로와상 | 3 | 13,500 | 13,500 |
| 카페라떼 | 3 | 13,500 | 13,500 |

```sql
-- 위 표를 만든 쿼리 (실측 확인)
SELECT m.name,
       SUM(od.quantity)                  AS qty,
       SUM(od.quantity * od.unit_price)  AS revenue_snapshot,
       SUM(od.quantity * m.price)        AS revenue_joined
FROM order_detail od
JOIN menu m ON m.id = od.menu_id
GROUP BY m.id
ORDER BY revenue_snapshot DESC;
```

`menu.price`를 조인해 매출을 계산하면 아메리카노 과거 매출이 **28,000원 → 32,000원으로 저절로 부풀어 오른다**. 가격을 한 번 올릴 때마다 지난달 결산이 바뀌는 회계 시스템이 된다. 이건 성능 최적화가 아니라 **정확성 문제**다.

**평가 자리에서 말할 대본 (그대로 읽기):**
> "`order_detail.unit_price`는 의도적인 반정규화입니다. `menu.price`를 조인해서 계산할 수도 있지만, 그러면 메뉴 가격을 올리는 순간 과거 매출까지 소급 변경됩니다. 실제로 아메리카노를 3500원에서 4000원으로 올려보니, 조인 방식은 과거 매출이 28,000원에서 32,000원으로 바뀌었고 스냅샷 방식은 28,000원 그대로였습니다. 그리고 엄밀히 말하면 이건 3NF 위반도 아닙니다. '그때 결제된 금액'과 '지금 판매가'는 서로 다른 사실이라, `menu_id`가 `unit_price`를 결정한다는 함수 종속 자체가 성립하지 않기 때문입니다."

반정규화 일반론도 한 줄로 정리해 둔다.

| 반정규화 유형 | 정당한 이유 | 대가 |
|---|---|---|
| 이력 스냅샷 (`unit_price`) | 과거 사실 보존. **정확성** 문제 | 거의 없다. 컬럼 하나만큼의 저장 공간, 그리고 "주문 시점 가격표와 스냅샷이 맞는지"를 DB가 검증해 줄 수 없다는 점 정도 |
| 집계 컬럼 (`order_header.total_amount`) | 읽기 성능 | 쓰기마다 동기화 필요, 불일치 위험. 트리거나 애플리케이션 트랜잭션으로 강제해야 한다 |
| 조인 회피 중복 (`order_detail.menu_name`) | 조인 감소 | 갱신 이상. **정당화하기 어렵다** |

세 줄의 차이를 한 문장으로: 첫 줄은 **다른 사실을 저장**하는 것이고, 아래 두 줄은 **같은 사실을 두 곳에 저장**하는 것이다. 앞은 반정규화라 부르기도 애매하고, 뒤는 진짜 반정규화라 근거가 필요하다.

"정규화는 기본값, 반정규화는 근거가 필요한 예외" — 이 순서로 말한다.

---

## 8. DBMS 이식성과 애플리케이션 예외 처리

브릿지 테이블 얘기를 하다 보면 "그럼 MySQL/PostgreSQL에서도 그대로 되나요?"가 반드시 따라온다. 버전 경계를 정확히 알고 있으면 여기서 신뢰가 생긴다.

### 8-1. 버전 경계표

| 기능 | SQLite | MySQL 8 | PostgreSQL |
|---|---|---|---|
| `CHECK` 제약 | 3.3.0(2006)부터 **강제** | 8.0.15까지는 **파싱만 하고 무시**, **8.0.16부터 강제**. 그 이전(5.7 포함)에는 `CHECK`가 장식이었다 | 오래전부터 강제 |
| 외래키 강제 | 3.6.19부터 지원하지만 **기본 OFF**. 연결마다 `PRAGMA foreign_keys = ON` | InnoDB는 항상 강제(MyISAM은 무시). `foreign_key_checks` 세션 변수로 일시 해제 가능 | 항상 강제 |
| `RIGHT JOIN` / `FULL OUTER JOIN` | **3.39.0(2022-06)부터** 지원. 그 이전에는 `LEFT JOIN` + `UNION`으로 우회했다 | `RIGHT JOIN` 있음, **`FULL OUTER JOIN` 없음**(`UNION`으로 우회) | 둘 다 있음 |
| `PRIMARY KEY` 컬럼의 암묵적 NOT NULL | rowid 테이블에서는 **안 걸린다**(§4-3). `WITHOUT ROWID`면 걸린다 | 자동 NOT NULL | 자동 NOT NULL |
| `AUTOINCREMENT` 계열 | `INTEGER PRIMARY KEY`가 이미 자동 증가. `AUTOINCREMENT`는 "id 재사용 안 함" 보장 추가(+ `sqlite_sequence` 유지 비용) | `AUTO_INCREMENT` | `GENERATED ... AS IDENTITY`(권장) 또는 `serial` |
| 커버링 인덱스 문법 | 별도 문법 없음(인덱스에 컬럼을 다 넣으면 커버링) | 별도 문법 없음. 보조 인덱스에 PK가 자동 포함 | `CREATE INDEX ... INCLUDE (...)` (11+) |
| UNIQUE에서 NULL 취급 | 서로 다름 | 서로 다름 | 기본은 서로 다름, **15+ `NULLS NOT DISTINCT`** 로 변경 가능 |
| 인덱스 skip scan | 없음 | 8.0.13+ | 18+ |
| 타입 시스템 | 동적 타입 + 어피니티(`DATE`, `BOOLEAN`은 실제 타입이 아니다) | 정적 타입 | 정적 타입 |

실측 확인(SQLite 3.46.1): `RIGHT JOIN`, `FULL JOIN` 모두 정상 동작. 3.39 미만 환경에서는 `near "RIGHT": syntax error`가 난다.

이 표에서 카페 스키마에 직접 걸리는 건 두 줄이다. `menu.price CHECK (price >= 0)`, `is_available CHECK (is_available IN (0,1))`, `order_header.status CHECK (...)`는 **MySQL 5.7에 그대로 올리면 조용히 무시된다.** 그리고 SQLite FK는 `PRAGMA` 없이는 검사되지 않는다. "제 스키마는 SQLite 기준이고, MySQL 8.0.16 미만으로 옮기면 CHECK가 무력화됩니다"라고 말할 수 있으면 이식성을 아는 사람이다.

### 8-2. 제약 위반을 애플리케이션에서 구분하기

브릿지 테이블에 INSERT할 때 나올 수 있는 실패는 성격이 완전히 다르다. "이미 담긴 태그입니다"(중복)와 "없는 메뉴입니다"(참조 실패)를 사용자에게 같은 메시지로 보여주면 안 된다. 그런데 **SQLite는 이 넷을 전부 `sqlite3.IntegrityError` 하나로 던진다.** 구분하려면 메시지 문자열을 파싱할 게 아니라 **확장 결과코드**를 봐야 한다(Python 3.11+에서 `sqlite_errorcode` / `sqlite_errorname` 속성 제공).

```python
import sqlite3

con = sqlite3.connect("cafe.db")
con.execute("PRAGMA foreign_keys = ON")   # 연결마다, 트랜잭션 밖에서 (§4-3)

try:
    con.execute(
        "INSERT INTO order_detail(order_id, menu_id, quantity, unit_price)"
        " VALUES (?, ?, ?, ?)",
        (1, 99, 1, 3500),          # menu_id = 99 는 존재하지 않는다
    )
    con.commit()
except sqlite3.IntegrityError as e:
    con.rollback()
    # Python 3.11+ : 확장 결과코드로 원인을 구분한다
    print(e.sqlite_errorname, e.sqlite_errorcode, e)
    # → SQLITE_CONSTRAINT_FOREIGNKEY 787 FOREIGN KEY constraint failed
```

실측한 확장 결과코드 매핑(SQLite 3.46.1):

| 상황 | Python 예외 | `sqlite_errorname` | 코드 | 메시지 |
|---|---|---|---|---|
| 중복 UNIQUE | `IntegrityError` | `SQLITE_CONSTRAINT_UNIQUE` | 2067 | `UNIQUE constraint failed: t.a` |
| 중복 복합 PK (`WITHOUT ROWID`) | `IntegrityError` | `SQLITE_CONSTRAINT_PRIMARYKEY` | 1555 | `UNIQUE constraint failed: mt.menu_id, mt.tag_id` |
| 없는 부모 참조 (FK ON) | `IntegrityError` | `SQLITE_CONSTRAINT_FOREIGNKEY` | 787 | `FOREIGN KEY constraint failed` |
| NOT NULL 위반 | `IntegrityError` | `SQLITE_CONSTRAINT_NOTNULL` | 1299 | `NOT NULL constraint failed: t.c` |
| CHECK 위반 | `IntegrityError` | `SQLITE_CONSTRAINT_CHECK` | 275 | `CHECK constraint failed: b > 0` |

읽는 법: 하위 8비트가 기본 코드 `19`(`SQLITE_CONSTRAINT`)이고, 상위 비트가 세부 원인이다(`787 & 0xff == 19`, `2067 & 0xff == 19`). 그래서 **`IntegrityError`만 잡으면 원인을 모른다.**

다른 DBMS는 표준 `SQLSTATE`로 구분한다. `23`으로 시작하는 클래스가 무결성 제약 위반이다.

| 원인 | PostgreSQL SQLSTATE | MySQL 8 errno (SQLSTATE) |
|---|---|---|
| UNIQUE/PK 중복 | `23505` unique_violation | `1062` ER_DUP_ENTRY (`23000`) |
| FK 위반 | `23503` foreign_key_violation | `1452` 자식 삽입 실패 / `1451` 부모 삭제 실패 (`23000`) |
| NOT NULL 위반 | `23502` not_null_violation | `1048` ER_BAD_NULL_ERROR (`23000`) |
| CHECK 위반 | `23514` check_violation | `3819` ER_CHECK_CONSTRAINT_VIOLATED (`HY000`) |

psycopg에서는 `e.sqlstate`(psycopg2는 `e.pgcode`), MySQL Connector/Python에서는 `e.errno`와 `e.sqlstate`로 읽는다. **원칙 한 줄: 에러 메시지 문자열을 정규식으로 파싱하지 않는다. 메시지는 버전이 바뀌면 변하고, 코드는 안 변한다.**

마지막으로 하나. `INSERT` 전에 `SELECT`로 존재 여부를 확인하고 넣는 방식(check-then-insert)은 동시성 하에서 깨진다. 두 세션이 동시에 확인하면 둘 다 통과한 뒤 하나가 실패한다. **제약은 DB에 걸어 두고, 애플리케이션은 실패를 잡아서 해석하는 쪽**이 정답이다. 필요하면 `INSERT ... ON CONFLICT DO NOTHING`(SQLite 3.24+/PostgreSQL 9.5+)이나 `INSERT IGNORE`(MySQL)로 의도를 명시한다.

---

## 9. 면접 예상 질문 6개 + 답변 대본

### Q1. "N:M 관계를 어떻게 푸나요?" — 60초 완벽 답변

> "관계형 DB는 한 칸에 값 하나만 넣을 수 있어서, N:M을 테이블 두 개로는 표현할 수 없습니다. 그래서 가운데에 브릿지 테이블을 하나 놓고, N:M 관계선 하나를 1:N 두 개로 쪼갭니다.
>
> 제 카페 스키마에서는 '고객과 메뉴'가 N:M입니다. 실제로 서로 다른 (고객, 메뉴) 조합이 16개 나옵니다. 이걸 `order_header`와 `order_detail`로 해소했습니다. `order_header`가 1이고 `order_detail`이 N, `menu`가 1이고 `order_detail`이 N이라, `order_detail`에서 두 개의 1:N이 만납니다. 이게 브릿지 테이블입니다.
>
> 그리고 제 브릿지에는 `quantity`와 `unit_price`가 붙어 있습니다. 이건 고객의 속성도 메뉴의 속성도 아니고 **관계 자체의 속성**이라, 브릿지가 아니면 둘 곳이 없습니다. 이렇게 속성이 붙으면 단순 연결 테이블이 아니라 독립 엔티티가 되고, 그래서 복합 PK 대신 대리키 `id`를 줬습니다."

(암기 순서: **원자값 제약 → 1:N 두 개로 분해 → 내 스키마 지목 → 관계 속성 → PK 선택 근거**)

### Q2. "브릿지 테이블 PK는 복합키로 하나요, 대리키로 하나요?"

> "그 조합이 두 번 나올 수 있는 도메인인지로 갈립니다. 메뉴-태그처럼 같은 조합이 두 번 나올 이유가 없으면 복합 PK `(menu_id, tag_id)`가 맞습니다. 중복 방지가 공짜로 되고 인덱스가 하나 줄어듭니다. 반대로 `order_detail`은 같은 주문에 아메리카노 ICE와 HOT이 별도 라인으로 들어갈 수 있어야 해서 `(order_id, menu_id)` UNIQUE를 일부러 걸지 않았고, 그래서 대리키 `id`를 썼습니다. 다만 SQLite에서 복합 PK를 쓸 땐 `WITHOUT ROWID`를 같이 붙입니다. 안 붙이면 자동 UNIQUE 인덱스가 따로 생겨서 PK 컬럼이 두 벌 저장되고, 40,000행 기준으로 파일이 약 2.5배 커지는 걸 실측했습니다."

### Q3. "복합 PK를 쓸 때 컬럼 순서가 중요한가요?"

> "중요합니다. 복합 인덱스는 앞 컬럼으로 먼저 정렬되기 때문에 `WHERE` 조건이 뒤 컬럼만 쓰면 정렬 순서를 이용할 수 없습니다. 실제로 `menu_tag(menu_id, tag_id)`에서 `menu_id`로 조회하면 `SEARCH ... USING PRIMARY KEY`가 나오는데, `tag_id`만으로 조회하면 `SCAN`이 나옵니다. 그래서 브릿지 테이블은 `(A,B)` PK에 `(B,A)` 보조 인덱스를 하나 더 두는 게 관행입니다. 양쪽 다 커버링 인덱스가 돼서 테이블 본체를 안 읽습니다.
>
> 두 가지 단서를 붙이면, InnoDB는 보조 인덱스 리프에 PK가 자동으로 붙으니까 `INDEX(tag_id)`만 만들어도 이미 `(tag_id, menu_id)`라 `(B,A)`를 명시할 필요가 없습니다. 그리고 MySQL 8.0.13이나 PostgreSQL 18의 skip scan은 선두 컬럼 값이 적을 때 후행 컬럼 조건도 인덱스를 타게 해 주지만, 그건 옵티마이저의 구제책이지 설계 대체재는 아닙니다."

### Q4. "그럼 `order_detail`은 인덱스가 충분한가요?"

> "아닙니다. 지금은 `idx_order_detail_order_id` 하나뿐이라 '주문 → 메뉴' 방향만 인덱스를 탑니다. `WHERE menu_id = 1`은 실행계획이 `SCAN order_detail`로 나옵니다. 18행이라 체감이 없을 뿐이고, 메뉴별 판매 집계가 주 쿼리가 되면 `(menu_id, order_id)` 인덱스를 추가해야 합니다. 실제로 걸어 보니 `SEARCH ... USING INDEX idx_order_detail_menu_id`로 바뀌고, 필요한 컬럼만 고르면 `COVERING INDEX`까지 나옵니다. SQLite와 PostgreSQL은 FK 컬럼에 인덱스를 자동으로 안 만들어 주는데, MySQL InnoDB는 만들어 줍니다."

### Q5. "정규화를 왜 하나요? 조인이 많아져서 느려지지 않나요?"

> "정규화의 목적은 성능이 아니라 이상 현상 제거입니다. 고객 이름을 주문 행마다 반복 저장하면 이메일 하나 바꿀 때 모든 행을 고쳐야 하는 갱신 이상, 주문 없는 카테고리는 넣을 수 없는 삽입 이상, 주문을 지우면 고객 정보까지 날아가는 삭제 이상이 생깁니다. 조인 비용은 인덱스로 줄일 수 있지만, 데이터 정합성이 깨지면 인덱스로 못 고칩니다. 그래서 정규화를 기본값으로 두고, 반정규화는 근거를 댈 수 있을 때만 예외로 씁니다."

### Q6. "그럼 `unit_price`는 반정규화 아닌가요?"

> "의도적인 반정규화 맞습니다. 다만 성능이 아니라 정확성 때문입니다. `menu.price`를 조인하면 가격을 올리는 순간 과거 매출이 소급 변경됩니다. 실측으로 아메리카노 과거 매출이 28,000원에서 32,000원으로 바뀌었습니다. 그리고 엄밀히는 '그때 결제된 금액'과 '지금 판매가'가 다른 사실이라 함수 종속이 성립하지 않아서, 3NF 위반이라고 보기도 어렵습니다."

### (보너스) Q7. "SQLite에서 FK 걸었는데 왜 안 막히죠?"

> "SQLite는 외래키 강제가 기본 OFF입니다. 연결할 때마다 `PRAGMA foreign_keys = ON`을 실행해야 하고, 이미 트랜잭션이 열린 뒤에는 이 PRAGMA가 에러도 없이 무시됩니다. 그래서 저는 연결 직후 첫 문장으로 실행합니다. MySQL InnoDB와 PostgreSQL은 항상 강제라 이 함정이 없습니다."

---

## 10. 30초 안에 스키마를 브릿지 관점으로 읊는 훈련

주석 없이 `01_schema.sql`을 열고, 아래 순서로 **소리 내어** 말하는 연습을 한다. 다섯 번 반복하면 속도가 붙는다.

```text
1) "테이블 5개, 1:N 관계 4개입니다."
   (menu→category, order_header→customer, order_detail→order_header, order_detail→menu)
2) "category 1:N menu, customer 1:N order_header — 여기까진 단순 마스터-디테일입니다."
3) "핵심은 order_detail입니다. order_header 1:N order_detail, menu 1:N order_detail."
4) "즉 order_detail에서 1:N 두 개가 만나고, 이게 고객-메뉴 N:M을 해소하는 브릿지 테이블입니다."
5) "브릿지에 quantity, unit_price라는 관계 속성이 붙어서 독립 엔티티가 됐고, 그래서 대리키 id를 썼습니다."
6) "(order_id, menu_id) UNIQUE는 옵션 다른 같은 메뉴 라인 때문에 일부러 뺐습니다."
7) "order_id에 CASCADE를 건 이유는 주문이 사라지면 그 라인이 고아가 되기 때문이고,
    menu_id에 안 건 이유는 메뉴가 단종돼도 과거 주문 이력은 남아야 하기 때문입니다."
8) "다만 SQLite라서 PRAGMA foreign_keys = ON 을 켜야 이 FK들이 실제로 검사됩니다."
```

이 8문장이 피드백 7번(정규화·N:M)과 피드백 8번(자신감)을 동시에 덮는다. 이미 스키마에 다 들어있는 내용이므로, **새로 공부하는 게 아니라 이미 한 일에 이름을 붙여 소리 내는 것**이 전부다.

### 부록 — 이 문서의 실측 재현 스크립트

```python
import sqlite3
con = sqlite3.connect("cafe.db")
con.execute("PRAGMA foreign_keys = ON")

# N:M 증명
print(con.execute("""
  SELECT COUNT(*) FROM (
    SELECT DISTINCT oh.customer_id, od.menu_id
    FROM order_header oh JOIN order_detail od ON od.order_id = oh.id)
""").fetchone())                                    # → (16,)

# 실행계획
for sql in ["SELECT * FROM order_detail WHERE order_id = 1",
            "SELECT * FROM order_detail WHERE menu_id  = 1"]:
    print(sql, con.execute("EXPLAIN QUERY PLAN " + sql).fetchall())

# 파괴적 DML 은 반드시 롤백
con.execute("DELETE FROM order_header WHERE id = 1")
print(con.execute("SELECT COUNT(*) FROM order_detail").fetchone())   # → (16,) CASCADE
con.rollback()
print(con.execute("SELECT COUNT(*) FROM order_detail").fetchone())   # → (18,) 복구
```

---

## 보강 — 평가 피드백 재점검에서 추가된 것


### 8. 브릿지 테이블의 PK 설계 — 세 가지 선택지

`order_detail`은 `id INTEGER PRIMARY KEY AUTOINCREMENT`라는 **대리키(surrogate key)** 를 썼다. 이게 유일한 답은 아니다.

| 안 | 정의 | 장점 | 단점 | 언제 |
|---|---|---|---|---|
| **A. 복합 PK** | `PRIMARY KEY (order_id, menu_id)` | 중복이 구조적으로 불가능. 인덱스가 하나 줄어든다 | 이 쌍을 참조하는 다른 테이블이 생기면 FK가 2컬럼이 된다. 순수 연결에만 적합 | 관계 속성이 없는 순수 N:M (예: `menu_tag`) |
| **B. 대리키 + UNIQUE** | `id` PK + `UNIQUE (order_id, menu_id)` | 참조가 간단하고 중복도 막힌다 | 인덱스 2개 유지 비용 | 관계에 속성이 있고, 한 쌍이 한 번만 등장해야 할 때 |
| **C. 대리키만** | `id` PK (**현재 스키마**) | 같은 쌍을 여러 줄로 남길 수 있다 | **중복을 DB가 못 막는다** | 같은 쌍이 여러 번 정당하게 등장할 때(시각별 이력 등) |

현재 스키마는 C다. 그리고 그게 실제로 구멍이 된다 — 실측:

```sql
INSERT INTO order_detail (order_id, menu_id, quantity, unit_price) VALUES (1, 1, 1, 3500);
```
```text
-- 성공한다. 결과:
  (id=1,  order_id=1, menu_id=1, quantity=2, unit_price=3500)
  (id=21, order_id=1, menu_id=1, quantity=1, unit_price=3500)
-- 같은 주문서에 아메리카노가 2줄. 영수증에 아메리카노가 두 번 찍힌다.
```

집계로도 티가 안 난다. `SUM(quantity * unit_price)`는 어차피 맞게 나오기 때문에 **버그가 조용히 산다.** 이게 정규화 이야기의 마지막 조각이다 — 정규화는 테이블을 쪼개는 것으로 끝나지 않고, **쪼갠 뒤 남은 불변식을 제약으로 못 박는 것**까지가 한 세트다.

판단은 도메인이 한다. "한 주문서에 같은 메뉴는 한 줄, 수량으로만 표현한다"가 규칙이라면 B로 가야 한다.

```sql
CREATE UNIQUE INDEX uq_order_detail_order_menu ON order_detail(order_id, menu_id);
```

반대로 "아메리카노 2잔은 얼음 많이, 1잔은 보통"처럼 줄마다 옵션이 다를 수 있다면 C가 맞고, 그때는 `option` 컬럼이 추가되어 실질 키가 `(order_id, menu_id, option)`이 된다. **평가장에서는 "현재는 대리키만 있어서 중복을 못 막습니다. 도메인 규칙이 '한 주문 한 메뉴 한 줄'이면 `UNIQUE(order_id, menu_id)`를 걸어야 합니다"까지 스스로 말하는 것이 최고점이다.** 결함을 먼저 짚는 사람은 결함을 지적당하지 않는다.

### 9. 손으로 만들어 보는 N:M — 메뉴 옵션

읽어서 아는 것과 설계하는 것은 다르다. 요구사항 한 줄에서 시작한다.

> "메뉴마다 선택 가능한 옵션이 있다. 샷 추가는 아메리카노·카페라떼·바닐라라떼에 모두 붙고, 시럽 추가도 여러 메뉴에 붙는다. 옵션마다 추가 요금이 다르고, **같은 옵션이라도 메뉴에 따라 요금이 다를 수 있다.**"

마지막 문장이 핵심이다. 요금이 `option`에 속하지 않고 **`(menu, option)` 쌍에 속한다**는 뜻이고, 그래서 브릿지 테이블에 속성이 붙는다.

```sql
CREATE TABLE option (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE                  -- '샷 추가', '시럽 추가', '오트밀크'
);

CREATE TABLE menu_option (                      -- 브릿지: menu 1:N menu_option N:1 option
    menu_id     INTEGER NOT NULL,
    option_id   INTEGER NOT NULL,
    extra_price INTEGER NOT NULL CHECK (extra_price >= 0),   -- 관계의 속성
    PRIMARY KEY (menu_id, option_id),           -- 같은 메뉴에 같은 옵션은 한 번뿐
    FOREIGN KEY (menu_id)   REFERENCES menu(id)   ON DELETE CASCADE,
    FOREIGN KEY (option_id) REFERENCES option(id) ON DELETE RESTRICT
);
CREATE INDEX idx_menu_option_option_id ON menu_option(option_id);  -- 복합 PK의 좌측 접두사가 menu_id라
                                                                    -- option_id 단독 조회는 못 탄다
```

설계 판단 네 개를 말로 설명할 수 있어야 한다.

| 판단 | 이유 |
|---|---|
| 복합 PK를 쓴 이유 | 이 관계에 속성(`extra_price`)이 있지만 한 쌍은 한 번만 등장하므로 A안이 맞다. `order_detail`과 달리 이 쌍을 참조할 자식 테이블도 없다 |
| `extra_price`를 `option`이 아니라 `menu_option`에 둔 이유 | 요금이 `(menu, option)`에 함수 종속하기 때문. `option`에 두면 메뉴별 차등이 불가능하다 |
| menu에 CASCADE, option에 RESTRICT | 메뉴를 지우면 그 메뉴의 옵션 연결은 의미가 없다. 반대로 옵션 자체를 지우는 건 여러 메뉴에 영향을 주므로 막아야 한다 |
| `option_id`에 인덱스를 따로 만든 이유 | 복합 PK 인덱스는 `(menu_id, option_id)` 순이라 "샷 추가가 붙는 메뉴 전부" 조회는 못 탄다 |

다음 단계로, 주문 시 선택한 옵션까지 저장하려면 `order_detail_option(order_detail_id, option_id, extra_price)` 브릿지가 하나 더 필요하고 여기서도 `extra_price`를 **주문 시점 스냅샷으로 복사**해야 한다. `order_detail.unit_price`와 정확히 같은 논리이며, 이 대칭을 말할 수 있으면 역정규화 판단까지 설명이 이어진다.
