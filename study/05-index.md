# 인덱스 — 왜 인덱싱인가

> 평가 피드백 5 대응 — 왜 하필 "색인"인가. 배열·해시맵·역색인에서 B+Tree까지, 실제 페이지를 따라가며.

---

## 인덱스 — 왜 '인덱싱'인가

> 평가 피드백 5번을 그대로 정면 반박하는 모듈이다. 아래 실측값은 전부 이 프로젝트의 `cafe.db`(SQLite 3.46.1, `PRAGMA page_size` = 4096)와, 같은 스키마를 100만 행으로 부풀린 사본에서 직접 측정한 것이다. 100만 행 사본의 생성 스크립트는 8절 끝에 그대로 실어 두었다 — **재현이 안 되는 수치는 실측이 아니다.**

---

### 0. 먼저 외울 30초 대본

평가장에서 "인덱싱이 왜 인덱싱이죠?"를 들으면 이 문단을 그대로 말하면 된다.

> "인덱스는 책 뒤의 색인과 같은 말입니다. 책에서 '라떼'라는 단어를 찾으려면 1페이지부터 다 읽거나, 뒤의 색인에서 '라떼 → 88쪽'을 보고 88쪽으로 바로 가거나 둘 중 하나입니다. DB도 똑같습니다. `order_header`에서 `customer_id = 1`인 주문을 찾을 때, 인덱스가 없으면 10건이든 100만 건이든 전부 읽습니다. 인덱스가 있으면 '`customer_id` 값 → 그 행의 rowid'만 정렬해 둔 별도의 B-Tree를 먼저 타고 내려가서 위치를 알아낸 뒤 그 페이지만 읽습니다. 제 프로젝트 Q15가 정확히 이 실험이고, 실행계획이 `SCAN order_header`에서 `SEARCH order_header USING INDEX idx_order_header_customer_id (customer_id=?)`로 바뀌는 걸 캡처해 뒀습니다."

---

### 1. 어원 — index는 원래 '집게손가락'이다

라틴어 *index*는 '가리키는 것', 집게손가락(index finger)이다. 책의 색인은 **본문을 가리키는 목록**이고, 본문 자체가 아니다. 여기서 핵심 성질 다섯 개가 나온다.

| 책의 색인 | DB 인덱스 | 이 프로젝트에서 |
|---|---|---|
| 본문과 별개의 페이지 | 테이블과 별개의 B-Tree 객체 | `idx_order_header_customer_id`는 `order_header`와 다른 페이지에 산다 |
| 가나다순으로 **정렬**돼 있다 | 인덱스 키가 정렬돼 저장된다 | `(1,1),(1,2),(1,12),(2,3),(2,9),(4,5),(5,6),(6,7),(7,8),(8,10)` ← 실제 리프 순서 |
| 단어 → **쪽번호**(본문 아님) | 키 → rowid/ctid/PK (행 전체 아님) | 리프에 `customer_id`와 `rowid`만 있다 |
| 책 뒤에 색인이 붙으면 책이 두꺼워진다 | 인덱스는 디스크를 더 먹는다 | 100만 행 실측: 39.2 MiB → 50.0 MiB (**+10.8 MiB, +27.7%**) |
| 본문을 고치면 색인도 다시 짜야 한다 | INSERT/UPDATE/DELETE 때 인덱스도 갱신 | 10만 행 INSERT 실측: 0.373 s → 0.888 s (**약 2.4배**) |

위 실측 인덱스 리프 순서를 잘 봐야 한다. `(1,1),(1,2),(1,12)` — SQLite의 인덱스 키는 `(인덱싱한 컬럼들…, rowid)`다. 즉 `customer_id`가 같으면 rowid로 2차 정렬된다. 실제 `order_header`의 `(customer_id, id)` 쌍은 `(1,1) (1,2) (2,3) (4,5) (5,6) (6,7) (7,8) (2,9) (8,10) (1,12)`인데, 인덱스 리프에서는 위 표의 순서로 재배열돼 있다. 이건 뒤의 '복합 인덱스'와 곧바로 이어진다.

---

### 2. 프로그래밍 언어에서의 '인덱싱' 계보 — 평가자가 콕 집은 부분

평가자가 "컴퓨터 언어에서 인덱싱은 어떤 것들이 있는지"를 물은 건, **인덱싱이 DB만의 개념이 아니라 '값 → 위치'로 점프하는 모든 기법의 총칭**이라는 걸 아느냐는 뜻이다.

#### 2-1. 배열 인덱싱 — 계산으로 주소가 나온다

```c
int a[100];
a[3]  // 주소 = base + 3 * sizeof(int) = base + 12
```

`a[3]`이 O(1)인 이유는 "빨리 찾아서"가 아니라 **탐색을 아예 안 하고 곱셈 한 번으로 주소가 나와서**다. 전제는 원소 크기가 모두 같고 메모리가 연속이라는 것. 이 전제가 깨지면 O(1)도 깨진다.

DB 대응: **rowid/PK 접근**이 여기에 가깝다. 실측으로 `SELECT * FROM order_header WHERE id = 3`은 인덱스 이름조차 안 나오고 `SEARCH order_header USING INTEGER PRIMARY KEY (rowid=?)`가 뜬다. SQLite에서 `INTEGER PRIMARY KEY`는 rowid 그 자체라 별도 인덱스가 아예 필요 없다.

> **함정 하나.** rowid 별칭이 되는 건 정확히 `INTEGER PRIMARY KEY`뿐이다. `INT PRIMARY KEY`라고 쓰면 별칭이 아니고, 실측하면 `sqlite_autoindex_t1_1`이라는 별도 인덱스가 생기며 실행계획도 `SEARCH t1 USING INDEX sqlite_autoindex_t1_1 (a=?)`로 바뀐다. 게다가 이 경우 PK 컬럼에 NULL이 여러 개 들어간다(SQLite의 오래된 하위호환 동작). 이 프로젝트의 5개 테이블은 전부 `INTEGER PRIMARY KEY`라 이 함정을 피했다.

#### 2-2. 파이썬 list — 포인터 배열이라 O(1)이 유지된다

```python
menu = ['아메리카노', '카페라떼', '바닐라라떼']
menu[2]    # '바닐라라떼'
menu[-1]   # 음수 인덱싱: len(menu) + (-1) = 2 로 정규화한 뒤 동일 계산
menu[1:3]  # 슬라이싱: 새 list를 만든다(얕은 복사). 뷰가 아니다
```

문자열 길이가 제각각인데도 `menu[2]`가 O(1)인 이유는, list가 문자열을 담은 게 아니라 **8바이트 포인터를 담은 배열**이기 때문이다. 크기가 균일해야 `base + i*8`이 성립한다. 음수 인덱싱은 마법이 아니라 `i < 0`이면 `i += len` 하는 한 줄이다.

#### 2-3. 해시맵/dict — 값을 계산해서 위치를 만든다

```python
cache = {}
cache['minjun@example.com'] = 1     # hash(key) -> 버킷 슬롯 번호
cache['minjun@example.com']         # 같은 계산 -> 같은 슬롯 -> 평균 O(1)
```

배열은 '주어진 인덱스'로 주소를 만들고, 해시맵은 '**임의의 키를 인덱스로 변환**'한다. 대가가 셋 있다.

- **충돌**: 다른 키가 같은 슬롯에 떨어진다 → 체이닝 또는 오픈 어드레싱으로 해결한다. 최악 O(n). (CPython dict는 체이닝이 아니라 오픈 어드레싱 + perturbation 탐사를 쓴다.)
- **리해싱**: 적재율이 임계치를 넘으면 테이블을 키우고 전부 다시 배치한다 → 그 한 번의 삽입만 비싸다. 증가 배율은 구현마다 다르므로 "무조건 2배"로 외우면 안 된다.
- **키 정렬 순서가 없다**: 해시 값은 원래 키의 대소 관계를 보존하지 않는다. 그래서 **범위 검색이 원리적으로 불가능**하다.

> 여기서 자주 틀리는 것 하나. "dict는 순서가 없다"는 말은 2026년 기준으로 반은 틀렸다. **CPython dict는 3.7부터 삽입 순서 보존이 언어 명세**다(3.6은 구현 세부였다). 없어진 건 '삽입 순서'가 아니라 '**키로 정렬된 순서**'다. DB 해시 인덱스가 범위 검색을 못 하는 이유도 정확히 후자다.

이게 시험에서 제일 자주 나오는 포인트다. `WHERE price BETWEEN 4000 AND 5000`, `ORDER BY price`는 해시 인덱스로 절대 못 한다. **DB가 해시가 아니라 B-Tree를 기본으로 쓰는 첫 번째 이유가 이것**이다.

#### 2-4. 역색인(inverted index)

```text
정방향:  menu 3 → "바닐라라떼"
역방향:  "라떼" → [menu 2, menu 3, menu 4]
```

문서를 토큰으로 쪼개서 `단어 → 문서 ID 목록`을 만든다. 검색엔진(Lucene/Elasticsearch)이 이 구조다. `WHERE name LIKE '%라떼%'`가 풀스캔인 문제를 정면으로 푸는 게 역색인이다.

**단, 토크나이저가 어떻게 자르느냐가 전부를 결정한다.** 9-3절에서 실측으로 보겠지만, 기본 토크나이저는 '카페라떼'를 한 덩어리로 잘라 버려서 '라떼'로는 못 찾는다. 한국어처럼 띄어쓰기 없이 붙는 언어에서는 n-gram/트라이그램 토크나이저가 필요하다.

#### 2-5. 계보 → DB 인덱스 매핑표

