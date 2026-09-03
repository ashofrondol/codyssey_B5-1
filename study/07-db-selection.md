# DB 사용법과 상황별 선택

> 평가 피드백 1, 4 대응 — DB는 용도가 정해진 게 아니다. 접근 패턴으로 고르는 법과, 그 전에 갖출 사용법.

---

## 0. 이 모듈이 답해야 할 두 문장

평가자가 남긴 문장은 두 개다.

> "데이터베이스 사용법에 대해 조금 더 공부했으면 좋겠습니다." (1번)
> "데이터베이스에 따라 사용 용도가 정해진 게 아니라, 어떠한 상황에서 그 데이터베이스를 이용해야 하는지를 학습했으면 합니다." (4번)

1번은 **스키마 밖의 기본기**를 묻는다. `CREATE TABLE`과 `SELECT`는 SQL이고, 트랜잭션·격리 수준·커넥션·바인딩·NULL 논리·마이그레이션·백업·오류 처리는 "데이터베이스 사용법"이다. 제출물의 README는 SQL은 잘 썼지만 트랜잭션은 `04_bonus.sql`의 `BEGIN ~ ROLLBACK` 한 번뿐이고(전체 `.sql` 파일에서 `BEGIN`은 `04_bonus.sql:158` 한 곳), 격리·커넥션·마이그레이션 얘기는 전혀 없다(README 전체에서 "격리", "커넥션", "인젝션", "마이그레이션", "백업"이 한 번도 등장하지 않고 "트랜잭션"이 1회 나온다).

4번은 **"MongoDB는 로그용, Redis는 캐시용"처럼 외운 대응표를 버리라**는 말이다. 고르는 축은 용도가 아니라 **접근 패턴(access pattern)**이다.

아래 수치는 전부 `codyssey_B5-1` 파일을 실제로 돌려 얻은 실측값이다(SQLite 3.46.1, `page_size=4096`, Python 3.14).

| 항목 | 실측 |
| --- | --- |
| `01+02` 직후 행 수 | category 10 / menu 12 / customer 10 / order_header 12 / order_detail 20 |
| `01+02` 직후 `order_header.status` 분포 | COMPLETED 9, CANCELLED 2, PENDING 1 |
| `01+02` 직후 COMPLETED 매출 총합 | 125,500원 (일자별 9행, 최대 2026-05-10의 20,000원) |
| 커밋된 `cafe.db` | Q13/Q14 적용 후 상태 — order_header 10행(COMPLETED 9, PENDING 1), order_detail 18행, 아메리카노 4,000원 |
| `cafe.db`의 `PRAGMA journal_mode` | `delete` (WAL 아님) |
| `cafe.db`의 `PRAGMA foreign_keys` | `0` — 새 연결에서 켜지 않으면 FK 검사가 꺼져 있다 |
| `cafe.db`의 `PRAGMA synchronous` | `2` (= FULL, SQLite 기본값) |
| 파일 크기 | `01+02` 직후 49,152바이트(12페이지) → `03` 실행 후 57,344바이트(14페이지) |
| `cafe.db`의 `PRAGMA freelist_count` | `0` — 재사용 대기 중인 빈 페이지가 하나도 없다 |

마지막 두 줄은 뒤(1.5)에서 VACUUM을 이야기할 때 다시 쓴다. **파일은 줄지 않은 게 아니라 늘었다.**

---

## 1. 데이터베이스 사용법 — 스키마 밖의 기본기

### 1.1 트랜잭션과 ACID: 카페 주문 한 건은 쪼개질 수 없다

카페 주문 한 건은 **테이블 두 개에 걸쳐 있다**. `order_header` 1행 + `order_detail` N행. 이 스키마에서 "아메리카노 2잔 + 크로와상 1개" 주문은 INSERT 3번이다.

```sql
BEGIN IMMEDIATE;                                  -- SQLite: RESERVED 락을 '즉시' 잡는다
INSERT INTO order_header (customer_id, status) VALUES (1, 'PENDING');
INSERT INTO order_detail (order_id, menu_id, quantity, unit_price)
VALUES (last_insert_rowid(), 1, 2, 3500);         -- 헤더 INSERT 바로 다음이라 아직 안전하다
INSERT INTO order_detail (order_id, menu_id, quantity, unit_price)
VALUES (?, 9, 1, 4500);                           -- 두 번째부터는 반드시 바인딩된 order_id
COMMIT;
```

**`BEGIN IMMEDIATE`를 쓰는 이유.** 그냥 `BEGIN`(= `BEGIN DEFERRED`)은 락을 미뤘다가 첫 쓰기 시점에 잡으려 한다. 그런데 그 사이에 다른 커넥션이 먼저 쓰기 락을 가져가면, 이미 읽기를 끝낸 내 트랜잭션은 승격에 실패해 `database is locked`로 죽는다 — 이때는 처음부터 다시 시작하는 것 말고 방법이 없다. `IMMEDIATE`는 시작하자마자 RESERVED 락을 요구하므로 실패해도 아직 아무것도 읽지 않은 상태라 재시도가 깨끗하다. (RESERVED는 "내가 쓸 것"이라는 예약이고, 실제 배타 락은 커밋 순간에 잡힌다. 그래서 이 트랜잭션이 열려 있는 동안에도 다른 커넥션의 **읽기는 계속 된다** — 1.2에서 실측한다.)

**`last_insert_rowid()`의 조용한 함정.** 두 번째 `order_detail` INSERT에도 `last_insert_rowid()`를 그대로 쓰면, 그 값은 이미 **방금 삽입된 `order_detail`의 rowid**로 바뀌어 있다. 실제로 돌려 보면 이렇게 된다.

```text
-- order_header 14번을 만든 뒤 detail 두 줄을 모두 last_insert_rowid()로 넣으면
-- 첫 줄: order_id = 14  (맞다)
-- 둘째 줄: order_id = 21  <- 방금 만든 order_detail 의 id
sqlite3.IntegrityError: FOREIGN KEY constraint failed
```

FK를 켜 두었기 때문에 에러로 걸렸다. **`PRAGMA foreign_keys`가 꺼져 있었다면 에러 없이 존재하지 않는 주문을 가리키는 고아 상세가 조용히 들어간다.** 그래서 `order_id`는 한 번만 읽어 변수에 담고 그 뒤로는 바인딩한다.

```python
cur.execute("INSERT INTO order_header (customer_id, status) VALUES (?, 'PENDING')", (1,))
order_id = cur.lastrowid                          # 여기서 한 번만 확정
for menu_id, qty, price in [(1, 2, 3500), (9, 1, 4500)]:
    cur.execute("INSERT INTO order_detail (order_id, menu_id, quantity, unit_price)"
                " VALUES (?, ?, ?, ?)", (order_id, menu_id, qty, price))
```

두 번째 INSERT에서 앱이 죽으면 어떻게 되는가. 트랜잭션이 없으면 **`order_detail`이 하나도 없는 유령 주문**이 `order_header`에 남는다. `04_bonus.sql`의 지표 1(일자별 매출)은 `order_header JOIN order_detail`이므로 그 주문은 매출 0원으로 조용히 사라지고, 지표 3(VIP)의 `COUNT(DISTINCT oh.id)`에도 안 잡힌다. 데이터가 "틀린" 게 아니라 **없는 척**한다. 이게 가장 잡기 어려운 종류의 버그다.

ACID를 이 스키마 문장으로 다시 쓴다.

| 글자 | 교과서 정의 | 이 프로젝트에서의 구체적 의미 |
| --- | --- | --- |
| **A**tomicity | 전부 또는 전무 | header 1행 + detail 2행이 함께 들어가거나 함께 안 들어간다. `04_bonus.sql` (2-e)의 `ROLLBACK` 후 `customer_left=0, order_left=0`이 이걸 실증한다 |
| **C**onsistency | 제약을 깨는 상태로 끝나지 않음 | `CHECK (quantity > 0)`, `CHECK (status IN (...))`, FK가 커밋 시점에도 성립. 커밋 직전에 `quantity = 0`이 되면 트랜잭션 전체가 실패한다 |
| **I**solation | 동시 트랜잭션이 서로 안 보임 | 다른 직원이 같은 순간 결제해도 내 주문의 중간 상태가 안 보인다 (1.2에서 실측) |
| **D**urability | 커밋되면 살아남음 | `COMMIT` 이 반환된 뒤 전원이 나가도 주문은 남는다. SQLite는 저널/WAL + `PRAGMA synchronous`가 이걸 보장한다 |

**Durability는 공짜가 아니다.** SQLite의 `PRAGMA synchronous` 기본값은 저널 모드와 무관하게 **FULL(2)**이고(실측), 커밋마다 `fsync`를 부른다. `NORMAL`로 낮추면 훨씬 빠른데, 여기서 **저널 모드에 따라 안전성이 완전히 갈린다.**

- **WAL + `synchronous=NORMAL`**: 전원이 나가면 마지막 커밋 몇 개를 잃을 수 있지만 **DB 파일은 깨지지 않는다.** 그래서 이 조합이 실무의 사실상 표준이다.
- **rollback journal + `synchronous=NORMAL`**: 저널의 fsync를 건너뛰므로 전원 손실 시 **DB 파일 자체가 손상될 수 있다.** 여기서는 NORMAL을 쓰면 안 된다.

즉 "NORMAL은 최근 커밋만 잃는다"는 말은 WAL 모드에 한정된 보장이다. **속도를 위해 D를 얼마나 포기할 것인가**가 실무 판단이고, 이게 뒤에 나올 "돈이냐 좋아요냐" 질문과 같은 축이다.

### 1.2 격리 수준 4단계와 이상 현상 — 실측부터

두 커넥션 A, B를 열고 실제로 돌린 결과다(01+02 직후 상태 사본에서 실행했으므로 아메리카노는 아직 3,500원이다. 커밋된 `cafe.db`는 Q13이 적용돼 4,000원이라 그대로 재현되지 않는다).

```python
A = sqlite3.connect("t.db", isolation_level=None, timeout=0.5)
B = sqlite3.connect("t.db", isolation_level=None, timeout=0.5)

A.execute("BEGIN")
A.execute("UPDATE menu SET price=9999 WHERE name='아메리카노'")
# A sees: 9999
# B sees (dirty read?): 3500   <- 커밋 안 된 값이 B에 안 보인다. 그리고 읽기 자체는 막히지 않는다
B.execute("BEGIN"); B.execute("UPDATE menu SET price=1 WHERE name='카페라떼'")
# -> OperationalError: database is locked
A.execute("ROLLBACK")
# after rollback: 3500
```

네 가지가 한 번에 증명됐다. ① SQLite에서 **dirty read는 일어나지 않는다.** ② A가 쓰기 트랜잭션을 잡고 있어도 **B의 읽기는 정상적으로 된다.** ③ 그러나 B가 **쓰려고 하면** 다른 테이블·다른 행이어도 `database is locked`다 — SQLite의 쓰기 락 단위는 행도 테이블도 아닌 **데이터베이스 파일 전체**다. ④ 롤백하면 원래 값으로 돌아온다.

②와 ③을 구분하는 게 중요하다. rollback journal 모드에서 reader가 실제로 막히는 구간은 쓰기 트랜잭션 전체가 아니라 **커밋 순간(PENDING → EXCLUSIVE 락)**뿐이다. WAL 모드는 그 짧은 구간마저 없앤다.

이상 현상 세 가지를 이 스키마로 정의한다.

| 이상 현상 | 이 스키마에서의 시나리오 |
| --- | --- |
| **Dirty read** | 직원 A가 `UPDATE menu SET price=9999`를 하고 아직 커밋 안 했는데, 키오스크 B가 9999원을 읽어 고객에게 청구한다. A가 롤백하면 존재한 적 없는 가격으로 결제된 것이다 |
| **Non-repeatable read** | 한 트랜잭션 안에서 `SELECT price FROM menu WHERE id=1`을 두 번 부르는데, 그 사이 다른 트랜잭션이 커밋해서 3500 → 4000으로 값이 **바뀐다**(같은 행, 다른 값) |
| **Phantom read** | `SELECT COUNT(*) FROM order_header WHERE status='COMPLETED'`를 두 번 부르는데, 그 사이 새 주문이 커밋되어 9 → 10이 된다(같은 조건, **행 수**가 달라진다) |

핵심 차이: non-repeatable read는 **이미 읽은 행의 값**이 변하는 것, phantom은 **조건에 맞는 행의 집합**이 변하는 것이다. 그래서 non-repeatable read는 행 락으로 막을 수 있지만 phantom은 아직 존재하지 않는 행이 대상이라 **범위 락(gap lock)이나 스냅샷**이 필요하다.

| 격리 수준 | dirty read | non-repeatable | phantom |
| --- | --- | --- | --- |
| READ UNCOMMITTED | 발생 | 발생 | 발생 |
| READ COMMITTED | 방지 | 발생 | 발생 |
| REPEATABLE READ | 방지 | 방지 | 표준상 발생 가능 |
| SERIALIZABLE | 방지 | 방지 | 방지 |

**DBMS별로 기본값과 실제 동작이 다르다. 이걸 뭉뚱그리면 안 된다.**

