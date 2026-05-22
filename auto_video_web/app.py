import base64
import json
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_from_directory, abort
from PIL import Image, ImageDraw, ImageFont
from werkzeug.utils import secure_filename

import config
import db

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.secret_key = config.FLASK_SECRET_KEY
app.config["MAX_CONTENT_LENGTH"] = config.MAX_UPLOAD_MB * 1024 * 1024

TASKS = {}
TASK_LOCK = threading.Lock()


for d in [
    config.UPLOAD_DIR,
    config.AUDIO_DIR,
    config.IMAGE_DIR,
    config.VIDEO_DIR,
    config.SUBTITLE_DIR,
    config.FINAL_DIR,
    config.TEMP_DIR,
]:
    d.mkdir(parents=True, exist_ok=True)


DEFAULT_SPEAKERS = [
    {"id": "S1", "name": "主持人A", "role": "理性介绍", "voice": "marin", "style": "自然、清晰、像知识型短视频主持人"},
    {"id": "S2", "name": "主持人B", "role": "宝妈体验", "voice": "nova", "style": "温柔、有亲和力、带一点惊喜和真实体验感"},
    {"id": "S3", "name": "主持人C", "role": "补充观点", "voice": "cedar", "style": "简洁、有节奏"},
    {"id": "S4", "name": "主持人D", "role": "总结收束", "voice": "shimmer", "style": "温暖、鼓励"},
]






def to_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def mask_secret_value(value):
    if value is None:
        return "***"
    text = str(value).strip()
    if not text:
        return text
    if len(text) >= 8:
        return f"{text[:3]}****{text[-4:]}"
    return "***"


def sanitize_request_params(form):
    sanitized = {}
    sensitive_tokens = ("key", "apikey", "token", "secret", "password")
    for key, value in dict(form).items():
        key_l = str(key).lower()
        if any(token in key_l for token in sensitive_tokens):
            sanitized[key] = mask_secret_value(value)
        else:
            sanitized[key] = value
    return sanitized

def resolve_api_key(primary_key, fallback_key):
    return (primary_key or "").strip() or (fallback_key or "").strip() or os.getenv("OPENAI_API_KEY", "").strip()


def default_speakers_for_mode(mode):
    mapping = {
        "monologue": [{"id":"S1","name":"旁白","role":"短视频口播","voice":"nova","style":"自然、温柔、有亲和力"}],
        "dialogue2": [
            {"id":"S1","name":"主持人A","role":"理性介绍","voice":"marin","style":"自然、清晰、像知识型短视频主持人"},
            {"id":"S2","name":"主持人B","role":"宝妈体验","voice":"nova","style":"温柔、有亲和力、带一点惊喜和真实体验感"},
        ],
        "dialogue3": [
            {"id":"S1","name":"主持人A","role":"引导话题","voice":"marin","style":"自然、清晰、负责引出主题"},
            {"id":"S2","name":"宝妈","role":"真实体验","voice":"nova","style":"温柔、真实、有亲和力"},
            {"id":"S3","name":"专家","role":"补充解释","voice":"cedar","style":"稳重、清晰、像早教科普解释"},
        ],
        "dialogue4": [
            {"id":"S1","name":"主持人A","role":"开场引导","voice":"marin","style":"自然、清晰"},
            {"id":"S2","name":"主持人B","role":"互动回应","voice":"nova","style":"温柔、有互动感"},
            {"id":"S3","name":"宝妈","role":"使用体验","voice":"shimmer","style":"真实、亲切、像日常分享"},
            {"id":"S4","name":"专家","role":"科普总结","voice":"cedar","style":"稳重、简洁、可信"},
        ],
    }
    return mapping.get(mode, mapping["dialogue2"])

def update_task(task_id, **kwargs):
    with TASK_LOCK:
        if task_id in TASKS:
            TASKS[task_id].update(kwargs)
    try:
        db.update_video_record(task_id, **kwargs)
    except Exception:
        pass


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def run_cmd(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(str(x) for x in cmd)}\n{p.stderr}")
    return p.stdout.strip()




