-- 보너스 쿼리 낭독 훈련용 (주석 전부 제거)
-- 사용법: 아래 각 쿼리를 보고 30초 안에 '무엇을 구하는 쿼리인지' 소리 내어 말한다.
-- 원본 주석은 절대 열지 말 것. 다 말한 뒤에만 원본과 대조한다.
PRAGMA foreign_keys = ON;

-- [1]
SELECT (SELECT COUNT(*) FROM order_header)                           AS orders_expect_12,
       (SELECT COUNT(*) FROM order_header WHERE status='CANCELLED')  AS cancelled_expect_2,
       (SELECT COUNT(*) FROM order_detail)                           AS details_expect_20,
       (SELECT price FROM menu WHERE name='아메리카노')              AS americano_expect_3500;

-- [2]
SELECT DISTINCT c.id, c.name
FROM   customer c
INNER  JOIN order_header oh ON oh.customer_id = c.id
INNER  JOIN order_detail od ON od.order_id    = oh.id
INNER  JOIN menu m          ON m.id           = od.menu_id
WHERE  m.name = '아메리카노'
ORDER  BY c.id;

-- [3]
SELECT id, name
FROM   customer
WHERE  id IN (
    SELECT oh.customer_id
    FROM   order_header oh
    JOIN   order_detail od ON od.order_id = oh.id
    JOIN   menu         m  ON m.id        = od.menu_id
    WHERE  m.name = '아메리카노'
)
ORDER BY id;

-- [4]
SELECT c.id, c.name
FROM   customer c
WHERE  EXISTS (
    SELECT 1
    FROM   order_header oh
    JOIN   order_detail od ON od.order_id = oh.id
    JOIN   menu         m  ON m.id        = od.menu_id
    WHERE  oh.customer_id = c.id
      AND  m.name = '아메리카노'
)
ORDER BY c.id;

-- [5]
EXPLAIN QUERY PLAN
SELECT DISTINCT c.id, c.name
FROM   customer c
INNER  JOIN order_header oh ON oh.customer_id = c.id
INNER  JOIN order_detail od ON od.order_id    = oh.id
INNER  JOIN menu m          ON m.id           = od.menu_id
WHERE  m.name = '아메리카노'
ORDER  BY c.id;

-- [6]
EXPLAIN QUERY PLAN
SELECT id, name FROM customer
WHERE  id IN (SELECT oh.customer_id FROM order_header oh
              JOIN order_detail od ON od.order_id = oh.id
              JOIN menu m ON m.id = od.menu_id
              WHERE m.name = '아메리카노')
ORDER BY id;

-- [7]
EXPLAIN QUERY PLAN
SELECT c.id, c.name FROM customer c
WHERE  EXISTS (SELECT 1 FROM order_header oh
               JOIN order_detail od ON od.order_id = oh.id
               JOIN menu m ON m.id = od.menu_id
               WHERE oh.customer_id = c.id AND m.name = '아메리카노')
ORDER BY c.id;

-- [8]
INSERT INTO order_header (customer_id, status) VALUES (999, 'PENDING');

-- [9]
INSERT INTO customer (name, email) VALUES ('중복이', 'minjun@example.com');

-- [10]
INSERT INTO order_header (customer_id, status) VALUES (1, 'DONE');

-- [11]
INSERT INTO customer (name, email) VALUES ('이메일없음', NULL);

-- [12]
BEGIN;

-- [13]
INSERT INTO customer (name, email, phone, joined_at)
VALUES ('신규고객', 'newbie@example.com', '010-9999-0000', '2026-05-11');

-- [14]
INSERT INTO order_header (customer_id, order_date, status)
VALUES ((SELECT id FROM customer WHERE email = 'newbie@example.com'),
        '2026-05-11 10:00:00', 'PENDING');

-- [15]
SELECT c.name, oh.id AS order_id, oh.status
FROM   customer c
JOIN   order_header oh ON oh.customer_id = c.id
WHERE  c.email = 'newbie@example.com';

-- [16]
ROLLBACK;

-- [17]
SELECT (SELECT COUNT(*) FROM customer     WHERE email = 'newbie@example.com') AS customer_left,
       (SELECT COUNT(*) FROM order_header WHERE status = 'PENDING'
                                            AND order_date = '2026-05-11 10:00:00') AS order_left;

-- [18]
SELECT  DATE(oh.order_date) AS sales_date,
        SUM(od.quantity * od.unit_price) AS daily_revenue,
        COUNT(DISTINCT oh.id)            AS order_count
FROM    order_header oh
JOIN    order_detail od ON od.order_id = oh.id
WHERE   oh.status = 'COMPLETED'
GROUP   BY DATE(oh.order_date)
ORDER   BY sales_date;

-- [19]
SELECT  m.name AS menu_name,
        SUM(od.quantity)                  AS total_qty,
        SUM(od.quantity * od.unit_price)  AS total_sales
FROM    order_detail od
JOIN    menu m          ON m.id  = od.menu_id
JOIN    order_header oh ON oh.id = od.order_id
WHERE   oh.status = 'COMPLETED'
GROUP   BY m.id, m.name
ORDER   BY total_qty DESC, total_sales DESC, m.id
LIMIT 5;

-- [20]
SELECT  c.name,
        COUNT(DISTINCT oh.id)            AS order_count,
        SUM(od.quantity * od.unit_price) AS total_paid
FROM    customer c
INNER   JOIN order_header oh ON oh.customer_id = c.id
INNER   JOIN order_detail od ON od.order_id    = oh.id
WHERE   oh.status = 'COMPLETED'
GROUP   BY c.id, c.name
ORDER   BY total_paid DESC, c.id
LIMIT 3;