| | SQLite | MySQL 8 (InnoDB) | PostgreSQL |
| --- | --- | --- | --- |
| 기본 격리 수준 | 사실상 SERIALIZABLE | **REPEATABLE READ** | **READ COMMITTED** |
| 구현 방식 | 파일 단위 락 (rollback journal) 또는 WAL 스냅샷 | MVCC + 언두 로그 + gap/next-key 락 | MVCC + 튜플 버전 + 스냅샷 |
| 동시 쓰기 | **writer 1명만.** 나머지는 `database is locked` | 행 단위 락, 다중 writer | 행 단위 락, 다중 writer |
| 동시 읽기+쓰기 | rollback journal: **쓰기 트랜잭션 중에도 읽기는 된다.** 커밋 순간에만 잠깐 차단 / **WAL: 그 짧은 차단마저 없다** | 항상 가능 (읽기는 락 안 잡음) | 항상 가능 |
| READ UNCOMMITTED | shared-cache 모드에서만 의미 있음(사실상 안 씀) | 지원 (실제로 dirty read 발생) | **요청해도 READ COMMITTED로 동작** — dirty read 자체가 불가능 |
| REPEATABLE READ의 phantom | 해당 없음 | next-key 락으로 대부분 차단 | 스냅샷이라 phantom 없음. 대신 **write skew** 가능 |
| SERIALIZABLE 구현 | 락 | 모든 읽기를 공유 락으로 승격 | **SSI** — 낙관적, 충돌 시 `serialization_failure`(SQLSTATE 40001)로 트랜잭션을 취소 |

실무 함의 하나만 짚는다. **PostgreSQL에서 SERIALIZABLE을 쓰면 애플리케이션에 재시도 로직이 반드시 있어야 한다.** SSI는 락으로 막는 대신 나중에 "너 직렬화 불가능했어"라며 에러를 던지기 때문이다. MySQL은 락으로 막으므로 재시도 대신 데드락(에러 1213, SQLSTATE 40001)과 대기 시간(에러 1205)이 문제가 된다. **같은 이름의 격리 수준이 전혀 다른 실패 모드를 만든다.**

### 1.3 커넥션, 커넥션 풀, 그리고 파라미터 바인딩

**커넥션은 비싸다.** TCP 핸드셰이크 + 인증 + 세션 설정이 붙는다. PostgreSQL은 커넥션 하나당 **OS 프로세스**를 포크하므로 수백 개만 열려도 메모리가 급격히 는다(그래서 PgBouncer 같은 외부 풀러를 쓴다). MySQL은 커넥션당 스레드다. SQLite는 **커넥션이 그냥 열린 파일 핸들**이라 비용이 거의 없다 — 대신 1.2에서 본 대로 writer가 하나뿐이라 풀을 키운다고 쓰기 처리량이 늘지 않는다.

**커넥션 풀**은 미리 N개를 열어두고 빌려주고 반납받는 구조다. 이 프로젝트의 `build_and_capture.py`는 커넥션을 하나 열고 끝나므로 풀이 필요 없지만, 웹 서버로 바뀌는 순간 필수가 된다.

**SQLite 특유의 함정 하나**: `PRAGMA foreign_keys`는 **연결마다** 설정된다. 풀에서 커넥션을 빌릴 때마다 켜주지 않으면 어떤 요청은 FK 검사를 하고 어떤 요청은 안 하는 비결정적 동작이 된다. 실제로 커밋된 `cafe.db`에 새로 붙어보면 `PRAGMA foreign_keys`가 `0`이다. 게다가 **이 PRAGMA는 트랜잭션 안에서는 변경이 조용히 무시된다.** 그래서 안전한 설정 시점은 "커넥션을 얻은 직후, 트랜잭션을 시작하기 전" 딱 하나이고, 풀 라이브러리의 connect 훅에 걸어야 한다.

```python
def on_connect(conn, _):
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")    # 락 대기 시 즉시 죽지 말고 5초 기다린다
```

**프리페어드 스테이트먼트**는 SQL 문장을 먼저 파싱·계획 수립해서 컴파일해두고, 값만 나중에 꽂는 방식이다. 두 가지 이득이 있다. ① 같은 모양의 쿼리를 반복할 때 파싱/플랜 생성을 재사용한다. ② **값이 SQL 문법으로 해석될 수 없다** — 이게 인젝션 방어의 원리다.

```python
# 나쁜 예 — 문자열 포매팅
email = "' OR 1=1 --"
cur.execute("SELECT id, name FROM customer WHERE email = '%s'" % email)
# 실제 실행된 SQL: SELECT id, name FROM customer WHERE email = '' OR 1=1 --'
# 실측 결과: 10행  <- customer 테이블 전체가 털렸다
```

```python
# 좋은 예 — 파라미터 바인딩 (SQLite/Python은 ? , psycopg는 %s , MySQL Connector는 %s)
cur.execute("SELECT id, name FROM customer WHERE email = ?", (email,))
# 실측 결과: 0행  <- "' OR 1=1 --" 라는 이메일을 가진 고객을 찾은 것이고, 그런 고객은 없다
```

**차이는 "따옴표를 이스케이프했다"가 아니다.** 바인딩된 값은 파싱이 끝난 뒤에 전달되므로 애초에 **문법이 될 기회가 없다.** 그래서 `str.replace("'", "''")` 같은 수동 이스케이프는 방어책이 아니다(멀티바이트 인코딩 트릭으로 뚫린다).

바인딩으로 못 막는 자리도 있다. **테이블명, 컬럼명, `ORDER BY` 방향은 바인딩할 수 없다.** 정렬 기준을 사용자가 고르게 하려면 화이트리스트를 코드에 두어야 한다.

```python
ALLOWED = {"price": "m.price", "name": "m.name", "qty": "total_qty"}
col = ALLOWED.get(user_input, "m.price")          # 목록에 없으면 기본값
direction = "DESC" if user_dir == "desc" else "ASC"
cur.execute(f"SELECT m.name, m.price FROM menu m ORDER BY {col} {direction}")
```

### 1.4 마이그레이션 — `DROP TABLE`로는 서비스를 운영할 수 없다

이 프로젝트의 `build_and_capture.py`는 `os.remove(DB_PATH)`로 파일을 지우고 `01_schema.sql`의 `DROP TABLE IF EXISTS`가 한 번 더 지운 뒤 다시 만든다. **학습용으로는 완벽하다** — 매번 같은 초기 상태를 재현하니까. 하지만 이 방식은 **데이터가 없어도 되는 세계에서만** 성립한다.

운영에서 `menu`에 `description TEXT` 컬럼을 추가해야 한다고 하자. `DROP` 후 재생성하면 12만 건의 주문 이력이 사라진다. 그래서 필요한 것이 **마이그레이션 — 스키마의 버전 관리**다.

```
migrations/
  001_init.sql               -- 현재의 01_schema.sql
  002_add_menu_description.sql
  003_add_order_index.sql
```

각 파일은 **되돌릴 수 없는 한 방향의 변경**이고, DB 안의 `schema_migrations` 테이블에 "몇 번까지 적용됐는지"를 기록한다. 도구는 Flyway, Liquibase, Alembic(Python), Django/Rails 내장 마이그레이션 등이 있다.

| | SQLite | MySQL 8 | PostgreSQL |
| --- | --- | --- | --- |
| `ALTER TABLE ADD COLUMN` | 지원 | 지원 (온라인 DDL) | 지원 |
| `ALTER TABLE RENAME COLUMN` | 3.25.0+ | 지원 | 지원 |
| `ALTER TABLE DROP COLUMN` | 3.35.0+ 지원(제약 있음 — PK/UNIQUE/인덱스에 걸린 컬럼은 불가) | 지원 | 지원 |
| 컬럼 타입 변경 | **불가** — 새 테이블 만들고 `INSERT SELECT` 후 `RENAME` (SQLite 문서의 12단계 공식 절차) | 지원 (테이블 재작성 발생 가능) | 지원 |
| CHECK 제약 추가/삭제 | **불가** — 테이블 재작성 필요 | `ALTER TABLE ... ADD CHECK` (8.0.16+ 부터 실제로 강제) | `ADD CONSTRAINT ... CHECK` |
| DDL 한 문장의 원자성 | 보장 | **8.0의 atomic DDL로 보장** — 중간에 죽어도 반쪽 스키마는 안 남는다 | 보장 |
| **여러 DDL을 한 트랜잭션으로 묶어 롤백** | **가능** | **불가** — DDL이 암묵적 커밋을 유발한다 | **가능** |
| `RIGHT` / `FULL OUTER JOIN` | 3.39.0+ (2022-07) | RIGHT만 지원, **FULL OUTER는 없음**(UNION으로 우회) | 둘 다 지원 |

마지막에서 두 번째 행이 실무에서 가장 크다. MySQL 8.0이 atomic DDL을 도입해 **DDL 한 문장**은 이제 원자적이지만, `BEGIN; ALTER TABLE A ...; ALTER TABLE B ...; COMMIT;`처럼 **여러 문장을 묶어 통째로 되돌리는 것은 여전히 불가능하다.** 첫 ALTER가 성공하고 둘째가 실패하면 반쪽 스키마가 남는다. PostgreSQL과 SQLite는 이걸 하나의 트랜잭션으로 되돌릴 수 있다.

이 스키마의 `menu.is_available` CHECK를 고치려면 SQLite에서는 **테이블 전체를 새로 만들어야 한다** — 이 사실 하나가 "SQLite는 스키마가 굳은 뒤에 쓰기 좋다"는 판단으로 이어진다. 마지막 행은 이식성 항목이다. `03_queries.sql`의 Q8/Q8-B가 `LEFT JOIN`으로 "메뉴가 0개인 카테고리"를 잡는데, 이걸 양방향으로 확장하려 들면 MySQL에서 막힌다.

### 1.5 백업/복구, WAL, VACUUM

**백업.** `cp cafe.db backup.db`는 **틀린 백업이다** — 복사 중에 쓰기가 일어나면 깨진 파일이 나온다. 올바른 방법은 `sqlite3 cafe.db ".backup backup.db"` 또는 Python `src.backup(dst)` API로, 락을 제대로 잡고 페이지 단위로 복사한다. MySQL은 `mysqldump --single-transaction`(논리) 또는 Percona XtraBackup(물리), PostgreSQL은 `pg_dump`(논리) / `pg_basebackup` + WAL 아카이빙(PITR, 특정 시각으로 복구)이다. **복구를 실제로 해 본 적 없는 백업은 백업이 아니다.**

**WAL(Write-Ahead Logging).** 변경을 원본 파일에 바로 쓰지 않고 `-wal` 파일에 먼저 append한 뒤 나중에 본체로 옮긴다(checkpoint). `PRAGMA journal_mode=WAL` 한 줄이면 켜지고, 파일에 영구 기록된다(실측: `delete` → `wal` 전환 후 커넥션을 닫았다 다시 열어도 `wal` 유지). 효과는 **읽기와 쓰기가 서로를 전혀 막지 않는 것**이다 — 1.2에서 rollback journal에 남아 있던 "커밋 순간의 짧은 읽기 차단"까지 사라진다. writer는 여전히 하나뿐이다. 대가는 운영 중 파일이 3개(`.db`, `.db-wal`, `.db-shm`)로 늘고 **네트워크 파일시스템(NFS)에서 못 쓴다**는 점인데, 후자의 이유는 WAL이 `-shm` 파일을 통한 **프로세스 간 공유 메모리(mmap)**를 요구하기 때문이다. 커넥션이 하나뿐이라면 `PRAGMA locking_mode=EXCLUSIVE`로 `-shm` 없이 WAL을 쓸 수 있다. PostgreSQL과 MySQL(InnoDB redo log)은 애초에 WAL이 기본 구조다.

**VACUUM.** 삭제된 공간은 파일에서 자동으로 회수되지 않는다 — 이 원칙은 맞다. 그런데 **이 프로젝트의 DB로는 그걸 실증할 수 없다.** 실측값이 그렇게 말한다.

| 시점 | 파일 크기 | page_count | freelist_count |
| --- | --- | --- | --- |
| `01+02` 직후 | 49,152 | 12 | 0 |
| `03_queries.sql` 실행 후 (= 커밋된 `cafe.db`) | **57,344** | 14 | **0** |
| 위 상태에서 `VACUUM` 실행 후 | 57,344 | 14 | 0 |

읽어야 할 것은 세 가지다. ① Q14가 헤더 2행 + CASCADE 상세 2행을 지웠지만 파일은 **줄지 않은 게 아니라 오히려 늘었다.** 늘어난 2페이지는 삭제와 무관하게 **Q15가 만든 인덱스 2개**다. ② `freelist_count`가 0이므로 "free page로 남아 재사용 대기 중"인 페이지는 하나도 없다. 4행 삭제는 페이지를 통째로 비우지 못했고, 페이지 **안**의 셀 공간만 반환됐다. ③ 그래서 `VACUUM`을 돌려도 크기가 그대로다 — **회수할 게 없기 때문이다.**