def get_edge_tts_bin():
    candidates = [
        Path(sys.executable).resolve().parent / "edge-tts",
        config.BASE_DIR / "venv/bin/edge-tts",
    ]
    for candidate in candidates:
        if candidate.exists() and candidate.is_file():
            return str(candidate)

    edge_tts_path = shutil.which("edge-tts")
    if edge_tts_path:
        return edge_tts_path

    raise RuntimeError("未找到 edge-tts，请在虚拟环境中执行 pip install edge-tts，并确认 venv/bin 在 PATH 中。")

def ffprobe_duration(file_path):
    out = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", file_path
    ])
    return float(out)


def choose_font(size=48):
    paths = [
        "C:/Windows/Fonts/msyh.ttc",
        "C:/Windows/Fonts/simhei.ttf",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in paths:
        if os.path.exists(p):
            return ImageFont.truetype(p, size=size)
    return ImageFont.load_default()


def cover_resize(img, target_w, target_h):
    w, h = img.size
    scale = max(target_w / w, target_h / h)
    new_w, new_h = int(w * scale), int(h * scale)
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def draw_big_caption(img, text):
    draw = ImageDraw.Draw(img, "RGBA")
    font = choose_font(58)
    max_width = img.width - 120
    words = list(text)
    lines = []
    cur = ""
    for ch in words:
        test = cur + ch
        if draw.textlength(test, font=font) <= max_width:
            cur = test
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    if len(lines) > 2:
        lines = lines[:2]
    final_text = "\n".join(lines)
    bbox = draw.multiline_textbbox((0, 0), final_text, font=font, spacing=8)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - tw) // 2
    y = int(img.height * 0.67)
    pad = 24
    draw.rounded_rectangle((x - pad, y - pad, x + tw + pad, y + th + pad), radius=18, fill=(0, 0, 0, 135))
    draw.multiline_text((x, y), final_text, font=font, fill=(255, 255, 255, 255), spacing=8)
    return img


def prepare_scene_image(src_path, orientation, subtitle_mode, caption, out_path):
    target_w, target_h = config.PORTRAIT_SIZE if orientation == "portrait" else config.LANDSCAPE_SIZE
    with Image.open(src_path).convert("RGB") as img:
        img = cover_resize(img, target_w, target_h)
        if subtitle_mode in ("both", "big"):
            img = draw_big_caption(img, caption)
        img.save(out_path, "JPEG", quality=95)


def speed_to_rate(speed):
    return {"慢": "0.9", "正常": "1.0", "稍快": "1.1"}.get(speed, "1.0")


def get_openai_client(api_key, base_url):
    if OpenAI is None:
        raise RuntimeError("openai SDK 不可用")
    return OpenAI(api_key=api_key, base_url=base_url)


def generate_openai_tts(text, voice, emotion, speaker_style, speech_speed, tts_model, api_key, base_url, output_path):
    client = get_openai_client(api_key, base_url)
    instructions = f"请用中文短视频讲解语气朗读。角色风格：{speaker_style}。情绪：{emotion}。语速：{speech_speed}。自然停顿，不要机械，不要夸张。"
    last_err = None
    for _ in range(3):
        try:
            with client.audio.speech.with_streaming_response.create(
                model=tts_model,
                voice=voice,
                input=text,
                instructions=instructions,
                format="mp3",
            ) as resp:
                resp.stream_to_file(output_path)
            return
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError(f"OpenAI TTS 失败: {last_err}")


def generate_edge_tts(text, voice, output_path):
    edge_voice = voice if "-" in voice else config.EDGE_TTS_VOICE_FALLBACK
    edge_tts_bin = get_edge_tts_bin()
    run_cmd([edge_tts_bin, "--voice", edge_voice, "--text", text, "--write-media", output_path])


