# CHECK·제약조건의 실제 동작

> 평가 피드백 3 대응 — CHECK가 언제 어떻게 검사되고, 그 에러가 애플리케이션까지 어떤 경로로 올라오는가.

---

## 0. 이 모듈이 답해야 하는 질문

평가자의 말은 "CHECK 문법을 외워라"가 아니다. `CHECK constraint failed` 라는 문자열이 **엔진 어디에서 만들어져서, 드라이버의 어떤 예외 객체로 바뀌고, 애플리케이션 코드에서 어떤 분기로 잡히는가** — 이 사슬을 끝까지 말할 수 있느냐를 물은 것이다. 사슬은 세 칸이다.

```text
[1] 엔진        INSERT 실행 중 제약 평가 → 위반 → 문장 롤백 + 에러코드 발생
[2] 드라이버    에러코드를 언어의 예외 클래스로 변환 (sqlite3.IntegrityError 등)
[3] 애플리케이션 예외를 잡아 "어떤 제약이 깨졌는지" 판별 → 사용자 메시지로 번역
```

아래 실측값은 전부 이 프로젝트의 `01_schema.sql` + `02_data.sql` 로 **새로 만든** DB에 Python 3.14.4 / SQLite 3.46.1 로 직접 돌린 결과다. 그 상태의 데이터는 customer 10명, category 10개(굿즈는 메뉴 0개 — 실측 확인), menu 12개, order_header 12건, order_detail 20행이다.

> **주의**: 리포지터리에 커밋되어 있는 `cafe.db` 는 이 상태가 아니다. `build_and_capture.py` 가 `03_queries.sql` 까지 끝낸 **최종 상태**이고, Q13(UPDATE)·Q14(DELETE)가 이미 적용되어 **order_header 10행 / order_detail 18행 / 아메리카노 4000원**이다. 커밋된 파일을 그대로 열어서 아래 수치를 대조하면 어긋난다. 재현하려면 `01_schema.sql` + `02_data.sql` 로 새 DB를 만들어야 한다.

---

## 1. 제약조건은 "언제" 검사되는가

기본값은 **문(statement) 단위 즉시 검사**다. `INSERT` 한 줄이 끝나기 전에 검사가 끝나고, 위반이면 그 문장만 통째로 취소된다(문 단위 원자성). COMMIT 까지 기다리지 않는다. 문장이 취소될 뿐 **트랜잭션 자체는 살아 있다** — 앞서 성공한 문장들은 그대로고, 이어서 다른 문장을 실행하거나 COMMIT 할 수 있다. (PostgreSQL 만 예외다. 트랜잭션 안에서 에러가 나면 그 트랜잭션은 `25P02 in_failed_sql_transaction` 상태가 되어 ROLLBACK 하거나 SAVEPOINT 로 되돌리기 전까지 어떤 문장도 받지 않는다. 이건 실무에서 자주 걸리는 차이다.)

예외가 **지연(DEFERRED) 제약**이다. 검사를 COMMIT 시점까지 미룬다.

| DBMS | FK 지연 | UNIQUE/PK 지연 | CHECK 지연 | NOT NULL 지연 |
|---|---|---|---|---|
| SQLite | 가능 — `DEFERRABLE INITIALLY DEFERRED` 또는 `PRAGMA defer_foreign_keys=1` | 불가 (아래 주의) | 불가 — 문법 자체가 거부됨 | 불가 |
| PostgreSQL | 가능 — `DEFERRABLE` 선언 후 `SET CONSTRAINTS ... DEFERRED` | 가능 (`DEFERRABLE` 선언 시) | 불가 | 불가 |
| MySQL 8 (InnoDB) | **불가** (지연 개념 자체가 없음) | 불가 | 불가 | 불가 |

**SQLite 의 UNIQUE 지연은 "문법이 통과하는 불가"라 더 위험하다.** 실측:

```text
CREATE TABLE t6 (a INTEGER UNIQUE DEFERRABLE INITIALLY DEFERRED);
→ 성공. sqlite_master 에도 DEFERRABLE INITIALLY DEFERRED 가 그대로 저장된다.

BEGIN;
INSERT INTO t6 VALUES (1);   -- 이미 1이 있는 상태
→ 그 자리에서 실패: UNIQUE constraint failed: t6.a | SQLITE_CONSTRAINT_UNIQUE
```

즉 파서는 받아주고 저장까지 하지만 **지연은 일어나지 않는다**. 반면 CHECK 에 같은 절을 붙이면 `near "DEFERRABLE": syntax error` 로 아예 거부된다. 문법이 통과했다고 동작한다고 믿으면 안 되는 사례가 여기서도 나온다.

MySQL 에는 `SET FOREIGN_KEY_CHECKS = 0` 이 있지만 이건 지연이 아니라 **세션 동안 검사를 아예 끄는** 스위치다. 끈 동안 들어온 고아 행은 다시 켜도 소급 검증되지 않는다. 덤프 복원용이지 애플리케이션 로직용이 아니다.

이 프로젝트 스키마의 FK 4개는 전부 지연 선언이 없으므로 **즉시 검사**다. 실측으로 대조하면 이렇다.

```text
[즉시(기본)] 부모 없는 자식 먼저 INSERT
  INSERT INTO oh_imm VALUES (1, 77)
  → 그 자리에서 실패: FOREIGN KEY constraint failed | SQLITE_CONSTRAINT_FOREIGNKEY

[DEFERRABLE INITIALLY DEFERRED] 같은 트랜잭션 안에서 자식 → 부모 순서
  BEGIN;
  INSERT INTO oh_def VALUES (1, 77);        → 통과 (아직 customer 77 이 없는데도)
  INSERT INTO cust   VALUES (77, ...);      → 부모를 뒤늦게 채움
  COMMIT;                                    → 성공

[DEFERRABLE 인데 부모를 끝내 안 만들면]
  BEGIN;
  INSERT INTO oh_def VALUES (2, 888);       → 통과
  COMMIT;                                    → 여기서 실패:
     sqlite3.IntegrityError: FOREIGN KEY constraint failed | SQLITE_CONSTRAINT_FOREIGNKEY
```

SQLite 에는 선언을 바꾸지 않고 쓰는 방법이 하나 더 있다. `PRAGMA defer_foreign_keys = 1` 을 켜면 **그 트랜잭션 동안만** 모든 FK 검사가 COMMIT 시점으로 밀린다. COMMIT 이 끝나거나 롤백되면 자동으로 0 으로 돌아간다. 스키마를 건드리지 않고 마이그레이션 한 번만 순서를 풀고 싶을 때 쓴다. (`foreign_keys=OFF` 와 달리 **검사를 없애지 않는다** — 미뤘다가 COMMIT 에서 반드시 확인한다.)

**왜 이게 실무에서 중요한가**: 지연 FK는 예외가 `INSERT` 줄이 아니라 `COMMIT` 줄에서 튀어나온다. try/except 를 INSERT 에만 걸어 두면 못 잡는다. 순환 참조가 있거나(A가 B를, B가 A를 참조) 배치 순서를 보장할 수 없을 때만 쓰고, 쓰기로 했으면 **COMMIT 을 try 블록 안에 넣어야 한다**.

`04_bonus.sql` 의 `(2-e)` 해결법 — 부모 customer 를 먼저 넣고 그 id 로 order_header 를 넣는 방식 — 은 지연을 쓰지 않고 **삽입 순서로** 즉시 검사를 만족시킨 것이다. 순서를 통제할 수 있으면 이쪽이 항상 낫다.

---

## 2. CHECK 가 실제로 하는 일

동작은 두 시점으로 쪼개진다.

| 시점 | 하는 일 |
|---|---|
| `CREATE TABLE` 실행 시 | 파서가 CHECK 안의 표현식을 파싱해 **스키마에 원문 그대로 저장**한다. 이때 값은 하나도 검사되지 않는다. |
| `INSERT` / `UPDATE` 실행 시 | 그 행의 새 값을 표현식에 대입해 **행 단위로 평가**한다. 결과가 거짓이면 거부한다. |

SQLite 에서는 저장된 원문을 그대로 볼 수 있다.

```sql
SELECT sql FROM sqlite_master WHERE name = 'order_header';
-- CHECK (status IN ('PENDING','COMPLETED','CANCELLED')) 가 문자열로 들어 있다
```

정확히는 SQLite 가 `sqlite_master.sql` 에 저장하는 것은 **CREATE 문 전체의 원문 텍스트**다. 실측하면 `01_schema.sql` 에 써 둔 한국어 주석까지 그대로 들어 있다. SQLite 는 이 문자열을 매번 다시 파싱해서 스키마를 복원한다 — 그래서 SQLite 에는 `ALTER TABLE ... ADD CONSTRAINT` 가 없고 테이블 재생성이 필요한 것이다.

핵심 두 가지.

