-- 핵심 쿼리 낭독 훈련용 (주석 전부 제거)
-- 사용법: 아래 각 쿼리를 보고 30초 안에 '무엇을 구하는 쿼리인지' 소리 내어 말한다.
-- 원본 주석은 절대 열지 말 것. 다 말한 뒤에만 원본과 대조한다.
PRAGMA foreign_keys = ON;

-- [1]
SELECT id, name, price, category_id
FROM   menu
WHERE  is_available = 1
ORDER  BY price DESC, id;

-- [2]
SELECT name, price, is_available
FROM   menu
WHERE  price >= 5000
ORDER  BY price DESC, id;

-- [3]
SELECT id, name, email, joined_at
FROM   customer
ORDER  BY joined_at DESC, id DESC
LIMIT  5;

-- [4]
SELECT id, customer_id, order_date, status
FROM   order_header
WHERE  status = 'COMPLETED'
ORDER  BY order_date DESC
LIMIT  10;

-- [5]
SELECT id, name, price
FROM   menu
WHERE  name LIKE '%라떼%'
ORDER  BY price DESC, id;

-- [6]
SELECT m.id, m.name AS menu_name, c.name AS category_name, m.price
FROM   menu m
INNER  JOIN category c ON c.id = m.category_id
ORDER  BY c.name, m.price DESC, m.id;

-- [7]
SELECT  oh.id        AS order_id,
        c.name       AS customer_name,
        m.name       AS menu_name,
        od.quantity,
        od.unit_price,
        (od.quantity * od.unit_price) AS line_total
FROM    order_detail od
INNER   JOIN order_header oh ON oh.id = od.order_id
INNER   JOIN customer     c  ON c.id  = oh.customer_id
INNER   JOIN menu         m  ON m.id  = od.menu_id
ORDER   BY oh.id, od.id;

-- [8]
SELECT  c.id,
        c.name,
        COUNT(oh.id) AS order_count
FROM    customer c
LEFT    JOIN order_header oh ON oh.customer_id = c.id
GROUP   BY c.id, c.name
ORDER   BY order_count DESC, c.id;

-- [9]
SELECT  c.id,
        c.name,
        COUNT(*)        AS cnt_star,
        COUNT(oh.id)    AS cnt_column,
        CASE WHEN COUNT(*) <> COUNT(oh.id) THEN '<== 차이 발생' ELSE '' END AS note
FROM    customer c
LEFT    JOIN order_header oh ON oh.customer_id = c.id
GROUP   BY c.id, c.name
ORDER   BY c.id;

-- [10]
SELECT  c.name AS category_name,
        COUNT(m.id) AS menu_count
FROM    category c
INNER   JOIN menu m ON m.category_id = c.id
GROUP   BY c.id, c.name
ORDER   BY menu_count DESC, c.name;

-- [11]
SELECT  c.name AS category_name,
        COUNT(m.id) AS menu_count
FROM    category c
LEFT    JOIN menu m ON m.category_id = c.id
GROUP   BY c.id, c.name
ORDER   BY menu_count DESC, c.name;

-- [12]
SELECT  status,
        COUNT(*) AS order_count
FROM    order_header
GROUP   BY status
ORDER   BY order_count DESC, status;

-- [13]
SELECT  c.id,
        c.name,
        COALESCE(SUM(od.quantity * od.unit_price), 0) AS total_paid
FROM    customer c
LEFT    JOIN order_header oh ON oh.customer_id = c.id
                            AND oh.status = 'COMPLETED'
LEFT    JOIN order_detail od ON od.order_id   = oh.id
GROUP   BY c.id, c.name
ORDER   BY total_paid DESC, c.id;

-- [14]
SELECT  c.id,
        c.name,
        COUNT(DISTINCT oh.id)                                                   AS orders_total,
        COUNT(DISTINCT CASE WHEN oh.status = 'COMPLETED' THEN oh.id END)        AS orders_completed,
        COUNT(DISTINCT CASE WHEN oh.status = 'CANCELLED' THEN oh.id END)        AS orders_cancelled,
        CASE
            WHEN COUNT(oh.id) = 0                                          THEN '주문 이력 없음'
            WHEN COUNT(CASE WHEN oh.status = 'COMPLETED' THEN 1 END) = 0    THEN '주문했으나 결제 완료 0건'
            ELSE                                                                '결제 이력 있음'
        END AS segment
FROM    customer c
LEFT    JOIN order_header oh ON oh.customer_id = c.id
GROUP   BY c.id, c.name
ORDER   BY c.id;

-- [15]
SELECT  c.name AS category_name,
        CAST(ROUND(AVG(m.price)) AS INTEGER) AS avg_price
FROM    category c
INNER   JOIN menu m ON m.category_id = c.id
GROUP   BY c.id, c.name
ORDER   BY avg_price DESC, c.name;

-- [16]
SELECT  c.name AS category_name,
        COUNT(m.id) AS menu_count,
        SUM(m.price) AS price_sum
FROM    category c
INNER   JOIN menu m ON m.category_id = c.id
WHERE   m.price >= 4000
GROUP   BY c.id, c.name
HAVING  COUNT(m.id) >= 2
ORDER   BY menu_count DESC, c.name;

-- [17]
SELECT  name, price
FROM    menu
WHERE   is_available = 1
  AND   price > (SELECT AVG(price) FROM menu WHERE is_available = 1)
ORDER   BY price DESC, id;

-- [18]
UPDATE menu
SET    price = 4000
WHERE  name = '아메리카노';

-- [19]
SELECT id, name, price FROM menu WHERE name = '아메리카노';

-- [20]
DELETE FROM order_header
WHERE  status = 'CANCELLED';

-- [21]
SELECT status, COUNT(*) AS cnt FROM order_header GROUP BY status ORDER BY status;

-- [22]
SELECT COUNT(*) AS order_detail_rows FROM order_detail;

-- [23]
DROP INDEX IF EXISTS idx_order_header_customer_id;

-- [24]
DROP INDEX IF EXISTS idx_order_detail_order_id;

-- [25]
EXPLAIN QUERY PLAN
SELECT * FROM order_header WHERE customer_id = 1;

-- [26]
EXPLAIN QUERY PLAN
SELECT * FROM order_detail WHERE order_id = 1;

-- [27]
CREATE INDEX IF NOT EXISTS idx_order_header_customer_id
    ON order_header (customer_id);

-- [28]
CREATE INDEX IF NOT EXISTS idx_order_detail_order_id
    ON order_detail (order_id);

-- [29]
EXPLAIN QUERY PLAN
SELECT * FROM order_header WHERE customer_id = 1;

-- [30]
EXPLAIN QUERY PLAN
SELECT * FROM order_detail WHERE order_id = 1;

-- [31]
SELECT name AS index_name,
       tbl_name AS table_name,
       CASE WHEN name LIKE 'sqlite_autoindex%' THEN 'UNIQUE 제약이 자동 생성' ELSE '직접 생성' END AS created_by
FROM   sqlite_master
WHERE  type = 'index'
ORDER  BY tbl_name, index_name;