| 언어 세계의 인덱싱 | 핵심 원리 | DB에서 대응되는 것 | 되는 것 / 안 되는 것 |
|---|---|---|---|
| 배열 `a[i]` | base + i·size, 탐색 없음 | rowid / InnoDB 클러스터드 PK | 정확 위치 O(1), 값으로는 못 찾음 |
| 파이썬 list (포인터 배열) | 균일 크기 포인터 배열 | PostgreSQL 힙 페이지의 라인 포인터 배열 + ctid(블록,오프셋) | 위치는 O(1), 값 검색은 별도 인덱스 필요 |
| dict / HashMap | 해시 → 슬롯 | MySQL MEMORY의 HASH, PostgreSQL `USING hash` | `=`만 가능. `<`, `BETWEEN`, `ORDER BY` 불가 |
| 정렬 배열 + 이진탐색 | 순서를 유지 | B-Tree / B+Tree 인덱스 | `=`, 범위, 정렬, 접두사 전부 가능 |
| 역색인 | 토큰 → 문서 ID 리스트 | SQLite FTS5, PostgreSQL GIN, MySQL FULLTEXT | 단어/부분 검색 가능. `%라떼%` 문제의 정답 |
| n-gram / 트라이그램 | 3글자씩 쪼개 색인 | SQLite FTS5 `tokenize='trigram'`, PostgreSQL `pg_trgm`, MySQL `ngram` 파서 | 한국어처럼 띄어쓰기 없이 붙는 언어의 부분일치 |

> 트라이(trie)를 여기에 끼워 넣는 답안이 많은데, **주류 RDBMS의 기본 인덱스는 트라이가 아니다.** MySQL의 이른바 prefix index(`KEY(name(10))`)도 트라이가 아니라 '값의 앞 10바이트만 잘라 B-Tree에 넣는' 것이다. 접두사 검색은 트라이가 없어도 B-Tree의 정렬 순서만으로 이미 된다.

---

### 3. 왜 이진 트리가 아니라 B-Tree인가 — '디스크'가 답이다

이진 탐색 트리도 정렬돼 있고 O(log n)이다. 그런데 왜 아무 DB도 안 쓰는가.

**디스크는 바이트 단위로 못 읽는다. 페이지 단위로 읽는다.**

| DBMS | 기본 페이지 크기 | 확인 방법 |
|---|---|---|
| SQLite | 4KB (`cafe.db` 실측 4096, 3.12.0부터 기본값) | `PRAGMA page_size` |
| MySQL 8 InnoDB | 16KB | `SHOW VARIABLES LIKE 'innodb_page_size'` |
| PostgreSQL | 8KB | 컴파일 타임 `BLCKSZ`, `SHOW block_size` |

노드 하나를 읽으려면 어차피 페이지 한 장을 통째로 가져온다. 이진 트리는 그 4KB짜리 페이지에 **키를 딱 1개** 담는다. 100만 행이면 높이 log₂(1,000,000) ≈ 20 → **페이지 읽기 20번**. 4KB 중 몇 십 바이트만 쓰고 나머지를 버리는 셈이다.

B-Tree는 반대로 **페이지 하나를 키로 꽉 채운다**. 자식 수(팬아웃)가 수백이 된다.

```text
팬아웃 200일 때 (각 레벨이 덮을 수 있는 리프 수)
  높이 1 →       200 개
  높이 2 →    40,000 개
  높이 3 → 8,000,000 개   ← 800만 행이 페이지 읽기 3번
```

**실측으로 확인한 값** — 100만 행 `order_header` 사본에서 `(customer_id, status)` 인덱스를 만들고 `dbstat` 가상 테이블의 `path` 컬럼으로 레벨을 직접 세었다.

```sql
-- 레벨별 페이지 수 세기 (path의 '/' 개수가 곧 깊이)
SELECT length(path) - length(replace(path,'/','')) AS lvl, pagetype, count(*)
FROM   dbstat WHERE name = 'idx_oh_cust_status' GROUP BY lvl, pagetype;
```

| 구분 | 루트 | 내부(루트 제외) | 리프 | 실측 팬아웃 | 트리 높이 |
|---|---|---|---|---|---|
| 인덱스 `idx_oh_cust_status` | 1장 (셀 30개) | 31장 | 6,036 → **5,036장** | 5,036 ÷ 31 ≈ **162** | **3단** |
| 테이블 `order_header` (rowid B-tree) | 1장 (셀 24개) | 25장 | **9,995장** | 9,995 ÷ 25 ≈ **400** | **3단** |

리프 5,036장을 그 위 내부 노드 31장이 덮고, 그 31장은 루트 1장(셀 30개 = 자식 31개)이면 정확히 덮인다. 그래서 **100만 행짜리 인덱스의 높이가 3**이다. 이진 트리였다면 20이다. 6~7배 차이가 아니라, 랜덤 디스크 I/O 20번과 3번의 차이다.

말로 할 때:

> "이진 트리를 안 쓰는 이유는 디스크가 페이지 단위로 읽기 때문입니다. 4KB를 읽어 놓고 키 하나만 쓰면 낭비죠. B-Tree는 한 페이지에 키를 수백 개 담아서 자식 수를 늘립니다. 제 DB에서 `dbstat`으로 실제로 재 보니 100만 행 인덱스의 팬아웃이 162였고, 리프 5,036장을 내부 노드 31장이 덮고 그 위가 루트 1장이라 트리 높이가 3이었습니다. 즉 100만 행에서 한 건 찾는 데 페이지 읽기 3번입니다."

---

### 4. B+Tree — 리프에만 데이터를 두고 리프끼리 잇는다

B-Tree와 B+Tree의 차이는 두 줄이다.

1. **B-Tree**: 내부 노드에도 데이터(또는 payload)가 있다.
2. **B+Tree**: 내부 노드는 **길잡이 키만**, 실제 데이터는 **리프에만**. 그리고 (전형적인 구현에서는) **리프끼리 좌우로 연결**된다.

이 두 줄에서 두 가지 성능 특성이 나온다.

- 내부 노드가 키만 담으니 **더 많이 담긴다 → 팬아웃이 더 커지고 높이가 더 낮아진다.**
- 리프가 연결돼 있으면, 시작점 하나만 찾은 뒤 **트리를 다시 안 타고 옆으로 걸어가면 된다.**

두 번째가 범위 검색의 원리다.

```sql
SELECT * FROM order_header WHERE customer_id BETWEEN 10 AND 20;
```

실측 실행계획(100만 행 사본): `SEARCH order_header USING INDEX idx_oh_cust_status (customer_id>? AND customer_id<?)`

`customer_id = 10`인 첫 리프까지 3단 내려간 다음, **거기서부터 순서대로 옆으로 쭉 읽다가 21이 나오면 멈춘다.** 트리 전체를 다시 타지 않는다. **`ORDER BY customer_id`도 같은 이유로 공짜다** — 인덱스를 순서대로 걸으면 그게 이미 정렬 결과라 정렬 연산 자체가 사라진다. 실측:

```sql
SELECT * FROM customer ORDER BY email;
-- SCAN customer USING INDEX sqlite_autoindex_customer_1

SELECT * FROM order_header ORDER BY customer_id;   -- 100만 행 사본
-- SCAN order_header USING INDEX idx_oh_cust_status
```

`SCAN`인데 `USING INDEX`가 붙었다. 전부 읽되 **인덱스 순서로** 읽어서 정렬을 생략했다는 뜻이다.

> **여기서 정확히 짚어야 할 것 — '리프 링크'는 엔진마다 있고 없다.**
>
> - **InnoDB**: 리프 페이지가 `PAGE_PREV`/`PAGE_NEXT`로 **이중 연결**된 전형적 B+Tree다.
> - **PostgreSQL nbtree**: Lehman-Yao **B-link 트리** 변형이라 리프에 우측 형제 포인터가 있고, 분할 중에도 잠금 없이 옆으로 갈 수 있다.
> - **SQLite**: 파일 포맷상 **형제 페이지를 가리키는 포인터가 아예 없다.** 내부 페이지 헤더에 '가장 오른쪽 자식 포인터'만 있을 뿐이다. 그래서 SQLite의 다음-행 이동(`sqlite3BtreeNext`)은 **커서가 들고 있는 부모 스택을 되짚어** 다음 리프로 올라갔다 내려온다. 결과는 같지만 기전이 다르다.
>
> 그리고 SQLite 내부 구조를 한 줄로 정리하면: **테이블 b-tree는 리프에만 payload를 두는 B+Tree 형태**이고(내부 페이지는 rowid 키와 자식 포인터만), **인덱스 b-tree는 내부 노드에도 키 payload를 두는 B-Tree 형태**다. 실제로 3절의 `dbstat` 결과에서 인덱스 내부 페이지 32장이 셀 5,035개를 들고 있는 게 그 증거다.

---

### 5. 실제 저장 형태 — 세 DBMS가 다르다

여기를 뭉뚱그리면 바로 티가 난다. 표로 외운다.

| | SQLite | MySQL 8 InnoDB | PostgreSQL |
|---|---|---|---|
| 테이블 저장 구조 | **rowid 기준 B-tree** (테이블 자체가 트리 = 항상 클러스터드) | **PK 기준 클러스터드 인덱스** (테이블 = PK B+Tree) | **힙(heap)** — 순서 없는 페이지 더미 |
| 행 식별자 | `rowid` (64bit 정수) | PK 값 | `ctid` = (블록번호, 오프셋) |
| 보조 인덱스 리프에 든 것 | 인덱스 키 + **rowid** | 인덱스 키 + **PK 값** | 인덱스 키 + **ctid** |
| 보조 인덱스로 조회 시 | 인덱스 → rowid → 테이블 B-tree 재탐색 | 인덱스 → PK → **클러스터드 인덱스 재탐색(2회 탐색)** | 인덱스 → ctid → 힙 페이지 직접 접근(1회 점프) |
| 리프 형제 포인터 | **없음** (커서 스택으로 이동) | 있음 (이중 연결) | 있음 (B-link 우측 포인터) |
| 클러스터드로 만들려면 | `CREATE TABLE … WITHOUT ROWID` | 기본이 클러스터드 | 없음. `CLUSTER` 명령은 1회성 재정렬일 뿐 유지 안 됨 |
| 인덱스만으로 끝내기 | 커버링 인덱스 → `USING COVERING INDEX` | 커버링 인덱스 → `Extra: Using index` | **Index Only Scan이지만 visibility map 확인 필요** (11+는 `INCLUDE` 컬럼 지원) |

**세 개만 깊게 짚는다.**