- **행 단위**다. 테이블 전체나 다른 행을 보지 않는다. 그래서 "한 주문의 상세 라인 합계가 10만원 이하" 같은 규칙은 CHECK 로 못 쓴다. (SQL 표준에는 여러 행·여러 테이블에 걸친 조건을 표현하는 `CREATE ASSERTION` 이 있지만 SQLite·MySQL·PostgreSQL 어느 쪽도 구현하지 않았다. 표준에 있다고 쓸 수 있는 게 아니다.)
- **제약이 없던 동안 들어온 행은 소급 검사되지 않는다.** 여기서 흔히 과장되는 서술이 있으니 정확히 구분해야 한다.

  | 상황 | 기존 행이 검증되는가 |
  |---|---|
  | PostgreSQL `ALTER TABLE ... ADD CONSTRAINT ... CHECK (...)` | **검증된다.** 위반 행이 있으면 ALTER 자체가 실패한다 |
  | PostgreSQL 에 `NOT VALID` 를 붙인 경우 | 건너뛴다. 나중에 `VALIDATE CONSTRAINT` 로 따로 검증 |
  | MySQL 8.0.16+ `ALTER TABLE ... ADD CHECK (...)` | **검증된다.** `NOT ENFORCED` 를 붙이면 건너뛴다 |
  | SQLite | `ADD CONSTRAINT` 자체가 없다. 테이블을 새로 만들어 `INSERT ... SELECT` 로 옮기는데, 이때는 검증된다 |
  | FK 를 끈 채(`foreign_keys=OFF`, `FOREIGN_KEY_CHECKS=0`) 넣은 행 | **검증되지 않는다.** 다시 켜도 소급 확인 안 함 |

  즉 "나중에 CHECK 를 걸어도 옛날 쓰레기 데이터는 그대로 남는다"는 무조건 참이 아니다. 참이 되는 경우는 **검사를 명시적으로 우회했을 때**(`NOT VALID` / `NOT ENFORCED` / FK 스위치 OFF) 와 **제약이 존재하지 않던 시기에 쓰인 행을 그 뒤로 한 번도 다시 쓰지 않은 경우**다. 그리고 이미 들어간 행은 UPDATE 로 건드리기 전까지 재평가되지 않는다.

### 2.1 결과가 NULL 이면 통과한다 — 3값 논리

이게 CHECK 의 가장 중요한 함정이고, 평가자가 "레이어단 동작"이라 부른 지점의 정중앙이다.

SQL 의 비교 연산은 참/거짓 두 값이 아니라 **참 / 거짓 / UNKNOWN 세 값**이다. NULL 이 끼면 결과는 UNKNOWN 이다.

```text
SELECT NULL >= 0      -> NULL
SELECT NULL IN (0,1)  -> NULL
SELECT 3500 >= 0      -> 1
SELECT NULL IS NULL   -> 1     ← IS NULL 만은 참/거짓을 낸다
```

그리고 CHECK 의 거부 조건은 "참이 아니면"이 아니라 **"거짓이면"**이다. UNKNOWN 은 거부 대상이 아니므로 **통과한다**. SQL 표준(ISO/IEC 9075)이 CHECK 를 "*not FALSE*" 로 정의하기 때문이고, SQLite·MySQL·PostgreSQL 이 모두 이 정의를 따른다. 실측:

```text
CREATE TABLE menu_nonull (id INTEGER PRIMARY KEY, name TEXT, price INTEGER CHECK (price >= 0));
INSERT INTO menu_nonull (name, price) VALUES ('유령커피', NULL);
→ 성공. 저장된 행: (1, '유령커피', None)
```

`CHECK (price >= 0)` 를 걸어 놨는데 가격이 NULL 인 메뉴가 태연히 들어간다. `CHECK (is_available IN (0,1))` 도 마찬가지로 NULL 을 통과시킨다.

**그래서 이 프로젝트 스키마가 옳다.**

```sql
price        INTEGER NOT NULL CHECK (price >= 0),
is_available INTEGER NOT NULL DEFAULT 1 CHECK (is_available IN (0, 1)),
quantity     INTEGER NOT NULL CHECK (quantity > 0),
unit_price   INTEGER NOT NULL CHECK (unit_price >= 0),
status       TEXT    NOT NULL DEFAULT 'PENDING'
             CHECK (status IN ('PENDING','COMPLETED','CANCELLED')),
```

`NOT NULL` 과 `CHECK` 는 **역할이 다른 두 제약이고, 둘 다 있어야 구멍이 없다**. NOT NULL 이 "값이 있는가"를 막고, CHECK 가 "그 값이 말이 되는가"를 막는다. NOT NULL 을 빼면 실측처럼 NULL 이 CHECK 를 우회한다.

굳이 하나로 합치고 싶다면 `CHECK (price IS NOT NULL AND price >= 0)` 처럼 NULL 검사를 표현식 안에 넣는 방법도 있다. 다만 이러면 위반 종류가 전부 `SQLITE_CONSTRAINT_CHECK` 하나로 뭉개져서 "빈 값"과 "이상한 값"을 애플리케이션에서 구분할 수 없다. 제약을 둘로 나눠 두는 편이 에러코드 분기까지 생각하면 낫다.

> 말로 설명할 때: **"CHECK 는 결과가 FALSE 일 때만 막는다. NULL 을 넣으면 비교 결과가 UNKNOWN 이 되고, UNKNOWN 은 FALSE 가 아니라서 통과한다. 그래서 price 에는 NOT NULL 과 CHECK 를 같이 걸었다."**

### 2.2 같은 3값 논리의 반대편 얼굴 — `NOT IN` 함정

CHECK 는 NULL 을 **통과**시켜서 문제였다. 같은 규칙이 `NOT IN` 에서는 정반대로 나타난다. **전부 탈락**시킨다.

```text
p = (1, 2, 3),  ch = (1, NULL)

SELECT id FROM p WHERE id NOT IN (SELECT pid FROM ch);
→ []            ← 한 행도 안 나온다

SELECT id FROM p WHERE NOT EXISTS (SELECT 1 FROM ch WHERE ch.pid = p.id);
→ [(2,), (3,)]  ← 의도한 답

SELECT id FROM p WHERE id IN (SELECT pid FROM ch);
→ [(1,)]        ← IN 은 멀쩡하다
```

이유는 전개해 보면 바로 보인다. `2 NOT IN (1, NULL)` 은 `2 <> 1 AND 2 <> NULL` 이고, 뒤쪽이 UNKNOWN 이므로 전체가 `TRUE AND UNKNOWN = UNKNOWN` 이다. WHERE 절은 CHECK 와 반대로 **"참일 때만" 행을 남기므로** UNKNOWN 은 탈락한다. 반대로 `IN` 은 `2 = 1 OR 2 = NULL` 인데 하나라도 TRUE 면 되므로 NULL 이 섞여도 문제가 없다.

정리하면 **같은 UNKNOWN 인데 CHECK 에서는 통과가 되고 WHERE 에서는 탈락이 된다**. 판정 기준이 CHECK 는 "FALSE 가 아니면 통과", WHERE 는 "TRUE 여야 통과"로 다르기 때문이다. 이 한 문장을 말할 수 있으면 3값 논리를 이해한 것이다.

실무 규칙은 두 개다. 부정 조건에는 `NOT EXISTS` 를 쓴다. `NOT IN` 을 꼭 써야 하면 서브쿼리에 `WHERE pid IS NOT NULL` 을 붙인다. `04_bonus.sql` (1-d) 의 마지막 주석이 이 이야기다.

### 2.3 CHECK 는 인덱스를 만들지 않는다 — UNIQUE 와의 구조적 차이

`UNIQUE` 와 `CHECK` 는 문법상 나란히 쓰이지만 저장 구조에서 하는 일이 전혀 다르다.

```text
PRAGMA index_list('customer')
→ [(0, 'sqlite_autoindex_customer_1', 1, 'u', 0)]

SELECT name FROM sqlite_master WHERE type='index'
→ sqlite_autoindex_customer_1  (customer.email)
   sqlite_autoindex_category_1 (category.name)
   sqlite_autoindex_menu_1     (menu.name)
```

UNIQUE 를 걸면 SQLite 가 자동으로 **B+트리 계열 인덱스**를 만든다. 유일성을 확인하려면 "이미 있는가"를 테이블 전체에서 찾아야 하고, 그걸 전수 스캔 없이 하려면 정렬된 자료구조가 필요하기 때문이다. 실측에서 CHECK 만 걸린 `price`·`status`·`quantity` 에는 인덱스가 하나도 만들어지지 않았다. CHECK 는 **그 행의 값만 표현식에 대입하면 끝**이라 다른 행을 찾아볼 일이 없기 때문이다.

여기서 갈리는 것이 비용의 성격이다. CHECK 는 행당 표현식 한 번 평가라 사실상 공짜에 가깝다. UNIQUE 는 쓰기마다 인덱스 탐색 + 인덱스 갱신이 붙는다. 그래서 "혹시 모르니 UNIQUE 를 많이 걸어 두자"는 CHECK 를 많이 거는 것과 비용이 다르다.

DBMS별 구현도 알아 두면 좋다. 세 엔진 다 인덱스는 **B+트리 계열**이지 B-트리가 아니다(실제 데이터/포인터가 리프에만 있고 리프끼리 연결되어 범위 스캔이 빠른 구조다).

