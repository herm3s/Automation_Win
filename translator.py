import os
import re
import glob
import shutil
import json
import urllib.request
import urllib.error
# pyrefly: ignore [missing-import]
from dotenv import load_dotenv
from utils import sanitize_filename, draw_progress_bar

# Load environment variables from .env
load_dotenv()

DEFAULT_SYSTEM_PROMPT = """You are a professional web novel translator. Translate the following chapter content.
Maintain the original tone, style, character names, and formatting (Markdown).
Translate the chapter title to English/Thai as appropriate and format it for a file name.
Ensure the chapter number in FILENAME uses Arabic numerals (e.g., 'บทที่ 111' or 'Chapter 111' instead of written-out words).

Provide the translation in the exact format shown below, with no introductory or concluding remarks:

FILENAME: <translated_chapter_title_suitable_for_filename_without_extension>
CONTENT:
<translated_markdown_content>
"""

_api_opener = None

def get_api_opener():
    global _api_opener
    if _api_opener is None:
        import ssl
        ssl_context = ssl._create_unverified_context()
        _api_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl_context)
        )
    return _api_opener

def thai_to_int(text: str) -> int | None:
    ONES = {
        'หนึ่ง': 1, 'เอ็ด': 1,
        'สอง': 2, 'ยี่': 2,
        'สาม': 3, 'สี่': 4, 'ห้า': 5,
        'หก': 6, 'เจ็ด': 7, 'แปด': 8, 'เก้า': 9,
    }
    result = 0

    m = re.match(r'^(หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)พัน(.*)', text)
    if m:
        result += ONES[m.group(1)] * 1000
        text = m.group(2)

    m = re.match(r'^(หนึ่ง|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)ร้อย(.*)', text)
    if m:
        result += ONES[m.group(1)] * 100
        text = m.group(2)

    m = re.match(r'^(ยี่|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)?(สิบ)(.*)', text)
    if m:
        tens_prefix = m.group(1)
        text = m.group(3)
        result += 20 if tens_prefix == 'ยี่' else (ONES[tens_prefix] * 10 if tens_prefix else 10)

    m = re.match(r'^(หนึ่ง|เอ็ด|สอง|สาม|สี่|ห้า|หก|เจ็ด|แปด|เก้า)', text)
    if m:
        result += ONES[m.group(1)]

    return result if result > 0 else None


def normalize_filename(filename: str) -> str:
    """
    Input:  0033_บทที่หนึ่งร้อยสามสิบสอง_กล้าที่จะทำกับกล้าที่จะไม่ทำ.md
    Output: 0033_บทที่ 132_กล้าที่จะทำกับกล้าที่จะไม่ทำ.md
    """
    # แยก: running_number _ ส่วนที่เหลือ
    m = re.match(r'^(\d{4})_(.*)', filename)
    if not m:
        return filename  # รูปแบบไม่ตรง → คืนเดิม

    running = m.group(1)   # "0033"
    rest    = m.group(2)   # "บทที่หนึ่งร้อยสามสิบสอง_กล้าที่จะทำกับกล้าที่จะไม่ทำ.md"

    # หา prefix (บทที่/ตอนที่) + [_\s]? + ตัวเลขไทย/อารบิก + ส่วนที่เหลือ
    m2 = re.match(r'^(บทที่|ตอนที่)[_\s]?([^_]+)(_.*)', rest)
    if not m2:
        return filename  # ไม่มี prefix → คืนเดิม

    prefix     = m2.group(1)   # "บทที่"
    thai_num   = m2.group(2)   # "หนึ่งร้อยสามสิบสอง"
    remainder  = m2.group(3)   # "_กล้าที่จะทำกับกล้าที่จะไม่ทำ.md"

    # ถ้าเป็นตัวเลขอารบิกอยู่แล้ว ไม่ต้องแปลง
    if re.match(r'^\d+$', thai_num.strip()):
        return f"{running}_{prefix} {thai_num.strip()}{remainder}"

    num = thai_to_int(thai_num.strip())
    if num is None:
        return filename  # แปลงไม่ได้ → คืนเดิม

    return f"{running}_{prefix} {num}{remainder}"


def rename_files(folder: str, dry_run: bool = True):
    if not os.path.exists(folder):
        return
    files = sorted(f for f in os.listdir(folder) if f.lower().endswith(('.md', '.mp3', '.mp4')))

    for filename in files:
        new_name = normalize_filename(filename)
        if new_name == filename:
            continue  # ไม่มีอะไรเปลี่ยน

        old_path = os.path.join(folder, filename)
        new_path = os.path.join(folder, new_name)

        if dry_run:
            try:
                print(f"  {filename}\n→ {new_name}\n")
            except UnicodeEncodeError:
                pass
        else:
            try:
                os.rename(old_path, new_path)
                try:
                    print(f"[*] Renamed: {filename} -> {new_name}")
                except UnicodeEncodeError:
                    print(f"[*] Renamed: (unicode filename hidden due to console encoding limits)")
            except Exception as e:
                try:
                    print(f"[!] Error renaming {filename} to {new_name}: {e}")
                except UnicodeEncodeError:
                    print(f"[!] Error renaming a file due to console encoding: {type(e).__name__}")