def generate_openai_image(prompt, image_model, quality, size, api_key, base_url, output_path):
    client = get_openai_client(api_key, base_url)
    rsp = client.images.generate(model=image_model, prompt=prompt, size=size, quality=quality)
    b64 = rsp.data[0].b64_json
    raw = base64.b64decode(b64)
    with open(output_path, "wb") as f:
        f.write(raw)


def fallback_storyboard(script_text, target_duration, speaker_configs, image_count, image_strategy):
    chunks = [x.strip() for x in re.split(r"[。！？!\n]", script_text) if x.strip()]
    if not chunks:
        chunks = ["这是一段商品介绍。"]
    scenes = []
    spk_num = len(speaker_configs)
    for i, chunk in enumerate(chunks, 1):
        dialogue = []
        for j in range(min(2, spk_num)):
            sp = speaker_configs[(i + j - 1) % spk_num]
            dialogue.append({
                "speaker_id": sp["id"], "speaker_name": sp["name"], "emotion": "自然", "text": chunk
            })
        scenes.append({
            "scene_id": i,
            "caption": chunk[:18],
            "visual_type": "uploaded_image" if image_strategy != "ai_only" else "ai_image",
            "image_index": (i - 1) % max(1, image_count),
            "image_prompt": "温暖家庭亲子阅读场景，明亮自然光，真实生活感",
            "dialogue": dialogue
        })
    return {
        "title": "自动生成短视频",
        "summary": "fallback 分镜",
        "target_duration": target_duration,
        "speakers": speaker_configs,
        "scenes": scenes,
    }


def generate_storyboard_with_ai(params, api_key, base_url):
    speaker_configs = params["speaker_configs"]
    target_duration = params["target_duration"]
    if not api_key or OpenAI is None:
        return fallback_storyboard(params["script_text"], target_duration, speaker_configs, params["image_count"], params["image_strategy"])

    client = get_openai_client(api_key, base_url)
    prompt = {
        "scriptText": params["script_text"],
        "hashtags": params["hashtags"],
        "targetDuration": target_duration,
        "videoStyle": params["video_style"],
        "narrationMode": params["narration_mode"],
        "dialogueStyle": params["dialogue_style"],
        "emotionLevel": params["emotion_level"],
        "speechSpeed": params["tts_default_speed"],
        "imageCount": params["image_count"],
        "imageStrategy": params["image_strategy"],
        "speakerConfigs": speaker_configs,
    }
    sys = "你是短视频分镜编剧。必须输出严格JSON，不允许markdown。儿童内容合规，禁止夸大功效。"
    usr = "按要求生成 JSON：title,summary,target_duration,speakers,scenes。每个scene有scene_id,caption,visual_type,image_index,image_prompt,dialogue。"
    rsp = client.chat.completions.create(
        model=params["script_model"],
        messages=[
            {"role": "system", "content": sys},
            {"role": "user", "content": usr + "\n输入参数:\n" + json.dumps(prompt, ensure_ascii=False)}
        ],
        response_format={"type": "json_object"},
        temperature=float(params.get("script_temperature", 0.7)),
        max_tokens=int(params.get("script_max_tokens", 4000))
    )
    content = rsp.choices[0].message.content
    try:
        data = json.loads(content)
        assert "scenes" in data
        return data
    except Exception:
        return fallback_storyboard(params["script_text"], target_duration, speaker_configs, params["image_count"], params["image_strategy"])


