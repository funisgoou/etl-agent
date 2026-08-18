-- 演示源库 biz_demo（DATA 文档第 7 章）：确定性种子，脏数据配比与 QualityContract 错误码一一对应。
-- 基准常量（C1 行数硬判据断言依据）：
--   customers: 10 行 = 合格 9 + 违规 1（E_BAD_EMAIL）
--   orders:    20 行 = 合格 17 + 违规 3（E_NOT_POSITIVE ×2 + E_NOT_NULL ×1）

CREATE TABLE IF NOT EXISTS customers (
  id BIGINT PRIMARY KEY,
  customer_no VARCHAR(32),
  name VARCHAR(128),
  email VARCHAR(255),
  phone VARCHAR(32),
  created_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS orders (
  id BIGINT PRIMARY KEY,
  order_no VARCHAR(32),
  customer_id BIGINT,
  amount DECIMAL(12,2),
  status VARCHAR(16),
  created_at DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- 只读账号授权（etl_reader 由镜像 env 创建）
GRANT SELECT ON biz_demo.* TO 'etl_reader'@'%';
FLUSH PRIVILEGES;

INSERT INTO customers (id, customer_no, name, email, phone, created_at) VALUES
 (1,'C0001','张三','zhangsan@163.com','13812346672','2026-01-01 09:00:00'),
 (2,'C0002','李四','lisi@126.com','15912340031','2026-01-02 10:00:00'),
 (3,'C0003','王五','wangwu@qq.com','13612345678','2026-01-03 11:00:00'),
 (4,'C0004','赵六','zhaoliu@163.com','13712349876','2026-01-04 12:00:00'),
 (5,'C0005','钱七','qianqi@gmail.com','18812341111','2026-01-05 13:00:00'),
 (6,'C0006','孙八','sunbai@outlook.com','19912342222','2026-01-06 14:00:00'),
 (7,'C0007','周九','zhoujiu@163.com','17012343333','2026-01-07 15:00:00'),
 (8,'C0008','吴十','wushi@qq.com','17112344444','2026-01-08 16:00:00'),
 (9,'C0009','郑一','zhengyi@126.com','17212345555','2026-01-09 17:00:00'),
 (10,'C0010','冯二','feng-er#invalid','17312346666','2026-01-10 18:00:00');  -- 脏：email 非法 → E_BAD_EMAIL

INSERT INTO orders (id, order_no, customer_id, amount, status, created_at) VALUES
 (1,'NO20260801001',1,199.00,'paid','2026-08-01 10:00:00'),
 (2,'NO20260801002',2,0.00,'closed','2026-08-01 11:00:00'),               -- 脏：amount<=0 → E_NOT_POSITIVE
 (3,'NO20260801003',3,-5.50,'refunded','2026-08-01 12:30:00'),             -- 脏：amount<0 → E_NOT_POSITIVE
 (4,NULL,4,88.80,'paid','2026-08-02 09:15:00'),                            -- 脏：order_no NULL → E_NOT_NULL
 (5,'NO20260802002',5,1299.00,'paid','2026-08-02 15:40:00'),
 (6,'NO20260803001',6,45.00,'paid','2026-08-03 08:00:00'),
 (7,'NO20260803002',7,320.00,'paid','2026-08-03 14:20:00'),
 (8,'NO20260804001',8,0.01,'paid','2026-08-04 19:00:00'),
 (9,'NO20260805001',9,780.50,'paid','2026-08-05 10:10:00'),
 (10,'NO20260805002',10,66.00,'closed','2026-08-05 16:00:00'),
 (11,'NO20260806001',1,120.00,'paid','2026-08-06 09:00:00'),
 (12,'NO20260806002',2,458.00,'shipped','2026-08-06 10:00:00'),
 (13,'NO20260807001',3,29.90,'paid','2026-08-07 11:00:00'),
 (14,'NO20260807002',4,999.99,'paid','2026-08-07 12:00:00'),
 (15,'NO20260808001',5,158.00,'shipped','2026-08-08 13:00:00'),
 (16,'NO20260808002',6,268.00,'paid','2026-08-08 14:00:00'),
 (17,'NO20260809001',7,39.00,'paid','2026-08-09 15:00:00'),
 (18,'NO20260809002',8,599.00,'paid','2026-08-09 16:00:00'),
 (19,'NO20260810001',9,88.00,'cancelled','2026-08-10 17:00:00'),
 (20,'NO20260810002',10,17.50,'paid','2026-08-10 18:00:00');
