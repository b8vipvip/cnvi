import base64
import json
import math
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file, send_from_directory
from PIL import Image, ImageDraw, ImageFont
from werkzeug.utils import secure_filename

import config

load_dotenv()

try:
    from openai import OpenAI
except Exception:
    OpenAI = None

app = Flask(__name__, static_folder="static", static_url_path="/static")
app.config["MAX_CONTENT_LENGTH"] = config.MAX_IMAGE_SIZE_MB * 1024 * 1024 * 20

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
    os.makedirs(d, exist_ok=True)


DEFAULT_SPEAKERS = [
    {"id": "S1", "name": "主持人A", "role": "理性介绍", "voice": "marin", "style": "自然、清晰、像知识型短视频主持人"},
    {"id": "S2", "name": "主持人B", "role": "宝妈体验", "voice": "nova", "style": "温柔、有亲和力、带一点惊喜和真实体验感"},
    {"id": "S3", "name": "主持人C", "role": "补充观点", "voice": "cedar", "style": "简洁、有节奏"},
    {"id": "S4", "name": "主持人D", "role": "总结收束", "voice": "shimmer", "style": "温暖、鼓励"},
]


def update_task(task_id, **kwargs):
    with TASK_LOCK:
        TASKS[task_id].update(kwargs)


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in config.ALLOWED_EXTENSIONS