**(1) InnoDB의 2회 탐색.** InnoDB에서 `order_header(customer_id)` 인덱스를 타면 리프에 `(customer_id, id)`가 들어 있다. `id`는 rowid 같은 물리 주소가 아니라 **논리 키**다. 그래서 행 전체가 필요하면 **PK 값을 들고 클러스터드 인덱스를 처음부터 다시 3단 내려가야 한다.** 이걸 bookmark lookup / 테이블 접근이라 한다. → 그래서 InnoDB에서 **PK를 길게 잡으면(UUID 문자열 등) 모든 보조 인덱스가 같이 뚱뚱해진다.** 이 프로젝트가 PK를 `INTEGER`로 잡은 게 정답인 이유다.

여기서 정확히 알아야 할 순서가 하나 더 있다. InnoDB는 PK가 없으면 곧바로 숨은 컬럼을 만드는 게 아니라, ① 먼저 **NOT NULL인 UNIQUE 인덱스**를 찾아 그것을 클러스터드 키로 승격시키고, ② 그것마저 없을 때 비로소 6바이트 `DB_ROW_ID` 기반의 숨은 클러스터드 인덱스(`GEN_CLUST_INDEX`)를 만든다.

참고로 InnoDB에는 **적응형 해시 인덱스(adaptive hash index)** 도 있다. 같은 인덱스 접두사로 반복 조회가 몰리면 InnoDB가 버퍼 풀 안에 해시 인덱스를 자동으로 만들어 B+Tree 탐색을 건너뛴다. 사용자가 만드는 물건이 아니고, 디스크에도 남지 않는다.

**(2) PostgreSQL의 visibility map.** PostgreSQL은 MVCC로 옛 버전 행을 힙에 그대로 남겨 둔다. **인덱스 항목에는 "이 행이 지금 트랜잭션에 보이는 버전인가"라는 정보가 없다.** 그래서 인덱스만 읽고 끝내려면(Index Only Scan) 그 페이지가 "전부 보이는 페이지(all-visible)"라고 표시된 visibility map을 봐야 한다. VACUUM을 안 돌리면 이 맵이 갱신 안 돼서 **Index Only Scan이 계획에는 잡히는데 실제로는 힙을 다 뒤지는 현상**이 생기고, `EXPLAIN (ANALYZE)`의 `Heap Fetches:` 값이 크게 찍힌다. (다만 인덱스 항목에 `LP_DEAD` 힌트 비트가 붙어 확실히 죽은 항목을 건너뛰는 최적화는 있다. 이건 가시성 판정이 아니라 '이미 죽은 걸 안다'는 캐시다.) SQLite와 MySQL InnoDB에는 이 문제 자체가 없다 — 두 엔진 모두 옛 버전을 별도 공간(롤백 저널/WAL, undo 로그)에 두기 때문이다.

**(3) SQLite의 `WITHOUT ROWID`.** 실측하면 차이가 실행계획 문자열로 드러난다.

```sql
CREATE TABLE t3(a TEXT PRIMARY KEY, b) WITHOUT ROWID;
EXPLAIN QUERY PLAN SELECT * FROM t3 WHERE a = 'k';
--   SEARCH t3 USING PRIMARY KEY (a=?)      ← 인덱스 객체가 따로 없다. 테이블 자체가 PK 트리다
SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='t3';   -- 0행
```

일반 테이블이면 `sqlite_autoindex_t3_1`이 하나 생기고 `SEARCH … USING INDEX …`가 뜬다. 덤으로 `WITHOUT ROWID` 테이블은 PK에 NULL을 넣으면 `NOT NULL constraint failed`로 막히는데, 일반 rowid 테이블의 비-INTEGER PK는 (하위호환 때문에) NULL이 들어간다.

---

### 6. 탐색 과정 — `order_header`에서 `customer_id = 1` 찾기, 단계별

실제 `cafe.db` 데이터로 그린다. `customer_id = 1`인 주문은 id 1, 2, 12 세 건이다(실측 확인).

```text
[인덱스 idx_order_header_customer_id 의 B-tree]

              ┌──────────── 루트 페이지 ────────────┐
              │  … | 4 | …                          │   "1은 4보다 작다 → 왼쪽"
              └────────────┬────────────────────────┘
                           ▼
              ┌──────────── 내부 페이지 ────────────┐
              │  1 | 2 | 4 | 5 | …                  │   "1로 시작하는 리프로"
              └────────────┬────────────────────────┘
                           ▼
   ┌──────────────── 리프 페이지 (정렬돼 있다) ────────────────┐
   │ (1,1) (1,2) (1,12) │ (2,3) (2,9) │ (4,5) │ (5,6) │ …      │
   │   ↑ 키 = (customer_id, rowid)                              │
   └────────┬───────────────────────────────────────────────────┘
            │ rowid 1, 2, 12 를 얻음  ← 여기까지가 인덱스 탐색
            ▼
[테이블 order_header 의 rowid B-tree]
   rowid=1  → 페이지 P 에서 (1, 1, '2026-04-15 09:12:00', 'COMPLETED')
   rowid=2  → 페이지 P 에서 (2, 1, '2026-04-25 14:05:00', 'COMPLETED')
   rowid=12 → 페이지 Q 에서 (12, 1, '2026-05-10 19:30:00', 'COMPLETED')
                                          ← 이 재탐색이 '테이블 접근' 비용
```

(10행짜리 `cafe.db`에서는 인덱스도 테이블도 페이지가 한 장뿐이라 위 그림의 3단은 개념도다. 실제 3단짜리 트리는 3절의 100만 행 실측을 보면 된다.)

말로 하는 대본:

> "① 옵티마이저가 `customer_id` 인덱스를 고릅니다. ② 인덱스 루트 페이지를 읽고 키를 비교해서 1이 들어갈 자식을 고릅니다. ③ 내부 노드에서 한 번 더 좁히고 ④ 리프에 도착합니다. 리프에는 `(customer_id, rowid)` 쌍이 정렬돼 있어서 `(1,1) (1,2) (1,12)`가 **연속으로 붙어 있습니다**. 그래서 하나 찾으면 나머지는 옆으로 읽으면 끝입니다. ⑤ 얻은 rowid 1, 2, 12로 테이블 B-tree를 다시 타서 실제 행을 꺼냅니다. ⑥ 만약 `SELECT customer_id` 처럼 인덱스 안의 컬럼만 필요했다면 ⑤단계를 아예 건너뜁니다. 그게 커버링 인덱스입니다."

⑥이 실측으로 확인된다(100만 행 사본, `idx_oh_cust_status`).

```sql
SELECT customer_id, status FROM order_header WHERE customer_id = 777;
-- SEARCH order_header USING COVERING INDEX idx_oh_cust_status (customer_id=?)

SELECT COUNT(*) FROM order_header WHERE customer_id = 777;
-- SEARCH order_header USING COVERING INDEX idx_oh_cust_status (customer_id=?)

SELECT * FROM order_header WHERE customer_id = 777;
-- SEARCH order_header USING INDEX idx_oh_cust_status (customer_id=?)   ← COVERING 이 사라짐
```

`COVERING` 한 단어가 붙고 안 붙고가 곧 **테이블 재탐색을 하냐 마냐**다. 참고로 SQLite에서는 `id`(= rowid)가 인덱스 키에 항상 딸려 오므로, `SELECT id, customer_id`도 커버링이 된다.

---

### 7. Q15 실험 — SCAN → SEARCH가 정확히 무슨 뜻인가

`03_queries.sql`의 Q15-A/Q15/Q15-B(294~347행)를 그대로 재현한 실측 결과다.

```sql
-- Q15-A: 인덱스를 지운 상태 (대조군)
DROP INDEX IF EXISTS idx_order_header_customer_id;
EXPLAIN QUERY PLAN SELECT * FROM order_header WHERE customer_id = 1;
--   SCAN order_header

-- Q15: 인덱스 생성
CREATE INDEX idx_order_header_customer_id ON order_header (customer_id);

-- Q15-B
EXPLAIN QUERY PLAN SELECT * FROM order_header WHERE customer_id = 1;
--   SEARCH order_header USING INDEX idx_order_header_customer_id (customer_id=?)
```

**SQLite 용어의 정확한 뜻**

| 표기 | 뜻 | 비용 |
|---|---|---|
| `SCAN t` | t의 모든 행을 처음부터 끝까지 방문 | O(N) |
| `SCAN t USING INDEX i` | 전부 읽되 **i의 순서대로** 읽음 (정렬 생략용) | O(N)이지만 ORDER BY가 공짜 |
| `SEARCH t USING INDEX i (col=?)` | 인덱스로 **후보를 좁혀서** 방문 | O(log N + 결과수) |
| `SEARCH t USING COVERING INDEX i` | 인덱스만 읽고 테이블 접근 없음 | 가장 싸다 |
| `SEARCH t USING INTEGER PRIMARY KEY (rowid=?)` | rowid 직접 접근, 인덱스 객체조차 불필요 | 가장 빠른 단건 조회 |
| `SEARCH t USING PRIMARY KEY (c=?)` | `WITHOUT ROWID` 테이블의 클러스터드 PK 접근 | 테이블 = 인덱스 |
| `USE TEMP B-TREE FOR ORDER BY` | 정렬을 받쳐 줄 인덱스가 없어 **임시 B-Tree를 만들어 정렬** | 결과를 전부 모아 정렬 |
| `USING AUTOMATIC COVERING INDEX` | **인덱스가 없어서 SQLite가 쿼리 실행 중 임시 인덱스를 즉석에서 만든 것** | "여기 인덱스 만들라"는 신호 |
| `BLOOM FILTER ON t (c=?)` | 조인 시 매칭 없는 행을 미리 걸러 내는 블룸 필터 (3.38.0+) | 탐색 자체를 건너뜀 |

마지막 두 줄이 실전에서 중요한 신호다. Q7(LEFT JOIN)을 인덱스 없는 상태로 돌리면 실제로 이렇게 나온다.

```text
SCAN c
BLOOM FILTER ON oh (customer_id=?)
SEARCH oh USING AUTOMATIC COVERING INDEX (customer_id=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```

인덱스를 만든 뒤 다시 돌리면 `AUTOMATIC`과 블룸 필터가 사라진다.

```text
SCAN c
SEARCH oh USING COVERING INDEX idx_order_header_customer_id (customer_id=?) LEFT-JOIN
USE TEMP B-TREE FOR ORDER BY
```

