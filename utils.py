import os
import re
import glob

def get_next_running_number(directory=".", pattern=r"^(\d+)") -> int:
    """
    Scans the directory for files matching *.md and extracts the highest running number prefix.
    Returns the next number in sequence (defaults to 1 if no matching files exist).
    """
    highest_num = 0
    # Search for all markdown files in the specified directory
    md_files = glob.glob(os.path.join(directory, "*.md"))
    
    # We also want to check files under 'done/' or other folders if necessary,
    # but scanning the current output folder is the main priority.
    for filepath in md_files:
        filename = os.path.basename(filepath)
        match = re.match(pattern, filename)
        if match:
            try:
                num = int(match.group(1))
                if num > highest_num:
                    highest_num = num
            except ValueError:
                continue
                
    return highest_num + 1

def clean_markdown_for_tts(md_text: str) -> str:
    """
    Strips Markdown formatting tags (like #, **, [links], etc.) from text 
    so that a TTS reader doesn't speak symbols or URLs.
    """
    if not md_text:
        return ""
        
    # 1. Remove markdown code blocks
    text = re.sub(r"```[\s\S]*?```", "", md_text)
    
    # 2. Remove inline code
    text = re.sub(r"`[^`]+`", "", text)
    
    # 3. Remove images: ![alt](url)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    
    # 4. Replace links: [text](url) -> text
    text = re.sub(r"\[(.*?)\]\(.*?\)", r"\1", text)
    
    # 5. Remove bold and italic markers: **text** or __text__ -> text, *text* or _text_ -> text
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"_([^_]+)_", r"\1", text)
    
    # 6. Remove strikethrough: ~~text~~ -> text
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    
    # 7. Remove markdown headers: # header -> header
    text = re.sub(r"^\s*#+\s*", "", text, flags=re.MULTILINE)
    
    # 7.5. Replace colons and ampersands which can break the Edge TTS XML parser
    text = text.replace(":", " ")
    text = text.replace("&", " and ")
    
    # Remove all quotes (both double, single, curly) as they break the Edge TTS server parser
    text = text.replace('"', "")
    text = text.replace("'", "")
    text = text.replace("“", "")
    text = text.replace("”", "")
    text = text.replace("‘", "")
    text = text.replace("’", "")
    
    # Remove parentheses, hyphens, em-dashes, and underscores which break the Edge TTS server parser for Thai
    text = text.replace("(", " ")
    text = text.replace(")", " ")
    text = text.replace("-", " ")
    text = text.replace("—", " ")
    text = text.replace("_", " ")
    
    # 8. Normalize whitespace and replace newlines with spaces (since newlines break the Edge TTS server parser)
    text = re.sub(r"[ \t]+", " ", text)
    text = text.replace("\n", " ")
    text = re.sub(r" +", " ", text)
    
    return text.strip()

def sanitize_filename(name: str) -> str:
    """
    Sanitizes a string to make it safe for use as a filename.
    Replaces spaces with underscores and removes invalid characters.
    """
    # Remove invalid characters
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    # Replace whitespace and newlines with underscores
    name = re.sub(r'\s+', "_", name)
    # Strip leading/trailing underscores/dots/hyphens
    name = name.strip("_-.")
    return name

def draw_progress_bar(current: int, total: int, width: int = 30) -> str:
    """
    Generates a text-based progress bar.
    Example: [██████░░░░] 60% (3/5)
    """
    if total <= 0:
        return ""
    percent = float(current) / float(total)
    filled_width = int(width * percent)
    bar = "█" * filled_width + "░" * (width - filled_width)
    pct = int(percent * 100)
    return f"[{bar}] {pct}% ({current}/{total})"
