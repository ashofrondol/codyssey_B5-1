#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
카페 주문 관리 DB - 빌드 & 결과 캡처 스크립트

이 스크립트 하나가 다음을 순서대로 수행한다.

    1) cafe.db 를 지우고 01_schema.sql + 02_data.sql 로 새로 만든다
    2) 04_bonus.sql   -> results/bonus_results.txt
    3) 03_queries.sql -> results/results.txt
    4) 만들어진 것이 '기대값 표'와 일치하는지 검사한다 (실패하면 종료 코드 1)

★ 왜 캡처만 하지 않고 검사까지 하나
   캡처는 "무슨 일이 일어났는지"를 적을 뿐, "일어나야 할 일이 일어났는지"는 말하지 않는다.
   FK 선언을 지워도, 샘플 데이터를 9행으로 줄여도, 일부러 실패해야 할 INSERT 가
   조용히 성공해도 - 예전의 이 스크립트는 끝까지 돌고 종료 코드 0 을 냈다.
   즉 명세 요구사항이 깨진 것을 사람이 결과 파일을 눈으로 비교해야만 알 수 있었다.
   지금은 아래 EXPECTED_* 표와 대조해 하나라도 어긋나면 종료 코드 1 로 멈춘다.

★ 왜 보너스를 먼저 캡처하나
   03_queries.sql 의 Q13(UPDATE) / Q14(DELETE) 는 DB 상태를 실제로 바꾼다.
   특히 Q14 는 CANCELLED 주문을 지우는데, 박지호의 유일한 주문이 취소건이라
   이걸 먼저 실행하면 04_bonus.sql (1)의 결과가 4행 -> 3행으로 달라진다.
   그래서 '깨끗한 데이터'를 전제로 하는 보너스를 항상 먼저 캡처한다.

★ 왜 파이썬인가
   sqlite3 CLI 가 설치되어 있지 않은 환경에서도 결과를 재생성할 수 있어야 하기 때문이다.
   (파이썬 표준 라이브러리의 sqlite3 모듈만 쓰므로 추가 설치가 필요 없다.)
   sqlite3 CLI 가 있다면 README '2. 실행 방법' 의 CLI 절차를 그대로 써도 결과는 같다.

★ 단일 진실 원천(single source of truth)
   출력은 제출용 SQL 파일(03_queries.sql / 04_bonus.sql)을 '직접' 읽어서 만든다.
   캡처용 사본을 따로 두지 않으므로 제출 파일과 결과가 어긋날 수 없다.

사용법:
    python build_and_capture.py          # 종료 코드 0 = 전부 통과, 1 = 검사 실패