`VACUUM`이 실제로 의미를 갖는 건 대량 삭제로 페이지 전체가 비어 freelist에 쌓였을 때다. 그때 `VACUUM`은 DB를 통째로 다시 써서 압축하고 조각을 없앤다(임시로 원본만큼 디스크가 더 필요하고, 실행 중 배타 락을 잡는다). 자동화하려면 `PRAGMA auto_vacuum=INCREMENTAL`을 테이블 생성 전에 켜두고 `PRAGMA incremental_vacuum`을 주기적으로 부른다.

PostgreSQL의 `VACUUM`은 이름은 같지만 **역할이 다르다** — MVCC로 생긴 죽은 튜플을 회수하는 것이고, autovacuum이 상시 돌며, 안 돌면 트랜잭션 ID wraparound라는 심각한 문제로 간다. 게다가 일반 `VACUUM`은 파일을 OS에 반납하지 않고(그건 `VACUUM FULL`이며 배타 락을 잡는다), 죽은 튜플 자리를 재사용 가능하게 만들 뿐이다. **같은 키워드가 DBMS마다 다른 일을 한다는 대표 사례**다.

### 1.6 NULL과 3값 논리 — 조용히 틀린 답이 나오는 자리

SQL의 비교는 참/거짓 두 개가 아니라 **참 / 거짓 / UNKNOWN 세 개**다. `NULL`은 "값이 없음"이 아니라 **"값을 모름"**이고, 모르는 값끼리는 같은지도 모른다.

```text
NULL = NULL     -> NULL (UNKNOWN)      NULL IS NULL  -> 1
1 = NULL        -> NULL                NOT NULL      -> NULL
NULL AND 0      -> 0    (모르든 말든 거짓)
NULL AND 1      -> NULL
NULL OR 1       -> 1    (모르든 말든 참)
NULL OR 0       -> NULL
```

이게 실제 동작으로 새어 나오는 자리가 네 군데다. 전부 실측했다.

**① `WHERE`는 UNKNOWN을 탈락시키지만 `CHECK`는 통과시킨다.** 이 비대칭이 핵심이다.

```sql
CREATE TABLE t (a INTEGER CHECK (a > 0));
INSERT INTO t VALUES (NULL);   -- 성공. NULL > 0 은 UNKNOWN 이고, CHECK 는 'FALSE 가 아니면' 통과다
INSERT INTO t VALUES (0);      -- CHECK constraint failed: a > 0
```

이 스키마에서 `menu.price INTEGER NOT NULL CHECK (price >= 0)`가 안전한 이유는 CHECK 때문이 아니라 **`NOT NULL`이 함께 붙어 있기 때문**이다. `NOT NULL`을 빼면 `CHECK (price >= 0)`만으로는 NULL 가격을 못 막는다. **CHECK는 NOT NULL과 짝으로 쓴다** — 이게 규칙이다. 유일하게 NULL을 허용한 `customer.phone`에는 CHECK가 없으니 문제가 없다.

**② `NOT IN` + NULL = 항상 빈 결과.**

```sql
-- 서브쿼리 결과가 {1, 2, NULL} 일 때
SELECT 3 WHERE 3 NOT IN (1, 2, NULL);   -- 0행. 3 <> NULL 이 UNKNOWN 이라 전체가 UNKNOWN
SELECT 3 WHERE 3     IN (1, 2, NULL);   -- 0행. 이쪽도 0행이지만 이유가 다르다
SELECT 3 WHERE NOT EXISTS (...);        -- 1행. NOT EXISTS 는 NULL 에 안전하다
```

`04_bonus.sql`의 주석이 짚은 그대로다. 실측으로 확인했다. **부정 조건에서는 `NOT IN` 대신 `NOT EXISTS`를 쓴다.** `NOT IN`을 꼭 써야 하면 서브쿼리에 `WHERE col IS NOT NULL`을 붙인다. 이 스키마에서 `order_header.customer_id`는 `NOT NULL`이라 지금은 안전하지만, 나중에 "비회원 주문"을 위해 NULL을 허용하는 순간 "한 번도 주문 안 한 고객 찾기" 쿼리가 조용히 0행이 된다.

**③ `UNIQUE`는 NULL을 여러 개 허용한다.** 표준 SQL이 그렇고 SQLite/PostgreSQL/MySQL이 다 그렇다(실측: `UNIQUE` 컬럼에 NULL 2행 삽입 성공). SQL Server만 1개로 제한한다. `customer.email`이 `NOT NULL UNIQUE`인 게 중요한 이유다 — `UNIQUE`만 걸면 이메일 없는 고객이 무한히 생긴다.

**④ 집계 함수는 NULL을 세지 않는다.** 값이 `{1, 2, NULL}`일 때 실측이다.

| 식 | 결과 | 의미 |
| --- | --- | --- |
| `COUNT(*)` | 3 | 행 수 |
| `COUNT(x)` | 2 | **NULL 아닌 값의 수** |
| `SUM(x)` | 3 | NULL 무시 |
| `AVG(x)` | 1.5 | **분모가 3이 아니라 2다** |

`03_queries.sql`의 Q7-B가 대조하는 게 정확히 이 함정이다. `LEFT JOIN` 뒤에 `COUNT(*)`를 쓰면 매칭이 없는 부모도 1로 세어 버리고, `COUNT(자식컬럼)`을 써야 0이 나온다. Q12의 `AVG(price)`도 `price`가 NULL을 허용했다면 분모가 달라졌을 것이다.

### 1.7 정규화 — 이 스키마가 왜 이미 3NF/BCNF인가

**함수 종속(FD)** `X → Y`는 "X의 값이 같은 두 행은 Y의 값도 반드시 같다"는 뜻이다. **후보키**는 행을 유일하게 식별하는 최소 속성 집합이고, 후보키 중 하나라도에 속한 속성을 **주요 속성(prime)**, 아닌 것을 **비주요 속성**이라 한다.

| 단계 | 정의 | 이 스키마 |
| --- | --- | --- |
| **1NF** | 모든 속성값이 원자값 (반복 그룹·배열 없음) | 만족. 주문 상세를 `menu` 컬럼에 `'아메리카노,크로와상'`처럼 넣지 않고 `order_detail` 행으로 쪼갰다 |
| **2NF** | 1NF + 모든 비주요 속성이 **모든 후보키에 완전 함수 종속**(부분 함수 종속 없음) | **자동 만족.** 다섯 테이블 모두 단일 컬럼 대리키 PK라 복합 후보키가 없고, 복합키가 없으면 부분 종속이 성립할 수 없다 |
| **3NF** | 2NF + 비주요 속성이 후보키에 **이행적으로** 종속되지 않음. (Zaniolo 형태: 모든 비자명 FD `X → A`에 대해 X가 슈퍼키이거나 A가 주요 속성) | 만족 |
| **BCNF** | 모든 비자명 FD `X → Y`에서 **X가 슈퍼키** | 만족 |

구체적으로 확인한다.

- **`menu`**: 후보키가 둘이다 — `id`(PK)와 `name`(UNIQUE). FD는 `id → name, price, category_id, is_available`와 `name → id, price, ...` 두 개뿐이고 **결정자가 둘 다 슈퍼키**라 BCNF다. 만약 `category_id → category_name` 같은 컬럼을 `menu`에 끌어들였다면 `category_name`이 키가 아닌 `category_id`에 종속돼 **3NF 위반(이행 종속)**이 된다. `category` 테이블을 분리한 것이 정확히 이 위반을 피한 결정이다.
- **`order_detail`**: FD는 `id → order_id, menu_id, quantity, unit_price` 하나뿐이다. `(order_id, menu_id)`에 UNIQUE를 **일부러 안 걸었으므로**(스키마 주석의 옵션 라인 근거) 그것은 후보키가 아니다.
- **`order_detail.unit_price`는 3NF 위반이 아니다.** "메뉴 가격은 `menu`에 있는데 왜 또 저장하나, 이건 중복 아닌가"가 흔한 오해다. 아니다. `unit_price`는 `menu_id`에 함수 종속되지 **않는다** — 같은 `menu_id`라도 주문 시점이 다르면 값이 다를 수 있기 때문이다. 이건 메뉴의 속성이 아니라 **주문 라인 자체의 속성**(그때 그 가격에 팔았다는 사실)이다. 따라서 정규화 위반이 아니라 정규화가 요구하는 대로 놓인 것이고, Q13이 가격을 3500 → 4000으로 올려도 과거 매출이 안 흔들리는 것은 그 결과다.

**3NF와 BCNF의 실무적 차이**: 3NF로의 분해는 **무손실이면서 종속성 보존**이 항상 가능하지만, BCNF 분해는 무손실은 보장해도 **종속성 보존은 보장하지 못한다.** 즉 BCNF로 밀어붙이다 보면 원래 하나의 CHECK/UNIQUE로 강제하던 규칙을 조인 없이는 검사할 수 없게 되는 경우가 생긴다. 그래서 실무의 기본선은 "3NF까지 가고, BCNF 위반이 실제 이상 현상을 만들 때만 더 쪼갠다"다.

**비정규화는 정규화를 모르고 하는 게 아니라 알고 하는 것이다.** 5장에서 다룰 NoSQL 실패 경로의 3번(고객 이름을 주문 문서에 복사)이 정확히 이행 종속을 일부러 만든 것이고, 그 대가가 갱신 이상(update anomaly)이다.

### 1.8 인덱스가 실제로 쓰이는 조건 — `LIKE '라떼%'`는 안 탄다

`03_queries.sql` Q4-B는 `WHERE name LIKE '%라떼%'`다. 앞에 `%`가 붙으면 인덱스를 못 쓴다는 건 맞다. 그런데 **앞을 고정한 `'라떼%'`도 SQLite 기본 설정에서는 인덱스를 못 쓴다.** `menu.name`에 UNIQUE 자동 인덱스가 있는데도 그렇다. 실측이다.

| 조건 | 실행계획 |
| --- | --- |
| `name LIKE '%라떼%'` (기본) | `SCAN menu USING COVERING INDEX sqlite_autoindex_menu_1` |
| `name LIKE '라떼%'` (기본) | `SCAN menu USING COVERING INDEX sqlite_autoindex_menu_1` |
| `name LIKE '라떼%'` + `PRAGMA case_sensitive_like=ON` | `SEARCH ... (name>? AND name<?)` |
| `name LIKE '라떼%'` + `name COLLATE NOCASE` 인덱스 | `SEARCH ... (name>? AND name<?)` |
| `name GLOB '라떼*'` | `SEARCH ... (name>? AND name<?)` |
| `name >= '라떼' AND name < '라뗍'` | `SEARCH ... (name>? AND name<?)` |

이유는 SQLite의 `LIKE`가 기본적으로 **ASCII 대소문자를 무시**하기 때문이다. BINARY 콜레이션으로 정렬된 인덱스는 그 의미를 재현할 수 없으므로 플래너가 최적화를 포기한다. `case_sensitive_like=ON`이거나 인덱스가 `NOCASE` 콜레이션일 때만 접두 LIKE가 범위 검색으로 변환된다. (첫 두 줄이 `SCAN`이면서도 `USING COVERING INDEX`인 건 인덱스를 **검색**에 쓴 게 아니라, 필요한 컬럼이 인덱스 안에 다 있어서 더 작은 인덱스를 처음부터 끝까지 훑은 것이다. `SCAN`과 `SEARCH`를 구분해서 읽어야 한다.)

다른 DBMS도 조건이 붙는다.

- **MySQL(InnoDB)**: `col LIKE 'prefix%'`는 인덱스 범위 스캔이 된다. 콜레이션이 대소문자 무시(`_ci`)여도 인덱스 자체가 그 콜레이션으로 정렬돼 있어 문제가 없다.
- **PostgreSQL**: C/POSIX 로케일이 아니면 기본 B-tree 인덱스로 `LIKE 'prefix%'`를 못 탄다. `CREATE INDEX ... (name text_pattern_ops)`를 따로 만들어야 한다. 이걸 모르고 "PostgreSQL이 인덱스를 안 탄다"고 하는 경우가 많다.

**교훈은 하나다. "인덱스가 있으니 빠르겠지"가 아니라 실행계획을 떠서 `SEARCH`가 나오는지 확인한다.** 이 스키마에서는 실제로 확인했다 — `SELECT * FROM order_header WHERE customer_id=1`은 `SEARCH order_header USING INDEX idx_order_header_customer_id (customer_id=?)`가 나온다(Q15 적용 후).

### 1.9 오류 처리 — 예외 하나로 뭉뚱그리면 재시도를 못 한다

Python `sqlite3`에서 `04_bonus.sql` (2)의 네 가지 위반을 잡아 보면, **넷 다 `IntegrityError` 하나로 온다.** 구분하려면 확장 결과 코드를 봐야 한다. 실측값이다(Python 3.11+의 `sqlite_errorname` / `sqlite_errorcode`).

