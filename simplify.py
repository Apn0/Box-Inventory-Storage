import re
with open('identify.py', 'r', encoding='utf-8') as f: text = f.read()
text = re.sub(r'\nOPENAI_MODEL =.*?\n', '\n', text)
text = re.sub(r'\nGEMINI_MODEL =.*?\n', '\n', text)
text = re.sub(r'\nGEMINI_URL =.*?\n', '\n', text)
for func in ['_gemini', '_openai', '_claude']:
    text = re.sub(r'\ndef ' + func + r'\(.*?->.*?(?=\n\n\w)', '', text, flags=re.DOTALL)

new_identify = '''def identify(path: pathlib.Path, config: IdentifyConfig) -> dict | None:
    media = SUPPORTED.get(path.suffix.lower()) or mimetypes.guess_type(path.name)[0]
    if media not in SUPPORTED.values():
        print(f"  skipped — {path.suffix} is not a supported image type")
        return None
    data = base64.standard_b64encode(path.read_bytes()).decode("ascii")
    prompt = f"Identify this part.\\n\\n{config.context}"
    token = vertex_token()
    if not token: raise RuntimeError("no gcloud token")
    return _vertex(data, media, prompt, token)
'''
text = re.sub(r'def identify\(path: pathlib\.Path, config: IdentifyConfig\).*?def _recoverable', new_identify + '\n\ndef _recoverable', text, flags=re.DOTALL)
text = re.sub(r'def _create_config.*?(?=\n\n\w)', 'def _create_config(provider: str, context: str) -> IdentifyConfig:\n    return IdentifyConfig(client=None, context=context, provider=provider, gemini_key=None, openai_key=None)', text, flags=re.DOTALL)
text = re.sub(r'    anthropic_key = read_key\("ANTHROPIC_API_KEY"\).*?sys\.exit\("pip install anthropic"\)\n\s+print\("  anthropic SDK not installed — skipping Claude"\)\n', '', text, flags=re.DOTALL)

with open('identify.py', 'w', encoding='utf-8') as f: f.write(text)
