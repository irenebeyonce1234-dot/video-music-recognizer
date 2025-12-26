# 项目存档记录

## 音乐识别项目 (v1)
**路径**: `/Users/bigfat25/Documents/trae_projects/music_recognizer_v1`
**时间**: 2025-12-18
**状态**: 已完成基础功能与 UI 优化，支持异步任务。

### 如何恢复开发？
1. 进入目录：`cd music_recognizer_v1`
2. 设置环境变量 (ACRCloud Keys)
3. 运行服务：`python3 webapp/app.py`
4. 内网穿透（可选）：`ssh -o StrictHostKeyChecking=no -R 80:localhost:8000 serveo.net`

### 主要文件
- `webapp/app.py`: Flask 后端（包含异步任务逻辑）
- `webapp/templates/index.html`: 前端界面（包含轮询逻辑）
- `recognizer.py`: 核心识别逻辑（包含去重、外链生成）
