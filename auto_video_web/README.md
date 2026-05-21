# AI 自动生成短视频工具

## 本地运行
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python app.py
```

## 宝塔面板部署（Nginx + Gunicorn + Flask）
1. 安装 Python 3
2. 安装 Git
3. 安装 FFmpeg
4. 拉取 GitHub 仓库
5. 创建虚拟环境
6. 安装 requirements
7. 创建 `.env`
8. 使用 gunicorn 启动
9. 宝塔网站反向代理到 `127.0.0.1:5000`

### Gunicorn 启动命令
```bash
gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app
```
> 当前任务状态保存在内存字典，生产请先使用 `-w 1`。

## Nginx 反向代理配置示例
```nginx
server {
    listen 80;
    server_name video.example.com;

    client_max_body_size 300M;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_connect_timeout 600;
        proxy_send_timeout 600;
        proxy_read_timeout 600;
    }
}
```

## systemd 服务示例
```ini
[Unit]
Description=Auto Video Web
After=network.target

[Service]
User=root
WorkingDirectory=/www/wwwroot/auto_video_web
EnvironmentFile=/www/wwwroot/auto_video_web/.env
ExecStart=/www/wwwroot/auto_video_web/venv/bin/gunicorn -w 1 -b 127.0.0.1:5000 wsgi:app
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

## .env 示例
参考 `.env.example`，关键项：
- OPENAI_API_KEY
- OPENAI_BASE_URL
- OPENAI_SCRIPT_MODEL（可留空）
- OPENAI_TTS_MODEL
- OPENAI_IMAGE_MODEL
- FLASK_SECRET_KEY
- MAX_UPLOAD_MB

## 常见问题
- `ffmpeg: command not found`
- `git clone` 失败
- OpenAI API 连接失败
- 上传图片 `413 Request Entity Too Large`
- 生成视频很慢
- 任务状态一直 `running`
- 中文字体乱码

## 三类模型单独配置
- 文案模型：用于生成分镜和多角色对话结构。
- TTS 模型：用于生成每个角色的配音音频。
- 图片模型：用于生成 AI 氛围图（可与上传图片混合）。

## 声音试听说明
- 前端角色卡片支持“试听声音”，会调用 `/api/tts-preview`。
- 使用 OpenAI TTS 时会产生少量 API 费用。
- 使用 Edge TTS 免费模式时，不需要 OpenAI Key。

## API Key 优先级
- 当前任务前端填写的模块 Key（script/tts/image）优先。
- 若模块 Key 为空，回退到通用 Key 与 `.env` 的 `OPENAI_API_KEY`。
- 若该模块需要 OpenAI 且仍未提供，则接口直接报错。

## MySQL 5.7（宝塔）部署
1. 在宝塔创建数据库：
   - 数据库名：`auto_video_db`
   - 用户名：`auto_video`
   - 密码：自定义
2. 在 `.env` 增加：
```env
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=auto_video
MYSQL_PASSWORD=你的密码
MYSQL_DATABASE=auto_video_db
MYSQL_CHARSET=utf8mb4
```
3. 初始化数据库：
```bash
source venv/bin/activate
python init_db.py
```
4. 重启服务：
```bash
systemctl restart auto-video
```
5. 访问：
- `https://你的域名/`
- `https://你的域名/records`
