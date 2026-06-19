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

Provide the translation in the exact format shown below, with no introductory or concluding remarks:

FILENAME: <translated_chapter_title_suitable_for_filename_without_extension>
CONTENT:
<translated_markdown_content>
"""

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
        import ssl
        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ssl_context) as response:
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
        import ssl
        ssl_context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ssl_context) as response:
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
    Parses the structured response from Gemini to extract filename, content, and glossary.
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
            
    # Look for FILENAME: and CONTENT: tags using regex (case-insensitive)
    match = re.search(r"FILENAME:\s*(.*?)\n+CONTENT:\s*(.*)", content_text, re.DOTALL | re.IGNORECASE)
    
    if match:
        filename = match.group(1).strip()
        content = match.group(2).strip()
        return filename, content, glossary
    else:
        # Fallback if model didn't follow the layout exactly
        print("[!] Warning: Could not parse response using standard template. Using fallback parser.")
        # Check if "FILENAME:" is present at all
        fn_match = re.search(r"FILENAME:\s*(.*)", content_text, re.IGNORECASE)
        if fn_match:
            # Split by lines
            lines = content_text.split("\n")
            filename = lines[0].replace("FILENAME:", "", 1).strip()
            # Content is the rest of the lines (excluding FILENAME: line, and CONTENT: if present)
            rest_lines = []
            skip_header = True
            for line in lines[1:]:
                if "CONTENT:" in line.upper() and skip_header:
                    skip_header = False
                    continue
                rest_lines.append(line)
            content = "\n".join(rest_lines).strip()
            return filename, content, glossary
        else:
            return None, content_text.strip(), glossary

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

def get_relevant_glossary(content, complete_glossary, max_terms=100):
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
    
    # Configure global proxy for urllib requests if proxy is enabled
    if proxy and proxy.lower() == "true":
        proxy_support = urllib.request.ProxyHandler({
            'http': 'http://siph-mmswg01.siph.com:8080',
            'https': 'http://siph-mmswg01.siph.com:8080'
        })
        opener = urllib.request.build_opener(proxy_support)
        urllib.request.install_opener(opener)
        print("[*] Proxy enabled for API requests: http://siph-mmswg01.siph.com:8080")
    
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
        
    # Retry loop configuration
    max_passes = 5
    pass_count = 1
    
    # Find all untranslated source markdown files initially
    all_files = glob.glob(os.path.join(output_dir, "*.md"))
    scraped_files = []
    for f in all_files:
        basename = os.path.basename(f)
        if re.match(r"^\d{4}_", basename) and basename != "gemini.md":
            scraped_files.append(f)
    scraped_files.sort()

    # Pass 1: Glossary Extraction
    complete_glossary_path = os.path.join(output_dir, "complete_glossary.json")
    complete_glossary = {}
    if os.path.exists(complete_glossary_path):
        try:
            with open(complete_glossary_path, "r", encoding="utf-8") as f:
                complete_glossary = json.load(f)
            print(f"[*] Loaded existing complete glossary with {len(complete_glossary)} terms.")
        except Exception as e:
            print(f"[!] Warning: Could not load complete_glossary.json: {e}")
    elif glossary_dict:
        complete_glossary = glossary_dict.copy()
        print(f"[*] Initialized complete glossary from glossary.json with {len(complete_glossary)} terms.")

    state_path = os.path.join(output_dir, "extraction_state.json")
    processed_files = []
    if os.path.exists(state_path):
        try:
            with open(state_path, "r", encoding="utf-8") as f:
                state_data = json.load(f)
                processed_files = state_data.get("processed_files", [])
            print(f"[*] Loaded Pass 1 progress: {len(processed_files)} files already processed.")
        except Exception as e:
            print(f"[!] Warning: Could not load extraction_state.json: {e}")

    # Determine files to extract terms from
    files_to_extract = [f for f in scraped_files if f not in processed_files]
    if files_to_extract:
        print(f"[*] Pass 1: Extracting glossary terms from {len(files_to_extract)} files...")
        
        extraction_batches = partition_files(files_to_extract, batch_size=10, merge_threshold=4)
        for eb_idx, e_batch in enumerate(extraction_batches):
            print(f"\n[*] Processing extraction batch {eb_idx + 1}/{len(extraction_batches)} (Size: {len(e_batch)} files)...")
            combined_text = ""
            for filepath in e_batch:
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        combined_text += f.read() + "\n"
                except Exception as e:
                    print(f"[!] Error reading {filepath} for glossary extraction: {e}")

            user_prompt_extract = f"[MODE: EXTRACT]\n{combined_text}"
            
            raw_ext = None
            
            # 1. Try Gemini first (if key is configured)
            gemini_key = get_gemini_api_key()
            if gemini_key and "your_gemini_api_key" not in gemini_key:
                print(f"[*] Trying Gemini (gemini-2.5-flash) for glossary extraction ({len(user_prompt_extract)} chars)...")
                try:
                    raw_ext = call_gemini_api(system_prompt, user_prompt_extract, gemini_key, "gemini-2.5-flash")
                except Exception as ge:
                    print(f"[!] Gemini extraction failed or token limit reached: {ge}")
            
            # 2. Fallback to DeepSeek if Gemini was not used or failed
            if raw_ext is None:
                ds_key = os.getenv("DEEPSEEK_API_KEY")
                if ds_key:
                    ds_model = model if ai == "deepseek" else "deepseek-v4-flash"
                    print(f"[*] Falling back to DeepSeek ({ds_model}) for glossary extraction ({len(user_prompt_extract)} chars)...")
                    try:
                        raw_ext, _ = call_deepseek_api(system_prompt, user_prompt_extract, ds_key, ds_model)
                    except Exception as de:
                        print(f"[!] DeepSeek extraction failed: {de}")
                else:
                    print("[!] DEEPSEEK_API_KEY not set in .env for fallback.")

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
                        if complete_glossary.get(zh) != th:
                            complete_glossary[zh] = th
                            added_terms += 1

                processed_files.extend(e_batch)
                
                # Save progress every batch of 10 files
                with open(complete_glossary_path, "w", encoding="utf-8") as f:
                    json.dump(complete_glossary, f, ensure_ascii=False, indent=2)
                with open(state_path, "w", encoding="utf-8") as f:
                    json.dump({"processed_files": processed_files}, f, ensure_ascii=False, indent=2)
                print(f"[✓] Saved Pass 1 progress. Total terms in complete glossary: {len(complete_glossary)}.")

            except Exception as e:
                print(f"[!] Error extracting glossary: {e}")
                print("[*] Progress saved. You can rerun the script to resume.")
                return

    # Pass 2: Unified Translation
    if os.path.exists(complete_glossary_path):
        try:
            with open(complete_glossary_path, "r", encoding="utf-8") as f:
                complete_glossary = json.load(f)
        except Exception as e:
            print(f"[!] Error loading complete_glossary.json: {e}")

    total_prompt_tokens = 0
    total_cache_hit_tokens = 0
    max_passes = 5
    pass_count = 1

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
                
            # Clean up state_path upon successful completion
            if os.path.exists(state_path):
                try:
                    os.remove(state_path)
                    print(f"[*] Cleared Pass 1 progress state: {state_path}")
                except Exception as e:
                    print(f"[!] Error clearing {state_path}: {e}")
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

        # 1. Combine all content of scraped_files to find matching glossary terms for the entire pass
        combined_all_content = ""
        for filepath in scraped_files:
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    combined_all_content += f.read() + "\n"
            except Exception as e:
                print(f"[!] Error reading {filepath} to find matching glossary: {e}")

        # 2. Get relevant glossary terms for this entire pass (capping at 500 terms)
        active_glossary = get_relevant_glossary(combined_all_content, complete_glossary, max_terms=500)
        
        # 3. Build unified system prompt containing guidelines and glossary (static throughout Pass 2 to achieve 100% cache hit)
        if active_glossary:
            print(f"[*] Found {len(active_glossary)} matching glossary terms for Pass 2 (from all files in run).")
            glossary_text = "\n".join([f"- {k} -> {v}" for k, v in sorted(active_glossary.items())])
            unified_system_prompt = f"""{system_prompt}

# GLOSSARY ที่ต้องใช้ (บังคับ):
{glossary_text}

คำเตือน: ห้ามเปลี่ยนคำแปลเหล่านี้เด็ดขาด!"""
        else:
            unified_system_prompt = system_prompt

        failed_count = 0

        # Translate all files individually
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

                # Decide on translated filename
                if not translated_title:
                    orig_text = filename.replace(f"{running_prefix}_", "", 1).replace(".md", "")
                    translated_title = f"translated_{orig_text}"

                sanitized_title = sanitize_filename(translated_title)
                new_filename = f"{running_prefix}_{sanitized_title}.md"
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

    if ai == "deepseek" and total_prompt_tokens > 0:
        overall_hit_rate = total_cache_hit_tokens / total_prompt_tokens
        print(f"\n[✓] Overall Cache Hit Rate: {overall_hit_rate:.1%} ({total_cache_hit_tokens}/{total_prompt_tokens} tokens)")

    print("\n[*] Translation stage completed.")


