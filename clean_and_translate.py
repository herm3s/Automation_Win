import os
import re
import json
import sys
import urllib.request
import urllib.error
from dotenv import load_dotenv

# Load env variables relative to the script location
script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(script_dir, ".env"))

def get_gemini_api_key():
    return os.getenv("GEMINI_API_KEY")

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

def call_gemini_api(system_prompt: str, prompt_text: str, api_key: str, model="gemini-2.5-flash") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "system_instruction": {
            "parts": [{"text": system_prompt}]
        },
        "contents": [{
            "parts": [{"text": prompt_text}]
        }],
        "safetySettings": [
            {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
            {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
        ]
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
            if "candidates" in res_json and len(res_json["candidates"]) > 0:
                candidate = res_json["candidates"][0]
                if "content" in candidate and "parts" in candidate["content"] and len(candidate["content"]["parts"]) > 0:
                    text = candidate["content"]["parts"][0].get("text", "")
                    return text
                else:
                    finish_reason = candidate.get("finishReason", "UNKNOWN")
                    raise RuntimeError(f"Gemini API returned no content. Finish reason: {finish_reason}. Full response: {res_json}")
            elif "error" in res_json:
                raise RuntimeError(res_json["error"].get("message", "Unknown error"))
            else:
                raise RuntimeError(f"Unexpected response structure: {res_json}")
    except urllib.error.HTTPError as e:
        error_info = e.read().decode("utf-8")
        try:
            err_json = json.loads(error_info)
            if "error" in err_json:
                err_msg = err_json["error"].get("message", "Unknown error")
                raise RuntimeError(f"Gemini API HTTP Error {e.code}: {err_msg}")
        except Exception:
            pass
        raise RuntimeError(f"Gemini API HTTP Error {e.code}: {error_info}")
    except Exception as e:
        raise RuntimeError(f"Gemini API Error: {e}")

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

def clean_special_chars(content: str) -> str:
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
    
    # 6. Remove parenthesized Chinese characters
    content = re.sub(r'\s*\([\u4e00-\u9fff]+\)', '', content)
    
    return content.strip()

def has_chinese(text: str) -> bool:
    return bool(re.search(r'[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]', text))

def translate_line(line: str, api_key: str) -> str:
    system_prompt = (
        "You are an expert Chinese-to-Thai translator. The input sentence is in Thai but contains some untranslated Chinese terms or phrases. "
        "Translate those Chinese terms into natural, fluent Thai in the context of the sentence. "
        "Return ONLY the translated Thai sentence. Do not include any explanations, notes, prefix, or markdown."
    )
    try:
        translated = call_gemini_api(system_prompt, line.strip(), api_key, model="gemini-2.5-flash")
        return translated.strip()
    except Exception as e:
        print(f"Error translating line: {e}")
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
        results.append(translate_line(line, api_key))
    return results

def sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = re.sub(r'\s+', "_", name)
    name = name.strip("_-.")
    return name

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
    m = re.match(r'^(\d{4})_(.*)', filename)
    if not m:
        return filename
    running = m.group(1)
    rest    = m.group(2)
    m2 = re.match(r'^(บทที่|ตอนที่)[_\s]?([^_]+)(_.*)', rest)
    if not m2:
        return filename
    prefix     = m2.group(1)
    thai_num   = m2.group(2)
    remainder  = m2.group(3)
    if re.match(r'^\d+$', thai_num.strip()):
        return f"{running}_{prefix} {thai_num.strip()}{remainder}"
    num = thai_to_int(thai_num.strip())
    if num is None:
        return filename
    return f"{running}_{prefix} {num}{remainder}"

def translate_chinese_filenames(folder: str, api_key: str):
    if not os.path.exists(folder):
        return
    files = sorted(os.listdir(folder))
    for filename in files:
        if has_chinese(filename):
            print(f"[*] Found Chinese in filename: {filename}")
            system_prompt = (
                "You are an expert Chinese-to-Thai translator. Translate the Chinese text in the filename to natural, clean Thai. "
                "The filename might contain chapter number and title, e.g. '第三百零九章：骑兵对决' -> 'บทที่ 309 การปะทะของทหารม้า'. "
                "Ensure chapter numbers are converted to Arabic numerals (e.g. 309). "
                "Replace spaces and colons with underscores to make it a safe filename. "
                "Return ONLY the translated Thai filename without file extension, e.g. 'บทที่_309_การปะทะของทหารม้า'. "
                "Do not include any notes, explanations, or quotes."
            )
            name_without_ext = os.path.splitext(filename)[0]
            clean_part = re.sub(r'^\d{4}_(?:translated_)?', '', name_without_ext)
            
            try:
                translated_part = call_gemini_api(system_prompt, clean_part, api_key, model="gemini-2.5-flash")
                translated_part = translated_part.strip().strip("'\"` \t")
                sanitized_part = sanitize_filename(translated_part)
                match = re.match(r'^(\d{4})_', filename)
                running_prefix = match.group(1) if match else "0000"
                ext = os.path.splitext(filename)[1]
                
                new_filename = f"{running_prefix}_{sanitized_part}{ext}"
                new_filename = normalize_filename(new_filename)
                
                old_path = os.path.join(folder, filename)
                new_path = os.path.join(folder, new_filename)
                
                os.rename(old_path, new_path)
                print(f"[✓] Translated filename: {filename} -> {new_filename}")
            except Exception as e:
                print(f"[!] Error translating filename {filename}: {e}")

def main():
    api_key = get_gemini_api_key()
    if not api_key:
        print("Error: GEMINI_API_KEY not found in .env file.")
        return
        
    novel_dir = "/Users/chettatosuanchit/Documents/ย้อนเวลาสู่หนานหมิงเป็นท่านอ๋อง"
    if len(sys.argv) > 1:
        novel_dir = sys.argv[1]
        
    translate_dir = os.path.join(novel_dir, "translate")
    if not os.path.exists(translate_dir):
        print(f"Error: translate directory does not exist: {translate_dir}")
        return
        
    files = sorted([os.path.join(translate_dir, f) for f in os.listdir(translate_dir) if f.endswith(".md")])
    
    # First pass: Clean special characters and parenthesized Chinese in all files
    print("[*] Phase 1: Performing punctuation and parenthesized Chinese cleanup on all files...")
    for filepath in files:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        cleaned_content = clean_special_chars(content)
        if cleaned_content != content:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(cleaned_content)
            print(f"  [✓] Cleaned: {os.path.basename(filepath)}")
            
    # Second pass: Collect unparenthesized Chinese lines globally
    print("\n[*] Phase 2: Scanning all files for remaining unparenthesized Chinese characters...")
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
        print("[*] No remaining Chinese characters found. Cleanup complete!")
        return
        
    unique_lines = list(lines_map.keys())
    print(f"[*] Found {len(unique_lines)} unique lines containing Chinese characters across all files.")
    
    # Translate unique lines in batches of 30
    batch_size = 30
    translations = {}
    for i in range(0, len(unique_lines), batch_size):
        chunk = unique_lines[i:i+batch_size]
        print(f"[*] Translating batch {i//batch_size + 1}/{(len(unique_lines)-1)//batch_size + 1} (Size: {len(chunk)} lines)...")
        translated_chunk = translate_lines_batch(chunk, api_key)
        for orig, trans in zip(chunk, translated_chunk):
            translations[orig] = trans
            
    # Apply translations back to files
    file_updates = {}
    for orig_line, occurrences in lines_map.items():
        translated_line = translations.get(orig_line, orig_line)
        for filepath, line_idx in occurrences:
            if filepath not in file_updates:
                file_updates[filepath] = {}
            file_updates[filepath][line_idx] = translated_line
            
    print("\n[*] Phase 3: Applying translated lines to files...")
    for filepath, updates in file_updates.items():
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.read().split("\n")
        for line_idx, translated_line in updates.items():
            lines[line_idx] = translated_line
        new_content = "\n".join(lines)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(new_content)
        print(f"  [✓] Updated: {os.path.basename(filepath)}")
        
    # Phase 4: Translate any remaining Chinese filenames
    print("\n[*] Phase 4: Checking and translating any remaining Chinese in filenames...")
    translate_chinese_filenames(translate_dir, api_key)
        
    print("\n[✓] Global batch translation and cleanup finished successfully!")

if __name__ == "__main__":
    main()
