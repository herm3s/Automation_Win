import os
import re
import time
# pyrefly: ignore [missing-import]
from bs4 import BeautifulSoup
# pyrefly: ignore [missing-import]
from playwright.sync_api import sync_playwright
# pyrefly: ignore [missing-import]
from utils import get_next_running_number, sanitize_filename, draw_progress_bar

# Default list of selectors to try for novel title, content, and next links
DEFAULT_TITLE_SELECTORS = [
    "h1.entry-title", "h1", "h2.chapter-title", ".chapter-title", 
    "#chapter-title", ".ep-title", ".title", "h2"
]

DEFAULT_CONTENT_SELECTORS = [
    "#novel-content", ".novel-content", ".chapter-content", ".reading-content", 
    ".story-content", "#story-content", "#content", ".ep-content", 
    ".entry-content", "article", ".chapter-detail"
]

# Next button selector heuristics
DEFAULT_NEXT_SELECTORS = [
    "a:has-text('ตอนถัดไป')", "a:has-text('ตอนต่อไป')", "a:has-text('บทถัดไป')",
    "a:has-text('Next Chapter')", "a:has-text('Next')", "a:has-text('next')",
    "a:has-text('ถัดไป')", "a:has-text('>')", "a:has-text('→')",
    "a:has-text('下一頁')", "a:has-text('下一章')", "a:has-text('下页')", "a:has-text('下章')",
    ".next-chap", "a.next", ".btn-next", "#next_chapter", ".next-link"
]

# Regex pattern to match Chinese chapter identifiers (e.g., 第1章, 第十二卷, 第三十六回, etc.)
CHAPTER_PATTERN = r'(第[\d零一二三四五六七八九十百千]+[章回节卷篇更])'

def clean_ad_content(text: str) -> str:
    """
    Applies regex to clean ads, images, and text containing 'www.' from the content.
    """
    if not text:
        return ""
        
    # Remove image markdown patterns (in case some were scraped)
    text = re.sub(r"!\[.*?\]\(.*?\)", "", text)
    
    # Split into lines to inspect each line for 'www.' and other ad patterns
    lines = text.split("\n")
    cleaned_lines = []
    
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            cleaned_lines.append("")
            continue
            
        # Check if line contains 'www.'
        if "www." in stripped_line.lower():
            # If it's a small mention or embedded link, we skip the line
            continue
            
        # Check if it matches typical ad domains or URLs
        if re.search(r"https?://[^\s]+", stripped_line):
            continue
            
        # Check for typical Thai/English ad keywords
        ad_keywords = [
            "โฆษณา", "สมัครสมาชิก", "คลิกเพื่อ", "click here", "add line", 
            "ไลน์กลุ่ม", "ติดตามตอนต่อไป", "อ่านฟรี", "อ่านตอนต่อไป", "แฟนเพจ"
        ]
        if any(kw in stripped_line.lower() for kw in ad_keywords):
            continue
            
        cleaned_lines.append(line)
        
    cleaned_text = "\n".join(cleaned_lines)
    # Remove excessive newlines
    cleaned_text = re.sub(r"\n{3,}", "\n\n", cleaned_text)
    return cleaned_text.strip()

def scrape_novel_chapter(page, title_selector=None, content_selector=None, next_selector=None):
    """
    Scrapes the current page for novel title, content, and the next chapter link.
    """
    # 1. Try to find the title
    title = "Untitled Chapter"
    title_selectors = [title_selector] if title_selector else DEFAULT_TITLE_SELECTORS
    for sel in title_selectors:
        title_element = page.locator(sel).first
        if title_element.is_visible():
            title = title_element.inner_text().strip()
            break
            
    # 2. Try to find the content
    content_text = ""
    content_selectors = [content_selector] if content_selector else DEFAULT_CONTENT_SELECTORS
    content_found = False
    
    for sel in content_selectors:
        content_element = page.locator(sel).first
        if content_element.is_visible():
            # Extract text paragraph by paragraph to preserve spacing cleanly
            paragraphs = content_element.locator("p").all_inner_texts()
            if paragraphs:
                content_text = "\n\n".join(paragraphs)
            else:
                # Fallback to inner_text if no <p> tags are found
                content_text = content_element.inner_text()
            
            content_found = True
            break
            
    if not content_found:
        # Extreme fallback: look for elements with long text if selectors failed
        body_text = page.locator("body").inner_text()
        # Just use it as fallback
        content_text = body_text
        
    # Clean the content text
    cleaned_content = clean_ad_content(content_text)
    
    # 3. Try to find next chapter URL
    next_url = None
    next_selectors = [next_selector] if next_selector else DEFAULT_NEXT_SELECTORS
    for sel in next_selectors:
        try:
            # Locate all matching elements and pick the first one that does not point to a "previous" page.
            # This handles generic selectors (like a.pages) matching both previous and next buttons.
            elements = page.locator(sel).all()
            for elem in elements:
                if elem.is_visible() and elem.get_attribute("href"):
                    text = (elem.inner_text() or "").strip().lower()
                    href = elem.get_attribute("href")
                    
                    # Previous-page indicators to filter out
                    prev_indicators = ["上一頁", "上一章", "上页", "上章", "上一", "prev", "previous", "←", "back", "ย้อนกลับ", "ก่อนหน้า"]
                    if any(indicator in text for indicator in prev_indicators):
                        continue
                        
                    next_url = href
                    # Handle relative URLs
                    if next_url:
                        from urllib.parse import urljoin
                        next_url = urljoin(page.url, next_url)
                    break
            if next_url:
                break
        except Exception:
            continue
            
    return title, cleaned_content, next_url