- **SQLite**: 테이블 자체가 rowid 를 키로 한 B+트리다(`WITHOUT ROWID` 면 PK 가 키). UNIQUE 인덱스는 별도 B트리이며 리프에 rowid 를 담는다.
- **InnoDB(MySQL)**: PK 가 **클러스터드 인덱스**여서 행 데이터 전체가 PK B+트리 리프에 들어 있다. 세컨더리 인덱스의 리프에는 행 주소가 아니라 **PK 값**이 들어 있어서, 커버링이 아니면 세컨더리 → PK 트리로 한 번 더 타는 이중 조회가 일어난다.
- **PostgreSQL**: 클러스터드 인덱스가 없다. 행은 **힙(heap)** 에 순서 없이 쌓이고 모든 인덱스는 힙의 위치(ctid)를 가리키는 세컨더리 인덱스다. PK 도 예외가 아니다. 그래서 인덱스만으로 답이 나와도 가시성 확인을 위해 힙을 봐야 할 수 있고(그걸 줄이는 장치가 visibility map 과 index-only scan 이다), UPDATE 가 새 행 버전을 만드는 MVCC 구조와 맞물려 VACUUM 이 필요하다.

CHECK 는 이 어느 층에도 흔적을 남기지 않는다. 순수하게 "쓰기 경로에서 표현식 한 번" 이다.

---

## 3. DBMS별 CHECK 지원 — 조용히 무시되던 사고

| DBMS / 버전 | CHECK 실제 강제 |
|---|---|
| SQLite (3.x 전 구간) | 지원. 항상 강제된다. |
| PostgreSQL (전 버전) | 지원. 항상 강제된다. |
| MySQL 5.7 이하 | **파싱만 하고 조용히 무시**한다. 에러도 경고도 없다. |
| **MySQL 8.0.0 ~ 8.0.15** | **여전히 무시한다.** "8이면 된다"가 아니다. |
| MySQL 8.0.16 이상 | 실제로 강제한다. errno 3819 (`ER_CHECK_CONSTRAINT_VIOLATED`). |
| MariaDB 10.2.1 이상 | 강제한다. MySQL 과 별개 계보이므로 버전 숫자를 섞어 말하면 안 된다. |

**버전 경계를 정확히 외워야 한다. `8.0` 이 아니라 `8.0.16` 이다.** MySQL 8.0.0 부터 8.0.15 까지는 5.7 과 똑같이 무시했다. 8.0.16 (2019-04-25) 에서야 `ER_CHECK_CONSTRAINT_VIOLATED` 와 함께 실제 강제가 들어왔고, 이때 `NOT ENFORCED` 옵션과 `information_schema.CHECK_CONSTRAINTS` 뷰도 같이 생겼다. "MySQL 8 쓰니까 괜찮다"고 말하면 8.0.11 짜리 프로덕션에서 그대로 터진다.

MySQL 5.7 의 동작이 실무 사고의 단골이다. `CREATE TABLE` 이 정상 성공하고, `SHOW CREATE TABLE` 에도 CHECK 절이 그대로 보이는데, 값 검사는 전혀 안 한다. 개발자는 스키마 파일과 SHOW 결과만 보고 "제약이 걸려 있다"고 믿는다. 그 상태로 `status='DONE'` 이 몇 달 쌓이고, 나중에 MySQL 8 로 올린 뒤 상태별 집계 쿼리가 이상해지고 나서야 발견된다. 더 나쁜 건 그다음이다. 8.0.16+ 로 올린 뒤 `ALTER TABLE ... ADD CHECK` 를 다시 걸면 기존 행을 검증하므로 **ALTER 가 실패한다**. 마이그레이션 당일에 "왜 스키마가 안 올라가지"부터 시작해 몇 달 치 쓰레기 데이터를 손으로 치우게 된다.

**교훈은 문법이 아니라 검증 습관이다**: 제약을 선언했으면 **일부러 깨뜨려 보고 에러가 나는지 확인**해야 한다. `04_bonus.sql` 의 (2) 섹션이 정확히 그 작업이다. "선언했다"와 "강제된다"는 다른 문제다.

---

## 4. CHECK 로 쓸 수 없는 것

| 쓰려는 규칙 | CHECK 가능? | 실측 / 대안 |
|---|---|---|
| `price >= 0` — 같은 행 한 컬럼 | 가능 | 정상 동작. 위반 시 `CHECK constraint failed: price >= 0` |
| 같은 **한 테이블** 안의 두 컬럼 비교 (예: `CHECK (b >= a)`) | 가능 | 실측: `(a,b)=(5,1)` 삽입 시 `CHECK constraint failed: b >= a` |
| `order_detail.unit_price <= menu.price` — 다른 테이블의 컬럼 | **불가** | unit_price 는 order_detail, price 는 menu 다. CHECK 는 자기 행 밖을 못 본다 → 트리거 또는 애플리케이션 |
| `menu_id IN (SELECT id FROM menu)` — 다른 테이블 조회 | **불가** | `OperationalError: subqueries prohibited in CHECK constraints` → **FK 로 가야 한다** |
| `order_date >= DATE('now')` — 비결정 함수 | **불가 (SQLite)** | CREATE 는 성공하지만 INSERT 시점에 `OperationalError: non-deterministic use of date() in a CHECK constraint` (`sqlite_errorname='SQLITE_ERROR'`, IntegrityError 가 아니다) |
| "주문 상세 합계가 10만원 이하" — 여러 행 집계 | 불가 | 트리거 또는 애플리케이션 계층 |

원문 표에 있던 "`unit_price <= price` — 같은 행 두 컬럼 비교 — 가능" 은 틀린 분류다. 이 스키마에서 `unit_price` 는 `order_detail`, `price` 는 `menu` 로 **서로 다른 테이블**이라 CHECK 로 표현할 수 없다. 같은 행 두 컬럼 비교가 되려면 두 컬럼이 한 테이블 안에 있어야 한다.

비결정 함수가 금지되는 이유는 명확하다. CHECK 는 **쓰기 시점에 딱 한 번** 평가된다. `DATE('now')` 를 넣으면 오늘 통과한 행이 내일은 위반 상태가 되어 버린다. 그러면 `VACUUM`, 테이블 재구축, 덤프 복원 같은 재검증 상황에서 멀쩡하던 데이터가 갑자기 거부된다. 즉 **제약이 데이터의 불변식(invariant)을 표현하지 못하게 된다**.

**중요한 건 엔진이 이걸 얼마나 막아주느냐가 DBMS마다 다르다는 점이다.**

| 엔진 | 서브쿼리 | 비결정 함수 |
|---|---|---|
| SQLite 3.46 | 금지 (CREATE 시점 거부) | `date()`/`time()`/`datetime()`/`julianday()`/`strftime()`/`current_*` 계열은 INSERT 시점에 거부. **`random()` 은 막지 않는다** |
| PostgreSQL | 금지 (`cannot use subquery in check constraint`) | **막지 않는다.** `now()` 같은 volatile 함수를 그냥 받아준다. 문서가 "쓰지 말라"고만 경고하고, 실제로는 덤프 복원 때 터진다 |
| MySQL 8.0.16+ | 금지 | 금지. 비결정 함수·저장 함수·사용자 변수·저장 프로시저 파라미터 모두 거부 |

SQLite 의 `random()` 을 실측하면 원문에 적힌 "통과시킨다"가 아니다. 더 나쁘다.

```text
CREATE TABLE t3 (a INTEGER CHECK (a > RANDOM()));   → 성공
INSERT INTO t3 VALUES (5) 를 200번 반복
→ 통과 85회 / 실패 115회  (CHECK constraint failed: a > RANDOM())
```

같은 값을 넣는데 될 때도 있고 안 될 때도 있다. "조용히 통과한다"가 아니라 **결과가 재현되지 않는다**가 실제 증상이다. 엔진이 전부 막아주지 않으므로 "CHECK 안에는 결정적(deterministic) 표현식만 쓴다"는 규칙을 사람이 지켜야 한다.

이 스키마에서 `menu.category_id` 를 CHECK 가 아니라 `FOREIGN KEY (category_id) REFERENCES category(id)` 로 쓴 이유가 바로 이것이다. **다른 테이블을 봐야 하는 규칙은 구조상 CHECK 의 사정거리 밖이라 FK 나 트리거로 갈 수밖에 없다.**

---

## 5. 에러가 애플리케이션까지 올라오는 경로

### 5.1 5가지 위반 실측 (Python 3.14.4 / SQLite 3.46.1)

`04_bonus.sql` 의 네 문장 + PK 위반 한 건을 그대로 Python 에서 돌린 결과다.