def get_gemini_api_key():
    """
    Retrieves the Gemini API key from environment variables.
    """
    return os.getenv("GEMINI_API_KEY")

def call_gemini_api(system_prompt: str, prompt_text: str, api_key: str, model="gemini-2.5-flash") -> str:
    """
    Makes a direct HTTP POST request to the Gemini API using urllib.
    Avoids heavy external dependencies like google-genai or cryptography.
    """
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    # Construct the JSON payload
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [{
            "parts": [{"text": prompt_text}]
        }]
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    
    try:
        opener = get_api_opener()
        with opener.open(req) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            # Extract generated text
            if "candidates" in res_json:
                text = res_json["candidates"][0]["content"]["parts"][0]["text"]
                return text
            elif "error" in res_json:
                err_msg = res_json["error"].get("message", "Unknown error")
                err_status = res_json["error"].get("status", "Unknown status")
                raise RuntimeError(f"Gemini API returned error: {err_status} - {err_msg}")
            else:
                # E.g. prompt was blocked by safety settings or other reasons
                raise RuntimeError(f"Unexpected API response structure (possibly blocked): {res_json}")
    except urllib.error.HTTPError as e:
        error_info = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_info)
            if "error" in err_json:
                err_msg = err_json["error"].get("message", "Unknown error")
                err_status = err_json["error"].get("status", "Unknown status")
                raise RuntimeError(f"Gemini API HTTP Error {e.code}: {err_status} - {err_msg}")
        except Exception:
            pass
        raise RuntimeError(f"Gemini API HTTP Error {e.code}: {error_info}")
    except Exception as e:
        raise RuntimeError(f"Error calling Gemini API: {e}")

def call_deepseek_api(system_prompt: str, prompt_text: str, api_key: str, model="deepseek-v4-flash") -> tuple:
    """
    Makes a direct HTTP POST request to the DeepSeek API using urllib.
    Avoids heavy external dependencies.
    """
    url = "https://api.deepseek.com/chat/completions"
    
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt_text}
        ],
        "stream": False
    }
    
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        },
        method="POST"
    )
    
    try:
        opener = get_api_opener()
        with opener.open(req) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            # Extract generated text from chat completion structure
            if "choices" in res_json and len(res_json["choices"]) > 0:
                text = res_json["choices"][0]["message"]["content"]
                usage = res_json.get("usage", {})
                return text, usage
            elif "error" in res_json:
                err_msg = res_json["error"].get("message", "Unknown error")
                err_type = res_json["error"].get("type", "Unknown type")
                raise RuntimeError(f"DeepSeek API returned error: {err_type} - {err_msg}")
            else:
                raise RuntimeError(f"Unexpected DeepSeek API response structure: {res_json}")
    except urllib.error.HTTPError as e:
        error_info = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_info)
            if "error" in err_json:
                err_msg = err_json["error"].get("message", "Unknown error")
                raise RuntimeError(f"DeepSeek API HTTP Error {e.code}: {err_msg}")
        except Exception:
            pass
        raise RuntimeError(f"DeepSeek API HTTP Error {e.code}: {error_info}")
    except Exception as e:
        raise RuntimeError(f"Error calling DeepSeek API: {e}")

def parse_gemini_response(response_text: str):
    """
    Parses the structured response from Gemini/DeepSeek to extract filename, content, and glossary.
    """
    glossary = []
    content_text = response_text
    
    # Extract GLOSSARY block if present (supporting optional markdown code blocks)
    glossary_match = re.search(r"GLOSSARY:\s*(?:```json\s*)?(\[.*?\])(?:\s*```)?", response_text, re.DOTALL | re.IGNORECASE)
    if glossary_match:
        try:
            glossary = json.loads(glossary_match.group(1).strip())
            # Strip the GLOSSARY block from the content_text to avoid it being in the main output content
            content_text = response_text[:glossary_match.start()].strip()
        except Exception as e:
            print(f"[!] Warning: Could not parse glossary JSON: {e}")
            
    # Parse lines to identify FILENAME/ชื่อไฟล์ and CONTENT/เนื้อหา dynamically
    filename = None
    content_lines = []
    
    filename_pattern = r"^\s*(?:\*\*?|)?(?:FILENAME|ชื่อไฟล์|ชื่อตอน|FILE_NAME|FILE\s+NAME)(?:\*\*?|)?\s*[:：]\s*(.*)"
    content_header_pattern = r"^\s*(?:\*\*?|)?(?:CONTENT|เนื้อหา|บทแปล)(?:\*\*?|)?\s*[:：]?\s*(?:\*\*?|)?\s*$"
    
    filename_regex = re.compile(filename_pattern, re.IGNORECASE)
    content_header_regex = re.compile(content_header_pattern, re.IGNORECASE)
    
    lines = content_text.split("\n")
    for line in lines:
        fn_match = filename_regex.match(line)
        if fn_match and filename is None:
            filename = fn_match.group(1).strip().strip("*_` \t")
            continue
            
        if content_header_regex.match(line):
            continue
            
        content_lines.append(line)
        
    content = "\n".join(content_lines).strip()
    
    # Fallback: if filename wasn't found using tag, extract from the first Markdown heading (# Heading)
    # or the first non-empty short line in the content.
    if not filename:
        h_match = re.search(r"^\s*#+\s*(.*)", content, re.MULTILINE)
        if h_match:
            filename = h_match.group(1).strip().strip("*_` \t")
        else:
            for line in content.split("\n"):
                line_strip = line.strip().strip("*_` \t")
                if line_strip:
                    if len(line_strip) < 100:
                        filename = line_strip
                    break
    return filename, content, glossary