| 위반 | 예외 클래스 | `sqlite_errorname` | `sqlite_errorcode` | 메시지 |
| --- | --- | --- | --- | --- |
| FK (`customer_id=999`) | `IntegrityError` | `SQLITE_CONSTRAINT_FOREIGNKEY` | 787 | `FOREIGN KEY constraint failed` |
| UNIQUE (중복 이메일) | `IntegrityError` | `SQLITE_CONSTRAINT_UNIQUE` | 2067 | `UNIQUE constraint failed: customer.email` |
| CHECK (`status='DONE'`) | `IntegrityError` | `SQLITE_CONSTRAINT_CHECK` | 275 | `CHECK constraint failed: status IN (...)` |
| NOT NULL (`email=NULL`) | `IntegrityError` | `SQLITE_CONSTRAINT_NOTNULL` | 1299 | `NOT NULL constraint failed: customer.email` |
| 락 경합 | **`OperationalError`** | `SQLITE_BUSY` | 5 | `database is locked` |

마지막 행이 중요하다. `database is locked`는 `IntegrityError`가 **아니다.** `except sqlite3.IntegrityError`만 잡아두면 락 에러가 그대로 위로 튄다.

```python
import sqlite3, time

def place_order(conn, customer_id, lines, retries=3):
    for attempt in range(retries):
        try:
            conn.execute("BEGIN IMMEDIATE")
            cur = conn.execute(
                "INSERT INTO order_header (customer_id, status) VALUES (?, 'PENDING')",
                (customer_id,))
            order_id = cur.lastrowid
            conn.executemany(
                "INSERT INTO order_detail (order_id, menu_id, quantity, unit_price)"
                " VALUES (?, ?, ?, ?)",
                [(order_id, m, q, p) for m, q, p in lines])
            conn.execute("COMMIT")
            return order_id

        except sqlite3.IntegrityError as e:
            conn.execute("ROLLBACK")
            # 제약 위반은 재시도해도 똑같이 실패한다. 입력을 고쳐야 하는 에러다.
            if e.sqlite_errorname == "SQLITE_CONSTRAINT_FOREIGNKEY":
                raise ValueError(f"없는 고객이거나 없는 메뉴입니다: {customer_id}") from e
            raise

        except sqlite3.OperationalError as e:
            conn.execute("ROLLBACK")
            # 락 경합은 '지금' 실패한 것이라 재시도가 의미 있다.
            if "locked" in str(e) and attempt < retries - 1:
                time.sleep(0.05 * (2 ** attempt))     # 지수 백오프
                continue
            raise
```

**원칙은 "재시도해야 하는 에러와 재시도하면 안 되는 에러를 코드로 가른다"**다. 제약 위반은 몇 번을 다시 해도 같은 결과이므로 사용자에게 돌려줘야 하고, 락/직렬화 충돌은 다시 하면 성공할 수 있으므로 백오프를 두고 재시도한다. DBMS를 옮기면 판별 코드만 바뀐다.

| 상황 | SQLite (확장 코드) | PostgreSQL (SQLSTATE) | MySQL (에러번호 / SQLSTATE) |
| --- | --- | --- | --- |
| UNIQUE 위반 | 2067 | `23505` unique_violation | 1062 / `23000` |
| FK 위반 | 787 | `23503` foreign_key_violation | 1452 / `23000` |
| CHECK 위반 | 275 | `23514` check_violation | 3819 / `HY000` |
| NOT NULL 위반 | 1299 | `23502` not_null_violation | 1048 / `23000` |
| **직렬화 실패 → 재시도** | — | `40001` serialization_failure | 1213 / `40001` (데드락) |
| **데드락 → 재시도** | 5 `SQLITE_BUSY` | `40P01` deadlock_detected | 1213 / `40001` |
| 락 대기 타임아웃 | 5 | `55P03` lock_not_available | 1205 / `HY000` |

`40001`은 표준이 "다시 해 보라"고 정한 코드다. **PostgreSQL을 SERIALIZABLE로 쓰기로 했다면 이 코드를 잡는 재시도 루프가 없으면 안 된다**(1.2의 결론과 같은 이야기다).

---

## 2. DB 종류별 지도 — 이름이 아니라 자료구조로 외운다

각 DB를 "무슨 용도"가 아니라 **"어떤 접근을 O(1)/O(log n)로 만들려고 그 자료구조를 골랐는가"**로 읽는다.

**먼저 B-트리와 B+트리를 정확히 갈라 둔다.** 둘을 섞어 쓰는 게 가장 흔한 오개념이다.

| | B-트리 | B+트리 |
| --- | --- | --- |
| 데이터(페이로드) 위치 | 내부 노드에도 있다 | **리프에만 있다** |
| 내부 노드 | 키 + 데이터 + 자식 포인터 | 키 + 자식 포인터만 → 같은 페이지에 키가 더 많이 들어가 트리가 낮아진다 |
| 리프 연결 | 없음 | **양방향 연결 리스트** → 범위 스캔이 리프를 따라 흐른다 |
| 점 조회 | 운 좋으면 내부 노드에서 조기 종료 | 항상 리프까지 |

**관계형 — PostgreSQL / MySQL(InnoDB) / SQLite.** 셋 다 정렬된 트리를 쓰지만 **어느 트리가 어느 종류인지는 다르다.**

- **InnoDB**: 테이블도 인덱스도 전부 **B+트리**다. 그리고 **클러스터드 인덱스**라 PK 순서로 행 전체가 리프에 들어 있어 PK 조회에 추가 접근이 없다. 세컨더리 인덱스는 행의 물리 주소가 아니라 **PK 값**을 담는다. 여기서 두 가지 귀결이 나온다. ① 커버링이 아닌 세컨더리 조회는 세컨더리 B+트리를 타고 PK를 얻은 뒤 **클러스터드 인덱스를 한 번 더 타야** 한다(bookmark lookup, 트리 탐색 2회). ② PK가 뚱뚱하면(UUID, 긴 문자열) **모든 세컨더리 인덱스가 함께 비대해진다.** 이 스키마가 `INTEGER` 증가 PK를 쓴 것은 MySQL로 옮겼을 때 그대로 이점이 된다 — 랜덤 PK는 클러스터드 인덱스의 페이지 분할까지 유발한다.
- **PostgreSQL**: **힙 + 별도 인덱스** 구조다. 인덱스 엔트리는 물리 위치(tid)를 가리키고, 인덱스 자체는 B+트리 계열(Lehman-Yao B-link 트리)이다. 클러스터드 인덱스가 없다 — `CLUSTER` 명령이 있지만 **1회성 물리 재배치일 뿐 이후 갱신에서 유지되지 않는다.** 그리고 결정적으로 **인덱스 엔트리는 가시성 정보를 갖지 않는다.** 그래서 인덱스로 행을 찾아도 원칙적으로 힙 튜플을 방문해 "내 스냅샷에서 이게 보이는가"를 확인해야 하고, index-only scan은 visibility map이 해당 페이지를 all-visible로 표시했을 때만 성립한다. 인덱스 종류가 풍부한 것(B-tree, Hash, GiST, SP-GiST, GIN, BRIN)은 힙 구조의 결과가 아니라 **확장 가능한 인덱스 접근 메서드(AM) 프레임워크** 덕이다. 그래서 pgvector가 `hnsw` / `ivfflat`을 **확장으로** 얹을 수 있다 — HNSW는 PostgreSQL 코어 인덱스가 아니다.
- **SQLite**: DB 전체가 파일 하나다. 그리고 **테이블과 인덱스가 서로 다른 종류의 트리**다. 테이블(rowid table)은 데이터를 리프에만 두는 **B+트리**이고, 인덱스는 내부 노드에도 키를 담는 **B-트리**다. 즉 이 스키마의 `idx_order_header_customer_id`는 **B+트리가 아니라 B-트리**이고, `order_header` 테이블 자체가 B+트리다. 흔히 반대로 말하는데 SQLite 파일 포맷 문서가 이렇게 정의한다.

관계형 공통의 강점은 **정렬된 트리 덕에 점 조회(`WHERE id = 5`)와 범위 조회(`WHERE joined_at BETWEEN ...`)가 둘 다 빠르다**는 것, 그리고 **조인과 선언적 제약** — 관계를 DB가 강제해 준다는 것이다.

**문서 — MongoDB.** BSON 문서를 저장하고 스토리지 엔진 WiredTiger는 **B+트리**다(WiredTiger에 LSM 코드가 있긴 했지만 MongoDB가 지원 옵션으로 노출한 적이 없고 이후 폐기됐다 — "B+트리"라고 보면 된다). 최적화 대상은 **"한 번의 조회로 화면 하나에 필요한 걸 다 가져오는 것"**이다. 주문 문서 안에 상세 배열을 통째로 넣으면 이 프로젝트의 4테이블 조인이 조회 1회가 된다. 대가는 **비정규화의 갱신 비용** — 메뉴 이름을 바꾸면 그 메뉴가 박힌 모든 주문 문서를 찾아 고쳐야 한다. 다중 문서 트랜잭션은 **4.0에서 복제셋 한정**으로, **샤딩 클러스터를 가로지르는 것은 4.2부터** 지원되지만, 단일 문서 원자성이 여전히 설계의 전제다.

**키-값 — Redis.** **인메모리 해시테이블**이 본체다. 키 조회가 O(1)이고, **명령 실행이 단일 스레드 이벤트 루프**라 명령 하나하나가 원자적이다(락이 필요 없다. 6.0부터 네트워크 I/O는 멀티스레드일 수 있지만 실행은 여전히 한 줄이다). 값 타입별로 자료구조가 다르고 **크기에 따라 인코딩이 승격**된다 — 작은 List/Hash/Sorted Set은 `listpack`이라는 연속 메모리 한 덩어리로 저장되다가 임계값(`list-max-listpack-size`, `zset-max-listpack-entries` 등)을 넘으면 각각 quicklist / skiplist+dict로 바뀐다. Sorted Set이 커진 뒤의 **스킵 리스트 + 해시** 조합이 "점수 순 랭킹 조회 O(log n) + 멤버 점수 조회 O(1)"을 동시에 만든다. **범위 스캔·조인·임의 조건 검색은 못 한다.** 인덱스가 키 하나뿐이기 때문이다. RDB 스냅샷/AOF로 디스크에 남기지만 기본은 휘발성이라고 보고 설계해야 한다.

**와이드 컬럼 — Cassandra / HBase.** **LSM 트리**다. 쓰기를 메모리(memtable)에 모았다가 정렬된 불변 파일(SSTable)로 순차 flush하고, 백그라운드에서 병합(compaction)한다. 랜덤 쓰기가 순차 쓰기로 바뀌므로 **쓰기 처리량이 압도적**이다. 대신 읽기는 여러 SSTable을 훑어야 해서 블룸 필터로 보완한다(블룸 필터는 "없다"를 확실히 말해 주고 "있다"는 위양성이 있을 수 있다 — 그래서 헛읽기를 줄여 줄 뿐 없애지는 못한다). 데이터 배치는 **파티션 키의 해시**로 노드가 정해지고, 파티션 안에서는 **클러스터링 키 순으로 정렬**된다. 그래서 "파티션 키를 알고 그 안에서 범위를 읽는" 접근만 빠르고, **조인이 없고 쿼리를 먼저 정하고 테이블을 그 쿼리에 맞춰 만든다**(query-first modeling).

**그래프 — Neo4j.** **index-free adjacency** — 각 노드가 이웃 노드의 물리 포인터를 직접 들고 있다. **한 홉 이동이 포인터 역참조라 그래프 전체 크기 N과 무관하게 O(1)**이다. 관계형에서 6단계 인맥을 찾으려면 자기 조인 6번인데, 매 조인마다 인덱스 탐색 O(log N)이 붙고 중간 결과가 폭발한다. 주의할 점: **"깊이가 늘어도 비용이 선형"인 게 아니다.** 전체 탐색 비용은 방문한 관계 수에 비례하므로 분기 계수 b, 깊이 d에 대해 대략 O(b^d)로 늘어난다. 이점은 "깊어도 싸다"가 아니라 **"홉 비용이 데이터 총량에 영향받지 않는다"**는 것이다. 대신 "모든 노드에 대한 집계"처럼 전역 스캔은 약하다.

**시계열 — InfluxDB / TimescaleDB.** 시간 축으로 **파티셔닝(청크/샤드)**하고 열 지향으로 압축한다. 타임스탬프는 델타-오브-델타, 부동소수 값은 XOR/Gorilla, 정수는 단순 델타+비트팩 계열 인코딩으로 원본의 수십 분의 1까지 줄인다. 최적화 대상은 **"최근 N시간의 특정 센서 값을 시간 버킷으로 집계"**다. 오래된 청크는 자동 삭제(retention policy)한다 — 파티션을 통째로 `DROP`하는 것이라 `DELETE`와 달리 사실상 공짜다(1.5에서 본 VACUUM 문제가 아예 발생하지 않는다). TimescaleDB는 **PostgreSQL 확장**이라 SQL과 조인을 그대로 쓴다 — 이게 중요한 선택지다.

