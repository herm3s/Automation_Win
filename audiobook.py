import os
import re
import glob
import shutil
import asyncio
import subprocess
from utils import clean_markdown_for_tts, get_next_running_number, draw_progress_bar

# Import static-ffmpeg wrapper to get system-independent binaries
try:
    from static_ffmpeg import run as ffmpeg_run
except ImportError:
    ffmpeg_run = None

import edge_tts

def get_ffmpeg_executables():
    """
    Retrieves the absolute paths of ffmpeg and ffprobe from static-ffmpeg.
    If it fails, falls back to checking the system PATH.
    """
    # 1. Try static-ffmpeg first
    if ffmpeg_run is not None:
        try:
            ffmpeg_bin, ffprobe_bin = ffmpeg_run.get_or_fetch_platform_executables_else_raise()
            if os.path.exists(ffmpeg_bin) and os.path.exists(ffprobe_bin):
                return ffmpeg_bin, ffprobe_bin
        except Exception as e:
            print(f"[!] Warning: static-ffmpeg failed: {e}. Falling back to system binaries...")

    # 2. Fallback: check system PATH using shutil.which
    system_ffmpeg = shutil.which("ffmpeg")
    system_ffprobe = shutil.which("ffprobe")
    
    if system_ffmpeg and system_ffprobe:
        print(f"[*] Found system FFmpeg: {system_ffmpeg}")
        print(f"[*] Found system FFprobe: {system_ffprobe}")
        return system_ffmpeg, system_ffprobe
        
    raise RuntimeError("Neither static-ffmpeg nor system-installed FFmpeg/FFprobe could be found.")

def find_cover_image(directory=".") -> str:
    """
    Searches for a cover image in the directory.
    Looks for files starting with 'cover' first, then falls back to any image file.
    Also falls back to the parent directory if not found.
    """
    # Ensure directory is absolute for robust parent fallback checking
    abs_dir = os.path.abspath(directory)
    
    # Look for files starting with 'cover'
    cover_patterns = ["cover.jpg", "cover.png", "cover.jpeg", "cover.webp", "cover.*"]
    for pattern in cover_patterns:
        matches = glob.glob(os.path.join(abs_dir, pattern))
        if matches:
            return matches[0]
            
    # Fallback: find any image file
    image_extensions = ["*.jpg", "*.jpeg", "*.png", "*.webp"]
    for ext in image_extensions:
        matches = glob.glob(os.path.join(abs_dir, ext))
        if matches:
            # Return the first one found
            return matches[0]
            
    # Fallback to parent directory
    parent_dir = os.path.dirname(abs_dir)
    if parent_dir and parent_dir != abs_dir:
        parent_cover = find_cover_image(parent_dir)
        if parent_cover:
            return parent_cover
            
    return None

async def text_to_speech(text: str, output_path: str, voice: str, proxy: str = None):
    """
    Converts cleaned text to an MP3 file using edge-tts.
    """
    communicate = edge_tts.Communicate(text, voice, proxy=proxy)
    await communicate.save(output_path)

def get_audio_duration(mp3_path: str, ffprobe_bin: str) -> float:
    """
    Queries the duration of an MP3 file in seconds using ffprobe.
    """
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        mp3_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode == 0:
        try:
            return float(result.stdout.strip())
        except ValueError:
            return 0.0
    else:
        raise RuntimeError(f"FFprobe error: {result.stderr}")