def collapse_repeating_punctuation(text: str) -> str:
    # Collapse 4 or more dots to three dots '...'
    text = re.sub(r'\.{4,}', '...', text)
    # Collapse 2 or more Chinese ellipses '……' to three dots '...'
    text = re.sub(r'…{2,}', '...', text)
    # Collapse 3 or more dashes '---' to three dots '...'
    text = re.sub(r'-{3,}', '...', text)
    # Collapse 2 or more Chinese em-dashes '——' to three dots '...'
    text = re.sub(r'—{2,}', '...', text)
    # Collapse 3 or more underscores '___' to three dots '...'
    text = re.sub(r'_{3,}', '...', text)
    # Collapse 3 or more asterisks '***' to three dots '...'
    text = re.sub(r'\*{3,}', '...', text)
    return text

def clean_translated_content(content: str) -> str:
    """
    Cleans special characters and noise from the translated content.
    """
    # 0. Strip any trailing glossary JSON array at the end of the file
    content = re.sub(r'(?:GLOSSARY:\s*)?\[\s*\{\s*"source":.*\}\s*\]\s*$', '', content.strip(), flags=re.DOTALL)
    content = re.sub(r'GLOSSARY:\s*$', '', content, flags=re.MULTILINE | re.IGNORECASE)

    # 1. Remove "# CONTENT:" or "CONTENT:" or "# CONTENT" at the start of a line
    content = re.sub(r'^\s*#?\s*CONTENT\s*:\s*\n?', '', content, flags=re.IGNORECASE | re.MULTILINE)
    content = re.sub(r'^\s*#?\s*CONTENT\s*$', '', content, flags=re.IGNORECASE | re.MULTILINE)
    
    # 2. Remove "# FILENAME:" or similar if present at the start of a line
    content = re.sub(r'^\s*#?\s*FILENAME\s*:\s*.*$', '', content, flags=re.IGNORECASE | re.MULTILINE)
    
    # 3. Strip '#' header markdown from the beginning of lines (e.g. "# บทที่ 1" -> "บทที่ 1")
    content = re.sub(r'^#+\s+(.*)$', r'\1', content, flags=re.MULTILINE)
    
    # 4. Remove standalone '#' or '##' lines and trailing hashes
    content = re.sub(r'^\s*#+\s*$', '', content, flags=re.MULTILINE)
    
    # 5. Collapse repeating punctuation
    content = collapse_repeating_punctuation(content)
    
    # 6. Remove parenthesized Chinese characters (e.g. 'เหลียวเฉิง (聊城)' -> 'เหลียวเฉิง')
    content = re.sub(r'\s*\([\u4e00-\u9fff]+\)', '', content)
    
    return content.strip()

def has_chinese(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))

def translate_line_chinese_to_thai(line: str, api_key: str) -> str:
    """
    Translates untranslated Chinese characters in a sentence using Gemini 2.5 Flash.
    """
    system_prompt = (
        "You are an expert Chinese-to-Thai translator. The input sentence is in Thai but contains some untranslated Chinese terms or phrases. "
        "Translate those Chinese terms into natural, fluent Thai in the context of the sentence. "
        "Return ONLY the translated Thai sentence. Do not include any explanations, notes, prefix, or markdown."
    )
    try:
        translated = call_gemini_api(system_prompt, line.strip(), api_key, model="gemini-2.5-flash")
        return translated.strip()
    except Exception as e:
        print(f"[!] Warning: Could not translate remaining Chinese in line: {e}")
        return line