| 위반 | 실행 SQL | 예외 클래스 | `sqlite_errorname` | `sqlite_errorcode` | 메시지 |
|---|---|---|---|---|---|
| FK | `INSERT INTO order_header (customer_id,status) VALUES (999,'PENDING')` | `sqlite3.IntegrityError` | `SQLITE_CONSTRAINT_FOREIGNKEY` | 787 | `FOREIGN KEY constraint failed` |
| UNIQUE | `INSERT INTO customer (name,email) VALUES ('중복이','minjun@example.com')` | `sqlite3.IntegrityError` | `SQLITE_CONSTRAINT_UNIQUE` | 2067 | `UNIQUE constraint failed: customer.email` |
| CHECK | `INSERT INTO order_header (customer_id,status) VALUES (1,'DONE')` | `sqlite3.IntegrityError` | `SQLITE_CONSTRAINT_CHECK` | 275 | `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')` |
| NOT NULL | `INSERT INTO customer (name,email) VALUES ('이메일없음',NULL)` | `sqlite3.IntegrityError` | `SQLITE_CONSTRAINT_NOTNULL` | 1299 | `NOT NULL constraint failed: customer.email` |
| PK | `INSERT INTO customer (id,name,email) VALUES (1,'x','x@x.com')` | `sqlite3.IntegrityError` | `SQLITE_CONSTRAINT_PRIMARYKEY` | 1555 | `UNIQUE constraint failed: customer.id` |

두 가지를 눈여겨봐야 한다.

첫째, 예외 클래스는 **다섯 개 다 똑같이 `IntegrityError`** 다. 구분은 오직 확장 에러코드로만 된다. 상속 계통은 실측으로 `IntegrityError → DatabaseError → Error → Exception → BaseException` 이다.

둘째, **PK 행이 코드와 문자열이 서로 다른 이름을 말한다.** 코드는 `SQLITE_CONSTRAINT_PRIMARYKEY`(1555)인데 메시지는 `UNIQUE constraint failed` 로 시작한다. 문자열을 파싱하면 안 되는 이유를 이 한 줄이 다 보여준다.

FK 위반 메시지에는 **어느 FK 인지, 어느 컬럼인지 정보가 아예 없다.** 그냥 `FOREIGN KEY constraint failed` 다. order_detail 처럼 FK 가 두 개인 테이블에서는 order_id 가 문제인지 menu_id 가 문제인지 메시지로는 알 수 없다. 이건 SQLite 의 한계이고, PostgreSQL 이라면 `e.diag.constraint_name` 으로 바로 나온다.

확장 에러코드의 정체도 알아 두면 좋다. 기본 코드 `SQLITE_CONSTRAINT = 19` 의 상위 바이트에 세부 종류를 얹은 값이다.

```text
275  = 19 | (1 << 8)   CHECK
787  = 19 | (3 << 8)   FOREIGNKEY
1299 = 19 | (5 << 8)   NOTNULL
1555 = 19 | (6 << 8)   PRIMARYKEY
2067 = 19 | (8 << 8)   UNIQUE
→ 하위 8비트는 전부 19. 즉 "code & 0xFF == 19" 면 제약 위반 계열이다.
```

`SQLITE_ERROR = 1` 계열과 헷갈리면 안 된다. 4절에서 본 `non-deterministic use of date()` 는 코드 1(`SQLITE_ERROR`)이고 예외 클래스도 `IntegrityError` 가 아니라 `OperationalError` 다. **제약을 어긴 게 아니라 스키마가 잘못된 것**이므로 분류가 다르다.

### 5.2 드라이버 매핑 표

| 위반 | Python `sqlite3` | PostgreSQL / psycopg3 | MySQL 8.0.16+ / Connector |
|---|---|---|---|
| CHECK | `IntegrityError` + `sqlite_errorname='SQLITE_CONSTRAINT_CHECK'` (275) | SQLSTATE **23514** → `psycopg.errors.CheckViolation` | errno **3819** (`ER_CHECK_CONSTRAINT_VIOLATED`), SQLSTATE `HY000` |
| FK | `IntegrityError` + `..._FOREIGNKEY` (787) | SQLSTATE **23503** → `ForeignKeyViolation` | errno **1452** (자식 INSERT/UPDATE) / **1451** (부모 DELETE), SQLSTATE `23000` |
| UNIQUE | `IntegrityError` + `..._UNIQUE` (2067) | SQLSTATE **23505** → `UniqueViolation` | errno **1062** (`ER_DUP_ENTRY`), SQLSTATE `23000` |
| PK | `IntegrityError` + `..._PRIMARYKEY` (1555) | 23505 (PK 도 unique_violation 이다) | errno **1062** (UNIQUE 와 동일) |
| NOT NULL | `IntegrityError` + `..._NOTNULL` (1299) | SQLSTATE **23502** → `NotNullViolation` | errno **1048** (`ER_BAD_NULL_ERROR`), SQLSTATE `23000` |

읽는 법이 DBMS마다 다르다.

- **PostgreSQL 이 가장 친절하다.** SQLSTATE 가 표준 5자리이고, psycopg3 는 그걸 **전용 예외 클래스**로 매핑해 준다. `except psycopg.errors.UniqueViolation:` 로 바로 분기할 수 있고, `e.diag` 로 어느 제약인지까지 구조화되어 온다. (psycopg2 도 2.8+ 에서 `psycopg2.errors` 로 같은 클래스를 제공하고, `e.pgcode` 로 SQLSTATE 를 읽는다. psycopg3 는 `e.sqlstate` 다.)
- **단, `e.diag` 가 항상 다 채워지는 건 아니다.** 이건 원문이 틀렸던 부분이다. PostgreSQL 서버가 어떤 필드를 보내는지는 에러 종류마다 다르다.

  | 위반 | `constraint_name` | `table_name` | `column_name` |
  |---|---|---|---|
  | NOT NULL (23502) | (없음) | 있음 | **있음** |
  | UNIQUE / PK (23505) | 있음 | 있음 | **없음 (None)** |
  | CHECK (23514) | 있음 | 있음 | **없음 (None)** |
  | FK (23503) | 있음 | 있음 | **없음 (None)** |

  즉 UNIQUE 위반에서 `e.diag.column_name` 을 읽으면 `None` 이다. 컬럼을 알고 싶으면 **`constraint_name` 을 읽고, 제약 이름 → 필드 매핑 테이블을 애플리케이션이 들고 있어야 한다**. 그래서 PostgreSQL 을 쓸 때는 제약에 이름을 반드시 명시적으로 붙인다(`CONSTRAINT uq_customer_email UNIQUE (email)`). 이름을 안 붙이면 `customer_email_key` 같은 자동 생성 이름이 오는데, 컬럼 목록이 바뀌면 이름도 같이 바뀌어서 분기가 깨진다.
- **MySQL 은 SQLSTATE 로 구분이 안 된다.** FK·UNIQUE·NOT NULL 이 전부 `23000` 이고 CHECK 만 엉뚱하게 `HY000` 이다. 반드시 `e.errno` 로 분기해야 한다.
- **Python sqlite3 는 예외 클래스가 하나뿐이다.** 대신 **Python 3.11 부터 `sqlite_errorcode` / `sqlite_errorname` 속성이 추가**됐다. 3.10 이하를 지원해야 하면 이 속성이 없으므로 `getattr(e, 'sqlite_errorname', None)` 로 방어해야 한다.

### 5.3 왜 메시지 문자열을 파싱하면 안 되는가

가장 흔한 안티패턴이 이것이다.

```python
except sqlite3.IntegrityError as e:
    if "UNIQUE" in str(e):        # 하면 안 된다
        ...
```

깨지는 이유가 최소 여섯 가지다.

1. **제약에 이름을 붙이면 메시지가 통째로 바뀐다.** 실측으로 확인했다.
   ```text
   이름 없는 CHECK : CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')
   이름 붙인 CHECK : CHECK constraint failed: ck_order_status
   ```
   `CONSTRAINT ck_order_status CHECK (...)` 라고 이름 하나 붙였을 뿐인데 `'PENDING' in str(e)` 로 짜 둔 분기가 전부 죽는다. 에러코드는 둘 다 275 로 동일하다.
2. **같은 코드가 다른 이름의 문자열을 낸다.** 5.1 의 PK 행이 그렇다. 코드는 `SQLITE_CONSTRAINT_PRIMARYKEY`(1555)인데 문자열은 `UNIQUE constraint failed: customer.id` 다. `"PRIMARY" in str(e)` 로 짜면 절대 안 잡힌다.
3. **엔진 버전에 따라 문구가 바뀐다.** SQLite 의 CHECK 위반 메시지는 버전에 따라 `constraint failed` → `CHECK constraint failed: <테이블명>` → (3.46 실측) `CHECK constraint failed: <표현식 또는 제약 이름>` 으로 바뀌어 왔다. 라이브러리 업그레이드가 곧 프로덕션 장애가 된다.
4. **로케일에 따라 번역된다.** MySQL 은 `lc_messages` 로 서버 메시지 언어를 바꿀 수 있어 같은 errno 1062 가 다른 문장으로 나올 수 있다.
5. **DBMS 를 바꾸면 전부 다시 짜야 한다.** SQLite `UNIQUE constraint failed: customer.email` 과 MySQL `Duplicate entry 'minjun@example.com' for key 'customer.email'` 은 공통 부분이 없다.
6. **오탐이 난다.** 사용자가 입력한 이메일이 `"UNIQUE@example.com"` 이면 MySQL 메시지 안에 값이 그대로 들어가서 `"UNIQUE" in str(e)` 가 참이 된다.