def run_cmd(cmd):
    p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if p.returncode != 0:
        raise RuntimeError(f"命令失败: {' '.join(cmd)}\n{p.stderr}")
    return p.stdout.strip()


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
    run_cmd(["edge-tts", "--voice", edge_voice, "--text", text, "--write-media", output_path])


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
        "speechSpeed": params["speech_speed"],
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
        response_format={"type": "json_object"}
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
        update_task(task_id, status="running", message="保存图片", progress=5)
        task_upload_dir = os.path.join(config.UPLOAD_DIR, task_id)
        os.makedirs(task_upload_dir, exist_ok=True)
        saved_images = []
        for file in uploaded_files:
            name = secure_filename(file.filename)
            dst = os.path.join(task_upload_dir, name)
            file.save(dst)
            saved_images.append(dst)

        update_task(task_id, message="AI 改写分镜", progress=15)
        storyboard = generate_storyboard_with_ai(params, params["openai_api_key"], params["openai_base_url"])

        task_audio_dir = os.path.join(config.AUDIO_DIR, task_id)
        task_img_dir = os.path.join(config.IMAGE_DIR, task_id)
        task_video_dir = os.path.join(config.VIDEO_DIR, task_id)
        task_sub_dir = os.path.join(config.SUBTITLE_DIR, task_id)
        for d in [task_audio_dir, task_img_dir, task_video_dir, task_sub_dir]:
            os.makedirs(d, exist_ok=True)

        subtitle_items = []
        scene_videos = []
        global_time = 0.0

        update_task(task_id, message="生成图片", progress=30)
        for scene in storyboard.get("scenes", []):
            sid = scene["scene_id"]
            raw_scene_img = os.path.join(task_img_dir, f"scene_{sid:03d}_raw.png")
            prepared_scene_img = os.path.join(task_img_dir, f"scene_{sid:03d}.jpg")

            use_uploaded = scene.get("visual_type") == "uploaded_image" or params["image_strategy"] == "uploaded_only"
            if use_uploaded and saved_images:
                src = saved_images[scene.get("image_index", 0) % len(saved_images)]
                shutil.copy(src, raw_scene_img)
            elif not use_uploaded and params["enable_ai_image"] and params["openai_api_key"]:
                try:
                    size = "1024x1536" if params["orientation"] == "portrait" else "1536x1024"
                    generate_openai_image(scene.get("image_prompt", "温暖亲子场景"), params["image_model"], params["image_quality"], size, params["openai_api_key"], params["openai_base_url"], raw_scene_img)
                except Exception:
                    if saved_images:
                        src = saved_images[scene.get("image_index", 0) % len(saved_images)]
                        shutil.copy(src, raw_scene_img)
                    else:
                        Image.new("RGB", (1536, 1024), (40, 40, 40)).save(raw_scene_img)
            else:
                if saved_images:
                    src = saved_images[scene.get("image_index", 0) % len(saved_images)]
                    shutil.copy(src, raw_scene_img)
                else:
                    Image.new("RGB", (1536, 1024), (40, 40, 40)).save(raw_scene_img)

            prepare_scene_image(raw_scene_img, params["orientation"], params["subtitle_mode"], scene.get("caption", ""), prepared_scene_img)

            update_task(task_id, message="生成配音", progress=45)
            scene_audio_files = []
            for i, d in enumerate(scene.get("dialogue", [])):
                speaker = next((s for s in storyboard.get("speakers", []) if s["id"] == d.get("speaker_id")), storyboard.get("speakers", [DEFAULT_SPEAKERS[0]])[0])
                out_audio = os.path.join(task_audio_dir, f"scene_{sid:03d}_{i:03d}.mp3")
                if params["api_provider"] == "edge_tts" or params["use_edge_for_tts"]:
                    generate_edge_tts(d.get("text", ""), speaker.get("voice", "zh-CN-XiaoxiaoNeural"), out_audio)
                else:
                    generate_openai_tts(
                        d.get("text", ""),
                        speaker.get("voice", "marin"),
                        d.get("emotion", params["emotion_level"]),
                        speaker.get("style", "自然"),
                        params["speech_speed"],
                        params["tts_model"],
                        params["openai_api_key"],
                        params["openai_base_url"],
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

            scene_silence = os.path.join(task_audio_dir, f"silence_{sid:03d}.mp3")
            run_cmd(["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo", "-t", "0.5", "-q:a", "9", scene_silence])
            scene_audio_files.append(scene_silence)
            global_time += 0.5

            list_file = os.path.join(task_audio_dir, f"scene_{sid:03d}_concat.txt")
            with open(list_file, "w", encoding="utf-8") as f:
                for p in scene_audio_files:
                    f.write(f"file '{os.path.abspath(p)}'\n")
            scene_mix = os.path.join(task_audio_dir, f"scene_{sid:03d}_mix.mp3")
            run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_file, "-c", "copy", scene_mix])
            scene_dur = ffprobe_duration(scene_mix)

            scene_video = os.path.join(task_video_dir, f"scene_{sid:03d}.mp4")
            run_cmd([
                "ffmpeg", "-y", "-loop", "1", "-i", prepared_scene_img, "-i", scene_mix,
                "-c:v", "libx264", "-t", str(scene_dur), "-r", "30", "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-shortest", "-movflags", "+faststart", scene_video
            ])
            scene_videos.append(scene_video)

        update_task(task_id, message="生成字幕", progress=75)
        srt_path = os.path.join(task_sub_dir, "subtitles.srt")
        ass_path = os.path.join(task_sub_dir, "subtitles.ass")
        build_subtitles(subtitle_items, params["show_speaker_name"], srt_path, ass_path, params["orientation"])

        update_task(task_id, message="合成视频", progress=85)
        concat_list = os.path.join(task_video_dir, "all_scenes.txt")
        with open(concat_list, "w", encoding="utf-8") as f:
            for p in scene_videos:
                f.write(f"file '{os.path.abspath(p)}'\n")
        final_no_sub = os.path.join(config.FINAL_DIR, f"{task_id}_no_sub.mp4")
        final_video = os.path.join(config.FINAL_DIR, f"{task_id}.mp4")

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

        update_task(task_id, status="success", message=msg, progress=100, video_url=f"/download/{task_id}.mp4")
    except Exception as e:
        update_task(task_id, status="failed", message="任务失败", progress=100, error=str(e))


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


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

    api_provider = form.get("apiProvider", "openai")
    openai_api_key = form.get("openaiApiKey", "").strip() or os.getenv("OPENAI_API_KEY", "")
    openai_base_url = form.get("openaiBaseUrl", "").strip() or config.OPENAI_BASE_URL

    need_openai = api_provider in ("openai", "mixed") or image_strategy in ("ai_fill", "ai_only")
    if need_openai and not openai_api_key:
        return jsonify({"success": False, "error": "当前配置需要 OpenAI API Key"}), 400

    narration_mode = form.get("narrationMode", "dialogue2")
    speaker_configs_raw = form.get("speakerConfigs", "[]")
    try:
        speaker_configs = json.loads(speaker_configs_raw)
    except Exception:
        speaker_configs = DEFAULT_SPEAKERS[:2]

    speaker_count_map = {"monologue": 1, "dialogue2": 2, "dialogue3": 3, "dialogue4": 4}
    speaker_need = speaker_count_map.get(narration_mode, 2)
    if len(speaker_configs) < speaker_need:
        speaker_configs = DEFAULT_SPEAKERS[:speaker_need]
    else:
        speaker_configs = speaker_configs[:speaker_need]

    task_id = uuid.uuid4().hex[:12]
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
        "speech_speed": form.get("speechSpeed", "正常"),
        "image_strategy": image_strategy,
        "api_provider": api_provider,
        "openai_api_key": openai_api_key,
        "openai_base_url": openai_base_url,
        "script_model": form.get("scriptModel", config.DEFAULT_SCRIPT_MODEL),
        "tts_model": form.get("ttsModel", config.DEFAULT_TTS_MODEL),
        "image_model": form.get("imageModel", config.DEFAULT_IMAGE_MODEL),
        "image_quality": form.get("imageQuality", config.DEFAULT_IMAGE_QUALITY),
        "speaker_configs": speaker_configs,
        "image_count": len(files),
        "enable_ai_image": form.get("enableAiImage", "true") == "true",
        "use_edge_for_tts": api_provider in ("edge_tts", "mixed"),
    }

    t = threading.Thread(target=process_task, args=(task_id, params, files), daemon=True)
    t.start()
    return jsonify({"success": True, "task_id": task_id})


@app.route("/api/task/<task_id>")
def get_task(task_id):
    with TASK_LOCK:
        task = TASKS.get(task_id)
    if not task:
        return jsonify({"success": False, "error": "task 不存在"}), 404
    return jsonify({"success": True, **task})


@app.route("/download/<filename>")
def download(filename):
    return send_file(os.path.join(config.FINAL_DIR, filename), as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