def translate_lines_batch(lines_to_translate: list, api_key: str) -> list:
    if not lines_to_translate:
        return []
        
    prompt_text = "Translate the following sentences (which contain some untranslated Chinese words) into natural, fluent Thai. Preserve the original meaning. Return the translations as a JSON array of strings in the exact order of the input sentences.\n\nInput sentences:\n"
    for i, line in enumerate(lines_to_translate):
        prompt_text += f"{i+1}. {line.strip()}\n"
        
    system_prompt = (
        "You are an expert Chinese-to-Thai translator. "
        "Translate the input sentences into natural Thai, correcting any Chinese words into Thai. "
        "Return ONLY a JSON array of strings containing the translated sentences in order, without any markdown formatting or extra text. E.g. [\"sentence1\", \"sentence2\"]"
    )
    
    try:
        response_text = call_gemini_api(system_prompt, prompt_text, api_key, model="gemini-2.5-flash")
        match = re.search(r'(\[.*\])', response_text, re.DOTALL)
        if match:
            translated_list = json.loads(match.group(1).strip())
            if len(translated_list) == len(lines_to_translate):
                print(f"  [✓] Batch translation succeeded for {len(lines_to_translate)} lines.")
                return [s.strip() for s in translated_list]
            else:
                print(f"  [!] Warning: Batch returned {len(translated_list)} lines, expected {len(lines_to_translate)}. Falling back to line-by-line.")
        else:
            print("  [!] Warning: Could not find JSON array in response. Falling back to line-by-line.")
    except Exception as e:
        print(f"  [!] Batch translation error: {e}. Falling back to line-by-line.")
        
    # Fallback to line-by-line
    results = []
    for line in lines_to_translate:
        print(f"    [Line-by-line] translating: {line.strip()}")
        results.append(translate_line_chinese_to_thai(line, api_key))
    return results

def translate_remaining_chinese_globally(translate_dir: str, api_key: str):
    """
    Scans all translated files in translate_dir, extracts lines with Chinese,
    batch-translates them, and replaces them back in files.
    """
    if not os.path.exists(translate_dir):
        return
        
    files = sorted([os.path.join(translate_dir, f) for f in os.listdir(translate_dir) if f.endswith(".md")])
    
    # Map of: line_text -> list of (filepath, line_index)
    lines_map = {}
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        lines = content.split("\n")
        for idx, line in enumerate(lines):
            # Ignore lines that look like JSON objects/arrays or glossary mapping
            if '"source":' in line or '"target":' in line or line.strip().startswith('[') or line.strip().startswith('{') or line.strip().startswith(']'):
                continue
            has_unparenthesized_chinese = False
            if has_chinese(line):
                stripped_line = re.sub(r'\s*\([\u4e00-\u9fff]+\)', '', line)
                if has_chinese(stripped_line):
                    has_unparenthesized_chinese = True
            
            if has_unparenthesized_chinese:
                line_val = line.strip()
                if line_val:
                    if line_val not in lines_map:
                        lines_map[line_val] = []
                    lines_map[line_val].append((filepath, idx))
                    
    if not lines_map:
        print("[*] No remaining Chinese characters found in any files.")
        return
        
    unique_lines = list(lines_map.keys())
    print(f"[*] Found {len(unique_lines)} unique lines containing Chinese characters across all files.")
    
    # Batch translate unique lines in chunks of 30
    batch_size = 30
    translations = {}
    
    for i in range(0, len(unique_lines), batch_size):
        chunk = unique_lines[i:i+batch_size]
        print(f"[*] Translating batch {i//batch_size + 1}/{(len(unique_lines)-1)//batch_size + 1} (Size: {len(chunk)} lines)...")
        translated_chunk = translate_lines_batch(chunk, api_key)
        for orig, trans in zip(chunk, translated_chunk):
            translations[orig] = trans
            
    # Apply translations back to the files
    file_updates = {}
    for orig_line, occurrences in lines_map.items():
        translated_line = translations.get(orig_line, orig_line)
        for filepath, line_idx in occurrences:
            if filepath not in file_updates:
                file_updates[filepath] = {}
            file_updates[filepath][line_idx] = translated_line
            
    for filepath, updates in file_updates.items():
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        for line_idx, translated_line in updates.items():
            lines[line_idx] = translated_line
        new_content = "\n".join(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"[✓] Applied translations and saved: {os.path.basename(filepath)}")

def parse_json_array(text: str):
    """
    Extracts and parses a JSON array from response text, supporting markdown blocks.
    """
    match = re.search(r"(\[.*?\])", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1).strip())
        except Exception as e:
            print(f"[!] Warning: Could not parse JSON array: {e}")
    return []

def get_relevant_glossary(content, complete_glossary, max_terms=500):
    """เลือกเฉพาะคำศัพท์ที่ปรากฏในเนื้อหา"""
    relevant = {}
    for term, trans in complete_glossary.items():
        if term in content:
            relevant[term] = trans
            if len(relevant) >= max_terms:
                break
    return relevant