**규칙: 분기는 에러코드/SQLSTATE 로, 메시지 문자열은 로그에만 남긴다.**

### 5.4 실제로 돌아가는 처리 코드

아래는 이 프로젝트 DB(01+02 로 새로 만든 상태)로 직접 실행해 결과까지 확인한 코드다.

```python
import sqlite3

# 제약 종류 → 사용자용 메시지. 도메인 지식은 여기 한 군데에만 둔다.
MESSAGES = {
    "SQLITE_CONSTRAINT_FOREIGNKEY": "존재하지 않는 고객이나 메뉴를 지정했다.",
    "SQLITE_CONSTRAINT_UNIQUE":     "이미 가입된 이메일이다.",
    "SQLITE_CONSTRAINT_PRIMARYKEY": "이미 존재하는 식별자다.",
    "SQLITE_CONSTRAINT_CHECK":      "허용되지 않는 값이다. 주문 상태는 PENDING/COMPLETED/CANCELLED 중 하나여야 한다.",
    "SQLITE_CONSTRAINT_NOTNULL":    "필수 항목이 비어 있다.",
}

def create_order(con, customer_id, status):
    try:
        cur = con.execute(
            "INSERT INTO order_header (customer_id, status) VALUES (?, ?)",
            (customer_id, status),
        )
        con.commit()
        return {"ok": True, "order_id": cur.lastrowid}
    except sqlite3.IntegrityError as e:
        con.rollback()
        # 문자열이 아니라 에러코드로 분기한다. 3.10 이하 대비로 getattr 방어.
        kind = getattr(e, "sqlite_errorname", "SQLITE_CONSTRAINT")
        return {
            "ok": False,
            "kind": kind,
            "message": MESSAGES.get(kind, "데이터 정합성 오류"),
            "raw": str(e),          # 로그용. 사용자에게 노출하지 않는다.
        }
```

실행 결과:

```text
(1,   'PENDING') -> {'ok': True, 'order_id': 13}
(999, 'PENDING') -> {'ok': False, 'kind': 'SQLITE_CONSTRAINT_FOREIGNKEY',
                     'message': '존재하지 않는 고객이나 메뉴를 지정했다.',
                     'raw': 'FOREIGN KEY constraint failed'}
(1,   'DONE')    -> {'ok': False, 'kind': 'SQLITE_CONSTRAINT_CHECK',
                     'message': '허용되지 않는 값이다. 주문 상태는 PENDING/COMPLETED/CANCELLED 중 하나여야 한다.',
                     'raw': "CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')"}
```

`IntegrityError` 만 잡고 `OperationalError` 는 안 잡는 것도 의도적이다. 4절에서 본 비결정 함수 오류나 문법 오류는 **데이터 문제가 아니라 코드/스키마 버그**라서 사용자 메시지로 번역하면 안 되고 그대로 터뜨려 로그에 남겨야 한다.

`customer` 는 UNIQUE 컬럼이 email 하나뿐이라(실측: `sqlite_autoindex_customer_1` 하나) 종류만 알면 필드까지 특정된다. 하지만 UNIQUE 컬럼이 둘 이상인 테이블이라면 **어느 컬럼인지**를 알아야 하고, 여기서 DBMS 차이가 갈린다.

```python
# PostgreSQL — 드라이버가 구조화해서 준다.
import psycopg

CONSTRAINT_FIELD = {          # 제약 이름 → 폼 필드. 제약에 이름을 붙여 놨기 때문에 가능하다.
    "uq_customer_email": "email",
    "ck_order_status":   "status",
}

try:
    ...
except psycopg.errors.UniqueViolation as e:
    # 주의: UNIQUE 위반에는 e.diag.column_name 이 채워지지 않는다(None).
    field = CONSTRAINT_FIELD.get(e.diag.constraint_name)
except psycopg.errors.NotNullViolation as e:
    field = e.diag.column_name            # NOT NULL 위반에서만 column_name 이 온다
except psycopg.errors.ForeignKeyViolation as e:
    field = CONSTRAINT_FIELD.get(e.diag.constraint_name)

# MySQL — SQLSTATE 가 죄다 23000 이라(CHECK 만 HY000) errno 로 갈라야 한다.
import mysql.connector
try:
    ...
except mysql.connector.IntegrityError as e:
    kind = {1062: "UNIQUE", 1452: "FK", 1451: "FK_PARENT", 1048: "NOT_NULL", 3819: "CHECK"}.get(e.errno)
```

sqlite3 에서 컬럼까지 알아야 한다면 메시지 파싱이 불가피하다. 그럴 때도 **종류 판별은 에러코드로 하고, 파싱은 컬럼명 추출에만 최소한으로 쓴다**.

```python
kind = getattr(e, "sqlite_errorname", "")
field = None
if kind in ("SQLITE_CONSTRAINT_UNIQUE", "SQLITE_CONSTRAINT_NOTNULL", "SQLITE_CONSTRAINT_PRIMARYKEY"):
    field = str(e).rsplit(":", 1)[-1].strip()   # 'customer.email'
```

실행 결과:

```text
('중복이', 'minjun@example.com') -> kind=SQLITE_CONSTRAINT_UNIQUE  field='customer.email'
('빈메일',  None)                -> kind=SQLITE_CONSTRAINT_NOTNULL field='customer.email'
```

이 파싱조차 복합 UNIQUE 에서는 `customer.a, customer.b` 처럼 여러 컬럼이 콤마로 오므로 그대로 쓰면 안 된다. 결국 sqlite3 는 "종류까지는 안전하게, 컬럼은 best-effort" 가 한계다.

---

## 6. 왜 애플리케이션 검증만으로는 부족한가

가장 강력한 반례가 **SELECT-후-INSERT 경쟁 조건**이다. 이메일 중복을 애플리케이션에서 미리 확인하는 코드는 이렇게 생긴다.

```python
if con.execute("SELECT COUNT(*) FROM customer WHERE email=?", (email,)).fetchone()[0] == 0:
    con.execute("INSERT INTO customer (name, email) VALUES (?, ?)", (name, email))
```

두 요청이 겹치면 이 사이에 틈이 생긴다. 두 개의 별도 연결로 실측:

```text
연결 A 가 본 개수: 0   → '가입 가능' 판정
연결 B 가 본 개수: 0   → '가입 가능' 판정   ← 둘 다 통과
A INSERT → 성공
B INSERT → IntegrityError: UNIQUE constraint failed: customer.email  ← DB 가 막았다
최종 customer: [(1, 'A', 'race@example.com')]     중복 없음
```

UNIQUE 제약을 뺀 테이블로 같은 시나리오를 돌리면 같은 이메일 두 행이 그냥 들어간다. **애플리케이션의 확인은 시점(point-in-time) 판단이고, DB 제약은 쓰기 순간의 판단이다.** 틈을 없앨 수 있는 건 후자뿐이다.

격리 수준을 올리면 되지 않느냐는 질문이 여기서 나온다. 답은 "그것도 제약이 아니라 잠금으로 푸는 것"이다. SERIALIZABLE 로 올리면 막히지만 처리량이 떨어지고, PostgreSQL 의 SERIALIZABLE 은 대신 직렬화 실패(40001)를 던져서 **애플리케이션이 재시도 루프를 갖고 있어야 한다**. UNIQUE 제약 하나면 격리 수준과 무관하게 항상 막힌다.

애플리케이션 검증이 무력해지는 경로는 이것 말고도 많다.

| 우회 경로 | 애플리케이션 검증 | DB 제약 |
|---|---|---|
| 동시 요청 2건 (위 실측) | 뚫림 | 막음 |
| 다른 언어로 짠 두 번째 서비스 | 검증 로직이 없음 | 막음 |
| 야간 배치 스크립트 / 데이터 마이그레이션 | 보통 우회함 | 막음 |
| 운영자가 DBeaver 로 직접 친 UPDATE | 아예 안 거침 | 막음 |
| 애플리케이션 코드의 버그 | 그 버그가 곧 구멍 | 막음 |

그래서 DB 제약은 **최후의 방어선(last line of defense)** 이다. "제약을 걸었으니 애플리케이션 검증은 필요 없다"도 틀리다. DB 제약만으로 부족한 이유가 대칭적으로 존재한다.

- **메시지가 사용자용이 아니다.** `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')` 를 그대로 화면에 띄우면 안 된다. 스키마 구조가 노출되는 정보 누출이기도 하다.
- **한 문장은 첫 위반에서 멈춘다.** 실측: `INSERT INTO customer (name,email) VALUES (NULL, 'minjun@example.com')` 는 name 의 NOT NULL 위반과 email 의 UNIQUE 위반이 둘 다 있는데, 보고되는 건 `NOT NULL constraint failed: customer.name` 하나뿐이다. 회원가입 폼에서 "이름을 입력하세요"만 보여주고, 고쳐서 다시 제출하면 그제야 "이미 가입된 이메일입니다"가 뜬다. **폼 단위로 여러 오류를 한꺼번에 모아 보여주려면 애플리케이션 검증이 필요하다.**
- **표현력이 부족하다.** 4절에서 본 대로 여러 행/여러 테이블에 걸친 규칙은 CHECK 로 못 쓴다.
- **비용.** 왕복 한 번을 아낄 수 있는 명백한 오류는 앞에서 거르는 게 낫다.