(`ORDER BY order_count DESC`는 집계 결과로 정렬하는 것이라 어떤 인덱스로도 못 없앤다. 그래서 `USE TEMP B-TREE`는 양쪽 모두에 남는다.)

> **한 가지 더 — 통계가 있으면 임시 인덱스도 안 만든다.** 인덱스가 없는 상태에서 `ANALYZE`를 돌린 뒤 같은 Q7을 돌리면 실행계획이 이렇게 바뀐다.
> ```text
> SCAN c
> SCAN oh LEFT-JOIN
> USE TEMP B-TREE FOR ORDER BY
> ```
> `order_header`가 10행이라는 걸 알고 나면, 임시 인덱스를 만드는 비용이 그냥 다 읽는 비용보다 크다고 판단한 것이다. 이 한 줄이 8절의 카디널리티 이야기로 바로 이어진다.

**세 DBMS 대응표** — 같은 개념을 각자 다른 단어로 부른다.

| 개념 | SQLite (`EXPLAIN QUERY PLAN`) | MySQL 8 (`EXPLAIN`의 `type`) | PostgreSQL (`EXPLAIN`) |
|---|---|---|---|
| 풀 테이블 스캔 | `SCAN t` | `type = ALL` | `Seq Scan` |
| 인덱스 전체 훑기 | `SCAN t USING INDEX i` | `type = index` | `Index Scan` / `Index Only Scan` (조건 없음) |
| 인덱스로 등치 검색 | `SEARCH t USING INDEX i (c=?)` | `type = ref` | `Index Scan` + `Index Cond` |
| 유니크/PK 단건 | `SEARCH t USING INTEGER PRIMARY KEY` | `type = const` / `eq_ref` | `Index Scan` (unique) |
| 범위 검색 | `SEARCH … (c>? AND c<?)` | `type = range` | `Index Scan` + 범위 `Index Cond` |
| 테이블 안 읽음 | `USING COVERING INDEX` | `Extra: Using index` | `Index Only Scan` |
| 여러 인덱스 결과 합치기 | (제한적) | `index_merge` | `BitmapAnd`/`BitmapOr` → `Bitmap Heap Scan` |
| 정렬을 위한 임시 구조 | `USE TEMP B-TREE FOR ORDER BY` | `Extra: Using filesort` | `Sort` 노드 |
| 실제 시간까지 측정 | `EXPLAIN ANALYZE` 없음. CLI `.scanstats on`(전용 빌드 옵션 필요, 이 프로젝트 빌드에는 없음) | `EXPLAIN ANALYZE` (8.0.18+) | `EXPLAIN ANALYZE` |

#### UNIQUE 제약과 인덱스는 사실상 같은 물건이다

`cafe.db`의 `sqlite_master`를 그대로 조회한 결과다.

```text
sqlite_autoindex_customer_1   customer      (sql = NULL, 자동 생성)
sqlite_autoindex_category_1   category      (sql = NULL, 자동 생성)
sqlite_autoindex_menu_1       menu          (sql = NULL, 자동 생성)
idx_order_header_customer_id  order_header  CREATE INDEX ...
idx_order_detail_order_id     order_detail  CREATE INDEX ...
```

인덱스가 5개인데 **직접 만든 건 2개뿐**이다. 나머지 3개는 `customer.email UNIQUE`, `category.name UNIQUE`, `menu.name UNIQUE`가 자동으로 만든 것이다. `sql` 컬럼이 `NULL`인 게 "사용자가 쓴 DDL이 아니다"라는 표시다. 실제로 지우려고 하면 이렇게 막힌다.

```text
DROP INDEX sqlite_autoindex_customer_1;
-- Error: index associated with UNIQUE or PRIMARY KEY constraint cannot be dropped
```

**왜 자동으로 만드는가.** UNIQUE를 지키려면 INSERT마다 "이 이메일이 이미 있나?"를 검사해야 한다. 인덱스 없이 하면 매 INSERT마다 풀스캔이다. **유일성 검사 자체가 조회**이므로 인덱스가 필수다. 그래서 부수 효과로 조회도 빨라진다.

```sql
SELECT * FROM customer WHERE email = 'minjun@example.com';
-- SEARCH customer USING INDEX sqlite_autoindex_customer_1 (email=?)

SELECT * FROM menu WHERE name = '아메리카노';
-- SEARCH menu USING INDEX sqlite_autoindex_menu_1 (name=?)
```

애플리케이션 쪽에서는 이 위반을 예외로 받는다. 아래는 실제로 실행해 확인한 결과다.

```python
import sqlite3
con = sqlite3.connect('cafe.db')
try:
    con.execute("INSERT INTO customer(name, email) VALUES ('중복', 'minjun@example.com')")
except sqlite3.IntegrityError as e:
    print(e)                       # UNIQUE constraint failed: customer.email
    print(e.sqlite_errorcode)      # 2067          (Python 3.11+ 속성)
    print(e.sqlite_errorname)      # SQLITE_CONSTRAINT_UNIQUE
```

`CHECK` 위반도 같은 `IntegrityError`지만 이름이 다르다 — `status`에 `'DONE'`을 넣으면 `CHECK constraint failed: status IN ('PENDING','COMPLETED','CANCELLED')` / `SQLITE_CONSTRAINT_CHECK`. **즉 "무엇을 어겼는가"는 예외 클래스가 아니라 확장 에러코드로 갈라야 한다.**

| 위반 | SQLite (확장 에러코드) | MySQL 8 | PostgreSQL (SQLSTATE) |
|---|---|---|---|
| UNIQUE / PK 중복 | `SQLITE_CONSTRAINT_UNIQUE` (2067) / `…_PRIMARYKEY` (1555) | 에러 1062, SQLSTATE 23000 | **23505** `unique_violation` |
| FK 위반 | `SQLITE_CONSTRAINT_FOREIGNKEY` (787) | 1452 / 1451, SQLSTATE 23000 | **23503** `foreign_key_violation` |
| NOT NULL | `SQLITE_CONSTRAINT_NOTNULL` (1299) | 1048, SQLSTATE 23000 | **23502** `not_null_violation` |
| CHECK | `SQLITE_CONSTRAINT_CHECK` (275) | 3819, SQLSTATE HY000 (**8.0.16부터 실제로 강제**) | **23514** `check_violation` |

> MySQL은 8.0.16 이전에는 `CHECK` 구문을 **파싱만 하고 무시**했다. 이 프로젝트 스키마의 `CHECK (price >= 0)`, `CHECK (status IN (...))`를 MySQL 5.7로 옮기면 아무것도 막지 않는다는 뜻이라, 포팅 이야기가 나오면 반드시 짚어야 하는 버전 경계다.

DBMS별 차이:

| | UNIQUE가 만드는 것 | 이름 |
|---|---|---|
| SQLite | 자동 인덱스 | `sqlite_autoindex_<table>_<n>` (직접 DROP 불가) |
| MySQL 8 | 자동 인덱스 | 컬럼명 기반 (`email`), `DROP INDEX`로 지우면 제약도 사라짐 |
| PostgreSQL | 제약 + 그 제약이 소유한 인덱스 | `customer_email_key`. **인덱스만 따로 DROP 불가**, `ALTER TABLE … DROP CONSTRAINT`로 지워야 함 |
| PRIMARY KEY | 셋 다 인덱스를 만든다 | SQLite는 `INTEGER PRIMARY KEY`면 rowid라 인덱스조차 안 만듦 (단 `INT PRIMARY KEY`는 만든다) |

---

### 8. 인덱스의 비용 — 그리고 이 프로젝트에서 실험이 안 보이는 이유

**실측 (100만 행 사본, `order_header`, 고객 5만 명 = 고객당 평균 20건)**

| 항목 | 인덱스 없음 | 인덱스 있음 | 배율 |
|---|---|---|---|
| `WHERE customer_id = ?` 조회 (랜덤 키, 결과 평균 20행) | **55.79 ms** | **0.070 ms** | **약 800배 빨라짐** |
| 파일 크기 (VACUUM 후) | 39.2 MiB | 50.0 MiB | +10.8 MiB (**+27.7%**) |
| 10만 행 INSERT (단일 트랜잭션) | **0.373 s** | **0.888 s** | **약 2.4배 느려짐** |
| `CREATE INDEX` 자체 소요 | — | 0.47 s | 만드는 동안 쓰기 잠금 |

복합 인덱스 `(customer_id, status)`로 바꾸면 비용이 더 커진다 — 파일 39.2 → 58.9 MiB(**+50.6%**), 10만 행 INSERT 1.05 s(**약 2.8배**), `CREATE INDEX` 0.68 s. **인덱스는 컬럼을 더할수록 정직하게 더 비싸진다.**

**실측 (실제 `cafe.db`, `order_header` 10행, 20만 회 평균)**

| 항목 | 인덱스 없음 | 인덱스 있음 |
|---|---|---|
| `WHERE customer_id = 1` 조회 | **0.0153 ms** | **0.0155 ms** |

**10행짜리 테이블에서는 인덱스 있는 쪽이 오히려 0.0002 ms 느렸다.** 측정 오차 범위이지만 방향이 중요하다. 왜 그런가.

10행은 페이지 한 장(4KB)에 다 들어간다. 풀스캔 = **페이지 읽기 1번**. 인덱스를 타면 인덱스 페이지 1번 + 테이블 페이지 1번 = **2번**이다. 즉 작은 테이블에서 인덱스는 **일을 늘린다.**

옵티마이저도 그걸 안다. `ANALYZE`를 돌려 통계를 만든 뒤 실측한 결과:

```sql
CREATE INDEX idx_oh_status ON order_header(status);
ANALYZE;
EXPLAIN QUERY PLAN SELECT * FROM order_header WHERE status = 'COMPLETED';
--   SCAN order_header          ← 인덱스가 있는데도 안 탄다
EXPLAIN QUERY PLAN SELECT * FROM order_header WHERE status = 'PENDING';
--   SCAN order_header          ← 1행뿐인 값인데도 안 탄다
```

`sqlite_stat1`을 보면 이유가 숫자로 나온다(실측 그대로).