def srt_time(sec):
    td = timedelta(seconds=sec)
    total = int(td.total_seconds())
    ms = int((sec - math.floor(sec)) * 1000)
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_time(sec):
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def build_subtitles(items, show_name, srt_path, ass_path, orientation):
    with open(srt_path, "w", encoding="utf-8") as f:
        for idx, it in enumerate(items, 1):
            text = f"{it['speaker_name']}：{it['text']}" if show_name else it["text"]
            f.write(f"{idx}\n{srt_time(it['start'])} --> {srt_time(it['end'])}\n{text}\n\n")

    play_res_x, play_res_y = (1080, 1920) if orientation == "portrait" else (1920, 1080)
    style_font = "Microsoft YaHei"
    fs = 44 if orientation == "portrait" else 38
    margin_v = 120
    header = """[Script]
ScriptType: v4.00+
Collisions: Normal
PlayResX: {x}
PlayResY: {y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font},{fs},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,0,0,0,0,100,100,0,0,1,2.2,0,2,40,40,{mv},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
""".format(x=play_res_x, y=play_res_y, font=style_font, fs=fs, mv=margin_v)
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)
        for it in items:
            text = f"{it['speaker_name']}：{it['text']}" if show_name else it["text"]
            text = text.replace("\n", "\\N")
            f.write(f"Dialogue: 0,{ass_time(it['start'])},{ass_time(it['end'])},Default,,0,0,0,,{text}\n")


