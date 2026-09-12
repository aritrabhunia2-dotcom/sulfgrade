DROP DATABASE IF EXISTS h2s_monitoring_system;

CREATE DATABASE h2s_monitoring_system;

USE h2s_monitoring_system;


-- ============================================================
-- USERS TABLE
-- ============================================================

CREATE TABLE users (

    id INT AUTO_INCREMENT PRIMARY KEY,

    full_name VARCHAR(100) NOT NULL,

    email VARCHAR(150) NOT NULL UNIQUE,

    mobile VARCHAR(20) NOT NULL UNIQUE,

    password_hash VARCHAR(255) NOT NULL,

    worker_id VARCHAR(30) NOT NULL UNIQUE,

    wristband_id VARCHAR(30) DEFAULT NULL,

    department VARCHAR(100)
        DEFAULT 'Operations',

    designation VARCHAR(100)
        DEFAULT 'Field Technician',

    site VARCHAR(150)
        DEFAULT 'MRPL - Refinery',

    shift VARCHAR(100)
        DEFAULT 'Day (6:00 AM - 2:00 PM)',

    date_of_birth DATE DEFAULT NULL,

    height VARCHAR(20) DEFAULT NULL,

    profile_photo VARCHAR(255) DEFAULT NULL,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP

);


-- ============================================================
-- BADGES TABLE
-- ============================================================

CREATE TABLE badges (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    wristband_id VARCHAR(30) NOT NULL,

    status ENUM(
        'Active',
        'Inactive',
        'Disconnected'
    ) DEFAULT 'Inactive',

    last_seen TIMESTAMP NULL DEFAULT NULL,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE

);


-- ============================================================
-- EXPOSURE RECORDS
-- ============================================================

CREATE TABLE exposure_records (

    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id INT NOT NULL,

    h2s_level DECIMAL(10,2) NOT NULL DEFAULT 0,

    exposure_ppm_hr DECIMAL(10,2) NOT NULL DEFAULT 0,

    recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id)
        REFERENCES users(id)
        ON DELETE CASCADE

);


-- ============================================================
-- SAMPLE USER
-- ============================================================
-- Password is: password123
--
-- This hash was generated using Werkzeug.
-- You can delete this sample user if you don't need it.
-- ============================================================

INSERT INTO users
(
    full_name,
    email,
    mobile,
    password_hash,
    worker_id,
    wristband_id,
    department,
    designation,
    site,
    shift,
    date_of_birth,
    height
)
VALUES
(
    'Rahul Kumar',
    'rahul.kumar@company.com',
    '9876543210',
    'scrypt:32768:8:1$sample$replace_with_registered_user',
    'WKR-10001',
    'WB-23A7F',
    'Operations',
    'Field Technician',
    'MRPL - Refinery',
    'Day (6:00 AM - 2:00 PM)',
    '2005-03-12',
    '5''8"'
);


-- ============================================================
-- SAMPLE BADGE
-- ============================================================

INSERT INTO badges
(
    user_id,
    wristband_id,
    status,
    last_seen
)
VALUES
(
    1,
    'WB-23A7F',
    'Active',
    NOW()
);


-- ============================================================
-- SAMPLE EXPOSURE DATA
-- ============================================================

INSERT INTO exposure_records
(
    user_id,
    h2s_level,
    exposure_ppm_hr,
    recorded_at
)
VALUES

(1, 0.8, 0.20, NOW() - INTERVAL 10 HOUR),

(1, 1.2, 0.30, NOW() - INTERVAL 9 HOUR),

(1, 1.0, 0.25, NOW() - INTERVAL 8 HOUR),

(1, 2.4, 0.45, NOW() - INTERVAL 7 HOUR),

(1, 1.7, 0.30, NOW() - INTERVAL 6 HOUR),

(1, 3.5, 0.50, NOW() - INTERVAL 5 HOUR),

(1, 4.2, 0.60, NOW() - INTERVAL 4 HOUR),

(1, 5.1, 0.70, NOW() - INTERVAL 3 HOUR),

(1, 3.8, 0.50, NOW() - INTERVAL 2 HOUR),

(1, 3.2, 0.40, NOW() - INTERVAL 1 HOUR);