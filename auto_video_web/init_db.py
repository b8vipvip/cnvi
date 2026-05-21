from dotenv import load_dotenv
import pymysql

import config
from db import get_connection

load_dotenv()

CREATE_DB_SQL = f"CREATE DATABASE IF NOT EXISTS `{config.MYSQL_DATABASE}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS `video_generation_records` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `task_id` VARCHAR(64) NOT NULL,
  `title` VARCHAR(255) DEFAULT NULL,
  `script_text` LONGTEXT,
  `script_summary` TEXT,
  `hashtags` VARCHAR(500) DEFAULT NULL,
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
  `progress` INT NOT NULL DEFAULT 0,
  `message` VARCHAR(500) DEFAULT NULL,
  `error_message` LONGTEXT,
  `orientation` VARCHAR(32) DEFAULT NULL,
  `width` INT DEFAULT NULL,
  `height` INT DEFAULT NULL,
  `duration_mode` VARCHAR(32) DEFAULT NULL,
  `target_duration` INT DEFAULT NULL,
  `final_duration` DECIMAL(10,2) DEFAULT NULL,
  `narration_mode` VARCHAR(32) DEFAULT NULL,
  `dialogue_style` VARCHAR(100) DEFAULT NULL,
  `subtitle_mode` VARCHAR(32) DEFAULT NULL,
  `script_model` VARCHAR(100) DEFAULT NULL,
  `tts_model` VARCHAR(100) DEFAULT NULL,
  `image_model` VARCHAR(100) DEFAULT NULL,
  `image_count` INT DEFAULT 0,
  `speaker_configs` LONGTEXT,
  `request_params` LONGTEXT,
  `storyboard_json` LONGTEXT,
  `video_filename` VARCHAR(255) DEFAULT NULL,
  `video_path` VARCHAR(500) DEFAULT NULL,
  `video_url` VARCHAR(500) DEFAULT NULL,
  `cover_image` VARCHAR(500) DEFAULT NULL,
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `finished_at` DATETIME DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_task_id` (`task_id`),
  KEY `idx_status` (`status`),
  KEY `idx_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
"""


def main():
    try:
        conn = get_connection(use_db=False)
        with conn.cursor() as cur:
            cur.execute(CREATE_DB_SQL)
        conn.close()

        conn = get_connection(use_db=True)
        with conn.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)
        conn.close()
        print("数据库和表初始化完成")
    except pymysql.MySQLError as e:
        raise SystemExit(f"数据库初始化失败: {e}")


if __name__ == "__main__":
    main()