def create_static_video(image_path: str, audio_path: str, output_path: str, ffmpeg_bin: str):
    """
    Creates a highly compatible, resource-efficient .mp4 video using a color filter background
    and overlaying the cover image on top. Uses standard 720p resolution, CRF 23, and a 5 fps
    frame rate to ensure smooth compatibility with macOS QuickTime, YouTube, and mobile players.
    Only decodes the cover image once to maximize rendering speed (runs at 10x+ speed).
    Uses 44.1kHz stereo AAC audio and +faststart flag to guarantee compatibility with QuickTime.
    """
    # -f lavfi -i "color=c=black:s=1280x720:r=5": Generates a 1280x720 black video stream at 5 fps
    # -i image_path: Input cover image (decoded once, overlaid continuously)
    # -i audio_path: Input audio track
    # -shortest: Terminate encoding when the audio finishes
    # -movflags +faststart: Move metadata to the start of the file for QuickTime compatibility
    # -ar 44100 -ac 2: Standardize audio sampling rate and channels (stereo)
    cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "lavfi",
        "-i", "color=c=black:s=1280x720:r=5",
        "-i", image_path,
        "-i", audio_path,
        "-filter_complex", "[1:v]scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2[img];[0:v][img]overlay=0:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "stillimage",
        "-crf", "23",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-ac", "2",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]
    
    print(f"[*] Rendering video: {output_path}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"FFmpeg rendering failed: {result.stderr}")

def format_seconds_to_hms(seconds: float) -> str:
    """
    Formats seconds float to a HH:MM:SS string.
    """
    s = int(seconds)
    hours = s // 3600
    minutes = (s % 3600) // 60
    secs = s % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

def process_audiobooks(voice="th-TH-PremwadeeNeural", generate_videos=False, output_dir=".", proxy=None):
    """
    Pipeline Step 3:
    - Finds all translated markdown files (000X_*.md in translate/ folder).
    - Converts each to MP3 and saves in Audiobook/ folder.
    - Skips generation if MP3 file already exists.
    - Creates separate static video for each chapter if generate_videos is True.
    - Retries any failed chapters at the end of the pass.
    """
    import time
    # Set directories
    translate_dir = os.path.join(output_dir, "translate")
    audiobook_dir = os.path.join(output_dir, "Audiobook")
    
    if not os.path.exists(translate_dir):
        print(f"[-] Translate directory '{translate_dir}' does not exist. No files to process.")
        return []
        
    if not os.path.exists(audiobook_dir):
        os.makedirs(audiobook_dir)
        print(f"[*] Created directory: {audiobook_dir}/")
        
    # Get FFmpeg bins
    try:
        ffmpeg_bin, ffprobe_bin = get_ffmpeg_executables()
    except Exception as e:
        print(f"[!] Warning: FFmpeg executables could not be retrieved: {e}")
        print("[!] Video creation features will be disabled. Only MP3s will be generated.")
        generate_videos = False
        ffmpeg_bin, ffprobe_bin = None, None
        
    cover_image = None
    if generate_videos:
        cover_image = find_cover_image(output_dir)
        if not cover_image:
            print("[!] Warning: No cover image found in working directory.")
            print("[!] Static video generation skipped. Please add a cover image if you want videos.")
            generate_videos = False
            
    generated_mp3s = []
    
    # Retry loop configuration
    max_passes = 5
    pass_count = 1
    
    while True:
        # Find all translated markdown files (files starting with a 4-digit number in translate_dir)
        all_files = glob.glob(os.path.join(translate_dir, "*.md"))
        translated_files = []
        for f in all_files:
            basename = os.path.basename(f)
            if re.match(r"^\d{4}_", basename) and basename != "gemini.md":
                translated_files.append(f)
                
        if not translated_files:
            if pass_count == 1:
                print(f"[-] No translated markdown files found in '{translate_dir}' to generate audio.")
            else:
                print("\n[✓] All chapters successfully processed to audiobooks!")
            break
            
        if pass_count > max_passes:
            print(f"\n[!] Maximum retry passes ({max_passes}) reached. Some files failed to process to audio:")
            for f in translated_files:
                print(f"  - {os.path.basename(f)}")
            break
            
        translated_files.sort()
        total_files = len(translated_files)
        
        if pass_count > 1:
            print(f"\n[!] Pass {pass_count}: Retrying {total_files} failed audiobook generations...")
            time.sleep(5)
        else:
            print(f"[*] Found {total_files} translated chapters to process.")
            
        failed_count = 0
        
        for idx, filepath in enumerate(translated_files):
            filename = os.path.basename(filepath)
            name_without_ext = os.path.splitext(filename)[0]
            mp3_filename = f"{name_without_ext}.mp3"
            mp4_filename = f"{name_without_ext}.mp4"
            
            mp3_filepath = os.path.join(audiobook_dir, mp3_filename)
            mp4_filepath = os.path.join(audiobook_dir, mp4_filename)
            
            progress = draw_progress_bar(idx + 1, total_files)
            print(f"\n[+] Processing {progress}: {filename}...")
            
            # Check if MP3 file already exists
            if os.path.exists(mp3_filepath):
                print(f"[✓] Audio file already exists (Skipping): {mp3_filepath}")
                if mp3_filepath not in generated_mp3s:
                    generated_mp3s.append(mp3_filepath)
                
                # Check video if requested
                if generate_videos and cover_image and not os.path.exists(mp4_filepath):
                    try:
                        create_static_video(cover_image, mp3_filepath, mp4_filepath, ffmpeg_bin)
                        print(f"[✓] Saved video: {mp4_filepath}")
                    except Exception as ve:
                        print(f"[!] Error creating video for {mp3_filename}: {ve}")
                continue
                
            try:
                # 1. Read and clean text for TTS
                with open(filepath, "r", encoding="utf-8") as f:
                    raw_text = f.read()
                    
                clean_text = clean_markdown_for_tts(raw_text)
                if not clean_text:
                    print(f"[!] Warning: Cleaned text for {filename} is empty. Skipping.")
                    continue
                    
                # Resolve proxy URL if proxy is enabled
                proxy_url = None
                if proxy and proxy.lower() == "true":
                    proxy_url = "http://siph-mmswg01.siph.com:8080"
                elif proxy and (proxy.startswith("http://") or proxy.startswith("https://")):
                    proxy_url = proxy

                # 2. Generate MP3 using edge-tts
                print(f"[*] Generating audio (Voice: {voice}) -> {mp3_filepath}")
                asyncio.run(text_to_speech(clean_text, mp3_filepath, voice, proxy=proxy_url))
                print(f"[✓] Saved audio: {mp3_filepath}")
                if mp3_filepath not in generated_mp3s:
                    generated_mp3s.append(mp3_filepath)
                
                # 3. Create static video if requested
                if generate_videos and cover_image:
                    try:
                        create_static_video(cover_image, mp3_filepath, mp4_filepath, ffmpeg_bin)
                        print(f"[✓] Saved video: {mp4_filepath}")
                    except Exception as ve:
                        print(f"[!] Error creating video for {mp3_filename}: {ve}")
                        
            except Exception as e:
                print(f"[!] Error processing {filename}: {e}")
                for temp_file in [mp3_filepath, mp4_filepath]:
                    if os.path.exists(temp_file):
                        try:
                            os.remove(temp_file)
                            print(f"[*] Cleaned up failed file: {temp_file}")
                        except Exception:
                            pass
                failed_count += 1
                continue
                
        if failed_count == 0:
            break
            
        pass_count += 1
        
    return generated_mp3s

def compile_audiobook_compilation(voice="th-TH-PremwadeeNeural", output_dir="."):
    """
    Compiles all chapter MP3 files in the Audiobook directory into a single
    audiobook video, generating timestamps (timetrack.txt) for YouTube.
    """
    audiobook_dir = os.path.join(output_dir, "Audiobook")
    if not os.path.exists(audiobook_dir):
        print(f"[-] Audiobook directory '{audiobook_dir}' does not exist. No files to compile.")
        return
        
    # Find all MP3 files starting with 4-digits inside Audiobook/
    mp3_files = []
    for f in glob.glob(os.path.join(audiobook_dir, "*.mp3")):
        basename = os.path.basename(f)
        if re.match(r"^\d{4}_", basename) and basename != "combined_audiobook.mp3":
            mp3_files.append(f)
            
    if not mp3_files:
        print(f"[-] No chapter MP3 files found in '{audiobook_dir}' to compile (files matching '000X_*.mp3').")
        return
        
    mp3_files.sort()
    
    # Check if FFmpeg is available
    try:
        ffmpeg_bin, ffprobe_bin = get_ffmpeg_executables()
    except Exception as e:
        print(f"[!] Error: FFmpeg/FFprobe required for compilation: {e}")
        return
        
    cover_image = find_cover_image(output_dir)
    if not cover_image:
        print(f"[!] Error: A cover image is required in '{output_dir}' to compile the video.")
        return
        
    print(f"\n[*] Compiling {len(mp3_files)} chapters into a single audiobook compilation...")
    
    # 1. Calculate durations and generate timestamps list
    cumulative_seconds = 0.0
    timetracks = []
    
    # Create input list file for FFmpeg concat demuxer
    concat_list_path = os.path.join(audiobook_dir, "concat_list.txt")
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for idx, mp3_filepath in enumerate(mp3_files):
            # Write file entry to concat list (handling single quotes for safety)
            # Use absolute path to ensure correct path resolution during ffmpeg execution
            abs_mp3_path = os.path.abspath(mp3_filepath)
            escaped_filename = abs_mp3_path.replace("'", "'\\''")
            f.write(f"file '{escaped_filename}'\n")
            
            # Format timestamp string
            timestamp_str = format_seconds_to_hms(cumulative_seconds)
            
            # Extract clean title name from filename
            # e.g., '0001_Chapter_Title.mp3' -> 'Chapter Title'
            mp3_file = os.path.basename(mp3_filepath)
            clean_name = os.path.splitext(mp3_file)[0]
            clean_name = re.sub(r"^\d{4}_", "", clean_name)
            clean_name = clean_name.replace("_", " ")
            
            timetracks.append(f"{timestamp_str} - {clean_name}")
            
            # Get duration of this MP3
            duration = get_audio_duration(mp3_filepath, ffprobe_bin)
            cumulative_seconds += duration
            
    # Write timetrack.txt inside Audiobook/ folder
    timetrack_filename = os.path.join(audiobook_dir, "timetrack.txt")
    with open(timetrack_filename, "w", encoding="utf-8") as f:
        f.write("\n".join(timetracks))
        
    print(f"[✓] Saved YouTube time track to: {timetrack_filename}")
    print("--- Time Track Content ---")
    for track in timetracks:
        print(track)
    print("--------------------------")
    
    # 2. Concatenate audio files into a single output MP3 inside Audiobook/ folder
    combined_audio = os.path.join(audiobook_dir, "combined_audiobook.mp3")
    print(f"[*] Concatenating audio files to: {combined_audio}")
    
    concat_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        combined_audio
    ]
    
    result = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if os.path.exists(concat_list_path):
        os.remove(concat_list_path) # Clean up temporary file
        
    if result.returncode != 0:
        print(f"[!] Error concatenating audio files: {result.stderr}")
        return
        
    print(f"[✓] Saved combined audio: {combined_audio}")
    
    # 3. Render the final combined video inside Audiobook/ folder
    combined_video = os.path.join(audiobook_dir, "combined_audiobook.mp4")
    try:
        create_static_video(cover_image, combined_audio, combined_video, ffmpeg_bin)
        print(f"[✓] Audiobook Compilation Video successfully created: {combined_video}")
    except Exception as e:
        print(f"[!] Error creating combined video: {e}")