**검색 — Elasticsearch.** **역색인(inverted index)**이다. "문서 → 단어"를 뒤집어 "단어 → 그 단어가 든 문서 목록"으로 저장한다. `LIKE '%라떼%'`는 전체 스캔이지만 역색인은 '라떼' 항목 하나만 보면 된다. 토크나이저/분석기가 색인 시점에 텍스트를 쪼개고 정규화하며, 자동완성은 **edge n-gram**('아', '아메', '아메리'…)으로 미리 색인해 만든다. 대가는 **근실시간(기본 refresh 1초)**, 트랜잭션 없음, 원본 저장소로 쓰면 안 된다는 점이다.

**임베디드 분석 — DuckDB.** "OLAP용 SQLite"다. 프로세스 안에서 도는 파일 DB인데 저장이 **열 지향**이고 실행기가 **벡터화**되어 있다. Parquet/CSV를 직접 SQL로 읽는다. 이 프로젝트의 `04_bonus.sql` 지표들을 수억 행 규모로 돌린다면 정확히 여기가 맞는 자리다.

**벡터 — pgvector / Pinecone / Qdrant.** 임베딩 벡터의 **근사 최근접 이웃(ANN)** 검색이 목적이다. HNSW(다층 근접 그래프)나 IVFFlat(클러스터 분할)로 정확도를 조금 포기하고 속도를 얻는다. `pgvector`는 PostgreSQL 확장이라 **벡터 유사도와 `WHERE category_id = 1` 필터를 한 쿼리에서 조인할 수 있다** — 별도 벡터 DB에는 없는 이점이다.

---

## 3. 고르는 기준은 '용도'가 아니라 '접근 패턴'

"로그니까 MongoDB"가 아니라, **"쓰기가 초당 5만 건이고, 조회는 항상 (기기ID, 시간범위)로만 하며, 조인이 없고, 30일 뒤 버린다"**이므로 시계열 DB나 Cassandra다. 아래 질문에 답하면 후보가 자동으로 좁혀진다.

**① 읽기/쓰기 비율과 접근 패턴의 모양은?**

| 접근 패턴 | 필요한 자료구조 | 후보 |
| --- | --- | --- |
| 키 하나로 값 하나 (O(1)) | 해시테이블 | Redis, DynamoDB |
| 정렬된 범위 스캔 | B+트리 | RDB 전반 |
| 여러 엔티티를 조건으로 결합 | B+트리 + 조인 옵티마이저 | PostgreSQL, MySQL |
| 관계를 여러 홉 추적 | 인접 포인터 | Neo4j |
| 단어로 문서 찾기 | 역색인 | Elasticsearch |
| 쓰기 폭주 + 파티션 내 범위 읽기 | LSM 트리 | Cassandra |
| 전체 스캔 후 집계 | 열 저장 | DuckDB, ClickHouse, BigQuery |
| 벡터 유사도 | HNSW/IVF | pgvector, Qdrant |

**② 스키마가 안정적인가, 조인이 필요한가?** 이 스키마의 `order_detail`은 컬럼 5개가 3년 뒤에도 그대로일 가능성이 높다 → RDB. 반대로 고객 리뷰의 첨부 메타데이터처럼 필드가 계속 늘어난다면 문서형이나 JSONB. **조인이 필요한데 조인 없는 DB를 고르면 그 조인을 애플리케이션 코드에서 for 루프로 짜게 된다** — 옵티마이저가 해 주던 일을 손으로 하는 것이고, 거의 항상 더 느리고 더 틀린다.

**③ 일관성이 얼마나 강해야 하는가?** 이게 가장 중요한 질문이다.

| 데이터 | 필요한 일관성 | 이유 |
| --- | --- | --- |
| `order_detail.unit_price`, 결제 금액 | **강한 일관성 필수** | 1원이 틀리면 회계가 안 맞는다. 되돌릴 수도 없다 |
| 메뉴 좋아요 수, 조회수 | 최종 일관성으로 충분 | 1분 뒤 반영돼도, 몇 개 틀려도 아무도 안 죽는다 |
| 좌석 재고 / 한정 메뉴 수량 | **강한 일관성 필수** | 초과 판매는 실제 손해다 |
| 추천 목록 | 최종 일관성 | 어차피 근사값이다 |

**"돈과 재고는 RDB, 그 외는 협상 가능"**이 실무의 기본선이다.

**④ 규모와 성장 속도 — 단일 노드로 되는가?** 현대 서버 한 대(64코어, 512GB RAM, NVMe)의 PostgreSQL은 **수억 행, 초당 수만 TPS**를 처리한다. 이 카페가 하루 1,000건 주문이면 연 36.5만 행이다. **10년치가 365만 행 — 노트북 SQLite로도 여유롭다.** 분산이 필요해지는 건 단일 노드 한계를 실제로 친 다음이고, 대부분의 팀은 거기까지 못 간다.

**⑤ 운영 인력과 생태계.** Cassandra 클러스터는 compaction 튜닝, repair 스케줄, 노드 교체를 아는 사람이 필요하다. 그 사람이 없으면 Cassandra는 **선택지가 아니다.** 이건 기술적 열등함이 아니라 조직의 제약이고, 아키텍처 결정에서 정당한 입력값이다.

**결정 표 (요약)**

| 상황 | 1순위 | 이유 |
| --- | --- | --- |
| 트랜잭션 + 조인 + 강한 일관성 | PostgreSQL | 기능 폭이 가장 넓고 확장으로 커버 범위가 크다 |
| 위와 같은데 팀이 MySQL에 익숙 | MySQL 8 | 생태계와 사람이 이긴다 |
| 단일 프로세스, 파일 하나, 동시 쓰기 거의 없음 | SQLite | 서버가 필요 없다 |
| 마이크로초 응답, 키 조회, 휘발 가능 | Redis | 인메모리 해시 |
| 초당 수만 쓰기, 조인 없음, 다중 리전 | Cassandra | LSM + 파티션 |
| 한국어 형태소 전문검색·자동완성 | Elasticsearch(+Nori) | 역색인 |
| 수십억 행 집계 리포트 | ClickHouse / DuckDB / BigQuery | 열 저장 |
| 스키마가 계속 변하는 부속 데이터 | PostgreSQL JSONB → 부족하면 MongoDB | JSONB로 대부분 커버된다 |

---

## 4. 같은 요구, 다른 선택 — 카페 도메인 확장 5개

### (a) 주문/결제 원장 → 관계형(PostgreSQL/MySQL). 논쟁의 여지가 없다

지금의 `order_header` + `order_detail`이다. **왜 RDB인가**: 원자성(header와 detail이 함께 커밋), 강한 일관성(금액), 선언적 제약(`CHECK (quantity > 0)`, FK), 그리고 **감사 가능성**. `unit_price`를 스냅샷으로 둔 설계 판단(가격이 바뀌어도 과거 매출 불변)은 관계형 모델링의 정석이고, 1.7에서 본 대로 **정규화 위반이 아니다** — `unit_price`는 `menu_id`에 함수 종속되지 않는 주문 라인 고유의 사실이다.

**왜 NoSQL이면 안 되는가**: 문서 DB에 주문을 통째 문서로 넣으면 조회는 편하지만, "이번 달 메뉴별 매출"을 뽑을 때 모든 문서를 스캔하며 배열을 펼쳐야 한다(`$unwind` + `$group`). 그리고 `menu.price`를 4000원으로 올리는 Q13 같은 작업이 **수만 문서의 배열 원소를 갱신하는 일**로 커진다. RDB에서는 `UPDATE menu SET price=4000 WHERE name='아메리카노'` 한 줄이고 과거 주문은 `unit_price` 덕에 자동으로 보존된다.

### (b) 실시간 대기번호·좌석 상태 → Redis. 단, RDB로도 충분히 된다

요구: 대기번호 발급, 현재 호출 번호, 좌석 12개의 점유 상태를 **초당 수백 번 조회**하고 화면에 즉시 반영.

**Redis가 맞는 이유**: `INCR wait:ticket`이 원자적으로 번호를 발급한다. 좌석 상태는 `HSET seat:status 3 occupied`. 데이터가 **작고, 휘발돼도 되고(가게 문 닫으면 리셋), 조회 빈도가 극단적으로 높고, 조인이 없다.** `EXPIRE`로 TTL도 공짜다. Pub/Sub으로 화면 갱신 푸시까지 한 곳에서 된다.

**사실 RDB로도 된다**: 좌석 12개짜리 테이블에 `UPDATE seat SET status='occupied' WHERE id=3`이면 끝이고, 하루 수천 번 갱신은 PostgreSQL에게 아무것도 아니다. **Redis를 도입하는 순간 저장소가 2개가 되고, 둘 사이의 정합성을 누가 맞출 것인가라는 새 문제가 생긴다.** 매장 하나면 RDB로 시작하고, 매장이 500개가 되어 좌석 조회가 DB 부하의 절반을 차지할 때 Redis를 앞에 세우는 게 순서다.

### (c) 메뉴 검색 자동완성 → Elasticsearch. 그런데 메뉴가 12개다

현재 `03_queries.sql` Q4-B는 `LIKE '%라떼%'`다. 실행계획을 떠 보면 `SCAN menu`다(1.8의 실측표). 앞이 열린 패턴이라 인덱스가 못 돕는다. **그리고 1.8에서 본 대로 SQLite에서는 앞을 고정한 `'라떼%'`도 기본 설정에서는 인덱스를 못 탄다.** 메뉴 12개면 무의미하지만 10만 개면 문제다.

**Elasticsearch가 맞는 이유**: '카라멜마키아또'를 '카라멜'로도 '마키아또'로도 찾아야 하고, 오타('아메리까노')를 교정해야 하고, 한글 초성 검색('ㅇㅁㄹㅋㄴ')이 필요하고, 인기순 가중치를 얹어 랭킹해야 한다면 이건 **검색 문제**지 조회 문제가 아니다. Nori 형태소 분석기 + edge n-gram이 필요하다.

**PostgreSQL로도 상당히 되지만, 조건이 있다**: `pg_trgm` 확장 + GIN 인덱스면 `%검색어%`도 인덱스를 탄다. 오타 허용(유사도 검색)도 `similarity()`로 된다. **다만 `pg_trgm`은 이름 그대로 3글자 단위 트라이그램이라 검색어가 3글자 이상일 때만 인덱스가 산다.** 하필 이 예제의 '라떼'는 2글자다 — 유효한 트라이그램이 만들어지지 않아 GIN 인덱스가 후보를 좁히지 못하고 순차 스캔으로 떨어진다. 2글자 검색까지 커버하려면 별도 n-gram 컬럼을 만들거나 검색 엔진으로 가야 한다. 한국어 형태소 분석도 약하다. **그래도 메뉴 수천 ~ 수만 개 구간에서 3글자 이상 검색이 주라면 PostgreSQL이 정답이고, Elasticsearch는 오버엔지니어링이다.**

### (d) 매장별 센서/판매 시계열 대시보드 → 시계열 DB

요구: 500개 매장의 에스프레소 머신 온도·추출압력을 **10초마다** 수집, 최근 7일을 5분 버킷으로 그래프.

계산해 보자. 500 매장 × 센서 4개 × 6회/분 × 60 × 24 = **일 1,728만 행**. 1년이면 63억 행이다. **여기가 RDB의 한계다** — B+트리는 삽입마다 인덱스를 갱신하고, 63억 행에 인덱스를 유지하는 비용과 저장 공간이 폭발한다. 그리고 1.5에서 본 문제가 여기서 커진다. 30일 지난 데이터를 `DELETE`로 지우면 공간이 즉시 반환되지 않고, PostgreSQL이면 죽은 튜플이 쌓여 autovacuum이 따라오지 못한다.

**시계열 DB가 맞는 이유**: 시간 축 파티셔닝으로 "최근 7일"이 청크 7개만 읽는다. 열 지향 압축으로 저장이 10~20배 줄고, 오래된 데이터는 retention policy로 **파티션을 통째로 `DROP`**해 사실상 공짜로 지워지며(삭제 후 VACUUM 문제가 아예 없다), 5분 버킷 집계(`time_bucket`)가 내장 함수다.

**중간 선택지**: TimescaleDB는 PostgreSQL 확장이므로 **매출 테이블과 센서 하이퍼테이블을 같은 DB에서 조인할 수 있다.** 저장소를 늘리지 않고 시계열 이점을 얻는 길이다. 하루 1,000건 주문의 매출 그래프 정도라면 **애초에 지금의 `order_header`로 충분하다** — 규모를 먼저 계산하고, 계산이 한계를 넘을 때만 옮긴다.

### (e) 고객 리뷰의 자유로운 스키마 → 문서 DB 또는 PostgreSQL JSONB

리뷰에는 별점·본문 외에 사진 URL 배열, 태그, 맛/분위기/친절도 세부 평점, 나중에 추가될 "재방문 의사" 같은 필드가 붙는다. **컬럼을 미리 다 정할 수 없다.**

**PostgreSQL JSONB로 하는 법**:

```sql
CREATE TABLE review (
    id          BIGSERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customer(id),   -- 핵심 관계는 컬럼으로
    order_id    INTEGER REFERENCES order_header(id),
    rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
    attributes  JSONB NOT NULL DEFAULT '{}'::jsonb,          -- 유동 필드만 JSONB
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_review_attributes ON review USING GIN (attributes);
```

