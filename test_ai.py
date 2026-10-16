import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()  # 从 .env 文件读取 API key

client = OpenAI(
    api_key=os.environ.get("DEEPSEEK_API_KEY"),
    base_url="https://api.deepseek.com",
)

response = client.chat.completions.create(
    model="deepseek-chat",
    messages=[
        {"role": "system", "content": "你是一个温柔的情侣和好助手。"},
        {"role": "user", "content": "我男朋友又忘了回我消息，我好生气！"},
    ],
)

print(response.choices[0].message.content)