**결론: 이중 방어.** 애플리케이션 검증은 UX 를 위해, DB 제약은 정합성을 위해. 그리고 **애플리케이션 검증을 통과했더라도 `IntegrityError` 는 반드시 잡는다.** 경쟁 조건은 반드시 남기 때문이다.

---

## 7. `PRAGMA foreign_keys = ON` 은 연결마다 꺼진다

이 스키마의 가장 실무적인 함정이다. `PRAGMA foreign_keys` 는 **데이터베이스 파일이 아니라 연결(connection)의 속성**이고, 하위호환 때문에 기본값이 **OFF** 다. 실측:

```text
새 연결의 기본 foreign_keys 값: 0        ← OFF
01_schema.sql 실행 후:          1        ← 파일 안의 PRAGMA 가 켠 것
그 연결을 닫고 다시 연 새 연결: 0        ← 다시 OFF
```

즉 `01_schema.sql` 이 PRAGMA 를 켜 놓아도 그건 **그 스크립트를 실행한 연결에만** 적용된다. 다음 날 DBeaver 로 새로 열거나, 웹 서버가 커넥션 풀에서 새 연결을 꺼내면 다시 OFF 다. FK 는 스키마에 멀쩡히 선언되어 있고 `.schema` 에도 보이는데 검사만 안 된다.

FK 가 꺼진 상태에서 무슨 일이 벌어지는지 실측했다.

```text
PRAGMA foreign_keys = OFF;
INSERT INTO order_header (customer_id, status) VALUES (999, 'PENDING');
→ 성공. 저장된 행: id=13, customer_id=999   (customer 에 999번은 없다)

PRAGMA foreign_key_check;
→ [('order_header', 13, 'customer', 0)]
   = order_header 의 rowid 13 이 customer 를 가리키는 0번 FK 를 위반 중

같은 상태에서 CHECK 는?
INSERT INTO order_header (customer_id, status) VALUES (1, 'DONE');
→ 여전히 실패: CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')
```

두 가지가 드러난다. **(1) PRAGMA 는 FK 만 끈다.** CHECK / NOT NULL / UNIQUE 는 영향받지 않고 계속 강제된다. **(2) 한번 들어간 고아 행은 나중에 PRAGMA 를 켜도 소급 검증되지 않는다.** 켠 이후의 쓰기만 검사된다. 그래서 `PRAGMA foreign_key_check` 라는 별도 진단 명령이 존재한다. (반환 튜플은 `(자식 테이블, rowid, 부모 테이블, FK 인덱스 번호)` 다. `PRAGMA foreign_key_list('order_header')` 로 그 번호가 어느 컬럼인지 확인할 수 있다.)

사고 시나리오는 이렇게 흘러간다. 개발자는 CLI 스크립트로 테스트해서 FK 가 잘 막히는 걸 확인한다. 그런데 웹 애플리케이션은 ORM 커넥션 풀을 쓰고, 거기엔 PRAGMA 를 켜는 코드가 없다. 운영 중 고아 `order_header` 가 조용히 쌓인다. 나중에 매출 집계 JOIN 이 고아 행을 떨어뜨려 숫자가 안 맞고, 그제야 원인을 찾는다.

**해결: 연결이 만들어질 때마다 자동으로 켠다.** SQLAlchemy 는 `connect` 이벤트를 쓴다.

```python
from sqlalchemy import event
from sqlalchemy.engine import Engine

@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    # 풀에서 새 연결이 만들어질 때마다 호출된다. 풀 재사용 시점이 아니라 '생성' 시점이다.
    import sqlite3
    if isinstance(dbapi_connection, sqlite3.Connection):   # 다른 DB 엔진과 섞여도 안전하게
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()
```

한 가지 더: **`PRAGMA foreign_keys` 는 트랜잭션 안에서 실행하면 조용히 무시된다(no-op)**. 실측:

```text
PRAGMA foreign_keys = OFF;
BEGIN;
  PRAGMA foreign_keys = ON;
  PRAGMA foreign_keys;   → 0     ← 켜지지 않았다. 에러도 없다
ROLLBACK;
PRAGMA foreign_keys;     → 0
```

에러가 안 나므로 "켰다"고 착각하기 딱 좋다. 반드시 트랜잭션 밖, 연결 직후에 실행해야 한다. Python `sqlite3` 는 기본 `isolation_level` 설정에서 DML 앞에 암묵적으로 BEGIN 을 넣으므로, 연결하자마자 첫 문장으로 실행하는 게 안전하다. Django 는 SQLite 백엔드에서 이걸 프레임워크가 알아서 켜 준다.

MySQL 과 PostgreSQL 에는 **"연결마다 기본 OFF"라는 이 함정이 없다.** 기본값이 켜져 있다. 다만 "항상 켜져 있어서 절대 못 끈다"는 건 아니다.

- MySQL: `SET FOREIGN_KEY_CHECKS = 0` (세션 단위). 1절에서 본 그 스위치다.
- PostgreSQL: `SET session_replication_role = 'replica'` 로 FK 트리거를 포함한 트리거를 건너뛰거나, `ALTER TABLE ... ADD FOREIGN KEY ... NOT VALID` 로 기존 행 검증만 생략할 수 있다.

차이는 **기본값과 의도**다. SQLite 는 아무것도 안 하면 꺼져 있고, 나머지 둘은 아무것도 안 하면 켜져 있으며 끄려면 일부러 문장을 하나 써야 한다. 이것도 "DBMS 특성을 알고 쓴다"의 한 사례다.

---

## 8. 제약 위반을 미리 피하는 UPSERT / 멱등 패턴

예외 처리로 잡는 것과 별개로, **"이미 있으면 그냥 넘어가라"** 같은 의도는 애초에 예외를 안 내는 문법으로 표현하는 게 낫다. 배치 재실행(멱등성)에서 특히 그렇다.

```sql
-- SQLite 3.24.0+ / PostgreSQL 9.5+ : UPSERT
-- (SQL 표준 문법은 아니다. 표준의 대응물은 MERGE 이고, SQLite 의 ON CONFLICT 는
--  PostgreSQL 문법을 그대로 차용한 것이다. MySQL 은 아예 다른 문법을 쓴다.)

-- ① 이미 있으면 아무것도 안 한다
INSERT INTO customer (name, email)
VALUES ('중복이', 'minjun@example.com')
ON CONFLICT(email) DO NOTHING;

-- ② 이미 있으면 전화번호만 갱신한다. excluded 는 '넣으려다 충돌한 그 행'을 가리킨다.
INSERT INTO customer (name, email, phone)
VALUES ('김민준', 'minjun@example.com', '010-0000-1111')
ON CONFLICT(email) DO UPDATE SET phone = excluded.phone;
```

실측 결과:

```text
① rowcount: 0,  customer 행수 10 → 10   (에러 없음, 삽입도 없음)
② before: (1, '김민준', '010-1000-0001')
   after : (1, '김민준', '010-0000-1111')
```

```sql
-- MySQL 8 : 문법이 다르다. 충돌 대상 컬럼을 명시하지 않고 '어떤 UNIQUE든' 걸리면 발동한다.
INSERT INTO customer (name, email, phone)
VALUES ('김민준', 'minjun@example.com', '010-0000-1111')
ON DUPLICATE KEY UPDATE phone = VALUES(phone);

-- MySQL 8.0.19 에서 행 별칭 문법이 도입됐고, 8.0.20 에서 VALUES() 가 deprecated 됐다.
-- 8.0.19+ 를 쓴다면 별칭 쪽으로 쓰는 게 맞다:
INSERT INTO customer (name, email, phone)
VALUES ('김민준', 'minjun@example.com', '010-0000-1111') AS new
ON DUPLICATE KEY UPDATE phone = new.phone;
```

| 구분 | SQLite / PostgreSQL | MySQL 8 |
|---|---|---|
| 문법 | `ON CONFLICT(col) DO NOTHING / DO UPDATE` | `ON DUPLICATE KEY UPDATE` |
| 충돌 대상 지정 | **가능** — `ON CONFLICT(email)` 로 특정 제약만 | 불가 — 모든 UNIQUE/PK 가 대상 |
| 새 값 참조 | `excluded.phone` | `VALUES(phone)`(≤8.0.19) 또는 `new.phone`(8.0.19+) |
| 표준 여부 | 표준 아님(PostgreSQL 확장) | 표준 아님(MySQL 확장) |

