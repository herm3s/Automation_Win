import argparse
import sys
from scraper import run_scraper
from translator import run_translation
from audiobook import process_audiobooks, compile_audiobook_compilation

def parse_limit(val):
    if val is None:
        return None
    val_str = str(val).strip().lower()
    if val_str in ("null", "none", "infinite", "inf", "unlimited", ""):
        return None
    try:
        return int(val)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid limit value: '{val}'. Must be an integer or 'null'.")

def main():
    parser = argparse.ArgumentParser(
        description="Web Novel Automation Tool: Scrape, Translate, and Generate YouTube Audiobooks"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")
    
    # 1. Scrape Command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape novel chapters from a starting URL")
    scrape_parser.add_argument("--url", required=True, help="Starting URL of the first chapter")
    scrape_parser.add_argument(
        "--limit", type=parse_limit, default=5, 
        help="Number of chapters to load sequentially, or 'null' for unlimited (default: 5)"
    )
    scrape_parser.add_argument(
        "--title-selector", default=None, 
        help="Optional CSS selector for chapter title"
    )
    scrape_parser.add_argument(
        "--content-selector", default=None, 
        help="Optional CSS selector for chapter content text"
    )
    scrape_parser.add_argument(
        "--next-selector", default=None, 
        help="Optional CSS selector for next chapter button/link"
    )
    scrape_parser.add_argument(
        "--option", default=".", 
        help="Working directory path to save/read files (default: .)"
    )
    scrape_parser.add_argument(
        "--proxy", default=None,
        help="Use proxy for scraper (e.g. 'true' or custom proxy URL)"
    )
    
    # 2. Translate Command
    translate_parser = subparsers.add_parser("translate", help="Translate scraped chapters using Gemini or DeepSeek API")
    translate_parser.add_argument(
        "--ai", default="gemini", choices=["gemini", "deepseek", "deep seek", "deep-seek"],
        help="AI translation provider to use (default: gemini)"
    )
    translate_parser.add_argument(
        "--model", default=None,
        help="Model name to use (default: gemini-2.5-flash for Gemini, deepseek-v4-flash for DeepSeek)"
    )
    translate_parser.add_argument(
        "--option", default=".", 
        help="Working directory path to save/read files (default: .)"
    )
    translate_parser.add_argument(
        "--proxy", default=None,
        help="Use proxy for translator API requests (e.g. 'true')"
    )
    
    translate_parser.add_argument(
        "--limit", type=parse_limit, default=None,
        help="Number of chapters to translate (default: all)"
    )
    audiobook_parser = subparsers.add_parser("audiobook", help="Generate MP3 files and video chapters")
    audiobook_parser.add_argument(
        "--voice", default="th-TH-NiwatNeural",
        help="TTS Voice code. (e.g. th-TH-NiwatNeural (male, working), th-TH-PremwadeeNeural (female, server-side G2P bug), etc. Default: th-TH-NiwatNeural)"
    )
    audiobook_parser.add_argument(
        "--no-video", action="store_true",
        help="Skip generating individual MP4 videos, only produce MP3s"
    )
    audiobook_parser.add_argument(
        "--combine", action="store_true",
        help="Concatenate all MP3s into a single combined audiobook MP3 and render a combined video with YouTube timestamps"
    )
    audiobook_parser.add_argument(
        "--option", default=".", 
        help="Working directory path to save/read files (default: .)"
    )
    audiobook_parser.add_argument(
        "--proxy", default=None,
        help="Use proxy for TTS API requests (e.g. 'true')"
    )
    
    audiobook_parser.add_argument(
        "--limit", type=parse_limit, default=None,
        help="Number of chapters to generate audio/video for (default: all)"
    )
    
    # 4. All Command (Full Pipeline)
    all_parser = subparsers.add_parser("all", help="Run the full pipeline: scrape, translate, and generate audiobook compilation")
    all_parser.add_argument("--url", required=True, help="Starting URL of the first chapter")
    all_parser.add_argument(
        "--limit", type=parse_limit, default=5, 
        help="Number of chapters to load sequentially, or 'null' for unlimited (default: 5)"
    )
    all_parser.add_argument(
        "--title-selector", default=None, 
        help="Optional CSS selector for chapter title"
    )
    all_parser.add_argument(
        "--content-selector", default=None, 
        help="Optional CSS selector for chapter content text"
    )
    all_parser.add_argument(
        "--next-selector", default=None, 
        help="Optional CSS selector for next chapter button/link"
    )
    all_parser.add_argument(
        "--ai", default="gemini", choices=["gemini", "deepseek", "deep seek", "deep-seek"],
        help="AI translation provider to use (default: gemini)"
    )
    all_parser.add_argument(
        "--model", default=None,
        help="Model name to use (default: gemini-2.5-flash for Gemini, deepseek-v4-flash for DeepSeek)"
    )
    all_parser.add_argument(
        "--voice", default="th-TH-NiwatNeural",
        help="TTS Voice code (default: th-TH-NiwatNeural)"
    )
    all_parser.add_argument(
        "--no-video", action="store_true",
        help="Skip generating individual MP4 videos, only produce MP3s"
    )
    all_parser.add_argument(
        "--option", default=".", 
        help="Working directory path to save/read files (default: .)"
    )
    all_parser.add_argument(
        "--proxy", default=None,
        help="Use proxy for scraper (e.g. 'true' or custom proxy URL)"
    )
    
    args = parser.parse_args()
    
    if args.command == "scrape":
        run_scraper(
            start_url=args.url,
            load_limit=args.limit,
            title_selector=args.title_selector,
            content_selector=args.content_selector,
            next_selector=args.next_selector,
            output_dir=args.option,
            proxy=args.proxy
        )
    elif args.command == "translate":
        ai_normalized = args.ai.lower().replace(" ", "").replace("-", "")
        run_translation(model=args.model, ai=ai_normalized, output_dir=args.option, proxy=args.proxy, limit=args.limit)
    elif args.command == "audiobook":
        # First process individual chapters (generate MP3s)
        print("[*] Generating individual chapter audio files...")
        mp3s = process_audiobooks(voice=args.voice, generate_videos=False, output_dir=args.option, proxy=args.proxy, limit=args.limit)
        
        # If combine flag is set, compile them together into a single video
        if args.combine:
            compile_audiobook_compilation(voice=args.voice, output_dir=args.option)
    elif args.command == "all":
        print("\n[*] --- STAGE 1: Scraping novel chapters ---")
        run_scraper(
            start_url=args.url,
            load_limit=args.limit,
            title_selector=args.title_selector,
            content_selector=args.content_selector,
            next_selector=args.next_selector,
            output_dir=args.option,
            proxy=args.proxy
        )
        
        print("\n[*] --- STAGE 2: Translating chapters ---")
        ai_normalized = args.ai.lower().replace(" ", "").replace("-", "")
        run_translation(model=args.model, ai=ai_normalized, output_dir=args.option, proxy=args.proxy, limit=args.limit)
        
        print("\n[*] --- STAGE 3: Generating audiobooks & video compilation ---")
        # Generate all MP3s first, then build the single compilation video
        process_audiobooks(voice=args.voice, generate_videos=False, output_dir=args.option, proxy=args.proxy, limit=args.limit)
        compile_audiobook_compilation(voice=args.voice, output_dir=args.option)
        print("\n[✓] Complete pipeline executed successfully!")
    else:
        parser.print_help()
        sys.exit(1)

if __name__ == "__main__":
    main()