`rating`에 `NOT NULL`을 붙인 것이 1.6의 교훈이다. `CHECK (rating BETWEEN 1 AND 5)`만으로는 NULL 별점을 못 막는다.

**핵심 원칙: 관계와 제약이 필요한 것은 컬럼으로, 나머지만 JSONB로.** `customer_id`를 JSONB에 넣으면 FK도 조인도 못 하고, 1.7에서 본 정규화 논의 자체가 성립하지 않는다. 이 절충이 실무의 기본형이다.

**MySQL 8도 `JSON` 타입이 있다.** 8.0.17부터 JSON 배열에 대한 **multi-valued index**가 추가되어 배열 원소 조회는 인덱스를 탈 수 있고, 그 밖에는 생성 컬럼(generated column) + 인덱스로 우회한다. 다만 GIN처럼 문서 전체를 통째로 색인해 **임의 경로 조회를 한 인덱스로 커버하지는 못한다.** **SQLite도 `json_extract()`(3.38부터 JSON 함수 기본 내장)와 JSONB 이진 포맷(3.45+)을 지원한다** — 다만 이 프로젝트 규모에서는 그냥 컬럼을 늘리는 게 낫다.

### 성급한 NoSQL 도입이 실패하는 전형적 경로

1. "확장성"을 이유로 MongoDB를 고른다. 실제 데이터는 200만 행이고 PostgreSQL이면 노트북에서도 돌아간다.
2. 조인이 없으니 애플리케이션에서 주문 목록을 가져온 뒤 각 주문마다 고객을 조회한다 → **N+1 쿼리**.
3. 그게 느려서 고객 이름을 주문 문서에 복사한다 → 1.7의 용어로는 **이행 종속을 일부러 만든 것**이다. 고객이 개명하면 **과거 주문의 이름이 안 바뀐다.** 어떤 화면은 옛 이름, 어떤 화면은 새 이름을 보여준다(갱신 이상).
4. `CHECK (status IN ('PENDING','COMPLETED','CANCELLED'))`가 없으니 어느 날 `'Completed'`, `'done'`, `null`이 섞여 들어온다. **집계 쿼리가 조용히 틀린 값을 낸다** — 특히 `status <> 'CANCELLED'` 같은 부정 조건은 1.6의 3값 논리 때문에 `null` 행을 통째로 빠뜨린다.
5. 결국 애플리케이션 코드에 검증 로직과 조인 로직을 다시 짠다 — **DB가 해 주던 일을 손으로 재구현한 것**이고, 버그는 이제 코드 전체에 흩어져 있다.

핵심은 **"NoSQL이 나쁘다"가 아니다.** 3번과 4번의 대가를 치를 준비 없이 1번을 한 것이 문제다. Cassandra를 쓰는 넷플릭스는 그 대가를 알고 치른다.

### "PostgreSQL 하나로 대부분 된다"는 반론 — 정직하게

| 하려는 것 | PostgreSQL 안의 답 |
| --- | --- |
| 문서 저장 | JSONB + GIN |
| 전문검색 | `tsvector` + `pg_trgm` (단, trgm은 3글자 이상) |
| 시계열 | 파티셔닝 또는 TimescaleDB |
| 벡터 검색 | pgvector (HNSW) |
| 작업 큐 | `SELECT ... FOR UPDATE SKIP LOCKED` |
| Pub/Sub | `LISTEN` / `NOTIFY` |
| 지리 정보 | PostGIS |

**PostgreSQL이 정말 안 되는 것도 있다**: 마이크로초 단위 캐시 응답(Redis가 훨씬 빠르다 — 디스크·WAL·MVCC를 거치지 않으므로 자릿수가 다르다), 한국어 형태소 분석 품질(Nori에 견줄 만큼 관리되는 확장이 없다), 수십억 행 애드혹 집계(열 저장이 아니다), 자동 수평 샤딩(Citus 같은 확장이 필요하다), 다중 리전 다중 마스터 쓰기.

**실무 결론**: PostgreSQL 하나로 시작한다. **부족함이 실제 지표로 증명될 때** 그 부분만 떼어낸다. 저장소를 늘리는 결정은 "정합성을 맞춰야 할 경계가 하나 늘어나는 결정"이기 때문이다.

---

## 5. CAP와 PACELC — 흔한 오해 교정

**가장 흔한 오해**: "MongoDB는 CP고 Cassandra는 AP다. 그래서 Cassandra는 일관성이 없다."

**정확한 진술**: CAP 정리는 **네트워크 분할(Partition)이 실제로 일어난 순간**에 무엇을 포기할지를 말한다. 분할은 선택지가 아니라 **주어지는 조건**이다(네트워크는 언젠가 끊긴다). 그러므로 진짜 선택지는 **CP냐 AP냐** 둘뿐이고, "CA 시스템"은 분산 환경에서 존재하지 않는다. 그리고 CAP의 C는 **선형화 가능성(linearizability)**이라는 아주 강한 정의이지, ACID의 C(제약 만족)와는 다른 것이다 — 이 둘을 같은 글자로 섞어 쓰는 것도 흔한 혼동이다.

| 분할 발생 시 | 선택 | 카페 예시 |
| --- | --- | --- |
| **CP** — 일관성 유지, 가용성 포기 | 다수파에 못 닿으면 **에러를 반환** | 결제 원장. 확실하지 않으면 결제를 거절하는 게 옳다 |
| **AP** — 가용성 유지, 일관성 포기 | 일단 받고 **나중에 수렴**시킨다 | 메뉴 좋아요 수. 잠깐 숫자가 달라도 된다 |

**두 번째 오해**: "단일 노드 PostgreSQL은 CAP에서 어디인가?" — **CAP이 적용되지 않는다.** 분할될 노드가 없으니 P가 발생하지 않는다. 이 프로젝트의 SQLite도 마찬가지다. **CAP은 분산 시스템의 정리이지 DB 일반의 정리가 아니다.**

**PACELC**이 더 유용하다. CAP이 다루지 않는 **평상시**를 포함하기 때문이다.

> **P**artition이 나면 **A**vailability냐 **C**onsistency냐, **E**lse(정상 작동 중이면) **L**atency냐 **C**onsistency냐.

정상 상태에서도 트레이드오프는 계속 있다. 3개 복제본 모두의 확인을 기다리면(강한 일관성) 응답이 느리고, 1개만 확인하고 응답하면 빠르지만 방금 쓴 걸 다른 노드에서 못 읽을 수 있다. Cassandra는 `QUORUM` / `ONE` 같은 **요청 단위 설정**으로 이 다이얼을 돌린다 — 쓰기 W + 읽기 R > 복제 수 N이면 강한 일관성을 얻는다. 즉 "Cassandra = AP"라는 라벨 자체가 부정확하다. **일관성은 DB의 속성이 아니라 요청의 설정일 수 있다.**

| 시스템 | PACELC |
| --- | --- |
| Cassandra / DynamoDB | PA/EL (기본), 설정으로 PC/EC까지 |
| MongoDB | PC/EC (기본 primary 읽기) |
| PostgreSQL 동기 복제 | PC/EC |
| PostgreSQL 비동기 복제 | PC/EL — 읽기 복제본에 복제 지연이 있다 |

**복제 지연은 실무에서 매일 만나는 문제다.** 주문을 넣자마자 읽기 복제본에서 조회하면 "방금 넣은 주문이 없다"가 나온다. 해결은 "쓰기 직후 읽기는 primary로" 라우팅하는 것이다(read-your-writes).

---

## 6. OLTP vs OLAP — `04_bonus.sql`의 지표들은 사실 OLAP이다

| | OLTP (온라인 트랜잭션 처리) | OLAP (온라인 분석 처리) |
| --- | --- | --- |
| 한 번에 다루는 행 | 1~수십 행 | 수백만~수십억 행 |
| 쓰는 컬럼 | 행 전체 | **몇 개 컬럼만** |
| 쿼리 모양 | `WHERE id = ?` | `GROUP BY` + `SUM/AVG` |
| 동시성 | 초당 수천 요청 | 초당 몇 건, 대신 무겁다 |
| 저장 구조 | **행 저장** | **열 저장** |
| 예 | 주문 넣기, 로그인 | 월별 매출 리포트 |

이 프로젝트를 나눠 보면 성격이 갈린다.

| 쿼리 | 성격 | 근거 |
| --- | --- | --- |
| Q1, Q4 (`WHERE` + `LIMIT` 조회) | OLTP | 소수 행을 조건으로 집는다 |
| Q13 `UPDATE menu SET price=4000` | OLTP | 1행 갱신 (`name` UNIQUE라 반드시 1행) |
| `04_bonus.sql` 지표 1 (일자별 매출) | **OLAP** | 전 기간 스캔 + `GROUP BY` + `SUM` |
| 지표 2 (인기 메뉴 TOP 5) | **OLAP** | 전체 집계 후 랭킹 |
| 지표 3 (VIP TOP 3) | **OLAP** | 전체 집계 후 랭킹 |

실행 계획을 실제로 떠 보면 성격이 그대로 드러난다(커밋된 `cafe.db`에서 실측).

```text
EXPLAIN QUERY PLAN
SELECT DATE(oh.order_date), SUM(od.quantity*od.unit_price)
FROM order_header oh JOIN order_detail od ON od.order_id = oh.id
WHERE oh.status='COMPLETED' GROUP BY DATE(oh.order_date);

SCAN od
SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)
USE TEMP B-TREE FOR GROUP BY
```

읽는 법은 이렇다. **`SCAN od`** — `order_detail`을 처음부터 끝까지 읽는다. 인덱스가 안 쓰인 게 아니라 **쓸 이유가 없다.** 어차피 전부 필요하기 때문이다. **`SEARCH oh USING INTEGER PRIMARY KEY (rowid=?)`** — 옵티마이저가 `order_detail`을 바깥 루프로 잡고, 각 상세 행마다 `order_header`를 PK로 찍는 nested loop를 택했다(`order_header.id`가 `INTEGER PRIMARY KEY`라 rowid 그 자체다). 그리고 `GROUP BY DATE(oh.order_date)`는 컬럼이 아니라 **함수 결과**로 묶으므로 인덱스가 원리적으로 못 돕고, 정렬을 위해 임시 B트리를 만든다. 지표 1의 전체 쿼리를 그대로 돌리면 `COUNT(DISTINCT oh.id)` 때문에 `USE TEMP B-TREE FOR count(DISTINCT)` 한 줄이 더 붙는다(실측).

20행에서는 아무 문제가 없다. 하지만 **2천만 행이면 이 쿼리 하나가 디스크를 통째로 읽고, 그동안 같은 DB에서 주문을 받는 OLTP 트랜잭션들이 I/O를 뺏긴다.** 리포트 하나가 주문 시스템을 느리게 만드는 것이다. SQLite라면 여기에 하나가 더 붙는다 — 1.2에서 본 대로 writer가 하나뿐이므로, 이 긴 읽기 자체는 쓰기를 막지 않더라도 캐시와 I/O 대역이 통째로 먹힌다.

**왜 열 저장이 답인가.** 행 저장은 `(id, order_id, menu_id, quantity, unit_price)`를 붙여서 저장하므로, `SUM(quantity * unit_price)`만 필요해도 **`id`와 `menu_id`까지 디스크에서 읽어 온다.** 열 저장은 컬럼별로 따로 모아두므로 `quantity`와 `unit_price` 두 열만 읽는다 — 이 테이블에서 **읽는 양이 5분의 2로 준다.** 게다가 같은 컬럼의 값은 성질이 비슷해서 압축률이 훨씬 높고(`unit_price`에는 3500, 4500, 5000이 반복된다 — 사전 인코딩이나 RLE가 잘 먹는다), CPU가 값을 벡터 단위로 한꺼번에 처리할 수 있다.

**그래서 실무의 해법**: OLTP DB(PostgreSQL)와 OLAP 저장소(ClickHouse, BigQuery, DuckDB)를 분리하고 ETL/CDC로 밤에 복사한다. 다만 **이 카페 규모에서는 절대 하면 안 되는 짓**이다 — 125,500원어치 매출 9행에 데이터 웨어하우스를 세울 이유는 없다. **알아야 할 것은 "지금 이 쿼리가 OLAP 성격이다"라는 인식이지, 지금 분리하는 것이 아니다.**

---

## 7. 면접 예상 질문 6개 + 그대로 읽을 답변 대본

### Q1. "이 프로젝트를 왜 SQLite로 했나요?"