MySQL 쪽이 위험한 이유는 "충돌 대상 지정 불가" 때문이다. email 중복을 처리하려고 썼는데 실제로는 phone 에 걸린 다른 UNIQUE 가 발동해서 엉뚱한 행이 갱신될 수 있다. SQLite/PostgreSQL 에서도 `ON CONFLICT` 를 대상 없이 쓰면 같은 문제가 생기므로 **항상 `ON CONFLICT(컬럼)` 으로 대상을 명시한다**.

**주의점 두 개.** 실측으로 확인했다.

1. **`ON CONFLICT` 는 UNIQUE/PK 충돌만 처리한다.** CHECK 위반에는 아무 효과가 없다.
   ```text
   INSERT INTO order_header (customer_id,status) VALUES (1,'DONE') ON CONFLICT DO NOTHING;
   → 여전히 실패: CHECK constraint failed: status IN (...) | SQLITE_CONSTRAINT_CHECK
   ```
   당연하다. `ON CONFLICT` 는 "충돌하는 기존 행"을 전제로 하는데, CHECK 위반에는 충돌 상대가 없다. FK 위반도 마찬가지로 처리되지 않는다.
2. **`INSERT OR IGNORE` 는 쓰면 안 된다.** SQLite 의 이 구문은 UNIQUE/PK 뿐 아니라 **CHECK 와 NOT NULL 위반까지 조용히 삼킨다**.
   ```text
   INSERT OR IGNORE INTO order_header (customer_id,status) VALUES (1,'DONE');
   → 에러 없음. order_header 행수 12 → 12. rowcount: 0

   INSERT OR IGNORE INTO customer (name,email) VALUES ('x', NULL);
   → 에러 없음. rowcount: 0
   ```
   `'DONE'` 이라는 잘못된 상태값을 넣으려던 심각한 버그가 **아무 흔적 없이 사라진다**. 프로그램은 정상 종료되고 데이터만 안 들어간다.

   단, **FK 위반만은 삼키지 않는다.** 실측:
   ```text
   INSERT OR IGNORE INTO order_header (customer_id,status) VALUES (999,'PENDING');
   → IntegrityError: FOREIGN KEY constraint failed | SQLITE_CONSTRAINT_FOREIGNKEY
   ```
   즉 `OR IGNORE` 는 **네 종류 중 셋만 무음 처리하는 반쪽짜리**다. "OR IGNORE 를 붙였으니 이 INSERT 는 절대 안 터진다"고 가정한 코드가 FK 위반에서 갑자기 예외를 던지므로 오히려 더 나쁘다.

   의도가 "중복이면 넘어가라"라면 반드시 `ON CONFLICT(email) DO NOTHING` 처럼 **대상 제약을 명시**해야 한다.

---

## 9. 말로 설명하는 스크립트

주석 지운 스키마를 보면서 평가자가 `CHECK (status IN (...))` 를 짚고 "이거 어떻게 동작합니까?"라고 물었을 때, 이렇게 이어서 말한다.

> **"CREATE TABLE 을 실행할 때 파서가 이 표현식을 파싱해서 스키마에 원문 그대로 저장합니다. 이 시점엔 아무 값도 검사하지 않습니다. 실제 평가는 INSERT 나 UPDATE 때 행 단위로 일어납니다. 새로 들어오는 status 값을 이 표현식에 대입해서, 결과가 FALSE 면 그 문장 전체를 롤백합니다. 문장만 롤백되고 트랜잭션은 살아 있습니다."**

> **"여기서 중요한 게 3값 논리입니다. 거부 조건은 '참이 아니면'이 아니라 '거짓이면'입니다. status 에 NULL 을 넣으면 `NULL IN (...)` 이 UNKNOWN 이 되는데, UNKNOWN 은 FALSE 가 아니라서 통과해 버립니다. 그래서 status 에는 NOT NULL 을 따로 걸었습니다. NOT NULL 은 '값이 있는가', CHECK 는 '그 값이 말이 되는가'로 역할이 다릅니다. 참고로 같은 UNKNOWN 이 WHERE 절에서는 반대로 동작해서, NOT IN 서브쿼리에 NULL 이 섞이면 결과가 통째로 비어 버립니다. WHERE 는 TRUE 만 통과시키기 때문입니다."**

> **"애플리케이션까지 올라오는 경로도 확인했습니다. `status='DONE'` 을 넣으면 SQLite 가 확장 에러코드 275, `SQLITE_CONSTRAINT_CHECK` 를 냅니다. Python sqlite3 는 이걸 `IntegrityError` 로 올려주는데, FK·UNIQUE·NOT NULL·PK 도 전부 같은 `IntegrityError` 라서 클래스만으로는 구분이 안 됩니다. Python 3.11 부터 붙은 `sqlite_errorname` 속성으로 분기해야 합니다. 메시지 문자열은 파싱하면 안 됩니다. 제약에 이름을 붙이면 메시지가 표현식에서 제약 이름으로 바뀌거든요. 코드는 그대로 275 인데 문자열만 달라집니다. PK 위반은 더 심해서, 코드는 PRIMARYKEY 인데 메시지는 'UNIQUE constraint failed' 로 나옵니다."**

> **"PostgreSQL 이면 SQLSTATE 23514 이고 psycopg3 가 `CheckViolation` 이라는 전용 클래스로 올려줍니다. 다만 diag 에서 컬럼명을 바로 얻을 수 있는 건 NOT NULL 위반뿐이고, UNIQUE·CHECK·FK 는 constraint_name 만 오기 때문에 제약에 이름을 붙여 두고 이름으로 매핑해야 합니다. MySQL 8 은 errno 3819 인데, MySQL 은 FK·UNIQUE·NOT NULL 이 SQLSTATE 가 전부 23000 이고 CHECK 만 HY000 이라 SQLSTATE 로는 구분이 안 되고 errno 로 갈라야 합니다. 그리고 MySQL 은 8.0.16 이전엔 CHECK 를 파싱만 하고 조용히 무시했습니다. 5.7 만 그런 게 아니라 8.0.0 부터 8.0.15 까지도 그랬습니다."**

FK 로 넘어가면 이어서 이렇게 말한다.

> **"참고로 이 스키마 맨 위의 `PRAGMA foreign_keys = ON` 은 연결 단위 설정이고 기본값이 OFF 입니다. 실제로 껐다 켜 보면, 끈 상태에서는 customer_id=999 짜리 order_header 가 그냥 들어가고, 나중에 다시 켜도 그 행은 소급 검증되지 않습니다. `PRAGMA foreign_key_check` 로 따로 찾아내야 합니다. 그리고 이 PRAGMA 는 트랜잭션 안에서 실행하면 에러 없이 무시되기 때문에 연결 직후에 켜야 합니다. 실무에서는 SQLAlchemy 의 connect 이벤트에서 연결마다 켜 줍니다. MySQL 과 PostgreSQL 은 기본이 켜져 있어서 이 함정이 없습니다 — 물론 FOREIGN_KEY_CHECKS 나 session_replication_role 로 일부러 끌 수는 있습니다."**

---

## 10. 한 장 요약

| 제약 | 검사 시점 | NULL 이면 | 다른 테이블 참조 | 지연 가능 (SQLite) | 인덱스 생성 |
|---|---|---|---|---|---|
| `NOT NULL` | 문 단위 즉시 | — (그게 검사 대상) | 불가 | 불가 | 안 함 |
| `CHECK` | 문 단위 즉시, 행 단위 평가 | **통과** (UNKNOWN) | 불가 (서브쿼리 금지) | 불가 (문법 자체가 거부됨) | 안 함 |
| `UNIQUE` | 문 단위 즉시 | NULL 은 서로 중복으로 안 봄 (SQLite·PostgreSQL·InnoDB 공통. SQL Server 는 다르다) | 불가 | 불가 — 다만 `DEFERRABLE` 을 붙이면 파서가 받고 조용히 무시 | **함 (B+트리)** |
| `FOREIGN KEY` | 기본 즉시 / DEFERRED 가능 | 자식이 NULL 이면 검사 안 함 | 그게 목적 | **가능** (선언 또는 `PRAGMA defer_foreign_keys`) | 자동 생성 안 함 (직접 걸어야 함) |

버전 경계 정리.

| 사실 | 경계 |
|---|---|
| MySQL 이 CHECK 를 실제로 강제 | **8.0.16** (8.0.0~8.0.15 는 무시) |
| MariaDB 가 CHECK 를 강제 | 10.2.1 |
| SQLite UPSERT (`ON CONFLICT`) | 3.24.0 |
| PostgreSQL UPSERT | 9.5 |
| MySQL `ON DUPLICATE KEY` 행 별칭 도입 / `VALUES()` deprecated | 8.0.19 / 8.0.20 |
| Python sqlite3 의 `sqlite_errorcode`·`sqlite_errorname` | Python 3.11 |
| psycopg2 의 `psycopg2.errors` 예외 클래스 | psycopg2 2.8 |

기억할 문장 네 개.