def process_task(task_id, params, uploaded_files):
    try:
        update_task(task_id, status="running", message="开始生成", progress=5)
        task_upload_dir = config.UPLOAD_DIR / task_id
        task_upload_dir.mkdir(parents=True, exist_ok=True)
        saved_images = []
        for file in uploaded_files:
            name = secure_filename(file.filename)
            dst = task_upload_dir / name
            file.save(dst)
            saved_images.append(dst)

        update_task(task_id, message="保存图片完成", progress=10)
        update_task(task_id, message="AI 改写分镜", progress=20)
        storyboard = generate_storyboard_with_ai(params, params["script_api_key"], params["script_base_url"])

        task_audio_dir = config.AUDIO_DIR / task_id
        task_img_dir = config.IMAGE_DIR / task_id
        task_video_dir = config.VIDEO_DIR / task_id
        task_sub_dir = config.SUBTITLE_DIR / task_id
        for d in [task_audio_dir, task_img_dir, task_video_dir, task_sub_dir]:
            d.mkdir(parents=True, exist_ok=True)

        subtitle_items = []
        scene_videos = []
        global_time = 0.0

        update_task(task_id, message="生成图片", progress=35)
        for scene_index, scene in enumerate(storyboard.get("scenes", []), start=1):
            sid = to_int(scene.get("scene_id", scene_index), scene_index)
            raw_scene_img = task_img_dir / f"scene_{sid:03d}_raw.png"
            prepared_scene_img = task_img_dir / f"scene_{sid:03d}.jpg"

            use_uploaded = scene.get("visual_type") == "uploaded_image" or params["image_strategy"] == "uploaded_only"
            if use_uploaded and saved_images:
                src = saved_images[to_int(scene.get("image_index", 0), 0) % len(saved_images)]
                shutil.copy(src, raw_scene_img)
            elif not use_uploaded and params["enable_ai_image"] and params["image_api_key"]:
                try:
                    size = "1024x1536" if params["orientation"] == "portrait" else "1536x1024"
                    generate_openai_image(scene.get("image_prompt", params["image_style_prompt"]), params["image_model"], params["image_quality"], size, params["image_api_key"], params["image_base_url"], raw_scene_img)
                except Exception:
                    if saved_images:
                        src = saved_images[to_int(scene.get("image_index", 0), 0) % len(saved_images)]
                        shutil.copy(src, raw_scene_img)
                    else:
                        Image.new("RGB", (1536, 1024), (40, 40, 40)).save(raw_scene_img)
            else:
                if saved_images:
                    src = saved_images[to_int(scene.get("image_index", 0), 0) % len(saved_images)]
                    shutil.copy(src, raw_scene_img)
                else:
                    Image.new("RGB", (1536, 1024), (40, 40, 40)).save(raw_scene_img)

            prepare_scene_image(raw_scene_img, params["orientation"], params["subtitle_mode"], scene.get("caption", ""), prepared_scene_img)

            update_task(task_id, message="生成配音", progress=55)
            scene_audio_files = []
            for i, d in enumerate(scene.get("dialogue", [])):
                speaker = next((s for s in storyboard.get("speakers", []) if s["id"] == d.get("speaker_id")), storyboard.get("speakers", [DEFAULT_SPEAKERS[0]])[0])
                out_audio = task_audio_dir / f"scene_{sid:03d}_{i:03d}.mp3"
                if params["tts_provider"] == "edge_tts":
                    generate_edge_tts(d.get("text", ""), speaker.get("voice", "zh-CN-XiaoxiaoNeural"), out_audio)
                else:
                    generate_openai_tts(
                        d.get("text", ""),
                        (speaker.get("voice", "marin") if params["enable_speaker_voices"] else params["default_voice"]),
                        d.get("emotion", params["tts_default_emotion"]),
                        speaker.get("style", "自然"),
                        params["tts_default_speed"],
                        params["tts_model"],
                        params["tts_api_key"],
                        params["tts_base_url"],
                        out_audio,
                    )
                dur = ffprobe_duration(out_audio)
                subtitle_items.append({
                    "start": global_time,
                    "end": global_time + dur,
                    "speaker_name": d.get("speaker_name", speaker.get("name", "主持人")),
                    "text": d.get("text", "")
                })
                global_time += dur + 0.3
                scene_audio_files.append(out_audio)

            scene_silence = task_audio_dir / f"silence_{sid:03d}.mp3"
            run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.5", "-q:a", "9", scene_silence])
            scene_audio_files.append(scene_silence)
            global_time += 0.5

            list_file = task_audio_dir / f"scene_{sid:03d}_concat.txt"
            with open(list_file, "w", encoding="utf-8") as f:
                for p in scene_audio_files:
                    f.write(f"file '{Path(p).resolve()}'\n")
            scene_mix = task_audio_dir / f"scene_{sid:03d}_mix.mp3"
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", scene_mix])
            scene_dur = ffprobe_duration(scene_mix)

            scene_video = task_video_dir / f"scene_{sid:03d}.mp4"
            run_cmd([
                "ffmpeg", "-y", "-loop", "1", "-i", prepared_scene_img, "-i", scene_mix,
                "-c:v", "libx264", "-t", str(scene_dur), "-r", "30", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", "-movflags", "+faststart", scene_video
            ])
            scene_videos.append(scene_video)

        update_task(task_id, message="生成字幕", progress=70)
        srt_path = task_sub_dir / "subtitles.srt"
        ass_path = task_sub_dir / "subtitles.ass"
        build_subtitles(subtitle_items, params["show_speaker_name"], srt_path, ass_path, params["orientation"])

        update_task(task_id, message="合成视频", progress=85)
        concat_list = task_video_dir / "all_scenes.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in scene_videos:
                f.write(f"file '{Path(p).resolve()}'\n")
        final_no_sub = config.FINAL_DIR / f"{task_id}_no_sub.mp4"
        final_video = config.FINAL_DIR / f"{task_id}.mp4"

        run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", final_no_sub])

        if params["subtitle_mode"] in ("both", "bottom"):
            run_cmd([
                "ffmpeg", "-y", "-i", final_no_sub, "-vf", f"ass={ass_path}",
                "-c:v", "libx264", "-c:a", "aac", "-pix_fmt", "yuv420p", "-movflags", "+faststart", final_video
            ])
        else:
            shutil.copy(final_no_sub, final_video)

        final_dur = ffprobe_duration(final_video)
        target_dur = params["target_duration"]
        msg = "完成"
        if params["duration_mode"] != "auto" and target_dur > 0:
            if abs(final_dur - target_dur) / target_dur > 0.2:
                msg = f"最终视频以配音真实时长为准，当前时长为 {final_dur:.1f} 秒。"

        update_task(task_id, status="success", message=msg, progress=100, video_url=f"/download/{task_id}.mp4", video_filename=f"{task_id}.mp4", video_path=str(final_video), final_duration=round(final_dur,2), storyboard_json=json.dumps(storyboard, ensure_ascii=False), finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))
    except Exception as e:
        err = str(e)
        for k in [params.get("script_api_key", ""), params.get("tts_api_key", ""), params.get("image_api_key", "")]:
            if k:
                err = err.replace(k, "***")
        update_task(task_id, status="failed", message="生成失败", progress=100, error=err, error_message=err, finished_at=time.strftime("%Y-%m-%d %H:%M:%S"))


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/records")
def records_page():
    return send_from_directory("static", "records.html")


