# Video Music Recognizer 工作流程文档

## 系统架构流程图

```mermaid
graph TD
    %% 定义样式
    classDef user fill:#f9f,stroke:#333,stroke-width:2px;
    classDef system fill:#e1f5fe,stroke:#0277bd,stroke-width:2px;
    classDef external fill:#fff3e0,stroke:#ef6c00,stroke-width:2px;
    classDef logic fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px;

    %% 阶段 1: 输入与下载
    Start([👤 用户输入视频 URL]) -->|提交表单| Flask[🖥️ Flask 后端接收]:::system
    Flask -->|调用 yt-dlp| Download[📥 下载音频 (MP3)]:::system
    Download -->|保存到临时目录| TempFile[(📄 临时音频文件)]:::system

    %% 阶段 2: 切片与识别循环
    TempFile -->|读取音频| Slicing[✂️ 音频切片处理]:::logic
    Slicing -->|每隔 15秒 切一段| Segment{🔁 还有片段?}:::logic
    
    Segment -- 是 --> SendACR[📤 发送指纹给 ACRCloud]:::external
    SendACR -->|返回 JSON| RawResult[获得原始识别结果]:::system
    
    RawResult -->|初筛| ScoreFilter{分数 > 30?}:::logic
    ScoreFilter -- No --> Segment
    ScoreFilter -- Yes --> SaveCand[💾 暂存候选结果]:::system
    SaveCand --> Segment

    %% 阶段 3: 聚合与清洗 (核心逻辑)
    Segment -- 否 (遍历结束) --> Aggregation[∑ 聚合与去重]:::logic
    Aggregation -->|按 ACRID 分组| UniqueList[生成唯一歌曲列表]:::system

    UniqueList --> LoopFinal[遍历最终列表]:::logic
    
    LoopFinal --> Blacklist{⛔ 黑名单/脏数据检测?}:::logic
    Note_Blacklist[检查: Mashup, Remix, <br>乱码, Cover, 拼写错误]:::logic
    Blacklist -- 命中 --> Reject[❌ 丢弃]:::system
    Reject --> LoopFinal
    
    Blacklist -- 通过 --> NeteaseCheck[🎵 网易云音乐 API 搜索]:::external
    NeteaseCheck -->|补充元数据| FinalItem[✅ 生成最终条目]:::system
    FinalItem --> LoopFinal

    %% 阶段 4: 输出
    LoopFinal -- 结束 --> Render[🎨 渲染 HTML 页面]:::system
    Render --> End([🏁 用户看到歌单列表]):::user

    %% 连接注释
    Note_Blacklist -.- Blacklist
```

## 核心模块说明

### 1. Recognizer (`recognizer.py`)
- **Video Download**: 使用 `yt-dlp` 下载视频并提取音频。
- **Slicing Strategy**: 采用 "15秒步长" (Stride) 遍历整个音频文件，确保捕捉到 Medley (串烧) 中的每一首短歌。
- **ACRCloud Integration**: 调用第三方指纹库进行音频识别。
- **Filtering Logic**: 包含自定义的黑名单和乱码检测算法，用于清洗 ACRCloud 返回的噪音数据。

### 2. Web Interface (`app.py` & `templates/`)
- 提供简单的用户界面，允许用户输入 URL 和配置 API Key。
- 实时展示识别日志和最终结果表格。

### 3. External Services
- **ACRCloud**: 提供核心的音频指纹识别能力。
- **Netease Cloud Music**: 用于验证歌曲是否存在于国内音乐平台，并获取中文元数据。