> "요구사항이 단일 사용자, 파일 하나, 재현 가능한 학습용 산출물이었습니다. SQLite는 서버 프로세스가 없어서 `python build_and_capture.py` 한 줄로 채점자가 제 환경을 그대로 재현할 수 있고, `cafe.db` 파일 하나를 그대로 커밋할 수 있습니다.
> 동시 쓰기가 없다는 점도 컸습니다. SQLite는 쓰기 트랜잭션 중에 다른 커넥션이 다른 테이블을 **쓰려고 하면** `database is locked`가 납니다 — 쓰기 락 단위가 파일 전체거든요. 다만 읽기는 그동안에도 됩니다. 제가 커넥션 두 개로 확인했는데, A가 커밋 안 한 상태에서도 B는 정상적으로 옛 값을 읽었고 쓰기만 막혔습니다. 웹 서버였으면 이게 치명적이지만, 이 프로젝트는 단일 프로세스라 제약이 아니었습니다.
> 다만 SQLite를 고른 대가도 압니다. 타입 어피니티 때문에 `price INTEGER`에 실제로 문자열이 들어갑니다. 제가 직접 넣어 봤는데 `'비싼값'`이 그대로 저장되고 `typeof`가 `text`로 나왔습니다. `CHECK (price >= 0)`도 통과했고요 — SQLite의 타입 정렬 순서에서 TEXT는 어떤 숫자보다 크게 비교되기 때문에 `'비싼값' >= 0`이 참이 됩니다. 실서비스라면 3.37부터 지원하는 STRICT 테이블을 쓰거나 PostgreSQL로 갔을 겁니다. STRICT 테이블에서 같은 걸 시도하면 `cannot store TEXT value in INTEGER column`으로 막힙니다."

### Q2. "MySQL로 바꾼다면 뭘 고쳐야 하나요?"

> "제 스키마 기준으로 열 가지를 고쳐야 합니다."

| # | SQLite (현재) | MySQL 8 | 이유 |
| --- | --- | --- | --- |
| 1 | `INTEGER PRIMARY KEY AUTOINCREMENT` | `INT AUTO_INCREMENT PRIMARY KEY` (또는 `BIGINT`) | 키워드 자체가 다르다. SQLite의 `AUTOINCREMENT`는 "테이블 수명 전체에 걸쳐 과거 값을 재사용하지 않는 단조 증가" 보장이고(없어도 자동 증가는 되지만 최대 rowid 행이 삭제되면 그 값이 재사용될 수 있다), MySQL의 `AUTO_INCREMENT`는 단순 자동 증가다 |
| 2 | `joined_at DATE DEFAULT (DATE('now'))` | `joined_at DATE NOT NULL DEFAULT (CURDATE())` | `DATE('now')`는 SQLite 함수. 게다가 **MySQL은 8.0.13부터** DATE 컬럼에 함수 기본값(괄호 친 표현식 DEFAULT)을 허용한다. 그 이전 버전이면 애플리케이션이 값을 넣어야 한다 |
| 3 | `order_date DATETIME DEFAULT CURRENT_TIMESTAMP` | `DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP` | 그대로 되지만 **SQLite는 UTC, MySQL은 세션 타임존**이라 날짜 경계가 달라진다. 지표 1의 `sales_date`가 바뀔 수 있다 |
| 4 | `name TEXT` | `name VARCHAR(50)` / `email VARCHAR(255)` | MySQL의 `TEXT`는 인덱스에 길이 지정(prefix)이 필요하고 prefix 인덱스로는 UNIQUE의 의미가 온전하지 않다. `email UNIQUE`가 걸려 있으니 `VARCHAR`여야 한다 |
| 5 | `is_available INTEGER CHECK (IN (0,1))` | `TINYINT(1)` 또는 `BOOLEAN` | MySQL `BOOLEAN`은 `TINYINT(1)`의 별칭이라 2, 7 같은 값도 들어간다. CHECK를 남겨두는 게 안전하다. **PostgreSQL이면 진짜 `BOOLEAN` 타입이라 CHECK 자체가 불필요해진다** |
| 6 | `status TEXT CHECK (IN (...))` | CHECK 유지 또는 `ENUM('PENDING','COMPLETED','CANCELLED')` | **MySQL은 8.0.16 이전에 CHECK를 파싱만 하고 무시했다.** 버전 확인이 필수다 |
| 7 | `PRAGMA foreign_keys = ON;` | **삭제** | InnoDB는 FK를 항상 강제한다. 스위치가 없다 |
| 8 | (없음) | `ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci` | MyISAM은 트랜잭션도 FK도 없다. `utf8`(3바이트)이 아니라 반드시 `utf8mb4` — 한글 이름과 이모지 |
| 9 | `CREATE INDEX idx_order_header_customer_id` | **불필요(중복)** | **InnoDB는 FK를 정의하면 인덱스를 자동 생성한다.** SQLite와 PostgreSQL은 안 해 준다. 제 `idx_order_detail_order_id`가 SQLite에서 꼭 필요했던 이유가 이겁니다 — `ON DELETE CASCADE`가 부모 1행 삭제마다 자식 전체를 훑거든요 |
| 10 | 타입 어피니티 | `sql_mode=STRICT_TRANS_TABLES` (8.0 기본) | Q1에서 본 `'비싼값'` 삽입이 여기서는 에러가 된다 |

> "추가로 `sqlite_sequence` 테이블이 사라지고, `EXPLAIN QUERY PLAN` 대신 `EXPLAIN ANALYZE`를 씁니다. 그리고 스키마 변경 전략이 달라집니다 — SQLite에서는 여러 DDL을 한 트랜잭션으로 묶어 롤백할 수 있는데 MySQL은 DDL이 암묵적 커밋을 일으켜서 못 합니다. MySQL 8.0의 atomic DDL 덕에 문장 하나는 원자적이지만, 마이그레이션 스크립트가 중간에 실패하면 앞의 ALTER는 이미 커밋돼 있습니다. 그래서 MySQL 마이그레이션은 각 단계가 독립적으로 재실행 가능(idempotent)하도록 짜야 합니다.
> 지표 1의 `DATE(oh.order_date)`는 MySQL에도 `DATE()`가 있어 그대로지만, **PostgreSQL이면 `CAST(order_date AS DATE)`나 `order_date::date`로 바꿔야 합니다.**"

### Q3. "트랜잭션이 왜 필요한지 이 프로젝트로 설명해 보세요."

> "주문 한 건이 테이블 두 개에 걸쳐 있기 때문입니다. `order_header` 1행과 `order_detail` N행인데, 중간에 앱이 죽으면 상세가 하나도 없는 주문 헤더가 남습니다. 그러면 제 매출 쿼리는 `order_header JOIN order_detail`이라 그 주문이 조인에서 탈락해서, 데이터가 틀린 게 아니라 **없는 것처럼 보입니다.** 이게 더 위험합니다.
> `04_bonus.sql`에서 실제로 확인했습니다. 신규 고객과 그 주문을 `BEGIN` 안에서 넣고 `ROLLBACK` 했더니 `customer_left=0`, `order_left=0`이 나왔습니다. 트랜잭션 안에서는 보이던 데이터가 롤백 후 흔적 없이 사라지는 게 원자성입니다.
> 실무에서는 `BEGIN`이 아니라 `BEGIN IMMEDIATE`를 씁니다. 그냥 `BEGIN`은 락을 미뤘다가 첫 쓰기에서 승격하려 하는데, 그 사이 다른 커넥션이 락을 가져가면 이미 읽기를 마친 트랜잭션이 실패해서 재시도가 지저분해집니다. `IMMEDIATE`는 시작 시점에 실패하니까 깨끗하게 다시 시작할 수 있습니다."

### Q4. "격리 수준을 아는 대로 말해 보세요."

> "네 단계고, 각 단계가 어떤 이상 현상을 허용하느냐로 나뉩니다. READ UNCOMMITTED는 커밋 안 된 값을 읽는 dirty read를 허용하고, READ COMMITTED는 그건 막지만 같은 행을 두 번 읽을 때 값이 바뀌는 non-repeatable read가 납니다. REPEATABLE READ는 그것도 막지만 조건에 맞는 **행 수**가 바뀌는 phantom이 표준상 남고, SERIALIZABLE은 전부 막습니다.
> 중요한 건 **기본값과 구현이 DB마다 다르다**는 겁니다. MySQL InnoDB는 REPEATABLE READ가 기본이고 next-key 락으로 phantom까지 대부분 막습니다. PostgreSQL은 READ COMMITTED가 기본이고, READ UNCOMMITTED를 요청해도 READ COMMITTED로 동작해서 **dirty read 자체가 불가능**합니다. PostgreSQL의 REPEATABLE READ는 스냅샷이라 phantom도 없지만 대신 write skew가 생길 수 있고요. SQLite는 파일 락이라 사실상 SERIALIZABLE입니다.
> 같은 SERIALIZABLE이라도 실패 모드가 정반대입니다. PostgreSQL은 SSI라서 낙관적으로 진행하다가 나중에 SQLSTATE 40001로 트랜잭션을 취소합니다 — 그래서 **애플리케이션에 재시도 루프가 없으면 안 됩니다.** MySQL은 읽기를 공유 락으로 승격해서 막으니까 재시도 대신 데드락과 대기 시간이 문제가 됩니다.
> 제가 커넥션 두 개로 직접 확인했습니다. A가 아메리카노 가격을 9999로 바꾸고 커밋 안 한 상태에서 B는 3500을 읽었고 — 읽기는 막히지 않았습니다 — B가 **다른 메뉴 행**을 수정하려 하자 `database is locked`가 났습니다. SQLite는 쓰기 락 단위가 행이나 테이블이 아니라 데이터베이스 파일 전체이기 때문입니다."

### Q5. "SQL 인젝션은 어떻게 막나요?"

> "파라미터 바인딩입니다. 문자열 포매팅으로 SQL을 만들면 안 됩니다.
> 제 DB에 직접 시도해 봤습니다. `email`에 `' OR 1=1 --`를 넣고 `%` 포매팅으로 조립하니 `WHERE email = '' OR 1=1 --'`가 되어 **customer 10행이 전부 나왔습니다.** 같은 값을 `?`로 바인딩하면 0행입니다 — 그런 이메일을 가진 고객이 없으니까요.
> 원리가 중요합니다. 이스케이프를 잘해서 막는 게 아니라, **바인딩된 값은 파싱이 끝난 뒤에 전달돼서 애초에 문법이 될 기회가 없습니다.** 그래서 따옴표 치환 같은 수동 방어는 안전하지 않습니다.
> 다만 바인딩으로 못 막는 곳도 압니다. 테이블명, 컬럼명, `ORDER BY` 방향은 바인딩이 안 되니까 화이트리스트로 처리해야 합니다. 저는 `{"price": "m.price", ...}` 같은 dict로 매핑하고 없는 키는 기본값으로 떨어뜨립니다."

### Q6. "이 서비스가 커지면 SQLite로 부족한 지점은 어디이고, 그때 뭘 어떻게 고르시겠습니까?"

> "먼저 **숫자로 확인**하겠습니다. 하루 1,000건 주문이면 연 36.5만 행이고, 10년치 365만 행은 SQLite로도 여유롭습니다. **부족해지는 건 행 수가 아니라 동시 쓰기입니다.** 매장이 여러 곳이 되어 여러 프로세스가 동시에 주문을 넣는 순간 `database is locked`가 실제 장애가 됩니다. 중간 단계로 `journal_mode=WAL`을 켜면 읽기와 쓰기가 서로를 안 막게 되지만 writer는 여전히 하나입니다. 그 한계를 치면 PostgreSQL로 갑니다 — 조인, 트랜잭션, 강한 일관성이 필요한 주문·결제 원장은 관계형이 유일한 답이기 때문입니다.
> 그다음은 **접근 패턴별로** 봅니다. 대기번호와 좌석 상태는 키 조회가 초당 수백 번이고 휘발돼도 되니 Redis가 맞습니다. 다만 매장이 하나일 때는 `UPDATE seat SET status=...` 한 줄로 충분하니 **저장소를 늘리지 않겠습니다.** 저장소가 두 개가 되는 순간 둘 사이 정합성이라는 새 문제가 생기니까요.
> 센서 데이터처럼 매장 500개 × 10초 간격이면 하루 1,728만 행이 나오는데, 여기는 B+트리 인덱스 유지 비용이 못 버팁니다. 게다가 30일 지난 데이터를 `DELETE`로 지우면 공간이 바로 안 돌아옵니다 — 제가 이 프로젝트에서 확인한 게 그건데, Q14로 4행을 지웠는데 파일이 전혀 안 줄었고 `freelist_count`도 0이었습니다. 시계열 DB는 파티션을 통째로 `DROP`하니까 이 문제가 아예 없습니다. 구체적으로는 PostgreSQL 확장인 TimescaleDB를 먼저 보겠습니다 — 매출 테이블과 같은 DB에서 조인할 수 있으니까요.
> 그리고 제 `04_bonus.sql`의 일자별 매출 쿼리는 사실 OLAP 성격입니다. 실행 계획에 `SCAN od`와 `USE TEMP B-TREE FOR GROUP BY`가 뜨는데, 지금 20행에서는 문제가 없지만 수천만 행이 되면 이 리포트 하나가 주문 트랜잭션의 I/O를 빼앗습니다. 그때 분석용 저장소를 분리합니다. **원칙은 하나입니다 — PostgreSQL로 시작하고, 부족함이 지표로 증명될 때만 그 부분을 떼어냅니다.**"

---

## 8. 이 모듈에서 반드시 가져갈 세 문장