1. **CHECK 는 FALSE 만 막는다. NULL 은 통과한다. 그래서 NOT NULL 이 따로 필요하다.**
2. **같은 UNKNOWN 이 WHERE 에서는 탈락이 된다. 그래서 `NOT IN` 대신 `NOT EXISTS` 를 쓴다.**
3. **분기는 에러코드/SQLSTATE 로 한다. 메시지 문자열은 로그에만 쓴다.**
4. **애플리케이션 검증은 UX 를 위해, DB 제약은 정합성을 위해. 경쟁 조건 때문에 둘 다 필요하다.**

---

참고한 실제 파일: `/home/coder/volume/codyssey_B5-1/01_schema.sql`, `/home/coder/volume/codyssey_B5-1/02_data.sql`, `/home/coder/volume/codyssey_B5-1/04_bonus.sql`, `/home/coder/volume/codyssey_B5-1/README.md`, `/home/coder/volume/codyssey_B5-1/cafe.db`. 모든 SQLite 실측값은 **Python 3.14.4 / SQLite 3.46.1** 에서, `01_schema.sql` + `02_data.sql` 로 새로 만든 DB(customer 10 / category 10 / menu 12 / order_header 12 / order_detail 20, 아메리카노 3500원)를 임시 복사본에 두고 재현했다. 커밋된 `cafe.db` 는 `03_queries.sql` 까지 반영된 최종 상태(order_header 10 / order_detail 18 / 아메리카노 4000원)이므로 수치가 다르다.

---

## 보강 — 평가 피드백 재점검에서 추가된 것


### 6. 제약에 이름을 붙여라 — 실측으로 드러나는 결정적 차이

지금 이 스키마의 CHECK 4개는 전부 이름이 없다. 이름이 있고 없고가 앱 코드의 난이도를 통째로 바꾼다. SQLite 3.46.1에서 직접 실측한 에러 메시지다.

| 위반한 문장 | 실제 메시지 | errorname |
|---|---|---|
| `INSERT INTO menu ... price = -1` | `CHECK constraint failed: price >= 0` | `SQLITE_CONSTRAINT_CHECK` |
| `INSERT INTO order_header ... status='DONE'` | `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')` | `SQLITE_CONSTRAINT_CHECK` |
| `INSERT INTO order_detail ... quantity = 0` | `CHECK constraint failed: quantity > 0` | `SQLITE_CONSTRAINT_CHECK` |
| 이름을 붙인 경우 `CONSTRAINT chk_a_nonneg CHECK (a >= 0)` | `CHECK constraint failed: chk_a_nonneg` | `SQLITE_CONSTRAINT_CHECK` |

무명일 때 SQLite는 **제약식의 원문 텍스트**를 그대로 뱉는다. 즉 앱에서 `"price >= 0" in str(e)` 같은 코드를 쓰게 되는데, 이건 스키마에서 공백 하나만 바꿔도 깨진다. 게다가 이 동작은 SQLite 버전에 따라 다르다 — 예전 버전은 테이블 이름을 뱉었다. **문자열 파싱은 계약이 아니다.**

고치는 법은 한 줄이다.

```sql
status TEXT NOT NULL DEFAULT 'PENDING'
  CONSTRAINT chk_order_status CHECK (status IN ('PENDING','COMPLETED','CANCELLED')),
```

이제 메시지가 `CHECK constraint failed: chk_order_status`가 되고, 앱은 스키마 원문이 아니라 **내가 정한 이름**에 의존한다. 이름 규칙은 `chk_/uq_/fk_/pk_ + 테이블 + 컬럼`으로 통일한다.

### 7. CHECK는 NULL을 막지 않는다 — 3값 논리

실측: `CREATE TABLE t(a INTEGER CHECK (a >= 0))`에 `INSERT INTO t VALUES (NULL)` → **통과한다.**

이유는 SQL의 CHECK가 "참일 때 통과"가 아니라 **"거짓이 아니면 통과"**로 정의돼 있기 때문이다. `NULL >= 0`은 참도 거짓도 아닌 UNKNOWN이고, UNKNOWN은 거짓이 아니므로 통과한다. 이 규칙은 SQLite / MySQL 8 / PostgreSQL 셋 다 동일하다.

| 값 | `a >= 0` 평가 | 통과? |
|---|---|---|
| `5` | TRUE | 통과 |
| `-1` | FALSE | **거부** |
| `NULL` | UNKNOWN | 통과 |

이 스키마가 무사한 건 `price`, `quantity`, `unit_price`, `is_available`, `status`에 전부 `NOT NULL`이 같이 붙어 있어서다. **CHECK와 NOT NULL은 세트로 움직인다**가 결론이고, 이 문장을 평가장에서 먼저 말하면 "실질적으로 어떻게 작동하는지"에 대한 답이 된다. 반대로 `phone`처럼 NULL 허용 컬럼에 `CHECK (LENGTH(phone) >= 9)`를 걸면 전화번호 없는 고객은 그대로 통과한다 — 그게 의도라면 맞고, 아니라면 `CHECK (phone IS NULL OR LENGTH(phone) >= 9)`로 의도를 드러내 써야 한다.

### 8. 앱 레이어 분기 — 세 DBMS를 한 함수로

평가자가 말한 "예외 처리가 쉬워진다"의 실체는 이 코드다.

```python
import sqlite3

def save_order(conn, customer_id, status, lines):
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO order_header (customer_id, status) VALUES (?, ?)",
            (customer_id, status))
        oid = cur.lastrowid                      # last_insert_rowid() 함정 회피: 즉시 변수로 받는다
        conn.executemany(
            "INSERT INTO order_detail (order_id, menu_id, quantity, unit_price)"
            " VALUES (?, ?, ?, ?)",
            [(oid, m, q, p) for m, q, p in lines])
        conn.commit()
        return oid
    except sqlite3.IntegrityError as e:
        conn.rollback()
        raise translate(e)                       # 400 계열: 사용자 입력이 틀렸다
    except sqlite3.OperationalError as e:
        conn.rollback()
        raise                                    # 503 계열: database is locked 등, 재시도 대상

RULES = {                                        # 제약 이름 -> 사용자 메시지
    "chk_order_status":   "주문 상태는 대기/완료/취소 중 하나여야 합니다.",
    "chk_detail_qty":     "수량은 1개 이상이어야 합니다.",
    "uq_customer_email":  "이미 가입된 이메일입니다.",
}

def translate(e):
    code = getattr(e, "sqlite_errorname", "")    # Python 3.11+ 에서 제공
    name = str(e).rsplit(": ", 1)[-1]            # "...failed: chk_order_status"
    if code == "SQLITE_CONSTRAINT_FOREIGNKEY":
        return ValueError("존재하지 않는 고객 또는 메뉴입니다.")
    if code == "SQLITE_CONSTRAINT_NOTNULL":
        return ValueError(f"필수 항목이 비어 있습니다: {name}")
    return ValueError(RULES.get(name, "입력값이 규칙에 맞지 않습니다."))
```

핵심은 **`IntegrityError`와 `OperationalError`를 분리해서 잡는 것**이다. 전자는 사용자에게 되돌려 줄 400이고 재시도하면 똑같이 실패한다. 후자는 잠금·타임아웃 계열이라 백오프 후 재시도하면 성공할 수 있는 503이다. 이 둘을 한 `except Exception`으로 뭉개면 "주문이 안 됩니다"만 뜨는 서비스가 된다.

같은 판별을 다른 DBMS에서 하는 방법.

| | 제약 종류 식별 | 제약 이름 얻기 |
|---|---|---|
| SQLite (`sqlite3`) | `e.sqlite_errorname` (`SQLITE_CONSTRAINT_CHECK/UNIQUE/FOREIGNKEY/NOTNULL`) | 메시지 끝. **이름을 붙여야만 안정적** |
| MySQL 8 (`mysqlclient`) | `e.args[0]` errno — 1062 중복, 1452 FK, 3819 CHECK, 1048 NOT NULL | 메시지에 제약 이름 포함 |
| PostgreSQL (`psycopg`) | `e.sqlstate` — 23505 unique, 23503 fk, 23514 check, 23502 not null | `e.diag.constraint_name` — **표준 필드로 깨끗하게 나온다** |

### 9. 이 항목의 30초 대본

> "CHECK는 INSERT나 UPDATE가 커밋되기 전, 문장 단위로 즉시 평가됩니다. 위반하면 그 문장만 롤백되고 트랜잭션은 살아 있습니다. 다만 PostgreSQL은 예외라서 트랜잭션 전체가 실패 상태가 됩니다. 엔진이 SQLITE_CONSTRAINT_CHECK 같은 코드를 올리면 드라이버가 `sqlite3.IntegrityError`로 바꾸고, 앱은 그걸 잡아서 사용자 메시지로 번역합니다. 여기서 중요한 건 제약에 이름을 붙이는 겁니다. 무명이면 SQLite가 제약식 원문을 그대로 뱉어서 앱이 `price >= 0` 같은 문자열을 파싱하게 되는데, 이건 스키마를 조금만 손봐도 깨집니다. 그리고 CHECK는 NULL을 막지 못합니다. NULL 비교는 UNKNOWN이고 CHECK는 거짓이 아니면 통과시키기 때문에, 항상 NOT NULL과 세트로 겁니다."
