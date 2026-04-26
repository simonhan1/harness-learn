import os
import json
import urllib.request

API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
API_URL = "https://api.deepseek.com/chat/completions"

def call_api(prompt: str) -> str:
    """直接调用 DeepSeek API"""
    data = json.dumps({
        "model": "deepseek-chat",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1000,
    }).encode("utf-8")

    req = urllib.request.Request(
        API_URL,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )

    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read().decode())
        return result["choices"][0]["message"]["content"]

if __name__ == "__main__":
    # 测试：让它分析一个项目
    print("=" * 60)
    print("测试：让 AI 分析当前项目的代码结构")
    print("=" * 60)

    response = call_api(
        "请分析当前项目的目录结构和代码质量，给出改进建议。"
    )
    print(response)

    print("\n" + "=" * 60)
    print("观察：AI 能看到你的项目文件吗？")
    print("=" * 60)