1. **"데이터베이스 사용법"은 SQL 문법이 아니라 트랜잭션·격리·바인딩·NULL 논리·마이그레이션·백업·오류 처리다.** 스키마를 잘 그려도 이걸 모르면 운영을 못 한다. 그리고 이 중 어느 것도 "대충 이럴 것이다"로 넘어가면 안 된다 — `EXPLAIN`을 뜨고 `freelist_count`를 세고 두 커넥션을 실제로 열어 본 뒤에야 아는 것이 된다.
2. **DB는 용도가 아니라 접근 패턴으로 고른다.** "로그니까 MongoDB"가 아니라 "쓰기 초당 5만, 조회는 (키, 시간범위)뿐, 조인 없음, 30일 뒤 폐기"라서 시계열 DB다. 그리고 그 접근 패턴을 O(1)/O(log n)으로 만드는 자료구조(해시 / B+트리 / LSM / 역색인 / 인접 포인터)가 무엇인지까지 말할 수 있어야 고른 것이다.
3. **저장소를 늘리는 결정은 정합성 경계를 하나 늘리는 결정이다.** 규모를 실제로 계산하고, 단일 노드 PostgreSQL의 한계를 실제로 친 다음에 옮긴다.

---

## 보강 — 평가 피드백 재점검에서 추가된 것


### 1.6 스키마를 바꾸는 법 — SQLite의 ALTER TABLE은 반쪽이다

`CHECK (status IN ('PENDING','COMPLETED','CANCELLED'))`에 `'REFUNDED'`를 추가하고 싶다고 하자. 여기서 DBMS 차이가 정면으로 드러난다.

| 하려는 일 | SQLite 3.46 | MySQL 8 | PostgreSQL |
|---|---|---|---|
| 컬럼 추가 | `ALTER TABLE ... ADD COLUMN` 가능 (기본값은 상수만) | 가능 | 가능 |
| 컬럼 이름 변경 | 3.25+ 가능 | 가능 | 가능 |
| 컬럼 삭제 | 3.35+ 가능 (단 인덱스/CHECK에 걸린 컬럼은 거부) | 가능 | 가능 |
| **CHECK 제약 수정/삭제** | **불가** — `ADD CONSTRAINT` 문법 자체가 없다 | `ALTER TABLE ... DROP CHECK c` | `DROP CONSTRAINT` / `ADD CONSTRAINT` |
| 컬럼 타입 변경 | 불가 | `MODIFY COLUMN` | `ALTER COLUMN ... TYPE` |

SQLite에서 `order_header.status`의 CHECK를 바꾸려면 공식 문서가 정한 **12단계 테이블 재작성** 절차를 밟아야 한다. 실무에서 쓰는 축약형은 이렇다.

```sql
PRAGMA foreign_keys = OFF;      -- 재작성 중 FK가 중간 상태를 보고 터지지 않게
BEGIN;
CREATE TABLE order_header_new (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL,
    order_date  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status      TEXT NOT NULL DEFAULT 'PENDING'
                CHECK (status IN ('PENDING','COMPLETED','CANCELLED','REFUNDED')),
    FOREIGN KEY (customer_id) REFERENCES customer(id)
);
INSERT INTO order_header_new SELECT id, customer_id, order_date, status FROM order_header;
DROP TABLE order_header;
ALTER TABLE order_header_new RENAME TO order_header;
CREATE INDEX idx_order_header_customer_id ON order_header(customer_id);  -- 인덱스는 같이 안 따라온다
PRAGMA foreign_key_check;       -- 커밋 전에 고아 행이 없는지 직접 확인
COMMIT;
PRAGMA foreign_keys = ON;
```

놓치기 쉬운 두 가지: (1) `DROP TABLE order_header`는 `order_detail`의 `ON DELETE CASCADE`를 **발동시키지 않는다** — DROP은 DML이 아니라 DDL이라 트리거/CASCADE 대상이 아니다. 다만 FK를 켜 둔 채로 하면 참조 중인 부모를 지운다며 막힐 수 있어 위에서 껐다. (2) **인덱스는 새 테이블로 따라오지 않는다.** Q15에서 만든 인덱스를 다시 만들어야 한다.

### 1.7 백업과 복구 — 파일 복사는 백업이 아니다

```bash
# 나쁨: 쓰기가 진행 중이면 찢어진 파일이 복사된다
cp cafe.db backup.db

# 좋음 1) 온라인 백업 API — 다른 커넥션이 쓰는 중에도 일관된 스냅샷
sqlite3 cafe.db ".backup backup.db"
sqlite3 cafe.db "VACUUM INTO 'backup.db'"   # 3.27+, 조각 정리까지 겸함

# 좋음 2) 논리 백업 — 텍스트라 diff/git 가능, 버전 이식 가능
sqlite3 cafe.db .dump > cafe_dump.sql
sqlite3 restored.db < cafe_dump.sql

# 무결성 확인
sqlite3 cafe.db "PRAGMA integrity_check; PRAGMA foreign_key_check;"
```

| | SQLite | MySQL 8 | PostgreSQL |
|---|---|---|---|
| 논리 백업 | `.dump` | `mysqldump` | `pg_dump` |
| 물리/온라인 백업 | `.backup`, `VACUUM INTO` | `mysqlbackup`, 클론 플러그인 | `pg_basebackup` |
| 시점 복구(PITR) | 없음(WAL은 체크포인트되면 사라진다) | binlog | WAL 아카이빙 |

### 1.8 콘솔 손놀림 — 평가장에서 손이 멈추지 않게

```bash
sqlite3 cafe.db
```
```text
.headers on
.mode box            -- 표로 예쁘게. 결과를 짚으며 말하기 쉬워진다
.tables              -- 테이블 목록
.schema order_detail -- 이 테이블의 CREATE 문 원문
.indexes order_header
.read 03_queries.sql
.timer on            -- 각 쿼리 실행 시간
.eqp on              -- 이후 모든 쿼리에 실행계획을 자동으로 붙여 출력
.once out.txt        -- 다음 한 번의 결과만 파일로
.quit
```
```sql
PRAGMA table_info(order_detail);       -- 컬럼·타입·NOT NULL·기본값·PK 여부
PRAGMA foreign_key_list(order_detail); -- 이 테이블이 건 FK 전부와 on_delete 동작
PRAGMA index_list(order_header);
PRAGMA foreign_keys;                   -- 실측: cafe.db 새 연결에서 0 이다. 매 연결 켜야 한다
```

### 1.9 이 항목의 30초 대본

> "DB 사용법을 SQL 문법이 아니라 세 층으로 나눠서 봅니다. 첫째 트랜잭션 — 이 프로젝트에서 주문 한 건은 `order_header` 1행과 `order_detail` N행이라 INSERT 3번이 한 단위여야 하고, 그래서 `BEGIN IMMEDIATE`로 묶습니다. 둘째 스키마 변경 — SQLite는 CHECK를 고치는 ALTER가 없어서 테이블 재작성 12단계를 밟아야 하고, 그때 인덱스는 따라오지 않으니 다시 만들어야 합니다. 셋째 운영 — 백업은 `cp`가 아니라 `.backup`이나 `VACUUM INTO`를 쓰고, 복구 후에는 `PRAGMA integrity_check`와 `foreign_key_check`로 검증합니다. 그리고 `PRAGMA foreign_keys`는 연결마다 꺼진 채 시작하기 때문에 애플리케이션이 연결을 열 때마다 켜 줘야 합니다. 제 `cafe.db`도 실측하면 0으로 나옵니다."

### 3. 이 카페를 확장하면 — 기능 5개에 DB를 직접 배정한다

"MongoDB는 로그용"이 왜 틀린 답인지 보이려면, **같은 도메인 안에서 기능마다 다른 답이 나오는 것**을 보여주면 된다. 카페 서비스가 커졌다고 가정하고 다섯 기능에 배정한다.

| 기능 | 접근 패턴 | 일관성 요구 | 배정 | 이유(한 문장) |
|---|---|---|---|---|
| 주문 접수·결제 | 쓰기, 여러 테이블에 걸친 1건, 초당 수십 | **강함** — 돈 | PostgreSQL / MySQL 8 | `order_header` 1행 + `order_detail` N행이 원자적이어야 하고, FK·CHECK로 불변식을 DB가 지켜야 한다 |
| 매장 화면 대기번호 | 읽기 폭주, 1~2초면 사라지는 값 | 약함 | Redis | 영속성이 필요 없고 원자적 카운터(`INCR`)와 TTL이면 끝. RDB에 넣으면 초당 UPDATE로 락만 만든다 |
| 일자별 매출 리포트 | 대량 스캔 + 집계, 쓰기 없음 | 약함(지연 허용) | 컬럼 저장(ClickHouse 등) 또는 읽기 복제본 | `SUM(quantity*unit_price) GROUP BY DATE(order_date)`처럼 **컬럼 몇 개만 전 구간 훑는** 패턴이라 행 지향 저장이 불리하다 |
| 메뉴 검색 ("라떼") | 부분 일치·오타 허용·랭킹 | 약함 | Elasticsearch / SQLite FTS5 | `LIKE '%라떼%'`는 선행 와일드카드라 B-tree 인덱스를 못 탄다. 역색인이 필요한 패턴 |
| 로그인 세션 | 키 하나로 읽고 쓰기, 만료됨 | 약함 | Redis | 조인이 없고 키 접근뿐이며 만료가 내장이면 되는 패턴 |

표의 요점은 **한 서비스가 다섯 개 DB를 쓸 수도 있다**는 것이 아니라, 배정 근거가 전부 '용도'가 아니라 '접근 패턴 + 일관성 요구'라는 것이다. 판단 축은 여섯 개뿐이다.

| 축 | 물어볼 질문 | RDB 쪽으로 기우는 답 |
|---|---|---|
| 트랜잭션 경계 | 여러 레코드가 한 단위로 성패를 같이 해야 하나? | 그렇다 |
| 조인 | 서로 다른 엔티티를 이어 붙여 조회하나? | 그렇다 |
| 스키마 안정성 | 필드가 매주 바뀌나? | 안 바뀐다 |
| 읽기/쓰기 비율과 형태 | 키 하나로 찍나, 범위를 훑나? | 범위·집계 |
| 동시 쓰기 | 여러 주체가 동시에 쓰나? | 그렇다면 SQLite 탈락 |
| 데이터 크기 | 단일 노드 메모리·디스크에 들어가나? | 들어간다 |

### 4. SQLite는 정확히 어디서 깨지는가 — 임계점을 수치로

"SQLite는 가볍고 작은 데 쓴다"는 애매한 말이다. 정확한 한계는 하나다. **쓰기 트랜잭션은 DB 파일 전체에 대해 동시에 하나만 가능하다.**

| 상황 | SQLite 결과 | 대응 |
|---|---|---|
| 여러 프로세스가 동시에 읽기 | 문제없음. 몇 개든 가능 | — |
| 읽는 중에 다른 프로세스가 쓰기 | 기본 `journal_mode=delete`에서는 **막힌다**. WAL이면 읽기는 계속 된다 | `PRAGMA journal_mode=WAL` |
| 두 프로세스가 동시에 쓰기 | 한쪽이 `SQLITE_BUSY: database is locked` | `PRAGMA busy_timeout=5000` + 재시도. 그래도 처리량은 직렬 |
| 쓰기가 초당 수백 건 이상 | 직렬화 한계에 걸림 | **서버형 DB로 이전할 시점** |
| 네트워크 파일시스템(NFS) 위 | 락이 정상 동작하지 않아 손상 위험 | 쓰면 안 됨 |

실측: 이 프로젝트의 `cafe.db`는 `PRAGMA journal_mode`가 `delete`, `busy_timeout`이 0이다. 즉 **웹 서버 두 개가 붙는 순간부터 `database is locked`가 난다.** 반대로 말하면 지금 상태 그대로도 "프로세스 하나가 쓰고 여러 개가 읽는" 구성에서는 WAL만 켜면 상당히 멀리 간다.

### 5. 이 항목의 30초 대본

> "DB는 용도로 고르는 게 아니라 접근 패턴으로 고릅니다. 축은 트랜잭션 경계가 여러 레코드에 걸치는지, 조인이 필요한지, 스키마가 자주 바뀌는지, 키로 찍는지 범위를 훑는지, 동시 쓰기가 있는지, 단일 노드에 들어가는지 여섯 개입니다. 같은 카페 서비스 안에서도 답이 갈립니다. 주문 결제는 `order_header`와 `order_detail`이 원자적이어야 하고 FK로 불변식을 지켜야 해서 관계형입니다. 대기번호는 2초 뒤 사라지는 값이라 Redis가 맞습니다. 매출 리포트는 컬럼 몇 개를 전 구간 훑는 패턴이라 컬럼 저장이 유리합니다. 메뉴 검색은 `LIKE '%라떼%'`가 인덱스를 못 타니까 역색인이 필요합니다. 제가 SQLite를 쓴 이유도 용도가 아니라, 단일 프로세스에서 쓰고 파일 하나로 재현되면 되는 과제라 접근 패턴이 맞았기 때문입니다. 반대로 동시 쓰기가 생기는 순간 SQLite는 쓰기 트랜잭션이 파일 전체에 하나뿐이라 그때가 이전 시점입니다."
