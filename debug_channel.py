#!/usr/bin/env python3

import yt_dlp
import json

url = "https://www.youtube.com/@Requestedreads"

print(f"Testing URL: {url}")
print("="*60)

# Test 1: Basic extraction
print("\nTest 1: Basic extraction with extract_flat='in_playlist'")
opts1 = {
    "quiet": False,
    "extract_flat": "in_playlist",
    "skip_download": True,
}

with yt_dlp.YoutubeDL(opts1) as ydl:
    info = ydl.extract_info(url, download=False)
    print(f"Channel title: {info.get('title', 'N/A')}")
    print(f"Channel ID: {info.get('channel_id', 'N/A')}")
    entries = info.get('entries', [])
    print(f"Number of entries: {len(entries)}")
    
    for i, entry in enumerate(entries[:5]):  # Show first 5
        print(f"\nEntry {i+1}:")
        print(f"  Type: {type(entry)}")
        print(f"  ID: {entry.get('id', 'N/A') if isinstance(entry, dict) else 'N/A'}")
        print(f"  Title: {entry.get('title', 'N/A') if isinstance(entry, dict) else 'N/A'}")
        print(f"  URL: {entry.get('url', 'N/A') if isinstance(entry, dict) else 'N/A'}")
        if isinstance(entry, dict) and 'entries' in entry:
            print(f"  Has sub-entries: {len(entry.get('entries', []))}")

# Test 2: Try with /videos suffix
print("\n" + "="*60)
print("\nTest 2: Trying with /videos suffix")
url_videos = url + "/videos"
print(f"URL: {url_videos}")

with yt_dlp.YoutubeDL(opts1) as ydl:
    info = ydl.extract_info(url_videos, download=False)
    entries = info.get('entries', [])
    print(f"Number of entries: {len(entries)}")
    
    for i, entry in enumerate(entries[:5]):  # Show first 5
        print(f"\nEntry {i+1}:")
        print(f"  ID: {entry.get('id', 'N/A') if isinstance(entry, dict) else 'N/A'}")
        print(f"  Title: {entry.get('title', 'N/A') if isinstance(entry, dict) else 'N/A'}")

# Test 3: Try without extract_flat
print("\n" + "="*60)
print("\nTest 3: Trying without extract_flat for first video")
opts3 = {
    "quiet": True,
    "playlistend": 1,  # Only get first video
    "skip_download": True,
}

try:
    with yt_dlp.YoutubeDL(opts3) as ydl:
        info = ydl.extract_info(url_videos, download=False)
        entries = info.get('entries', [])
        print(f"Number of entries: {len(entries)}")
        if entries and isinstance(entries[0], dict):
            print(f"First video: {entries[0].get('title', 'N/A')}")
            print(f"First video ID: {entries[0].get('id', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")