```text
('order_header', 'idx_oh_status',                '10 5')   → 10행, 값 하나당 평균 5행
('order_header', 'idx_order_header_customer_id', '10 2')   → 10행, 값 하나당 평균 2행 = 20%
('order_detail',  'idx_order_detail_order_id',   '18 2')
('menu',          'sqlite_autoindex_menu_1',     '12 1')   → 값 하나당 1행 = 완전 유일
```

`stat1`의 형식은 `총행수 키당평균행수`(컬럼이 여러 개면 접두사 길이별로 값이 더 붙는다)다. 여기서 정확히 짚어야 할 게 하나 있다.

> **`status`의 실제 카디널리티는 3이 아니라 2다.** `CHECK`가 허용하는 값은 `PENDING/COMPLETED/CANCELLED` 3종이지만, `03_queries.sql`의 Q14가 `CANCELLED` 주문을 이미 삭제해서 **현재 데이터에 실재하는 값은 `COMPLETED` 9행, `PENDING` 1행 두 종뿐**이다. 그래서 10 ÷ 2 = 5, 즉 `'10 5'`다. "제약이 허용하는 값의 개수"와 "데이터에 실제로 들어 있는 서로 다른 값의 개수"는 다른 이야기이고, 옵티마이저가 보는 건 후자다.

그리고 한 가지 더. 실제 분포는 9:1로 심하게 치우쳐 있는데 `sqlite_stat1`은 **평균 하나만** 담는다. 그래서 옵티마이저는 1행밖에 안 나오는 `status = 'PENDING'`도 "평균 5행쯤 나오겠지"로 보고 똑같이 풀스캔을 고른다. 히스토그램 같은 분포 통계(`sqlite_stat4`, PostgreSQL `pg_statistic`, MySQL 히스토그램)가 필요한 이유가 정확히 이 지점이다. **이게 카디널리티이고, 여기서부터가 통계다.**

> **평가장에서 반드시 먼저 말할 것.** "제 데이터는 `order_header`가 10행이라 실행시간 차이는 측정이 안 됩니다. 그래서 **실행계획으로** 검증했습니다. 시간 차이는 같은 스키마를 100만 행으로 부풀려서 따로 재 봤고, 55.8 ms에서 0.07 ms로 줄었습니다."

**옵티마이저 혼선**도 실제 비용이다. 인덱스가 많으면 옵티마이저가 검토할 실행계획 조합이 늘고, 통계가 낡으면 **엉뚱한 인덱스를 골라 오히려 느려진다.** MySQL은 `FORCE INDEX`(또는 8.0의 `invisible index`로 후보에서 잠시 빼기), PostgreSQL은 `enable_seqscan = off`, SQLite는 `INDEXED BY`로 강제·배제할 수 있지만 전부 최후의 수단이다.

#### 100만 행 사본 재현 스크립트

위 수치는 아래 스크립트로 그대로 재현된다(SQLite 3.46.1, `page_size` 4096 기준. 절대 시간은 장비마다 다르고, 배율만 의미가 있다).

```python
import sqlite3, random, time, os, shutil
random.seed(42)
con = sqlite3.connect('big_noidx.db')
con.executescript("""
PRAGMA page_size=4096;
CREATE TABLE order_header (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  customer_id INTEGER NOT NULL,
  order_date  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status      TEXT NOT NULL DEFAULT 'PENDING'
              CHECK (status IN ('PENDING','COMPLETED','CANCELLED')));
""")
st = ['PENDING','COMPLETED','CANCELLED']
rows = ((random.randint(1, 50_000),
         "2026-%02d-%02d %02d:%02d:00" % (random.randint(1,12), random.randint(1,28),
                                          random.randint(0,23), random.randint(0,59)),
         st[random.randint(0,2)]) for _ in range(1_000_000))
con.executemany("INSERT INTO order_header(customer_id,order_date,status) VALUES(?,?,?)", rows)
con.commit(); con.execute("VACUUM"); con.close()

shutil.copy('big_noidx.db', 'big_idx.db')
con = sqlite3.connect('big_idx.db')
t = time.time(); con.execute("CREATE INDEX idx_oh_cust ON order_header(customer_id)"); con.commit()
print('CREATE INDEX', time.time() - t)
con.execute("VACUUM"); con.close()
print(os.path.getsize('big_noidx.db'), os.path.getsize('big_idx.db'))
```

---

### 9. 복합 인덱스, 좌측 접두사, 안티패턴

#### 9-1. 좌측 접두사(leftmost prefix) 규칙 — 실측

```sql
CREATE INDEX idx_oh_cust_status ON order_header(customer_id, status);
```

이 인덱스는 `(customer_id, status, rowid)` 순으로 정렬된 목록이다. 전화번호부가 `성 → 이름` 순으로 정렬된 것과 같다. **성을 모르면 이름만으로는 못 찾는다.**

| 쿼리 | 실측 실행계획 (100만 행 사본) | 왜 |
|---|---|---|
| `WHERE customer_id=777` | `SEARCH … (customer_id=?)` ✅ | 첫 컬럼 = 좌측 접두사 |
| `WHERE customer_id=777 AND status='COMPLETED'` | `SEARCH … (customer_id=? AND status=?)` ✅ | 둘 다 사용 |
| `WHERE status='COMPLETED'` | **`SCAN order_header`** ❌ | 두 번째 컬럼만으로는 못 탄다 |
| `WHERE customer_id BETWEEN 10 AND 20` | `SEARCH … (customer_id>? AND customer_id<?)` ✅ | 범위도 첫 컬럼이면 OK |
| `WHERE status='COMPLETED' AND customer_id>1000` | `SEARCH … (customer_id>?)` ⚠️ | **`customer_id`로만 좁히고 `status`는 읽으면서 걸러 낸다** |

마지막 줄이 중요하다. 첫 컬럼이 범위 조건이면 **그 뒤 컬럼은 인덱스로 좁히는 데 못 쓰인다.** 실행계획에 `status=?`가 안 붙는 게 그 증거다.

**컬럼 순서를 정하는 규칙**: ① 등치(`=`) 조건으로 쓰는 컬럼을 앞에, 범위(`>`, `BETWEEN`)는 뒤에. ② 그 다음은 `ORDER BY`에 쓰는 컬럼 — `(a, b)` 인덱스는 `WHERE a=? ORDER BY b`의 정렬까지 공짜로 없애 준다. ③ 등치 컬럼끼리 순서를 고민할 때만 카디널리티가 높은(값 종류가 많은) 쪽을 앞에. `(customer_id, status)`가 `(status, customer_id)`보다 나은 이유다. **"무조건 카디널리티 높은 순"이 아니라 "쿼리가 실제로 거는 조건의 모양"이 1순위다.**

> **버전별 예외.** 좌측 접두사는 원칙이지만 2026년 기준으로 예외가 셋 있다.
> - **PostgreSQL**: 선두 컬럼이 빠져도 인덱스 전체를 훑는 게 힙 스캔보다 싸면 그렇게 한다(Bitmap Index Scan).
> - **MySQL 8.0.13+**: Skip Scan Range Access — 선두 컬럼의 값 종류가 적으면 값마다 따로 범위 스캔을 돌려 인덱스를 살려 쓴다.
> - **PostgreSQL 18+**: 멀티컬럼 B-tree에 skip scan이 들어왔다. 같은 발상이다.
>
> 즉 "선두 컬럼이 없으면 절대 못 쓴다"가 아니라 "**선두 컬럼이 없으면 인덱스를 좁히는 용도로는 못 쓰고, 엔진이 우회로를 쓸 수 있을 뿐**"이 정확한 답이다.

#### 9-2. 인덱스를 못 타게 만드는 안티패턴 — 전부 실측

```sql
-- ① 컬럼에 함수를 씌운다
SELECT * FROM customer WHERE lower(email) = 'a@b.com';   -- SCAN customer  ❌
SELECT * FROM customer WHERE email = 'a@b.com';          -- SEARCH … (email=?)  ✅

-- ② 컬럼에 연산을 한다
SELECT * FROM order_header WHERE id + 0 = 3;             -- SCAN order_header  ❌
SELECT * FROM order_header WHERE id = 3;                 -- SEARCH … INTEGER PRIMARY KEY  ✅

-- ③ 타입을 바꾼다
SELECT * FROM order_header WHERE CAST(customer_id AS TEXT) = '1';  -- SCAN  ❌
```

**원리는 하나다.** 인덱스에 정렬돼 저장된 건 `email` 원본 값이지 `lower(email)`이 아니다. `lower()`를 통과한 값의 순서는 인덱스가 모르므로, 모든 행에 함수를 적용해 보는 수밖에 없다. → **"인덱스 컬럼은 WHERE 절 왼쪽에서 벌거벗겨 두고, 변형은 오른쪽 상수에 한다."**

해결책은 세 DBMS 모두 **표현식 인덱스**다. 실측으로 확인했다.

```sql
CREATE INDEX idx_cust_lower_email ON customer(lower(email));
EXPLAIN QUERY PLAN SELECT * FROM customer WHERE lower(email) = 'minjun@example.com';
--   SEARCH customer USING INDEX idx_cust_lower_email (<expr>=?)     ← 탄다
```

`(<expr>=?)` 라는 표기가 "표현식 인덱스를 쓰고 있다"는 SQLite의 표시다.

| | 표현식 인덱스 지원 |
|---|---|
| SQLite | **3.9.0+** `CREATE INDEX i ON customer(lower(email))` |
| PostgreSQL | 오래전부터 지원, 동일 문법 (단 함수가 `IMMUTABLE`이어야 한다) |
| MySQL 8 | **8.0.13+** `CREATE INDEX i ON customer((lower(email)))` — 괄호 두 겹 필수. 그 이전 버전은 생성 컬럼(generated column)을 만들어 인덱싱해야 했다 |

#### 9-3. Q4-B가 정확히 이 케이스다

```sql
-- 03_queries.sql Q4-B (73~81행)
SELECT id, name, price FROM menu WHERE name LIKE '%라떼%' ORDER BY price DESC, id;
-- 실측 실행계획:
--   SCAN menu                        ← sqlite_autoindex_menu_1(name UNIQUE)이 있는데도 못 탄다
--   USE TEMP B-TREE FOR ORDER BY     ← 정렬까지 임시 B-Tree로 따로 한다
```

