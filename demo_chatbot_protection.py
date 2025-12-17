from flask import Flask, request, jsonify
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import time

# 模拟一个简单的 Flask 应用
app = Flask(__name__)

# 1. 引入 Rate Limiting (速率限制)
# key_func=get_remote_address 使用 IP 地址作为限制依据
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per day", "50 per hour"],
    storage_uri="memory://"
)

# 模拟的大模型调用函数
def call_llm_model(prompt):
    # 模拟耗时操作
    time.sleep(1)
    return f"模型回复: 收到您的消息，长度为 {len(prompt)}"

@app.route("/chat", methods=["POST"])
@limiter.limit("5 per minute") # 限制每分钟只能发5条 (防止刷屏)
def chat():
    data = request.json
    user_input = data.get("message", "")
    
    # 2. 后端强制截断 (Backend Truncation)
    # 即使前端不限制，后端也必须有最后一道防线
    # 假设我们限制 2000 个字符 (对于中文模型通常足够表达诉求，且不会导致 Token 爆炸)
    MAX_CHARS = 2000
    
    if len(user_input) > MAX_CHARS:
        # 策略 A: 直接报错 (严格模式)
        # return jsonify({"error": "输入过长，请限制在2000字以内"}), 400
        
        # 策略 B: 自动截断 (体验更好，防止报错)
        # 很多时候用户复制粘贴长文本，保留前2000字通常能包含核心意图
        user_input = user_input[:MAX_CHARS]
        warning = f"您的输入过长，已自动截取前 {MAX_CHARS} 个字符。"
    else:
        warning = None

    # 3. 这里调用模型
    try:
        response = call_llm_model(user_input)
        return jsonify({
            "response": response,
            "warning": warning
        })
    except Exception as e:
        return jsonify({"error": "模型服务繁忙，请稍后再试"}), 503

# 错误处理：当触发限流时返回友好的中文提示
@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({
        "error": "发送太频繁了，请休息一下再试 (Rate limit exceeded)",
        "detail": str(e.description)
    }), 429

if __name__ == "__main__":
    app.run(port=5001)
