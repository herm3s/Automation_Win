import os
import re
import glob
import shutil
import json
import urllib.request
import urllib.error
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

def call_deepseek_api(system_prompt: str, prompt_text: str, api_key: str, model="deepseek-v4-flash") -> str:
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
                return text
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
    
    # Extract GLOSSARY block if present
    glossary_match = re.search(r"GLOSSARY:\s*(\[.*?\])", response_text, re.DOTALL | re.IGNORECASE)
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

def run_translation(model=None, ai="gemini", output_dir="."):
    """
    Scans the specified folder for untranslated scraped markdown files,
    translates them using Gemini or DeepSeek, saves the translations, and moves the originals to done/
    Retries any failed chapters at the end of the pass before proceeding.
    """
    import time
    
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
    
    while True:
        # Find all source markdown files (files starting with a 4-digit number, e.g. 0001_title.md)
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
            # Wait 5 seconds to avoid hitting rate limits too quickly
            time.sleep(5)
        else:
            print(f"[*] Found {total_files} files to translate.")
            
        failed_count = 0
        
        if ai == "deepseek":
            # Partition files for DeepSeek batching
            batches = partition_files(scraped_files)
            processed_count = 0
            
            for batch_idx, batch in enumerate(batches):
                print(f"\n[*] Processing DeepSeek Batch {batch_idx + 1}/{len(batches)} (Size: {len(batch)} files)...")
                
                # 1. Combine content of all files in this batch to match against glossary
                combined_batch_text = ""
                for filepath in batch:
                    try:
                        with open(filepath, "r", encoding="utf-8") as f:
                            combined_batch_text += f.read() + "\n"
                    except Exception as e:
                        print(f"[!] Error reading {filepath} for batch glossary: {e}")
                
                # 2. Compare with glossary.json to create a snapshot dictionary
                snapshot_glossary = {}
                for zh_term, th_term in glossary_dict.items():
                    if zh_term in combined_batch_text:
                        snapshot_glossary[zh_term] = th_term
                
                # 3. Write snapshot glossary to snapshot_glossary.json in output_dir
                snapshot_path = os.path.join(output_dir, "snapshot_glossary.json")
                try:
                    with open(snapshot_path, "w", encoding="utf-8") as f:
                        json.dump(snapshot_glossary, f, ensure_ascii=False, indent=2)
                    print(f"[✓] Created snapshot_glossary.json with {len(snapshot_glossary)} matching terms for this batch.")
                except Exception as e:
                    print(f"[!] Error writing snapshot_glossary.json: {e}")
                
                # 4. Translate all files in the current batch
                for filepath in batch:
                    processed_count += 1
                    filename = os.path.basename(filepath)
                    progress = draw_progress_bar(processed_count, total_files)
                    print(f"\n[+] Translating {progress}: {filename}...")
                    
                    # Get running number prefix (e.g. '0001')
                    match = re.match(r"^(\d{4})_", filename)
                    running_prefix = match.group(1) if match else "0000"
                    
                    try:
                        # Read file content
                        with open(filepath, "r", encoding="utf-8") as f:
                            content_to_translate = f.read()
                            
                        # Load snapshot glossary from snapshot_glossary.json
                        current_snapshot = {}
                        if os.path.exists(snapshot_path):
                            try:
                                with open(snapshot_path, "r", encoding="utf-8") as sf:
                                    current_snapshot = json.load(sf)
                            except Exception as sf_err:
                                print(f"[!] Warning: Could not read snapshot_glossary.json: {sf_err}. Using in-memory snapshot.")
                                current_snapshot = snapshot_glossary
                        else:
                            current_snapshot = snapshot_glossary
                            
                        # Format prompt using sorted snapshot glossary terms (helps prefix caching)
                        sorted_keys = sorted(current_snapshot.keys())
                        prompt_with_glossary = content_to_translate
                        if sorted_keys:
                            print(f"[*] Found {len(sorted_keys)} glossary terms in snapshot for this batch.")
                            glossary_instruction = "\n\n=== GLOSSARY REFERENCE (Use these exact translations for consistency) ===\n"
                            for zh_term in sorted_keys:
                                glossary_instruction += f"- {zh_term} -> {current_snapshot[zh_term]}\n"
                            glossary_instruction += "========================================================================\n"
                            prompt_with_glossary = glossary_instruction + content_to_translate
                            
                        print(f"[*] Sending content to DeepSeek ({len(prompt_with_glossary)} chars)...")
                        raw_response = call_deepseek_api(system_prompt, prompt_with_glossary, api_key, model)
                        
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
                        
                        # Update glossary dictionary and file
                        if new_glossary:
                            added_terms = 0
                            for item in new_glossary:
                                zh = item.get("source", "").strip()
                                th = item.get("target", "").strip()
                                if zh and th:
                                    if glossary_dict.get(zh) != th:
                                        glossary_dict[zh] = th
                                        added_terms += 1
                            if added_terms > 0:
                                try:
                                    with open(glossary_path, "w", encoding="utf-8") as f:
                                        json.dump(glossary_dict, f, ensure_ascii=False, indent=2)
                                    print(f"[✓] Updated glossary.json with {added_terms} new terms (Total: {len(glossary_dict)}).")
                                except Exception as ge:
                                    print(f"[!] Error saving glossary.json: {ge}")
                        
                        # Move original file to done/
                        dest_path = os.path.join(done_dir, filename)
                        shutil.move(filepath, dest_path)
                        print(f"[*] Moved original file to: {dest_path}")
                        
                    except Exception as e:
                        print(f"[!] Error translating {filename}: {e}")
                        print("[*] Skipping this file for now...")
                        failed_count += 1
                        continue
                
                # 5. Clear/Delete snapshot_glossary.json after completing the batch
                if os.path.exists(snapshot_path):
                    try:
                        os.remove(snapshot_path)
                        print(f"[*] Cleared {snapshot_path}")
                    except Exception as e:
                        print(f"[!] Error deleting {snapshot_path}: {e}")
                        
        else:
            # Gemini/Standard path (individual file translation and individual glossary search)
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
                        
                    # Search glossary for terms present in the source text
                    matching_glossary = []
                    for zh_term, th_term in glossary_dict.items():
                        if zh_term in content_to_translate:
                            matching_glossary.append({"source": zh_term, "target": th_term})
                    
                    prompt_with_glossary = content_to_translate
                    if matching_glossary:
                        print(f"[*] Found {len(matching_glossary)} matching glossary terms in this chapter.")
                        glossary_instruction = "\n\n=== GLOSSARY REFERENCE (Use these exact translations for consistency) ===\n"
                        for item in matching_glossary:
                            glossary_instruction += f"- {item['source']} -> {item['target']}\n"
                        glossary_instruction += "========================================================================\n"
                        prompt_with_glossary = glossary_instruction + content_to_translate
                        
                    print(f"[*] Sending content to Gemini ({len(prompt_with_glossary)} chars)...")
                    raw_response = call_gemini_api(system_prompt, prompt_with_glossary, api_key, model)
                    
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
                    
                    # Update glossary dictionary and file
                    if new_glossary:
                        added_terms = 0
                        for item in new_glossary:
                            zh = item.get("source", "").strip()
                            th = item.get("target", "").strip()
                            if zh and th:
                                if glossary_dict.get(zh) != th:
                                    glossary_dict[zh] = th
                                    added_terms += 1
                        if added_terms > 0:
                            try:
                                with open(glossary_path, "w", encoding="utf-8") as f:
                                    json.dump(glossary_dict, f, ensure_ascii=False, indent=2)
                                print(f"[✓] Updated glossary.json with {added_terms} new terms (Total: {len(glossary_dict)}).")
                            except Exception as ge:
                                print(f"[!] Error saving glossary.json: {ge}")
                    
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
            # All files succeeded in this pass
            break
            
        pass_count += 1
        
    print("\n[*] Translation stage completed.")