**왜 못 타는가.** B-Tree는 `아메리카노, 얼그레이, 자몽에이드, 초콜릿라떼, 카페라떼…` 순으로 **앞글자부터** 정렬돼 있다. 색인이 '가나다순'인 것과 같다. "가운데에 '라떼'가 들어간 단어"는 사전 어디에도 모여 있지 않다. 시작점을 못 잡으니 전부 봐야 한다. 게다가 `ORDER BY price DESC, id`를 받쳐 줄 인덱스도 없어서 정렬용 임시 B-Tree까지 하나 더 만든다. **한 쿼리에 안티패턴이 두 개 들어 있는 셈이다.**

**앞 와일드카드를 떼면 어떻게 되는가** — 여기서 SQLite의 함정이 하나 나온다. 실측:

```sql
SELECT * FROM menu WHERE name LIKE '아메%';
--   기본 상태:                          SCAN menu                                       ❌
--   PRAGMA case_sensitive_like=ON:     SEARCH menu USING INDEX … (name>? AND name<?)   ✅
```

기본 상태에서도 못 탄다. 이유는 **SQLite의 `LIKE`가 기본적으로 대소문자를 구분하지 않는데(ASCII 한정) 인덱스는 BINARY 콜레이션으로 정렬돼 있어서** 순서가 일치하지 않기 때문이다. 조건이 맞으면 SQLite는 `LIKE '아메%'`를 **`name >= '아메' AND name < '아메(다음문자)'` 범위 검색으로 바꿔치기한다**(LIKE optimization). 실행계획의 `(name>? AND name<?)`가 그 증거다.

다만 `PRAGMA case_sensitive_like=ON`은 **DB 전체의 LIKE 의미를 바꿔 버리는** 부작용이 있다. 더 나은 해법은 콜레이션을 맞춘 인덱스를 따로 만드는 것이고, 이것도 실측했다.

```sql
CREATE INDEX idx_menu_name_nocase ON menu(name COLLATE NOCASE);
EXPLAIN QUERY PLAN SELECT * FROM menu WHERE name LIKE '아메%';
--   SEARCH menu USING INDEX idx_menu_name_nocase (name>? AND name<?)   ← 기본 PRAGMA 상태에서도 탄다
```

| | `LIKE '아메%'` (접두사) | `LIKE '%라떼%'` (앞 와일드카드) |
|---|---|---|
| SQLite | `case_sensitive_like=ON`이거나 인덱스가 `COLLATE NOCASE`여야 인덱스 사용 | 항상 풀스캔 |
| MySQL 8 | 인덱스 사용 (`type = range`) | 항상 풀스캔 |
| PostgreSQL | **기본 로케일에서는 못 씀.** `text_pattern_ops` 연산자 클래스(opclass) 인덱스 또는 C 로케일 필요 | 항상 풀스캔. `pg_trgm` GIN/GiST 인덱스로 해결 가능 |

**대량 데이터에서의 정답은 인덱스 튜닝이 아니라 구조 교체다.** 그런데 여기서 한국어 때문에 흔히 틀린다.

```sql
-- ❌ 이렇게 하면 0행이 나온다 (실측)
CREATE VIRTUAL TABLE menu_fts USING fts5(name, content='menu', content_rowid='id');
INSERT INTO menu_fts(rowid, name) SELECT id, name FROM menu;
SELECT rowid FROM menu_fts WHERE menu_fts MATCH '라떼';    -- 0행
SELECT rowid FROM menu_fts WHERE menu_fts MATCH '라떼*';   -- 0행
SELECT rowid FROM menu_fts WHERE menu_fts MATCH '카페라떼';-- 1행 (2)
```

FTS5의 기본 토크나이저(`unicode61`)는 **공백과 구두점으로만** 자른다. 한국어 `'카페라떼'`는 통째로 **한 토큰**이라, `MATCH '라떼'`로는 절대 못 찾는다. `*`는 접두사 검색이라 `'라떼*'`도 소용없다. 즉 **위 코드는 `%라떼%` 문제의 해답이 아니다.**

한국어 부분일치의 실제 해답은 **트라이그램 토크나이저**(SQLite 3.34.0+)다. 이건 `LIKE '%…%'`와 `GLOB`을 인덱스로 처리해 준다. 실측:

```sql
-- ✅ 트라이그램 (3글자 단위로 색인)
CREATE VIRTUAL TABLE menu_tri USING fts5(
    name, content='menu', content_rowid='id', tokenize='trigram');
INSERT INTO menu_tri(rowid, name) SELECT id, name FROM menu;

SELECT m.id, m.name, m.price
FROM   menu_tri f JOIN menu m ON m.id = f.rowid
WHERE  f.name LIKE '%라떼%'
ORDER  BY m.price DESC, m.id;
--  (3, '바닐라라떼', 5000) / (4, '초콜릿라떼', 5000) / (2, '카페라떼', 4500)   ← 3행, 정답
--  실행계획: SCAN f VIRTUAL TABLE INDEX 0:L0
--            SEARCH m USING INTEGER PRIMARY KEY (rowid=?)
```

`INDEX 0:L0`의 `L`이 "LIKE 조건을 트라이그램 인덱스로 밀어 넣었다"는 표시다. 주의할 제약이 둘 있다.

- 트라이그램은 3글자 단위라 **검색어가 3글자 이상**이어야 한다. 실측으로 `MATCH '바닐라'`(3글자)는 적중하지만 `MATCH '라떼'`(2글자)는 0행이다. 반면 `LIKE '%라떼%'`는 위처럼 잘 동작한다 — 그래서 트라이그램은 `MATCH`보다 `LIKE`/`GLOB`과 함께 쓴다.
- 외부 콘텐츠 테이블(`content='menu'`)을 쓰면 원본이 바뀔 때 FTS가 자동으로 안 따라온다. 트리거로 동기화하거나 `content=` 없이 자체 저장해야 한다.

문법 함정도 하나. `MATCH` 왼쪽에는 **별칭이 아니라 테이블 이름**이 와야 한다. `JOIN menu_fts f … WHERE f MATCH '라떼'`는 `no such column: f` 에러가 난다.

말로 할 때:

> "Q4-B는 의도적으로 느린 쿼리입니다. `LIKE '%라떼%'`는 앞에 와일드카드가 있어서 B-Tree의 정렬 순서를 쓸 수 없고, 실행계획도 `SCAN menu` 더하기 `USE TEMP B-TREE FOR ORDER BY`로 나옵니다. B-Tree는 '앞글자부터 정렬된 사전'이라 가운데 글자로는 시작점을 못 잡기 때문입니다. 메뉴가 12개라 지금은 문제가 없지만, 규모가 커지면 구조를 바꿔야 합니다. 다만 SQLite FTS5를 기본 토크나이저로 붙이면 '카페라떼'가 한 토큰이라 '라떼'로 검색해도 0행이 나옵니다. 제가 직접 확인했고, 그래서 `tokenize='trigram'`으로 만들어야 `LIKE '%라떼%'`가 인덱스를 탑니다. PostgreSQL이면 `pg_trgm` GIN, MySQL이면 `ngram` 파서, 실무 규모면 Elasticsearch입니다. 전부 같은 발상 — 한국어는 단어 단위로 자르면 안 되고 n-gram으로 잘라야 한다는 겁니다."

#### 9-4. NULL과 인덱스 — 자주 나오는 통념 하나

"인덱스는 NULL을 저장하지 않는다"는 말이 널리 퍼져 있는데, 이건 **Oracle의 단일 컬럼 B-tree 인덱스에 한정된 이야기**다. SQLite와 PostgreSQL은 NULL도 인덱스에 넣는다. 실측:

```sql
CREATE INDEX idx_cust_phone ON customer(phone);          -- phone은 유일하게 NULL 허용 컬럼
EXPLAIN QUERY PLAN SELECT * FROM customer WHERE phone IS NULL;
--   SEARCH customer USING INDEX idx_cust_phone (phone=?)   ← IS NULL 도 인덱스를 탄다
```

같이 알아 둘 것 두 가지.

- **UNIQUE 컬럼에 NULL은 몇 개든 들어간다.** SQL 표준이 "NULL은 서로 같지 않다"고 보기 때문이다. 실측으로 `x TEXT UNIQUE` 컬럼에 `NULL`을 3번 넣어도 3행이 전부 들어간다. PostgreSQL 15+는 `UNIQUE NULLS NOT DISTINCT`로 이 동작을 뒤집을 수 있다.
- **`NOT IN` + NULL 함정.** `WHERE id NOT IN (SELECT customer_id FROM order_header)`에서 서브쿼리 결과에 NULL이 하나라도 있으면 조건이 UNKNOWN이 되어 **결과가 통째로 0행**이 된다(3값 논리). 그래서 이 프로젝트는 Q7/Q8에서 `NOT IN` 대신 `LEFT JOIN … WHERE 우측 IS NULL` 형태를 쓴다. `NOT EXISTS`도 안전한 대안이다. 이 프로젝트의 `order_header.customer_id`는 `NOT NULL`이라 지금은 문제가 없지만, 스키마가 바뀌면 조용히 터지는 종류의 버그다.

#### 9-5. 부분 인덱스와 내림차순 인덱스

인덱스를 꼭 컬럼 전체에 걸 필요는 없다. **부분 인덱스(partial index)** 는 조건을 만족하는 행만 담아서 훨씬 작다.

```sql
CREATE INDEX idx_oh_pending ON order_header(customer_id) WHERE status = 'PENDING';
EXPLAIN QUERY PLAN SELECT * FROM order_header WHERE customer_id = 2 AND status = 'PENDING';
--   SEARCH order_header USING INDEX idx_oh_pending (customer_id=?)     ← 실측, 탄다
```

"미처리 주문만 자주 조회한다" 같은 실무 패턴에 딱 맞는다. 전체 주문의 5%만 `PENDING`이면 인덱스도 5% 크기다. 단, **쿼리의 `WHERE`가 인덱스의 조건을 논리적으로 포함해야만** 옵티마이저가 쓴다.