@app.route("/health")
def health():
    
    try:
        conn = db.get_connection()
        conn.close()
        return jsonify({"success": True, "message": "ok"})
    except Exception as e:
        return jsonify({"success": False, "message": f"db error: {e}"}), 500



@app.route("/api/generate-video", methods=["POST"])
def generate_video():
    form = request.form
    files = request.files.getlist("images")

    script_text = form.get("scriptText", "").strip()
    if not script_text:
        return jsonify({"success": False, "error": "scriptText 不能为空"}), 400

    orientation = form.get("orientation", "portrait")
    if orientation not in ("portrait", "landscape"):
        return jsonify({"success": False, "error": "orientation 非法"}), 400

    duration_mode = form.get("durationMode", "auto")
    if duration_mode not in ("auto", "15", "30", "45", "60", "custom"):
        return jsonify({"success": False, "error": "durationMode 非法"}), 400

    custom_duration = int(form.get("customDuration", "60") or 60)
    if duration_mode == "custom" and not (5 <= custom_duration <= 300):
        return jsonify({"success": False, "error": "customDuration 需在 5-300"}), 400

    image_strategy = form.get("imageStrategy", "ai_fill")
    if image_strategy == "uploaded_only" and not files:
        return jsonify({"success": False, "error": "uploaded_only 模式必须上传图片"}), 400

    for f in files:
        if f.filename and not allowed_file(f.filename):
            return jsonify({"success": False, "error": f"不支持的图片格式: {f.filename}"}), 400

    common_key = form.get("openaiApiKey", "").strip()
    script_provider = form.get("scriptProvider", "openai")
    script_api_key = resolve_api_key(form.get("scriptApiKey", "").strip(), common_key)
    script_base_url = form.get("scriptBaseUrl", "").strip() or config.OPENAI_BASE_URL
    tts_provider = form.get("ttsProvider", "openai")
    tts_api_key = resolve_api_key(form.get("ttsApiKey", "").strip(), common_key)
    tts_base_url = form.get("ttsBaseUrl", "").strip() or config.OPENAI_BASE_URL
    image_api_key = resolve_api_key(form.get("imageApiKey", "").strip(), common_key)
    image_base_url = form.get("imageBaseUrl", "").strip() or config.OPENAI_BASE_URL

    need_script_openai = script_provider in ("openai", "openai_compatible")
    need_tts_openai = tts_provider == "openai"
    need_image_openai = image_strategy in ("ai_fill", "ai_only") and form.get("enableAiImage", "true") == "true"
    if (need_script_openai and not script_api_key) or (need_tts_openai and not tts_api_key) or (need_image_openai and not image_api_key):
        return jsonify({"success": False, "error": "当前配置需要 OpenAI API Key"}), 400

    narration_mode = form.get("narrationMode", "dialogue2")
    speaker_configs_raw = form.get("speakerConfigs", "[]")
    try:
        speaker_configs = json.loads(speaker_configs_raw)
    except Exception:
        speaker_configs = default_speakers_for_mode(narration_mode)

    speaker_need = len(default_speakers_for_mode(narration_mode))
    defaults = default_speakers_for_mode(narration_mode)
    if len(speaker_configs) < speaker_need:
        speaker_configs = defaults
    else:
        speaker_configs = speaker_configs[:speaker_need]

    task_id = uuid.uuid4().hex[:12]
    try:
        db.create_video_record({
            "task_id": task_id,
            "script_text": script_text,
            "hashtags": form.get("hashtags", "").strip(),
            "status": "pending",
            "progress": 0,
            "message": "已创建任务",
            "request_params": json.dumps(sanitize_request_params(form), ensure_ascii=False),
            "speaker_configs": speaker_configs_raw,
            "image_count": len(files),
            "orientation": orientation,
            "duration_mode": duration_mode,
            "narration_mode": narration_mode,
            "subtitle_mode": form.get("subtitleMode", "both"),
            "script_model": form.get("scriptModel", "").strip() or config.OPENAI_SCRIPT_MODEL or "gpt-5.5",
            "tts_model": form.get("ttsModel", "").strip() or config.OPENAI_TTS_MODEL,
            "image_model": form.get("imageModel", "").strip() or config.OPENAI_IMAGE_MODEL,
        })
    except Exception:
        pass

    with TASK_LOCK:
        TASKS[task_id] = {
            "success": True,
            "status": "pending",
            "message": "已创建任务",
            "progress": 0,
            "video_url": "",
            "error": "",
        }

    target_duration = 0 if duration_mode == "auto" else int(custom_duration if duration_mode == "custom" else duration_mode)

    params = {
        "script_text": script_text,
        "hashtags": form.get("hashtags", "").strip(),
        "orientation": orientation,
        "duration_mode": duration_mode,
        "target_duration": target_duration,
        "video_style": form.get("videoStyle", "NotebookLM 音频概览风格"),
        "subtitle_mode": form.get("subtitleMode", "both"),
        "show_speaker_name": form.get("showSpeakerName", "true") == "true",
        "narration_mode": narration_mode,
        "dialogue_style": form.get("dialogueStyle", "NotebookLM 音频概览"),
        "emotion_level": form.get("emotionLevel", "有感染力"),
        "image_strategy": image_strategy,
        "script_provider": script_provider,
        "script_api_key": script_api_key,
        "script_base_url": script_base_url,
        "script_model": form.get("scriptModel", "").strip() or config.OPENAI_SCRIPT_MODEL or "gpt-5.5",
        "script_temperature": float(form.get("scriptTemperature", "0.7") or 0.7),
        "script_max_tokens": int(form.get("scriptMaxTokens", "4000") or 4000),
        "tts_provider": tts_provider,
        "tts_api_key": tts_api_key,
        "tts_base_url": tts_base_url,
        "tts_model": form.get("ttsModel", "").strip() or config.OPENAI_TTS_MODEL,
        "tts_default_speed": form.get("ttsDefaultSpeed", "正常"),
        "tts_default_emotion": form.get("ttsDefaultEmotion", "自然"),
        "enable_speaker_voices": form.get("enableSpeakerVoices", "true") == "true",
        "default_voice": "nova",
        "image_provider": form.get("imageProvider", "openai"),
        "image_api_key": image_api_key,
        "image_base_url": image_base_url,
        "image_model": form.get("imageModel", "").strip() or config.OPENAI_IMAGE_MODEL,
        "image_quality": form.get("imageQuality", config.DEFAULT_IMAGE_QUALITY),
        "speaker_configs": speaker_configs,
        "image_count": len(files),
        "enable_ai_image": form.get("enableAiImage", "true") == "true",
        "image_style_prompt": form.get("imageStylePrompt", "温暖亲子场景"),
    }

    t = threading.Thread(target=process_task, args=(task_id, params, files), daemon=True)
    t.start()
    return jsonify({"success": True, "task_id": task_id})




