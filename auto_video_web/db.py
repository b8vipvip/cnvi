import json
from pathlib import Path

import pymysql

import config


DB_FIELDS = {
    "title", "script_text", "script_summary", "hashtags", "status", "progress", "message", "error_message",
    "orientation", "width", "height", "duration_mode", "target_duration", "final_duration", "narration_mode",
    "dialogue_style", "subtitle_mode", "script_model", "tts_model", "image_model", "image_count", "speaker_configs",
    "request_params", "storyboard_json", "video_filename", "video_path", "video_url", "cover_image", "finished_at",
}


def get_connection(use_db=True):
    return pymysql.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE if use_db else None,
        charset=config.MYSQL_CHARSET,
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
    )


def create_video_record(data):
    fields = [
        "task_id", "title", "script_text", "script_summary", "hashtags", "status", "progress", "message",
        "orientation", "duration_mode", "target_duration", "narration_mode", "dialogue_style", "subtitle_mode",
        "script_model", "tts_model", "image_model", "image_count", "speaker_configs", "request_params",
    ]
    values = [data.get(k) for k in fields]
    sql = f"INSERT INTO video_generation_records ({','.join(fields)}) VALUES ({','.join(['%s'] * len(fields))})"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, values)


def update_video_record(task_id, **fields):
    updates = {k: v for k, v in fields.items() if k in DB_FIELDS}
    if not updates:
        return
    clause = ", ".join([f"{k}=%s" for k in updates.keys()])
    sql = f"UPDATE video_generation_records SET {clause} WHERE task_id=%s"
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, list(updates.values()) + [task_id])


def get_video_record(task_id):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM video_generation_records WHERE task_id=%s LIMIT 1", (task_id,))
            return cur.fetchone()


def list_video_records(page=1, page_size=10, status=None, keyword=None):
    page = max(1, int(page))
    page_size = max(1, min(100, int(page_size)))
    where = []
    params = []
    if status:
        where.append("status=%s")
        params.append(status)
    if keyword:
        where.append("(task_id LIKE %s OR title LIKE %s OR script_text LIKE %s)")
        like = f"%{keyword}%"
        params.extend([like, like, like])
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) AS total FROM video_generation_records{where_sql}", params)
            total = cur.fetchone()["total"]
            cur.execute(
                f"SELECT * FROM video_generation_records{where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s",
                params + [page_size, (page - 1) * page_size],
            )
            return {"total": total, "records": cur.fetchall()}


def delete_video_record(task_id, delete_files=True):
    rec = get_video_record(task_id)
    if not rec:
        return False
    if delete_files and rec.get("video_path"):
        p = Path(rec["video_path"])
        if p.exists() and p.is_file():
            p.unlink(missing_ok=True)
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM video_generation_records WHERE task_id=%s", (task_id,))
    return True


def get_app_setting(key, default=None):
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT setting_value FROM app_settings WHERE setting_key=%s LIMIT 1", (key,))
            row = cur.fetchone()
            if not row or row.get("setting_value") is None:
                return default
            try:
                return json.loads(row["setting_value"])
            except Exception:
                return row["setting_value"]


def set_app_setting(key, value):
    payload = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO app_settings (setting_key, setting_value) VALUES (%s,%s)
                ON DUPLICATE KEY UPDATE setting_value=VALUES(setting_value)
            """, (key, payload))