| | 부분 인덱스 | 내림차순 인덱스 |
|---|---|---|
| SQLite | **3.8.0+** 지원 | `CREATE INDEX … ON t(a DESC)` 지원 |
| PostgreSQL | 지원 | 지원 (`ASC/DESC`, `NULLS FIRST/LAST`) |
| MySQL 8 | **미지원** (생성 컬럼 + 인덱스로 흉내) | **8.0.1+** 부터 진짜 내림차순 인덱스. 그 이전엔 `DESC`를 파싱만 하고 무시했다 |

내림차순 인덱스가 필요한 순간은 `ORDER BY a ASC, b DESC`처럼 **방향이 섞일 때**다. 방향이 전부 같으면 인덱스를 거꾸로 읽으면 그만이라 별도 인덱스가 필요 없다.

---

### 10. B-Tree 말고 다른 인덱스들 — 언제 쓰는가

| 인덱스 | 자료구조 | 잘하는 것 | 못하는 것 / 대가 | 어디에 |
|---|---|---|---|---|
| **B+Tree** | 다분기 균형 트리 (+ 리프 링크) | `=`, 범위, `ORDER BY`, 접두사 — 만능 | 특별히 못하는 게 없어서 기본값 | SQLite/MySQL/PG 전부 기본 |
| **Hash** | 해시 테이블 | `=` 하나만. 상수 시간 | **범위·정렬 불가.** 크기가 크면 리해싱 비용 | MySQL MEMORY 엔진(기본이 HASH), PostgreSQL `USING hash` (**10부터 WAL 기록 = 크래시 안전**), InnoDB 적응형 해시(자동·메모리 전용) |
| **LSM-Tree** | 메모리 memtable + 디스크 SSTable 계층 | **쓰기 폭주에 강함**(순차 쓰기로 바꿔 버림) | 읽기가 여러 레벨을 뒤짐(블룸 필터로 완화), 컴팩션 부하와 쓰기 증폭 | RocksDB, LevelDB, Cassandra, HBase |
| **GIN** | 역색인 (키 → 행 목록) | 배열/JSONB 포함 검색, 전문 검색, `pg_trgm` | 갱신이 느림(`fastupdate` 대기 목록으로 완화) | PostgreSQL `jsonb @>`, `to_tsvector` |
| **GiST / SP-GiST** | 확장 가능한 균형 트리 | 지리(PostGIS), 범위 타입 겹침, 최근접 검색 | 정확도가 연산자 클래스에 달림 | PostgreSQL 공간 검색 |
| **BRIN** | 블록 범위별 min/max 요약 | 물리 순서와 값 순서가 맞는 거대 테이블(시계열 로그) | 순서가 흐트러지면 무용지물 | PostgreSQL 9.5+ |
| **비트맵** | 값마다 비트 벡터 | 저카디널리티 컬럼 여러 개 AND/OR | 쓰기 시 락 범위가 큼 | Oracle. PG는 영구 객체가 아니라 쿼리 중 임시로만 생성(Bitmap Scan) |
| **역색인(FTS)** | 토큰 → 문서 ID | `%라떼%` 류 부분/단어 검색 | 토크나이저 선택이 결과를 좌우, 저장소 추가 | SQLite FTS5, MySQL FULLTEXT(한국어는 `ngram` 파서), Elasticsearch |
| **R-Tree** | 경계 상자 트리 | 2차원 범위(지도) | 1차원엔 무의미 | SQLite R*Tree 모듈, PostGIS |

"어떤 DB를 언제 쓰느냐"(피드백 4번)와 여기가 붙는다. **쓰기가 읽기를 압도하는 로그/시계열이면 LSM-Tree 계열(Cassandra, RocksDB), 읽기와 범위 조회가 중심인 트랜잭션 업무면 B+Tree 계열(PostgreSQL/MySQL)** 이라고 한 줄로 이으면 좋다.

---

### 11. 버전 경계 한 장 — 이 모듈에서 인용한 기능들

"됩니다/안 됩니다"로만 답하면 반드시 "어느 버전부터요?"가 따라온다.

| 기능 | 도입 버전 |
|---|---|
| SQLite 부분 인덱스 | **3.8.0** (2013) |
| SQLite 표현식 인덱스, FTS5 | **3.9.0** (2015) |
| SQLite 기본 `page_size` 4096 | **3.12.0** (2016) |
| SQLite FTS5 `tokenize='trigram'` | **3.34.0** (2020) |
| SQLite 실행계획의 `BLOOM FILTER` | **3.38.0** (2022) |
| SQLite `RIGHT JOIN` / `FULL OUTER JOIN` | **3.39.0** (2022) — 그 이전엔 `LEFT JOIN`만 가능해서 좌우를 뒤집어 써야 했다 |
| MySQL 진짜 내림차순 인덱스 | **8.0.1** |
| MySQL 함수 인덱스, Skip Scan | **8.0.13** |
| MySQL `CHECK` 제약 **실제 강제** | **8.0.16** — 이전 버전은 파싱만 하고 무시 |
| MySQL `EXPLAIN ANALYZE` | **8.0.18** |
| PostgreSQL Index Only Scan | **9.2** |
| PostgreSQL BRIN | **9.5** |
| PostgreSQL 해시 인덱스 WAL 기록(크래시 안전) | **10** |
| PostgreSQL 커버링 인덱스 `INCLUDE` | **11** |
| PostgreSQL `UNIQUE NULLS NOT DISTINCT` | **15** |
| PostgreSQL B-tree skip scan | **18** |

---

### 12. 면접 예상 질문 6개 + 답변 대본

**Q1. 인덱싱이 왜 '인덱싱'입니까?**
> "index는 '가리키는 것'이라는 뜻이고, 책 뒤의 색인과 같은 말입니다. 색인은 본문이 아니라 '단어 → 쪽번호' 목록이고, DB 인덱스도 행 전체가 아니라 '컬럼 값 → 행 위치'의 정렬된 사본입니다. 제 DB의 `idx_order_header_customer_id`도 리프에 `(customer_id, rowid)` 쌍만 들어 있고, 실제 주문 데이터는 없습니다. 그래서 인덱스만으로 답이 나오는 쿼리는 테이블을 아예 안 읽는데, 그게 커버링 인덱스입니다."

**Q2. 왜 이진 트리가 아니라 B-Tree입니까?**
> "디스크가 페이지 단위로 읽기 때문입니다. SQLite는 4KB, InnoDB는 16KB, PostgreSQL은 8KB입니다. 이진 트리는 4KB를 읽어서 키 하나만 쓰니까 낭비고, 100만 행이면 높이가 20이라 페이지 읽기가 20번 필요합니다. B-Tree는 페이지 하나에 키를 수백 개 담아 팬아웃을 키웁니다. 제가 100만 행 사본에서 `dbstat`으로 실제로 재 보니 팬아웃이 162였고, 리프 5,036장을 그 위 내부 노드 31장이 덮고 그 위가 루트 한 장이라 트리 높이가 3이었습니다. 페이지 읽기 20번과 3번의 차이입니다."

**Q3. B-Tree와 B+Tree의 차이, 그리고 `BETWEEN`이 왜 인덱스를 탑니까?**
> "B+Tree는 데이터를 리프에만 두고, 내부 노드는 길잡이 키만 담습니다. 그래서 내부 노드에 키가 더 많이 들어가서 높이가 더 낮아집니다. 그리고 InnoDB나 PostgreSQL처럼 리프끼리 좌우로 연결해 두는 구현이 많습니다. `customer_id BETWEEN 10 AND 20`이면 10인 첫 리프까지 트리를 세 번 타고 내려간 다음, 거기서부터 순서대로 옆으로 읽다가 21이 나오면 멈춥니다. `ORDER BY`도 같은 이유로 공짜입니다 — 인덱스를 순서대로 읽으면 그게 이미 정렬 결과라 정렬 연산이 사라집니다. 반대로 해시 인덱스는 키의 대소 관계를 보존하지 않기 때문에 이게 원리적으로 불가능합니다. 다만 정확히는, SQLite에는 리프 형제 포인터가 없고 커서가 부모 스택을 되짚어 다음 리프로 갑니다. 결과는 같지만 구현은 엔진마다 다릅니다."

**Q4. `EXPLAIN QUERY PLAN`에서 SCAN과 SEARCH가 뭐가 다릅니까?**
> "SCAN은 테이블 전체를 처음부터 끝까지 방문하는 풀스캔이고, SEARCH는 인덱스로 후보를 좁혀서 들어가는 겁니다. 제 Q15가 그 실험인데, 인덱스를 지운 상태에서 `SCAN order_header`였다가 인덱스를 만들면 `SEARCH order_header USING INDEX idx_order_header_customer_id (customer_id=?)`로 바뀝니다. MySQL로 치면 `type=ALL`이 `ref`로 바뀌는 것이고, PostgreSQL로 치면 `Seq Scan`이 `Index Scan`으로 바뀌는 것입니다. 두 가지 더 있는데, `SCAN customer USING INDEX`처럼 SCAN인데 USING INDEX가 붙는 경우는 전부 읽되 인덱스 순서로 읽어서 ORDER BY를 생략한 케이스이고, `USING AUTOMATIC COVERING INDEX`가 뜨면 SQLite가 쿼리 도는 중에 임시 인덱스를 만들었다는 뜻이라 '여기 인덱스를 만들어라'는 신호입니다."

**Q5. 인덱스를 많이 만들면 왜 안 됩니까? 언제 안 만듭니까?**
> "세 가지 비용이 있습니다. 첫째, 쓰기마다 인덱스 B-Tree도 같이 갱신해야 합니다. 100만 행 테이블에서 10만 건을 넣어 보니 인덱스가 없을 때 0.37초, 단일 인덱스가 있을 때 0.89초로 2.4배, 두 컬럼 복합 인덱스면 1.05초로 2.8배 느렸습니다. 둘째, 디스크입니다. 같은 실험에서 파일이 39.2MiB에서 50.0MiB로 28% 늘었고, 복합 인덱스는 50% 늘었습니다. 셋째, 옵티마이저가 고를 후보가 늘어서 통계가 낡으면 엉뚱한 인덱스를 탈 수 있습니다. 안 만드는 기준은 카디널리티입니다. 제 `order_header.status`는 Q14 이후 실제 값이 COMPLETED와 PENDING 둘뿐이라 인덱스를 만들어 놓고 `ANALYZE`를 돌려도 SQLite가 안 탔습니다. `sqlite_stat1`에 '10 5'로 기록되는데, 10행을 서로 다른 값 2개가 나눠 가져 값 하나가 평균 5행, 즉 절반을 가리킨다는 뜻이라 인덱스를 타 봐야 어차피 절반을 읽으니 풀스캔이 낫다고 판단한 겁니다."