@app.route("/api/tts-preview", methods=["POST"])
def tts_preview():
    data = request.get_json(silent=True) or {}
    provider = data.get("provider", "openai")
    text = (data.get("text") or "你好，这是一段配音试听。宝宝启蒙真的很重要，我们一起来看看这套绘本有什么特点。").strip()
    voice = data.get("voice", "nova")
    emotion = data.get("emotion", "自然")
    speed = data.get("speed", "正常")
    style = data.get("style", "自然")
    tts_model = data.get("ttsModel", config.OPENAI_TTS_MODEL)
    api_key = resolve_api_key(data.get("apiKey", ""), "")
    base_url = (data.get("baseUrl") or config.OPENAI_BASE_URL).strip()
    preview_dir = config.TEMP_DIR / "preview_audio"
    preview_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4().hex}.mp3"
    output_path = preview_dir / filename
    try:
        if provider == "edge_tts":
            generate_edge_tts(text, voice, output_path)
        else:
            if not api_key:
                return jsonify({"success": False, "message": "缺少 OpenAI API Key"}), 400
            generate_openai_tts(text, voice, emotion, style, speed, tts_model, api_key, base_url, output_path)
        return jsonify({"success": True, "audio_url": f"/preview_audio/{filename}"})
    except Exception as e:
        msg = str(e).replace(api_key, "***") if api_key else str(e)
        return jsonify({"success": False, "message": msg}), 500


