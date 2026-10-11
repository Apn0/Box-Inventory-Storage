with open('identify.py', 'r', encoding='utf-8') as f: text = f.read()
import re
text = text.replace('prompt = f"Identify this part.\n\n{config.context}"', 'prompt = f"Identify this part.\\n\\n{config.context}"')
with open('identify.py', 'w', encoding='utf-8') as f: f.write(text)
