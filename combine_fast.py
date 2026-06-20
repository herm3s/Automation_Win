import os
import sys
import argparse
import subprocess

# Add local path to import audiobook helper
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
try:
    from audiobook import get_ffmpeg_executables, create_static_video
except ImportError:
    print("[!] Error: Could not import audiobook helpers. Run this script in the Automation directory.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description="Fast Video Concatenator: Prepend a new audio file (as a static video) to an existing compiled video"
    )
    parser.add_argument("--cover", required=True, help="Path to the cover image")
    parser.add_argument("--new-audio", required=True, help="Path to the new audio (.mp3) file to prepend")
    parser.add_argument("--old-video", required=True, help="Path to the existing combined video (.mp4)")
    parser.add_argument("--output", required=True, help="Path to save the final concatenated video (.mp4)")
    
    args = parser.parse_args()
    
    # Verify files exist
    for label, path in [("Cover image", args.cover), ("New audio", args.new_audio), ("Old video", args.old_video)]:
        if not os.path.exists(path):
            print(f"[!] Error: {label} not found at '{path}'")
            sys.exit(1)
            
    try:
        ffmpeg_bin, ffprobe_bin = get_ffmpeg_executables()
    except Exception as e:
        print(f"[!] Error finding FFmpeg: {e}")
        sys.exit(1)
        
    temp_mp4 = args.output + ".temp_new_segment.mp4"
    concat_list = args.output + ".temp_concat_list.txt"
    
    try:
        # 1. Create static video for the new segment
        print(f"[*] Rendering static video for new segment: {temp_mp4}")
        create_static_video(args.cover, args.new_audio, temp_mp4, ffmpeg_bin)
        
        # 2. Write concat list
        print(f"[*] Creating concatenation manifest: {concat_list}")
        with open(concat_list, "w", encoding="utf-8") as f:
            f.write(f"file '{os.path.abspath(temp_mp4)}'\n")
            f.write(f"file '{os.path.abspath(args.old_video)}'\n")
            
        # 3. Concatenate the videos instantly using copy codec
        print(f"[*] Concatenating videos instantly to: {args.output}")
        concat_cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_list,
            "-c", "copy",
            args.output
        ]
        res = subprocess.run(concat_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        
        if res.returncode == 0:
            print(f"[✓] Success! Combined video created successfully at: {args.output}")
        else:
            print(f"[!] Concatenation failed: {res.stderr}")
            sys.exit(1)
            
    finally:
        # Clean up temporary files
        for f in [temp_mp4, concat_list]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception:
                    pass

if __name__ == "__main__":
    main()