**Q6. `WHERE name LIKE '%라떼%'`는 왜 느립니까?**
> "제 Q4-B가 그 케이스입니다. `menu.name`은 UNIQUE라 인덱스가 자동으로 있는데도 실행계획이 `SCAN menu`에 `USE TEMP B-TREE FOR ORDER BY`까지 붙습니다. B-Tree는 앞글자부터 정렬된 사전이라 '가운데에 라떼가 든 단어'는 어디에도 모여 있지 않고, 시작점을 못 잡으니 전부 봐야 합니다. 앞 %를 떼서 `'아메%'`로 하면 SQLite가 이걸 `name >= '아메' AND name < ...` 범위 검색으로 바꿔서 인덱스를 탑니다. 다만 SQLite는 LIKE가 기본으로 대소문자를 무시하는데 인덱스는 BINARY 콜레이션이라, `PRAGMA case_sensitive_like=ON`이거나 인덱스를 `COLLATE NOCASE`로 만들어야 실제로 탑니다. 이건 제가 직접 확인했습니다. 데이터가 커지면 인덱스 튜닝이 아니라 구조를 바꿔야 하는데, 여기서 한 번 더 함정이 있습니다. SQLite FTS5를 기본 토크나이저로 붙이면 '카페라떼'가 한 토큰이라 '라떼'로 검색해도 0행입니다. 실제로 돌려서 확인했고, `tokenize='trigram'`으로 만들어야 `LIKE '%라떼%'`가 인덱스를 탑니다. PostgreSQL은 pg_trgm GIN, MySQL은 ngram 파서, 실무 규모면 Elasticsearch로 가고, 전부 '단어가 아니라 n-gram으로 잘라 역색인을 만든다'는 같은 발상입니다."

---

### 13. 한 장 요약 — 손으로 그릴 것

```text
색인(index) = 값 → 위치 의 '정렬된 사본'

  값으로 위치를 만든다 ─┬─ 계산     : 배열 base+i·size     → rowid / PK 직접 접근
                        ├─ 해싱     : dict, HashMap        → HASH 인덱스 (= 만 가능)
                        ├─ 순서유지 : 정렬배열+이진탐색     → B+Tree 인덱스 (= 범위 정렬 전부)
                        └─ 뒤집기   : 토큰 → 문서ID 리스트  → FTS / GIN (%라떼% 의 정답)
                                       ※ 한국어는 단어가 아니라 n-gram 으로 잘라야 한다

  B+Tree 를 쓰는 이유 = 디스크가 페이지(4~16KB) 단위라서
      팬아웃 162 (실측) → 100만 행에 트리 높이 3 → 페이지 읽기 3번 (이진 트리면 20번)

  인덱스는 조회를 800배 빠르게 하고 (55.8ms → 0.07ms)
  쓰기를 2.4배 느리게 하고 디스크를 28% 더 먹는다 (전부 실측, 100만 행)
  → 그래서 '자주 조건/조인 키로 쓰이고 카디널리티가 높은 컬럼'에만 건다
  → 10행짜리 테이블에서는 인덱스가 오히려 손해다 (0.0153ms → 0.0155ms, 실측)
```

---

**참고한 파일**
- `/home/coder/volume/codyssey_B5-1/01_schema.sql` — `UNIQUE`가 `sqlite_autoindex_*`를 만든다는 주석이 이미 달려 있다
- `/home/coder/volume/codyssey_B5-1/03_queries.sql` — Q4-B(LIKE 안티패턴, 73~81행), Q15-A/Q15/Q15-B(인덱스 전후 실행계획, 294~347행)
- `/home/coder/volume/codyssey_B5-1/cafe.db` — 실측 대상 (현재 상태: customer 10 / category 10 / menu 12 / order_header 10 / order_detail 18, 인덱스 5개, `order_header` 상태 분포는 COMPLETED 9 / PENDING 1)

**실측 환경**
- SQLite 3.46.1 (Python 3.14.4의 `sqlite3` 모듈), `PRAGMA page_size` = 4096
- `dbstat` 가상 테이블 사용 가능 (`PRAGMA compile_options`에 `ENABLE_DBSTAT_VTAB` 확인). `STMT_SCANSTATUS`는 없어서 `.scanstats`는 못 쓴다
- 100만 행 사본 생성 스크립트는 8절에 그대로 실었다

---

## 보강 — 평가 피드백 재점검에서 추가된 것


### 9. FK를 걸면 인덱스가 생기는가 — DBMS가 갈리는 지점

| DBMS | 자식(FK) 컬럼 인덱스 | 부모(참조 대상) 인덱스 |
|---|---|---|
| **SQLite** | **자동 생성 안 함** | 부모는 PK/UNIQUE여야만 하므로 사실상 항상 있음 |
| **MySQL 8 (InnoDB)** | **자동 생성함** — 없으면 만들어 준다 | 필수 |
| **PostgreSQL** | **자동 생성 안 함** | 필수 |

즉 "FK를 걸었으니 인덱스는 됐다"는 MySQL에서만 맞는 말이고, 이 프로젝트(SQLite)에서는 틀리다. 이 한 문장이 피드백 5번에 대한 가장 강한 답이다.

### 10. 그래서 이 스키마에 빠진 인덱스 두 개 — 실측

`03_queries.sql`의 Q15는 인덱스를 두 개 만들었다. FK는 네 개인데 두 개만 덮은 것이다.

| FK | 인덱스 | 상태 |
|---|---|---|
| `order_header.customer_id` → `customer.id` | `idx_order_header_customer_id` | 있음 |
| `order_detail.order_id` → `order_header.id` | `idx_order_detail_order_id` | 있음 |
| `order_detail.menu_id` → `menu.id` | 없음 | **빠짐** |
| `menu.category_id` → `category.id` | 없음 | **빠짐** |

실측(`cafe.db`, SQLite 3.46.1):

```text
EXPLAIN QUERY PLAN SELECT * FROM order_detail WHERE menu_id = 1;
  -> SCAN order_detail                       (풀스캔)
EXPLAIN QUERY PLAN SELECT * FROM menu WHERE category_id = 1;
  -> SCAN menu                               (풀스캔)
```

더 중요한 건 조회가 아니라 **부모 삭제**다. FK 검사는 "이 부모를 참조하는 자식이 있는가?"를 자식 테이블에서 찾는 작업이고, 인덱스가 없으면 그게 풀스캔이 된다.

```text
EXPLAIN QUERY PLAN DELETE FROM order_header WHERE id = 1;
  -> SEARCH order_header USING INTEGER PRIMARY KEY (rowid=?)
  -> SEARCH order_detail USING COVERING INDEX idx_order_detail_order_id (order_id=?)   ← 인덱스 있음: 찍어 찾음

EXPLAIN QUERY PLAN DELETE FROM category WHERE id = 9;
  -> SEARCH category USING INTEGER PRIMARY KEY (rowid=?)
  -> SCAN menu                                                                          ← 인덱스 없음: 전부 훑음
```

두 계획을 나란히 놓으면 인덱스의 값어치가 한눈에 보인다. 위쪽은 CASCADE 대상을 인덱스로 찍어 찾고, 아래쪽은 삭제 한 건을 위해 `menu` 전체를 읽는다. 메뉴가 12개면 무시할 만하지만 100만 개면 카테고리 하나 지우는 데 100만 행을 읽는다.

보완은 두 줄이다.

```sql
CREATE INDEX IF NOT EXISTS idx_order_detail_menu_id ON order_detail(menu_id);
CREATE INDEX IF NOT EXISTS idx_menu_category_id     ON menu(category_id);
```

### 11. 인덱스를 만들었는데 안 타는 다섯 경우 — 이 스키마로

| 안 타는 쿼리 | 왜 | 고친 쿼리 |
|---|---|---|
| `WHERE LENGTH(name) = 5` | 컬럼에 함수를 씌우면 인덱스 키 순서가 무의미해진다 | 표현식 인덱스 `CREATE INDEX ... ON menu(LENGTH(name))` (SQLite 3.9+, PG 가능, MySQL 8.0.13+) |
| `WHERE name LIKE '%라떼'` | 선행 와일드카드라 시작 지점을 못 잡는다 | `LIKE '라떼%'`는 탄다(단 SQLite는 `PRAGMA case_sensitive_like` 등 조건이 붙는다). 전문 검색은 FTS5 |
| `WHERE customer_id = '1'` (문자열) | SQLite의 타입 친화성 때문에 비교 규칙이 달라질 수 있다 | 바인딩할 때 정수로 넘긴다 |
| `WHERE order_id = 1 OR menu_id = 1` | 인덱스 하나로는 두 조건을 못 만족 | `UNION`으로 쪼개거나 각각 인덱스를 두고 옵티마이저의 OR 최적화에 맡긴다 |
| `ORDER BY quantity`만 있는 쿼리 | 정렬 대상 컬럼에 인덱스가 없으면 `USE TEMP B-TREE FOR ORDER BY` | 정렬이 잦으면 그 컬럼에 인덱스 |

### 12. 복합 인덱스의 좌측 접두사 규칙

`CREATE INDEX idx ON order_detail(order_id, menu_id)`를 만들면 인덱스 키는 `(order_id, menu_id, rowid)` 순으로 정렬된다. 전화번호부가 (성, 이름) 순으로 정렬된 것과 같다.

| 조건 | 탈 수 있나 | 이유 |
|---|---|---|
| `WHERE order_id = 1 AND menu_id = 2` | 완전히 탄다 | 성과 이름을 다 아는 경우 |
| `WHERE order_id = 1` | 탄다 | 성만 알아도 그 구간으로 점프 가능 |
| `WHERE menu_id = 2` | **못 탄다** | 이름만 알고 성을 모르면 전화번호부를 처음부터 봐야 한다 |

그래서 컬럼 순서가 설계다. 등호 조건으로 자주 쓰는 컬럼을 앞에 둔다.