@app.route("/preview_audio/<filename>")
def preview_audio(filename):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".mp3"):
        abort(404)
    preview_dir = (config.TEMP_DIR / "preview_audio").resolve()
    file_path = (preview_dir / safe_name).resolve()
    if preview_dir not in file_path.parents or not file_path.exists():
        abort(404)
    return send_from_directory(preview_dir, safe_name, as_attachment=False)

@app.route("/api/task/<task_id>")
def get_task(task_id):
    rec = None
    try:
        rec = db.get_video_record(task_id)
    except Exception:
        rec = None
    if rec:
        return jsonify({
            "success": True,
            "task_id": rec.get("task_id"),
            "status": rec.get("status", "pending"),
            "progress": rec.get("progress", 0),
            "message": rec.get("message") or "",
            "error": rec.get("error_message") or "",
            "video_url": rec.get("video_url") or "",
            "created_at": str(rec.get("created_at") or ""),
            "updated_at": str(rec.get("updated_at") or ""),
        })
    with TASK_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return jsonify({"success": False, "error": "task 不存在"}), 404
    return jsonify({"success": True, "task_id": task_id, **task})


@app.route("/api/records")
def list_records():
    page = int(request.args.get("page", 1) or 1)
    page_size = int(request.args.get("page_size", 10) or 10)
    status = request.args.get("status", "").strip() or None
    keyword = request.args.get("keyword", "").strip() or None
    data = db.list_video_records(page=page, page_size=page_size, status=status, keyword=keyword)
    return jsonify({"success": True, "page": page, "page_size": page_size, "total": data["total"], "records": data["records"]})


@app.route("/api/records/<task_id>")
def record_detail(task_id):
    rec = db.get_video_record(task_id)
    if not rec:
        return jsonify({"success": False, "message": "not found"}), 404
    return jsonify({"success": True, "record": rec})


@app.route("/api/records/<task_id>", methods=["DELETE"])
def delete_record(task_id):
    ok = db.delete_video_record(task_id, delete_files=True)
    if not ok:
        return jsonify({"success": False, "message": "not found"}), 404
    return jsonify({"success": True})


@app.route("/download/<filename>")
def download(filename):
    safe_name = Path(filename).name
    if safe_name != filename or not safe_name.endswith(".mp4"):
        abort(404)
    file_path = (config.FINAL_DIR / safe_name).resolve()
    final_dir = config.FINAL_DIR.resolve()
    if final_dir not in file_path.parents or not file_path.exists():
        abort(404)
    return send_from_directory(final_dir, safe_name, as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5028, debug=False)
