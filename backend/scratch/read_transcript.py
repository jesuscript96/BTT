import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

path = r"C:\Users\Famil\.gemini\antigravity\brain\046173e2-46fa-4293-a559-5e20c48574d6\.system_generated\logs\transcript.jsonl"
with open(path, "r", encoding="utf-8") as f:
    for idx, line in enumerate(f):
        data = json.loads(line)
        if data.get("type") == "USER_INPUT":
            content = data.get("content", "")
            if any(word in content.lower() for word in ["ventana", "hora", "horario"]):
                print(f"=== User Input at step {idx} ===")
                print(content)
                print("="*60)
