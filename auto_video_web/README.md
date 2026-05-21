# AI 自动生成短视频工具（MVP）

## 1. 项目介绍
本项目是一个本地 Web 工具：输入商品文案 + 上传商品图，即可自动生成“多人对话配音 + 字幕 + 短视频 MP4”。

## 2. 功能列表
- AI 改写文案为结构化分镜 JSON
- 单人/双人/三人/四人对话
- 每个 speaker 使用不同 voice
- OpenAI TTS（gpt-4o-mini-tts）+ edge-tts 备用
- OpenAI 图片生成（gpt-image-2）
- 字幕输出 SRT + ASS
- FFmpeg 合成 scene + 拼接 + 字幕烧录
- 任务状态轮询（内存字典）

## 3. 环境要求
- Python 3.8+
- FFmpeg（需要 ffmpeg + ffprobe）
- OpenAI API Key（可选但推荐）

## 4. 安装依赖
```bash
pip install -r requirements.txt
```

## 5. Windows 安装 FFmpeg
```bash
winget install Gyan.FFmpeg
```

## 6. 启动
```bash
python app.py
```

## 7. 浏览器访问
http://127.0.0.1:5000

## 8. API Key 使用说明
- 可直接在前端输入 Key（仅本次任务使用）
- 也可在 `.env` 设置：`OPENAI_API_KEY=...`
- 生产环境建议使用环境变量，不建议写死在前端

## 9. 使用流程
1. 粘贴文案
2. 上传商品图片
3. 选择单人/双人/三人/四人
4. 配置声音与 API
5. 点击生成视频，等待任务完成

## 10. 常见问题
1. **ffmpeg 找不到**：请确认 ffmpeg/ffprobe 已加入 PATH。
2. **OpenAI API Key 错误**：检查 key 是否有效，base_url 是否正确。
3. **gpt-image-2 生成失败**：会自动 fallback 到上传图片（如存在）。
4. **TTS 配音失败**：可切到 edge-tts 或检查网络/API。
5. **中文字体乱码**：安装微软雅黑/黑体或 Noto CJK/WQY 字体。
6. **视频时长偏差**：最终以真实配音时长为准。
7. **商品图被裁剪**：当前为 cover 裁剪以适配 9:16 或 16:9。

## 11. 目录结构
```text
auto_video_web/
├─ app.py
├─ config.py
├─ requirements.txt
├─ README.md
├─ static/
│  ├─ index.html
│  ├─ style.css
│  └─ app.js
├─ uploads/
├─ output/
│  ├─ audio/
│  ├─ images/
│  ├─ videos/
│  ├─ subtitles/
│  └─ final/
└─ temp/
```
