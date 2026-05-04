import json

with open(r'C:\Users\hanzhenfeng\.local\share\opencode\tool-output\tool_dec11e1b3001qi2v4D5twMJQKP', 'r', encoding='utf-8') as f:
    data = json.load(f)

for i, item in enumerate(data['items']):
    topics = ','.join(item.get('topics', []))
    desc = item.get('description', '') or ''
    lang = item.get('language', '') or ''
    print(f"{i}|{item['full_name']}|{item['html_url']}|{desc}|{item['stargazers_count']}|{lang}|{topics}")