"""

import os
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "cafe.db")
RESULTS_DIR = os.path.join(BASE_DIR, "results")

SCHEMA_SQL = "01_schema.sql"
DATA_SQL = "02_data.sql"
QUERIES_SQL = "03_queries.sql"
BONUS_SQL = "04_bonus.sql"

# 일부러 실패하는 문장이 들어 있는 파일 (에러가 나도 계속 진행한다)
ALLOW_ERRORS = {BONUS_SQL}


# =====================================================================
# 기대값 표 - "무엇이 맞는 상태인가"를 여기 한 곳에만 적는다
#
#   지금까지 이 사실들은 README 표·SQL 주석·아래 print 문 세 곳에 흩어져 있었고,
#   셋이 어긋나도 아무도 알아채지 못했다. 아래 상수만 고치면 검사 전체가 따라 움직인다.
#   각 항목 옆의 R번호는 README '0. 과제 명세' 의 요구사항 ID 다.
# =====================================================================

# R4-1 : 각 테이블 10행 이상
MIN_ROWS_PER_TABLE = 10

# R2-1 : 최소 4개 테이블 (이 저장소는 5개)
EXPECTED_TABLES = ("customer", "category", "menu", "order_header", "order_detail")

# R2-3 : (자식 테이블, 부모 테이블) 형태의 1:N 관계. 명세 하한은 2개, 이 저장소는 4개.
EXPECTED_FOREIGN_KEYS = (
    ("menu", "category"),
    ("order_detail", "menu"),
    ("order_detail", "order_header"),
    ("order_header", "customer"),
)

# R3-3 / 보너스 B2 : 04_bonus.sql (2-a)~(2-d) 가 '일부러' 일으켜야 하는 에러.
#   여기서 기대하는 것은 성공이 아니라 실패다. 이 INSERT 들이 조용히 성공하면
#   제약이 선언만 되어 있고 실제로는 꺼져 있다는 뜻이므로 검사를 실패시킨다.
EXPECTED_VIOLATIONS = (
    ("(2-a) FK", "FOREIGN KEY constraint failed"),
    ("(2-b) UNIQUE", "UNIQUE constraint failed: customer.email"),
    ("(2-c) CHECK", "CHECK constraint failed"),
    ("(2-d) NOT NULL", "NOT NULL constraint failed: customer.email"),
)

# 03_queries.sql 의 Q13/Q14/Q15 까지 적용한 뒤의 최종 상태.
#   README '1. 디렉터리 구성' 의 cafe.db 설명과 같은 값이어야 한다.
EXPECTED_FINAL_STATE = (
    ("아메리카노 price (Q13)", "SELECT price FROM menu WHERE name = '아메리카노'", 4000),
    ("order_header 행수 (Q14)", "SELECT COUNT(*) FROM order_header", 10),
    ("order_detail 행수 (Q14 CASCADE)", "SELECT COUNT(*) FROM order_detail", 18),
    (
        "직접 만든 인덱스 개수 (Q15)",
        "SELECT COUNT(*) FROM sqlite_master "
        "WHERE type = 'index' AND name NOT LIKE 'sqlite_%'",
        2,
    ),
)

# R3-3 : `PRAGMA foreign_keys = ON` 은 '연결마다' 켜야 하므로 네 스크립트 모두가 직접 선언해야 한다.
#   러너(build_database)가 방어적으로 한 번 더 켜기 때문에, .sql 에서 이 줄이 사라져도
#   러너로 돌리면 아무 일도 일어나지 않는다 - 그러나 README '2. 실행 방법' 의 sqlite3 CLI
#   경로로 돌리는 채점자는 FK 가 꺼진 DB 를 얻는다. 그래서 '연결 상태'가 아니라
#   '파일에 그 선언이 있는가'를 따로 본다.
PRAGMA_FK_FILES = (SCHEMA_SQL, DATA_SQL, QUERIES_SQL, BONUS_SQL)
PRAGMA_FK_RE = re.compile(r"^\s*PRAGMA\s+foreign_keys\s*=\s*(?:ON|1)\s*;", re.IGNORECASE | re.MULTILINE)

# 과제 제약(README 0.6) : 뷰 / 트리거 금지. 프로시저는 SQLite 에 존재하지 않는다.
FORBIDDEN_OBJECT_TYPES = ("view", "trigger")

# 학습용 낭독 사본은 원본에서 '주석만' 뺀 것이어야 한다.
#   사본이 원본과 갈라지면 제출 파일이 사실상 두 벌이 되므로 diff 로 고정한다.
DRILL_COPIES = (
    (QUERIES_SQL, os.path.join("drill", "03_queries_naked.sql")),
    (BONUS_SQL, os.path.join("drill", "04_bonus_naked.sql")),
)

# README 0.10 이 쿼리를 가리킬 때 쓰는 좌표 - 줄번호가 아니라 라벨 태그다.
#   예) `03_queries.sql [Q7]` , `04_bonus.sql (2-a)` , `04_bonus.sql (지표 1)`
#   줄번호는 한 줄만 넣어도 전부 밀려 거짓이 되지만, 태그는 코드와 함께 움직인다.
#   대신 '태그가 사라지는' 사고는 아래 check_readme_tag_refs() 가 잡는다.
README_MD = "README.md"
#   좌표는 라벨 안에 **그대로** 들어 있는 문자열이어야 한다 - 즉 grep 으로 찾아진다.
#   `[Q7]` `(2-a)` 처럼 여는 괄호가 있는 것도, `지표 1)` 처럼 없는 것도 같은 규칙을 따른다.
README_REF_RE = re.compile(
    r"`(0[1-4]_[0-9a-z_]+\.sql) (\[[^\]`]+\]|\([^)`]+\)|[^\s`\[(][^`)]*\))`"
)

# README 가 '앞으로도 고쳐질 파일' 을 줄번호로 가리키는 것은 이 저장소에서 두 번 깨졌다.
#   1) 맨 앞에 0장을 삽입하면서 자기 참조가 전부 밀렸다
#   2) 그걸 고치는 커밋이 범위의 시작만 밀어 `README.md:39-41` -> `README.md:415-41` 을 만들었다
# 그래서 이 두 파일은 절 이름·함수 이름으로만 가리키고, 줄번호가 되살아나면 여기서 막는다.
#   (`.sql` 과 `results/*.txt` 는 제출 시점에 고정되는 산출물이라 줄번호를 그대로 둔다.)
VOLATILE_LINE_REF_RE = re.compile(r"`(?:README\.md|build_and_capture\.py):\d+")


# ---------------------------------------------------------------------
# 출력 포맷 - sqlite3 CLI 의 `.mode box` 를 재현한다
# ---------------------------------------------------------------------
def dwidth(text):
    """터미널 표시 폭. 한글/전각 문자는 2칸을 차지한다."""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in str(text))


def pad(text, width, align="left"):
    text = str(text)
    space = width - dwidth(text)
    if space <= 0:
        return text
    if align == "center":
        left = space // 2
        return " " * left + text + " " * (space - left)
    return text + " " * space


def render_box(headers, rows):
    """헤더는 가운데, 값은 왼쪽 정렬 - sqlite3 .mode box 와 동일한 규칙."""
    cells = [[("" if v is None else str(v)) for v in row] for row in rows]
    widths = [
        max([dwidth(h)] + [dwidth(r[i]) for r in cells]) for i, h in enumerate(headers)
    ]

    def line(left, mid, right):
        return left + mid.join("─" * (w + 2) for w in widths) + right

    out = [line("┌", "┬", "┐")]
    out.append("│ " + " │ ".join(pad(h, widths[i], "center") for i, h in enumerate(headers)) + " │")
    out.append(line("├", "┼", "┤"))
    for r in cells:
        out.append("│ " + " │ ".join(pad(v, widths[i]) for i, v in enumerate(r)) + " │")
    out.append(line("└", "┴", "┘"))
    return "\n".join(out)


def render_query_plan(rows):
    """EXPLAIN QUERY PLAN 은 sqlite3 CLI 처럼 트리 모양으로 출력한다."""
    out = ["QUERY PLAN"]
    for row in rows:
        out.append("`--" + str(row[-1]))
    return "\n".join(out)


# ---------------------------------------------------------------------
# SQL 파일 파싱 - 문장 단위로 자르고, `-- [라벨] 설명` 주석을 섹션 제목으로 쓴다
# ---------------------------------------------------------------------
LABEL_RE = re.compile(r"^--\s*>>\s*(.+)$")


def parse_statements(path):
    """(label, statement) 목록을 돌려준다. label 은 직전에 나온 `-- [..]` 주석."""
    statements = []
    buffer = ""
    pending_label = None
    current_label = None

    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            stripped = raw.strip()

            # 아직 문장을 모으는 중이 아닐 때만 주석에서 라벨을 뽑는다
            if not buffer.strip():
                m = LABEL_RE.match(stripped)
                if m:
                    pending_label = m.group(1).strip()
                    continue
                if stripped.startswith("--") or not stripped:
                    continue

            buffer += raw
            if sqlite3.complete_statement(buffer):
                sql = buffer.strip()
                buffer = ""
                if pending_label is not None:
                    current_label = pending_label
                    pending_label = None
                    statements.append((current_label, sql))
                else:
                    statements.append((None, sql))

    if buffer.strip():
        statements.append((pending_label, buffer.strip()))
    return statements


# ---------------------------------------------------------------------
# 실행 & 캡처
# ---------------------------------------------------------------------
def run_script(con, filename, out_lines, allow_errors=False):
    """캡처 줄을 out_lines 에 채우고, 발생한 에러 메시지 목록을 돌려준다.

    건수가 아니라 메시지를 돌려주는 이유: 04_bonus.sql 의 위반 4종은 '몇 건 났는가'가
    아니라 '어떤 제약이 걸렸는가'가 증거다. 건수만 세면 FK 위반 4번으로도 4건이 된다.
    """
    path = os.path.join(BASE_DIR, filename)
    errors = []

    for label, sql in parse_statements(path):
        if label:
            out_lines.append("")
            out_lines.append("=" * 70)
            out_lines.append(label)
            out_lines.append("=" * 70)

        cur = con.cursor()
        try:
            cur.execute(sql)
        except sqlite3.Error as exc:
            errors.append(f"{type(exc).__name__}: {exc}")
            out_lines.append(f"Runtime error: {type(exc).__name__}: {exc}")
            if not allow_errors:
                raise
            continue

        if cur.description:  # SELECT / EXPLAIN 계열
            headers = [d[0] for d in cur.description]
            rows = cur.fetchall()
            if not rows:
                out_lines.append("(결과 없음 - 0행)")
            elif sql.lstrip().upper().startswith("EXPLAIN QUERY PLAN"):
                out_lines.append(render_query_plan(rows))
            else:
                out_lines.append(render_box(headers, rows))
        else:  # INSERT / UPDATE / DELETE / DDL
            verb = sql.lstrip().split(None, 1)[0].upper()
            if verb in ("INSERT", "UPDATE", "DELETE"):
                out_lines.append(f"-- {verb} 완료: 변경된 행 {cur.rowcount}개")

    return errors


# ---------------------------------------------------------------------
# 검사 - 기대값 표와 대조한다. 하나라도 어긋나면 main() 이 종료 코드 1 을 낸다
# ---------------------------------------------------------------------
class CheckLog:
    """검사 결과를 모아 두는 곳. 첫 실패에서 멈추지 않고 전부 보여준 뒤 실패한다.

    한 번 돌려서 깨진 것을 한꺼번에 보는 편이, 고치고 다시 돌리기를 반복하는 것보다 싸다.
    """

    def __init__(self):
        self.passed = 0
        self.failures = []

    def expect(self, ok, what, detail=""):
        if ok:
            self.passed += 1
            print(f"      [PASS] {what}")
        else:
            self.failures.append(what if not detail else f"{what} - {detail}")
            print(f"      [FAIL] {what}" + (f"  -> {detail}" if detail else ""))
        return ok

    def expect_equal(self, actual, expected, what):
        return self.expect(actual == expected, what, f"기대 {expected!r} / 실제 {actual!r}")


def check_schema_and_data(con, log):
    """R2-1 테이블 / R4-1 행 수 / R2-3 FK / R3-3 FK 강제 - 파괴적 DML 이전 상태에서 본다."""
    names = tuple(
        row[0]
        for row in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' "
            "AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
    )
    log.expect_equal(names, tuple(sorted(EXPECTED_TABLES)), "테이블 목록 (R2-1)")

    for table in EXPECTED_TABLES:
        # 테이블 이름은 위 상수에서만 오므로 문자열 조립이 외부 입력과 닿지 않는다.
        count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        log.expect(
            count >= MIN_ROWS_PER_TABLE,
            f"{table} 행수 >= {MIN_ROWS_PER_TABLE} (R4-1)",
            f"실제 {count}행",
        )

    found = []
    for table in EXPECTED_TABLES:
        for row in con.execute(f"PRAGMA foreign_key_list({table})"):
            found.append((table, row[2]))  # (자식, 부모)
    log.expect_equal(tuple(sorted(found)), tuple(sorted(EXPECTED_FOREIGN_KEYS)), "FK 관계 (R2-3)")

    # 선언만으로는 부족하다. SQLite 는 연결마다 FK 검사가 기본 OFF 다.
    log.expect_equal(con.execute("PRAGMA foreign_keys").fetchone()[0], 1, "PRAGMA foreign_keys = ON (R3-3)")


def check_violations(errors, log):
    """04_bonus.sql (2-a)~(2-d) 가 '실제로' 막혔는지 - 보너스 B2 / R3-3 의 증명."""
    log.expect_equal(len(errors), len(EXPECTED_VIOLATIONS), "의도된 제약 위반 에러 건수")
    for name, needle in EXPECTED_VIOLATIONS:
        log.expect(
            any(needle in message for message in errors),
            f"{name} 위반이 차단됨",
            f"'{needle}' 를 담은 에러가 없음",
        )


def check_final_state(con, log):
    """Q13/Q14/Q15 적용 후 상태가 README 서술과 같은지."""
    for what, sql, expected in EXPECTED_FINAL_STATE:
        log.expect_equal(con.execute(sql).fetchone()[0], expected, what)


def check_forbidden_objects(con, log):
    """과제 제약(README 0.6) - 뷰·트리거 0개."""
    for kind in FORBIDDEN_OBJECT_TYPES:
        count = con.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = ?", (kind,)
        ).fetchone()[0]
        log.expect_equal(count, 0, f"{kind} 0개 (과제 제약)")


# ---------------------------------------------------------------------
# 문서·사본이 코드와 갈라지지 않았는지 - DB 를 열지 않고 파일만 읽는 검사
# ---------------------------------------------------------------------

def strip_sql_comments(text):
    """`--` 줄 주석만 제거한다. 작은따옴표 문자열 안의 `--` 는 건드리지 않는다."""
    out = []
    i = 0
    end = len(text)
    in_string = False
    while i < end:
        ch = text[i]
        if in_string:
            out.append(ch)
            if ch == "'":
                if i + 1 < end and text[i + 1] == "'":  # '' 는 이스케이프된 따옴표
                    out.append(text[i + 1])
                    i += 2
                    continue
                in_string = False
            i += 1
            continue
        if ch == "'":
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "-" and i + 1 < end and text[i + 1] == "-":
            while i < end and text[i] != "\n":
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def normalized_statements(path):
    """주석 제거 + 공백 정규화 후의 SQL 문장 목록. 서식 차이를 무시하고 내용만 비교하기 위한 것."""
    text = strip_sql_comments(open(path, encoding="utf-8").read())
    statements = []
    buffer = ""
    for line in text.splitlines(True):
        if not buffer.strip() and not line.strip():
            continue
        buffer += line
        if sqlite3.complete_statement(buffer):
            statements.append(re.sub(r"\s+", " ", buffer).strip())
            buffer = ""
    if buffer.strip():
        statements.append(re.sub(r"\s+", " ", buffer).strip())
    return statements


def check_pragma_declarations(log):
    """네 스크립트가 각자 `PRAGMA foreign_keys = ON` 을 선언하는지 - R3-3 의 파일 쪽 증거."""
    for filename in PRAGMA_FK_FILES:
        text = open(os.path.join(BASE_DIR, filename), encoding="utf-8").read()
        log.expect(
            bool(PRAGMA_FK_RE.search(strip_sql_comments(text))),
            f"{filename} 이 PRAGMA foreign_keys = ON 을 선언함 (R3-3)",
            "선언이 없다 - sqlite3 CLI 경로에서는 FK 가 꺼진다",
        )


def check_drill_copies(log):
    """drill/*_naked.sql 이 원본에서 주석만 뺀 것인지 확인한다."""
    for source, copy in DRILL_COPIES:
        want = normalized_statements(os.path.join(BASE_DIR, source))
        got = normalized_statements(os.path.join(BASE_DIR, copy))
        if want == got:
            log.expect(True, f"{copy} == {source} (주석 제거·공백 정규화 후, {len(want)}문장)")
            continue
        if len(want) != len(got):
            detail = f"문장 수 {len(want)} vs {len(got)}"
        else:
            first = next(i for i in range(len(want)) if want[i] != got[i])
            detail = f"{first + 1}번째 문장부터 다름: {got[first][:60]!r}"
        log.expect(False, f"{copy} == {source}", detail)


def sql_labels(path):
    """`-- >> ...` 라벨의 본문 목록. 캡처 파일의 섹션 제목이 되는 바로 그 문자열이다."""
    labels = []
    with open(path, encoding="utf-8") as fh:
        for raw in fh:
            match = LABEL_RE.match(raw.strip())
            if match:
                labels.append(match.group(1).strip())
    return labels


def _label_has_tag(label, tag):
    """라벨 `[Q1] 기본 조회 …` 안에 좌표 `[Q1]` 가 **글자 그대로** 들어 있는가.

    부분 문자열 비교인 이유: 좌표의 값은 "채점자가 grep 하면 그 줄이 나온다" 는 것이다.
    글자가 조금이라도 다르면(예: 라벨은 `지표 1)` 인데 README 는 `(지표 1)`) 검사만 통과하고
    실제 검색은 0건이 된다 - 문서가 조용히 거짓이 되는 바로 그 경로다.

    닫는 괄호를 좌표에 포함시키므로 `[Q1]` 이 `[Q15]`·`[Q1-B]` 에 잘못 붙지 않는다
    (`"[Q1]" in "[Q15] …"` 는 False).
    """
    return tag in label


def check_readme_tag_refs(log):
    """README 가 가리키는 쿼리 태그가 실제로 존재하는지.

    README 0.10 의 판정 근거는 원래 `03_queries.sql:35-38` 같은 줄번호였다.
    줄번호는 위에 한 줄만 넣어도 전부 밀려 조용히 거짓이 된다 - 실제로 한 번 그렇게 깨졌다.
    지금은 라벨 태그를 가리키고, 그 태그가 사라지면 이 검사가 실패한다.
    """
    readme = os.path.join(BASE_DIR, README_MD)
    refs = set(README_REF_RE.findall(open(readme, encoding="utf-8").read()))
    log.expect(bool(refs), "README 0.10 이 태그 좌표를 사용함", "태그 참조가 하나도 없음")

    cache = {}
    for filename, tag in sorted(refs):
        if filename not in cache:
            cache[filename] = sql_labels(os.path.join(BASE_DIR, filename))
        log.expect(
            any(_label_has_tag(label, tag) for label in cache[filename]),
            f"README 참조 `{filename} {tag}` 가 실제 라벨을 가리킴",
            "해당 `-- >>` 라벨 없음",
        )

    volatile = VOLATILE_LINE_REF_RE.findall(open(readme, encoding="utf-8").read())
    log.expect(
        not volatile,
        "README.md / build_and_capture.py 를 줄번호로 가리키지 않음",
        f"{len(volatile)}건: {', '.join(sorted(set(volatile))[:3])}",
    )


def build_database():
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    # isolation_level=None : 자동 커밋 모드.
    #   BEGIN / ROLLBACK 을 SQL 에 쓴 그대로 동작시키려면 파이썬이 트랜잭션에 개입하면 안 된다.
    con = sqlite3.connect(DB_PATH, isolation_level=None)
    con.execute("PRAGMA foreign_keys = ON")

    for filename in (SCHEMA_SQL, DATA_SQL):
        with open(os.path.join(BASE_DIR, filename), encoding="utf-8") as fh:
            con.executescript(fh.read())
        # executescript 가 트랜잭션을 커밋하면서 PRAGMA 가 초기화될 수 있어 매번 다시 켠다
        con.execute("PRAGMA foreign_keys = ON")

    return con


def header_lines(source_file, con):
    fk = con.execute("PRAGMA foreign_keys").fetchone()[0]
    return [
        "=" * 70,
        f"  소스 파일    : {source_file}",
        f"  생성 시각    : {datetime.now(timezone.utc).astimezone().isoformat(timespec='seconds')}",
        f"  SQLite 버전  : {sqlite3.sqlite_version}",
        f"  Python 버전  : {sys.version.split()[0]} ({sys.platform})",
        f"  foreign_keys : {'ON' if fk else 'OFF'}",
        f"  생성 명령    : python build_and_capture.py",
        "=" * 70,
    ]


def write_capture(con, source_file, out_file, allow_errors):
    lines = header_lines(source_file, con)
    errors = run_script(con, source_file, lines, allow_errors=allow_errors)
    lines.append("")

    path = os.path.join(RESULTS_DIR, out_file)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines))
    return path, errors


def main():
    """빌드 -> 캡처 -> 검사. 검사가 하나라도 실패하면 1 을 돌려준다."""
    os.makedirs(RESULTS_DIR, exist_ok=True)
    log = CheckLog()

    print("[1/4] cafe.db 재생성 (01_schema.sql + 02_data.sql)")
    con = build_database()
    counts = {
        t: con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in EXPECTED_TABLES
    }
    print("      행수:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    # 행 수 하한은 '샘플 데이터' 에 대한 요구(R4-1)이므로 Q13/Q14 가 건드리기 전에 본다.
    check_schema_and_data(con, log)

    print("[2/4] 04_bonus.sql -> results/bonus_results.txt  (파괴적 DML 이전 상태에서 캡처)")
    path, errs = write_capture(con, BONUS_SQL, "bonus_results.txt", allow_errors=True)
    print(f"      완료: {path}  (의도된 제약 위반 에러 {len(errs)}건)")
    check_violations(errs, log)

    print("[3/4] 03_queries.sql -> results/results.txt")
    path, _ = write_capture(con, QUERIES_SQL, "results.txt", allow_errors=False)
    print(f"      완료: {path}")

    print("[4/4] 기대값 대조")
    check_final_state(con, log)
    check_forbidden_objects(con, log)
    con.close()
    check_pragma_declarations(log)
    check_drill_copies(log)
    check_readme_tag_refs(log)

    print()
    print(f"검사 결과: 통과 {log.passed}건 / 실패 {len(log.failures)}건")
    if log.failures:
        for failure in log.failures:
            print(f"  x {failure}")
        print()
        print("기대값과 어긋났다. results/ 와 cafe.db 는 만들어졌지만 제출 가능한 상태가 아니다.")
        return 1

    print("커밋되는 cafe.db 최종 상태 (README 1장 서술과 일치 확인됨):")
    for what, _sql, expected in EXPECTED_FINAL_STATE:
        print(f"  {what} = {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
