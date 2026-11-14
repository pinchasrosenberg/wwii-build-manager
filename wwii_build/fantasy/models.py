import json
import os
import re
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

from .store import DATA_DIR

VLM_URL = os.environ.get('FANTASY_VLM_URL', 'http://127.0.0.1:8080')
VLM_KEY_FILE = Path(os.environ.get('FANTASY_VLM_KEY_FILE', DATA_DIR / 'vlm.key'))
VLM_NAME = 'Qwen3-VL-30B-A3B (llama.cpp, מקומי)'
VLM_SNAPSHOTS = Path.home() / '.cache/huggingface/hub/models--Qwen--Qwen3-VL-30B-A3B-Instruct-GGUF/snapshots'
OLLAMA_URL = os.environ.get('FANTASY_OLLAMA_URL', 'http://127.0.0.1:11434')
OLLAMA_MODEL = os.environ.get('FANTASY_LLM', 'qwen2.5:14b')


def vlm_key():
    return VLM_KEY_FILE.read_text().strip() if VLM_KEY_FILE.is_file() else ''


def get_json(url, timeout=3, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read() or b'{}')


def post_json(url, body, timeout, headers=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json', **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def vlm_weights():
    snaps = sorted(VLM_SNAPSHOTS.glob('*/')) if VLM_SNAPSHOTS.is_dir() else []
    pick = lambda pattern: next((p for s in snaps for p in sorted(s.glob(pattern))), None)
    return pick('Qwen3VL-30B-A3B-Instruct-*.gguf'), pick('mmproj-*.gguf')


def vlm_up():
    try:
        return get_json(f'{VLM_URL}/health', 2).get('status') == 'ok'
    except (urllib.error.URLError, OSError, ValueError):
        return False


def ollama_up():
    try:
        return any(m.get('name', '').startswith(OLLAMA_MODEL.split(':')[0]) for m in get_json(f'{OLLAMA_URL}/api/tags', 2).get('models', []))
    except (urllib.error.URLError, OSError, ValueError):
        return False


def status():
    model, mmproj = vlm_weights()
    return {
        'vision': {'name': VLM_NAME, 'up': vlm_up(), 'installed': bool(model and mmproj), 'can_start': bool(model and mmproj and shutil.which('llama-server'))},
        'text': {'name': f'{OLLAMA_MODEL} (Ollama, מקומי)', 'up': ollama_up()},
    }


def start_vlm():
    model, mmproj = vlm_weights()
    binary = shutil.which('llama-server')
    if vlm_up() or not (model and mmproj and binary):
        return vlm_up()
    if not VLM_KEY_FILE.is_file():
        VLM_KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        VLM_KEY_FILE.write_text(os.urandom(18).hex())
        VLM_KEY_FILE.chmod(0o600)
    log = open(DATA_DIR / 'vlm-server.log', 'ab')
    subprocess.Popen([binary, '-m', str(model), '--mmproj', str(mmproj), '--host', '127.0.0.1', '--port', VLM_URL.rsplit(':', 1)[-1],
                      '-c', '16384', '-np', '1', '-ngl', '99', '--offline', '--api-key-file', str(VLM_KEY_FILE),
                      '--image-min-tokens', '256', '--image-max-tokens', '1024'],
                     stdout=log, stderr=log, start_new_session=True)
    return False


def parse_json(text):
    cleaned = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M).strip()
    start, end = cleaned.find('{'), cleaned.rfind('}')
    return json.loads(cleaned[start:end + 1])


def vlm_json(system, text, images=(), schema=None, max_tokens=2200, timeout=300):
    content = [{'type': 'image_url', 'image_url': {'url': img}} for img in images] + [{'type': 'text', 'text': text}]
    body = {'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}],
            'temperature': 0.25, 'max_tokens': max_tokens,
            'response_format': {'type': 'json_schema', 'json_schema': {'name': 'plan', 'schema': schema}} if schema else {'type': 'json_object'}}
    data = post_json(f'{VLM_URL}/v1/chat/completions', body, timeout, {'Authorization': f'Bearer {vlm_key()}'})
    return parse_json(data['choices'][0]['message']['content'])


def ollama_json(system, text, schema=None, timeout=150):
    body = {'model': OLLAMA_MODEL, 'system': system, 'prompt': text, 'stream': False, 'format': schema or 'json', 'keep_alive': '5m',
            'options': {'temperature': 0.2, 'num_predict': 1800, 'num_ctx': 8192}}
    return parse_json(post_json(f'{OLLAMA_URL}/api/generate', body, timeout)['response'])


def ask_json(system, text, images=(), schema=None):
    if vlm_up():
        return vlm_json(system, text, images, schema), VLM_NAME
    if images:
        raise RuntimeError('מודל הראייה לא פעיל — אי אפשר לקרוא את התמונה')
    return ollama_json(system, text, schema), f'{OLLAMA_MODEL} (Ollama)'