def partition_files(files, batch_size=10, merge_threshold=4):
    """
    Partitions files into batches of batch_size.
    If the final batch size is <= merge_threshold, it is merged into the previous batch.
    For example, with 44 files and batch_size=10, merge_threshold=4,
    it returns batches of size 10, 10, 10, 14.
    """
    N = len(files)
    if N <= batch_size + merge_threshold:
        return [files]
    batches = []
    i = 0
    while i < N:
        remaining = N - i
        if remaining <= batch_size + merge_threshold:
            batches.append(files[i:])
            break
        else:
            batches.append(files[i : i + batch_size])
            i += batch_size
    return batches

def run_translation(model=None, ai="gemini", output_dir=".", proxy=None):
    """
    Scans the specified folder for untranslated scraped markdown files,
    translates them using Gemini or DeepSeek, saves the translations, and moves the originals to done/
    Retries any failed chapters at the end of the pass before proceeding.
    """
    import time
    start_time = time.time()
    global _api_opener
    import ssl
    ssl_context = ssl._create_unverified_context()
    
    # Configure global proxy for urllib requests if proxy is enabled
    if proxy and proxy.lower() == "true":
        proxy_support = urllib.request.ProxyHandler({
            'http': 'http://siph-mmswg01.siph.com:8080',
            'https': 'http://siph-mmswg01.siph.com:8080'
        })
        _api_opener = urllib.request.build_opener(
            proxy_support,
            urllib.request.HTTPSHandler(context=ssl_context)
        )
        urllib.request.install_opener(_api_opener)
        print("[*] Proxy enabled for API requests: http://siph-mmswg01.siph.com:8080")
    else:
        _api_opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl_context)
        )
        urllib.request.install_opener(_api_opener)
    
    # Ensure output directory exists
    if output_dir and output_dir != ".":
        os.makedirs(output_dir, exist_ok=True)
        print(f"[*] Work directory set to: {output_dir}")
        
    # Resolve API provider and key
    if ai == "gemini":
        api_key = get_gemini_api_key()
        if not api_key or "your_gemini_api_key" in api_key:
            print("[!] Error: GEMINI_API_KEY is not set in the .env file.")
            print("[*] Please open the '.env' file and add your Google AI Studio API key.")
            return
        if not model:
            model = "gemini-2.5-flash"
    elif ai == "deepseek":
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            print("[!] Error: DEEPSEEK_API_KEY is not set in the .env file.")
            print("[*] Please open the '.env' file and add your DEEPSEEK_API_KEY.")
            return
        if not model:
            model = "deepseek-v4-flash"
    else:
        print(f"[!] Error: Unsupported AI provider '{ai}'. Use 'gemini' or 'deepseek'.")
        return
        
    # Read system prompt from gemini.md in the current novel folder. 
    # If not present locally, check the script's directory for a global template to copy from.
    system_prompt_path = os.path.join(output_dir, "gemini.md")
    if not os.path.exists(system_prompt_path):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        global_template_path = os.path.join(script_dir, "gemini.md")
        if os.path.exists(global_template_path):
            print(f"[*] Copying global gemini.md from {global_template_path} to local novel directory...")
            shutil.copy(global_template_path, system_prompt_path)
        elif os.path.exists("gemini.md"):
            print(f"[*] Copying global gemini.md from current directory to local novel directory: {output_dir}...")
            shutil.copy("gemini.md", system_prompt_path)
        elif os.path.exists("../gemini.md"):
            print(f"[*] Copying global gemini.md from parent directory to local novel directory: {output_dir}...")
            shutil.copy("../gemini.md", system_prompt_path)
        else:
            print("[*] gemini.md not found. Creating default prompt template...")
            with open(system_prompt_path, "w", encoding="utf-8") as f:
                f.write(DEFAULT_SYSTEM_PROMPT)
            
    with open(system_prompt_path, "r", encoding="utf-8") as f:
        system_prompt = f.read().strip()
        
    # Load existing glossary if it exists
    glossary_path = os.path.join(output_dir, "glossary.json")
    glossary_dict = {}
    if os.path.exists(glossary_path):
        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                glossary_dict = json.load(f)
            print(f"[*] Loaded existing glossary with {len(glossary_dict)} terms from glossary.json.")
        except Exception as e:
            print(f"[!] Warning: Could not load glossary.json: {e}")
        
    # Create 'done' directory if it doesn't exist
    done_dir = os.path.join(output_dir, "done")
    if not os.path.exists(done_dir):
        os.makedirs(done_dir)
        print(f"[*] Created directory: {done_dir}/")
        
    # Create 'translate' directory if it doesn't exist
    translate_dir = os.path.join(output_dir, "translate")
    if not os.path.exists(translate_dir):
        os.makedirs(translate_dir)
        print(f"[*] Created directory: {translate_dir}/")
        
    # Auto-rename existing files to normalize chapter numbers to Arabic numerals
    print("[*] Normalizing existing translated files and audiobooks...")
    rename_files(translate_dir, dry_run=False)
    audiobook_dir = os.path.join(output_dir, "Audiobook")
    if os.path.exists(audiobook_dir):
        rename_files(audiobook_dir, dry_run=False)
        
    # --- PHASE 0: PREPARE ---
    # 1. Read glossary.json -> complete_glossary (copy all)
    glossary_path = os.path.join(output_dir, "glossary.json")
    complete_glossary = {}
    if os.path.exists(glossary_path):
        try:
            with open(glossary_path, "r", encoding="utf-8") as f:
                complete_glossary = json.load(f)
            print(f"[*] PHASE 0: Loaded existing glossary with {len(complete_glossary)} terms from glossary.json.")
        except Exception as e:
            print(f"[!] Warning: Could not load glossary.json: {e}")
            if glossary_dict:
                complete_glossary = glossary_dict.copy()
    elif glossary_dict:
        complete_glossary = glossary_dict.copy()
        print(f"[*] PHASE 0: Initialized complete glossary from memory glossary_dict with {len(complete_glossary)} terms.")

    # 2. Find all untranslated source markdown files (scraped files) to translate
    all_files = glob.glob(os.path.join(output_dir, "*.md"))
    scraped_files = []
    for f in all_files:
        basename = os.path.basename(f)
        if re.match(r"^\d{4}_", basename) and basename != "gemini.md":
            scraped_files.append(f)
    scraped_files.sort()

    # 3. Combine content of all files to be translated to filter terms
    combined_all_content = ""
    for filepath in scraped_files:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                combined_all_content += f.read() + "\n"
        except Exception as e:
            print(f"[!] Error reading {filepath} to find matching glossary: {e}")

    # 4. Filter complete_glossary with the combined content of all files to translate to initialize active_glossary
    active_glossary = get_relevant_glossary(combined_all_content, complete_glossary, max_terms=500)
    print(f"[*] PHASE 0: Filtered relevant glossary. Found {len(active_glossary)} matching terms from {len(complete_glossary)} total terms.")

    # --- PHASE 1: EXTRACT GLOSSARY ---
    state_path = os.path.join(output_dir, "extraction_state.json")
    processed_files = []
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                processed_files = state_data.get("processed_files", [])
            print(f"[*] PHASE 1: Loaded extraction progress: {len(processed_files)} files already processed.")
        except Exception as e:
            print(f"[!] Warning: Could not load extraction_state.json: {e}")

    # Determine files to extract terms from
    files_to_extract = [f for f in scraped_files if f not in processed_files]
    if files_to_extract:
        print(f"[*] PHASE 1: Extracting glossary terms from {len(files_to_extract)} files...")
        
        extraction_batches = partition_files(files_to_extract, batch_size=10, merge_threshold=4)
        for eb_idx, e_batch in enumerate(extraction_batches):
            print(f"\n[*] PHASE 1: Processing extraction batch {eb_idx + 1}/{len(extraction_batches)} (Size: {len(e_batch)} files)...")
            combined_text = ""
            for filepath in e_batch:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        combined_text += f.read() + "\n"
                except Exception as e:
                    print(f"[!] Error reading {filepath} for glossary extraction: {e}")

            # Send extract prompt explicitly prompting for terminology extraction (not translation)
            user_prompt_extract = f"[MODE: EXTRACT]\n{combined_text}"
            
            raw_ext = None
            
            # 1. Try DeepSeek first (if key is configured)
            ds_key = os.getenv("DEEPSEEK_API_KEY")
            if ds_key:
                ds_model = model if ai == "deepseek" else "deepseek-v4-flash"
                print(f"[*] Trying DeepSeek ({ds_model}) for glossary extraction ({len(user_prompt_extract)} chars)...")
                try:
                    raw_ext, _ = call_deepseek_api(system_prompt, user_prompt_extract, ds_key, ds_model)
                except Exception as de:
                    print(f"[!] DeepSeek extraction failed: {de}")
            
            # 2. Fallback to Gemini if DeepSeek was not used or failed
            if raw_ext is None:
                gemini_key = get_gemini_api_key()
                if gemini_key and "your_gemini_api_key" not in gemini_key:
                    print(f"[*] Falling back to Gemini (gemini-2.5-flash) for glossary extraction ({len(user_prompt_extract)} chars)...")
                    try:
                        raw_ext = call_gemini_api(system_prompt, user_prompt_extract, gemini_key, "gemini-2.5-flash")
                    except Exception as ge:
                        print(f"[!] Gemini extraction failed: {ge}")
                else:
                    print("[!] GEMINI_API_KEY not set in .env for fallback.")

            if raw_ext is None:
                print("[!] Error: Glossary extraction failed on both Gemini and DeepSeek.")
                print("[*] Progress saved. You can rerun the script to resume.")
                return

            try:
                extracted_list = parse_json_array(raw_ext)
                print(f"[✓] Extracted {len(extracted_list)} glossary terms from this batch.")

                added_terms = 0
                for item in extracted_list:
                    zh = item.get("source", "").strip()
                    th = item.get("target", "").strip()
                    if zh and th:
                        # Merge newly extracted terms into complete_glossary
                        if complete_glossary.get(zh) != th:
                            complete_glossary[zh] = th
                            added_terms += 1
                        # Also merge into active_glossary (since they are in the current files)
                        active_glossary[zh] = th

                processed_files.extend(e_batch)
                
                # Save progress incrementally to glossary.json
                with open(glossary_path, "w", encoding="utf-8") as f:
                    json.dump(complete_glossary, f, ensure_ascii=False, indent=2)
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump({"processed_files": processed_files}, f, ensure_ascii=False, indent=2)
                print(f"[✓] Saved PHASE 1 progress. Total terms in complete glossary: {len(complete_glossary)}.")

            except Exception as e:
                print(f"[!] Error extracting glossary: {e}")
                print("[*] Progress saved. You can rerun the script to resume.")
                return

    # --- PHASE 2: TRANSLATE ---
    # Re-filter complete_glossary against combined_all_content to include newly extracted terms
    active_glossary = get_relevant_glossary(combined_all_content, complete_glossary, max_terms=500)
    
    # Build unified system prompt containing guidelines and active glossary (static throughout Pass 2 to achieve 100% cache hit)
    if active_glossary:
        print(f"[*] PHASE 2: Found {len(active_glossary)} matching glossary terms for Pass 2 (from all files in run).")
        glossary_text = "\n".join([f"- {k} -> {v}" for k, v in sorted(active_glossary.items())])
        unified_system_prompt = f"""{system_prompt}

# GLOSSARY ที่ต้องใช้ (บังคับ):
{glossary_text}

คำเตือน: ห้ามเปลี่ยนคำแปลเหล่านี้เด็ดขาด!"""
    else:
        unified_system_prompt = system_prompt

    total_prompt_tokens = 0
    total_cache_hit_tokens = 0
    max_passes = 5
    pass_count = 1

    # Keep a collection of newly discovered glossary terms during translation
    newly_translated_glossary = {}

    while True:
        # Find all untranslated source markdown files (files starting with a 4-digit number, e.g. 0001_title.md)
        all_files = glob.glob(os.path.join(output_dir, "*.md"))
        scraped_files = []
        for f in all_files:
            basename = os.path.basename(f)
            if re.match(r"^\d{4}_", basename) and basename != "gemini.md":
                scraped_files.append(f)

        if not scraped_files:
            if pass_count == 1:
                print("[-] No untranslated scraped markdown files found (files matching pattern '000X_*.md').")
            else:
                print("\n[✓] All chapters successfully translated!")
            break

        if pass_count > max_passes:
            print(f"\n[!] Maximum retry passes ({max_passes}) reached. Some files failed to translate:")
            for f in scraped_files:
                print(f"  - {os.path.basename(f)}")
            break

        scraped_files.sort()
        total_files = len(scraped_files)

        if pass_count > 1:
            print(f"\n[!] Pass {pass_count}: Retrying {total_files} failed translations...")
            time.sleep(5)
        else:
            print(f"[*] Found {total_files} files to translate in Pass 2.")

        failed_count = 0

        # Translate all files individually using the static unified_system_prompt
        for idx, filepath in enumerate(scraped_files):
            filename = os.path.basename(filepath)
            progress = draw_progress_bar(idx + 1, total_files)
            print(f"\n[+] Translating {progress}: {filename}...")

            # Get running number prefix (e.g. '0001')
            match = re.match(r"^(\d{4})_", filename)
            running_prefix = match.group(1) if match else "0000"

            try:
                # Read file content
                with open(filepath, "r", encoding="utf-8") as f:
                    content_to_translate = f.read()

                user_prompt_translate = f"[MODE: TRANSLATE]\n{content_to_translate}"
                print(f"[*] Sending content to {ai} ({len(user_prompt_translate)} chars)...")
                
                if ai == "deepseek":
                    raw_response, usage = call_deepseek_api(unified_system_prompt, user_prompt_translate, api_key, model)
                    # Show cache hit rate if available
                    if usage and 'prompt_tokens' in usage and usage['prompt_tokens'] > 0:
                        cache_hit_tokens = usage.get('prompt_cache_hit_tokens', 0)
                        if cache_hit_tokens == 0 and 'prompt_tokens_details' in usage:
                            cache_hit_tokens = usage['prompt_tokens_details'].get('cached_tokens', 0)
                        
                        hit_rate = cache_hit_tokens / usage['prompt_tokens']
                        print(f"[*] Cache Hit Rate: {hit_rate:.1%} ({cache_hit_tokens}/{usage['prompt_tokens']} tokens)")
                        
                        total_prompt_tokens += usage['prompt_tokens']
                        total_cache_hit_tokens += cache_hit_tokens
                else:
                    # Gemini
                    raw_response = call_gemini_api(unified_system_prompt, user_prompt_translate, api_key, model)

                # Parse response
                translated_title, translated_content, new_glossary = parse_gemini_response(raw_response)

                # Collect new glossary terms returned by LLM and save incrementally
                if new_glossary:
                    print(f"[*] Found {len(new_glossary)} new terms in LLM translation response.")
                    updated_glossary = False
                    for item in new_glossary:
                        zh = item.get("source", "").strip()
                        th = item.get("target", "").strip()
                        if zh and th:
                            newly_translated_glossary[zh] = th
                            if complete_glossary.get(zh) != th:
                                complete_glossary[zh] = th
                                updated_glossary = True
                    if updated_glossary:
                        try:
                            with open(glossary_path, "w", encoding="utf-8") as f:
                                json.dump(complete_glossary, f, ensure_ascii=False, indent=2)
                            print(f"[✓] Incrementally saved new terms to glossary.json")
                        except Exception as e:
                            print(f"[!] Warning: Could not save glossary.json incrementally: {e}")

                # Clean special characters first
                translated_content = clean_translated_content(translated_content)

                # Decide on translated filename
                if not translated_title:
                    orig_text = filename.replace(f"{running_prefix}_", "", 1).replace(".md", "")
                    translated_title = f"translated_{orig_text}"

                sanitized_title = sanitize_filename(translated_title)
                new_filename = f"{running_prefix}_{sanitized_title}.md"
                new_filename = normalize_filename(new_filename)
                new_filepath = os.path.join(translate_dir, new_filename)

                # Save translated file directly to translate/
                with open(new_filepath, "w", encoding="utf-8") as f:
                    f.write(translated_content)

                print(f"[✓] Saved translation: translate/{new_filename}")

                # Move original file to done/
                dest_path = os.path.join(done_dir, filename)
                shutil.move(filepath, dest_path)
                print(f"[*] Moved original file to: {dest_path}")

            except Exception as e:
                print(f"[!] Error translating {filename}: {e}")
                print("[*] Skipping this file for now...")
                failed_count += 1
                continue

        if failed_count == 0:
            break

        pass_count += 1

    # Merge newly translated terms into complete_glossary at the end of translation
    if newly_translated_glossary:
        print(f"\n[*] PHASE 2: Merging {len(newly_translated_glossary)} new terms from translation into complete glossary...")
        for zh, th in newly_translated_glossary.items():
            complete_glossary[zh] = th

    if ai == "deepseek" and total_prompt_tokens > 0:
        overall_hit_rate = total_cache_hit_tokens / total_prompt_tokens
        print(f"\n[✓] Overall Cache Hit Rate: {overall_hit_rate:.1%} ({total_cache_hit_tokens}/{total_prompt_tokens} tokens)")

    # --- PHASE 3: FINALIZE ---
    # Global scanning and batch translation of any remaining Chinese characters
    g_key = get_gemini_api_key()
    if g_key and "your_gemini_api_key" not in g_key:
        print("[*] PHASE 3: Scanning and batch-translating remaining Chinese characters globally...")
        translate_remaining_chinese_globally(translate_dir, g_key)

    # Auto-rename existing files to normalize chapter numbers to Arabic numerals
    print("[*] PHASE 3: Normalizing translated files and audiobooks...")
    rename_files(translate_dir, dry_run=False)
    audiobook_dir = os.path.join(output_dir, "Audiobook")
    if os.path.exists(audiobook_dir):
        rename_files(audiobook_dir, dry_run=False)

    print(f"\n[*] PHASE 3: Saving final complete glossary (superset) with {len(complete_glossary)} terms to glossary.json...")
    try:
        with open(glossary_path, "w", encoding="utf-8") as f:
            json.dump(complete_glossary, f, ensure_ascii=False, indent=2)
        print("[✓] Save complete.")
    except Exception as e:
        print(f"[!] Error saving final glossary.json: {e}")

    # Clean up state_path upon successful completion
    if os.path.exists(state_path):
        try:
            os.remove(state_path)
            print(f"[*] Cleared Pass 1 progress state: {state_path}")
        except Exception as e:
            print(f"[!] Error clearing {state_path}: {e}")

    elapsed_time = time.time() - start_time
    hours, rem = divmod(elapsed_time, 3600)
    minutes, seconds = divmod(rem, 60)
    print(f"\n[*] Total time elapsed: {int(hours)}h {int(minutes)}m {seconds:.2f}s")
    print("\n[*] Translation stage completed.")


