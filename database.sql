-- ============================================================
--  Smart Quiz System — Full Database Schema
--  MySQL 8.0+
-- ============================================================

CREATE DATABASE IF NOT EXISTS quiz_system
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE quiz_system;

-- ──────────────────────────────────────────
--  ADMIN TABLE
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS admin (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    email         VARCHAR(120) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────
--  PARTICIPANTS TABLE
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS participants (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(100) NOT NULL,
    register_no     VARCHAR(50)  NOT NULL UNIQUE,
    email           VARCHAR(120) NOT NULL UNIQUE,
    attempt_status  ENUM('not_attempted', 'in_progress', 'completed') DEFAULT 'not_attempted',
    quiz_start_time TIMESTAMP NULL,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────
--  QUESTIONS TABLE
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS questions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    question_text  TEXT NOT NULL,
    option_a       TEXT NOT NULL,
    option_b       TEXT NOT NULL,
    option_c       TEXT NOT NULL,
    option_d       TEXT NOT NULL,
    correct_answer ENUM('A','B','C','D') NOT NULL,
    marks          INT DEFAULT 1,
    is_active      BOOLEAN DEFAULT TRUE,
    created_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────
--  QUIZ SETTINGS TABLE (Single Row Config)
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS quiz_settings (
    id               INT AUTO_INCREMENT PRIMARY KEY,
    duration_minutes INT DEFAULT 30,
    is_active        BOOLEAN DEFAULT FALSE,
    start_time       DATETIME NULL,
    end_time         DATETIME NULL,
    max_violations   INT DEFAULT 3,
    updated_at       TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- ──────────────────────────────────────────
--  SUBMISSIONS TABLE
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS submissions (
    id             INT AUTO_INCREMENT PRIMARY KEY,
    participant_id INT NOT NULL,
    score          INT DEFAULT 0,
    total_marks    INT DEFAULT 0,
    time_taken     INT DEFAULT 0,  -- seconds
    auto_submitted BOOLEAN DEFAULT FALSE,
    answers_json   JSON,           -- stores { question_id: chosen_option }
    submitted_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);

-- ──────────────────────────────────────────
--  VIOLATIONS TABLE
-- ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS violations (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    participant_id  INT NOT NULL,
    violation_count INT DEFAULT 0,
    violation_type  VARCHAR(100) DEFAULT 'tab_switch',
    device_info     TEXT,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (participant_id) REFERENCES participants(id) ON DELETE CASCADE
);

-- ──────────────────────────────────────────
--  SEED: Default admin (password = Admin@123)
--  bcrypt hash for 'Admin@123'
-- ──────────────────────────────────────────
INSERT INTO quiz_settings (duration_minutes, is_active)
VALUES (30, FALSE);

INSERT INTO admin (email, password_hash)
VALUES ('admin@quiz.com',
        '$2b$12$na1V31LDBTasrV050ZuOsec9zUX0nrGuZ3YNU6DZb9E4rbv77ubwa');
-- Password = Admin@123  (bcrypt hash generated 2026-02-23)