def run_scraper(start_url, load_limit, title_selector=None, content_selector=None, next_selector=None, output_dir=".", proxy=None):
    """
    Main entry point to run the Playwright scraper sequential loop.
    """
    print(f"[*] Starting scraper at: {start_url}")
    print(f"[*] Chapters to load: {load_limit}")
    
    # Ensure output directory exists
    if output_dir and output_dir != ".":
        os.makedirs(output_dir, exist_ok=True)
        print(f"[*] Work directory set to: {output_dir}")
        
    with sync_playwright() as p:
        # Launch Chromium headless with optional proxy
        browser_args = {}
        if proxy:
            if proxy.lower() == "true":
                proxy_server = "http://siph-mmswg01.siph.com:8080"
            else:
                proxy_server = proxy
            browser_args["proxy"] = {"server": proxy_server}
            print(f"[*] Playwright launcher configured with proxy: {proxy_server}")
            
        browser = p.chromium.launch(headless=True, **browser_args)
        # Create browser context with common user-agent to bypass basic scrape protection
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        current_url = start_url
        chapters_scraped = 0
        
        while current_url and chapters_scraped < load_limit:
            progress = draw_progress_bar(chapters_scraped + 1, load_limit)
            print(f"\n[+] Loading page {progress}: {current_url}")
            try:
                # Navigate to the URL
                page.goto(current_url, timeout=30000, wait_until="domcontentloaded")
                # Give some extra time for dynamic javascript content to load
                time.sleep(2)
                
                title, content, next_url = scrape_novel_chapter(
                    page, title_selector, content_selector, next_selector
                )
                
                # Check if the title matches the Chinese chapter pattern (e.g., 第1章, 第十二卷)
                if not re.search(CHAPTER_PATTERN, title):
                    print(f"[!] Warning: Title '{title}' does not match the chapter pattern. Skipping this page...")
                    if not next_url:
                        print("[-] Next chapter button/link not found on skipped page. Scraping stopped.")
                        break
                    # Wait shortly and navigate directly to the next page
                    time.sleep(1)
                    current_url = next_url
                    continue
                
                if not content or len(content) < 50:
                    print("[!] Warning: Scraped content seems very short or empty. Retrying with a small delay...")
                    time.sleep(3)
                    title, content, next_url = scrape_novel_chapter(
                        page, title_selector, content_selector, next_selector
                    )
                
                # Determine next running number
                run_num = get_next_running_number(output_dir)
                filename = f"{run_num:04d}_{sanitize_filename(title)}.md"
                filepath = os.path.join(output_dir, filename)
                
                # Save content as markdown
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(f"# {title}\n\n")
                    f.write(content)
                    
                print(f"[✓] Saved chapter: {filename} ({len(content)} characters)")
                chapters_scraped += 1
                
                if not next_url:
                    print("[-] Next chapter button/link not found. Scraping stopped.")
                    break
                    
                # Small human-like delay before next page
                time.sleep(1)
                current_url = next_url
                
            except Exception as e:
                print(f"[!] Error loading or scraping {current_url}: {e}")
                break
                
        browser.close()
        print(f"\n[*] Finished! Successfully scraped {chapters_scraped} chapters.")
