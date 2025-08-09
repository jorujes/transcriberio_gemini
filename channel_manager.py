"""
Channel Processing Module

This module detects YouTube channel URLs, lists all videos from the channel
using yt-dlp (flat extraction), persists a resumable state JSON inside a
channel-specific folder, and processes videos sequentially (download +
transcription) while skipping already-processed items.

It reuses the existing YouTubeDownloader and TranscriptionService.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yt_dlp

from downloader import YouTubeDownloader
from transcriber import create_transcription_service, TranscriptionError
from audio_metadata import create_metadata_manager
from datetime import datetime


CHANNEL_URL_PATTERNS = [
    r"https?://(?:www\.)?youtube\.com/@[\w\-_.]+/?(?:videos)?/?$",
    r"https?://(?:www\.)?youtube\.com/channel/[\w\-_/]+/?(?:videos)?/?$",
    r"https?://(?:www\.)?youtube\.com/c/[\w\-_/]+/?(?:videos)?/?$",
    r"https?://(?:www\.)?youtube\.com/user/[\w\-_/]+/?(?:videos)?/?$",
]


@dataclass
class ChannelVideo:
    id: str
    url: str
    title: str


@dataclass
class ChannelState:
    channel_id: str
    channel_title: str
    channel_url: str
    created_at: str
    updated_at: str
    videos: List[ChannelVideo]
    status: Dict[str, Dict]
    last_index: int = 0

    def to_dict(self) -> dict:
        return {
            "channel_id": self.channel_id,
            "channel_title": self.channel_title,
            "channel_url": self.channel_url,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "videos": [asdict(v) for v in self.videos],
            "status": self.status,
            "last_index": self.last_index,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChannelState":
        videos = [ChannelVideo(**v) for v in data.get("videos", [])]
        return cls(
            channel_id=data.get("channel_id", ""),
            channel_title=data.get("channel_title", ""),
            channel_url=data.get("channel_url", ""),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
            videos=videos,
            status=data.get("status", {}),
            last_index=int(data.get("last_index", 0)),
        )


def is_channel_url(url: str) -> bool:
    if not isinstance(url, str):
        return False
    url = url.strip()
    for pattern in CHANNEL_URL_PATTERNS:
        if re.match(pattern, url, flags=re.IGNORECASE):
            return True
    # Fallback: treat clearly-non-video YouTube URLs as channel-like targets
    if "youtube.com" in url and "watch?v=" not in url and "shorts/" not in url:
        return True
    return False


def _safe_channel_key(info: dict, url: str) -> str:
    # Prefer handle (e.g., @handle) if present in URL
    m = re.search(r"youtube\.com/(@[\w\-_.]+)", url)
    if m:
        return m.group(1)
    # Fallback to channel id from info
    for key in ("channel_id", "id", "uploader_id"):
        val = info.get(key)
        if isinstance(val, str) and val:
            return f"channel_{val}"
    # Last resort: sanitize last path segment
    try:
        last = url.rstrip("/").split("/")[-1]
        last = re.sub(r"[^A-Za-z0-9_\-@]+", "_", last)
        return last or "channel_unknown"
    except Exception:
        return "channel_unknown"


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _extract_channel_entries(url: str) -> Tuple[dict, List[ChannelVideo]]:
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",  # Changed to extract videos in playlist
        "skip_download": True,
    }
    
    # Ensure we're getting the videos tab
    if "@" in url and not url.endswith("/videos"):
        url = url.rstrip("/") + "/videos"
    
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    entries: List[ChannelVideo] = []
    if not info:
        return {}, entries

    raw_entries = info.get("entries") or []
    for e in raw_entries:
        # Skip non-video entries (like tabs)
        if not isinstance(e, dict):
            continue
            
        # Check if this is a tab entry (has its own entries)
        if "entries" in e:
            # This is a tab, skip it
            continue
            
        # Each entry typically contains 'id', 'title', and 'url' (video webpage URL)
        vid = e.get("id") or ""
        title = e.get("title") or "Untitled"
        weburl = e.get("url") or e.get("webpage_url") or e.get("webpage_url_basename")
        
        # Skip if no video ID
        if not vid:
            continue
            
        # Some flat entries have URL as video ID only; construct full URL if needed
        if weburl and weburl.startswith("http"):
            full_url = weburl
        else:
            full_url = f"https://www.youtube.com/watch?v={vid}"
            
        # Only add if we have both ID and valid URL
        if vid and full_url and not any(skip in title.lower() for skip in ["- videos", "- live", "- shorts", "- community"]):
            entries.append(ChannelVideo(id=vid, url=full_url, title=title))

    return info, entries


class ChannelManager:
    def __init__(self, base_dir: Path | str = "./downloads"):
        # base_dir is the temporary downloads directory (kept for audio files)
        self.base_dir = Path(base_dir)
        # Channel JSON and transcripts must live under output/channels
        self.channels_root = Path("output") / "channels"
        self.channels_root.mkdir(parents=True, exist_ok=True)

    def _channel_dir_for(self, channel_key: str) -> Path:
        channel_dir = self.channels_root / channel_key
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir

    def _state_path_for(self, channel_key: str) -> Path:
        channel_dir = self.channels_root / channel_key
        channel_dir.mkdir(parents=True, exist_ok=True)
        return channel_dir / "state.json"

    def load_or_create_state(self, url: str) -> Tuple[ChannelState, str, Path]:
        info, entries = _extract_channel_entries(url)
        if not info:
            raise ValueError("Failed to extract channel information")

        channel_title = info.get("title") or info.get("channel") or "Unknown Channel"
        channel_key = _safe_channel_key(info, url)
        state_path = self._state_path_for(channel_key)

        if state_path.exists():
            with open(state_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            state = ChannelState.from_dict(raw)
            # If we have zero videos saved but extractor returned entries, populate
            if not state.videos and entries:
                state.videos = entries
                state.updated_at = _now_iso()
                self._save_state(state, state_path)
        else:
            state = ChannelState(
                channel_id=info.get("channel_id") or info.get("id") or channel_key,
                channel_title=channel_title,
                channel_url=url,
                created_at=_now_iso(),
                updated_at=_now_iso(),
                videos=entries,
                status={},
                last_index=0,
            )
            self._save_state(state, state_path)

        return state, channel_key, state_path

    def _save_state(self, state: ChannelState, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        state.updated_at = _now_iso()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(state.to_dict(), f, indent=2, ensure_ascii=False)

    def process(self, url: str, max_videos: Optional[int] = None, verbose: bool = False, translate_languages: Optional[List[str]] = None) -> None:
        state, channel_key, state_path = self.load_or_create_state(url)

        # Prepare services (downloads go to temporary downloads directory)
        downloader = YouTubeDownloader(output_directory="./downloads", audio_format="mp3", audio_quality="best", verbose=verbose)

        # Transcription service uses environment for keys and default model
        transcription_service = create_transcription_service(verbose=verbose)

        # Translation service (if needed)
        translator = None
        if translate_languages:
            from translator_normalizer import create_translator_normalizer
            translator = create_translator_normalizer(verbose=verbose)

        processed_count = 0

        for idx, video in enumerate(state.videos):
            status = state.status.get(video.id, {})
            
            # Check if we need to process this video
            needs_processing = False
            if not status.get("transcribed"):
                needs_processing = True
            elif translate_languages:
                # Check if all requested translations exist
                translations = status.get("translations", {})
                for lang in translate_languages:
                    if lang not in translations or not translations[lang].get("completed"):
                        needs_processing = True
                        break
            
            if not needs_processing:
                continue

            # Respect max_videos bound
            if max_videos is not None and processed_count >= max_videos:
                break

            print(f"\n{'='*60}")
            print(f"📹 Processing video {idx+1}/{len(state.videos)}: {video.title}")
            print(f"{'='*60}")

            # Download audio if not already downloaded
            audio_id = status.get("audio_id")
            if not status.get("downloaded") or not audio_id:
                result = downloader.download_audio(video.url)
                if not result.success or not result.audio_id:
                    state.status[video.id] = {
                        "downloaded": False,
                        "transcribed": False,
                        "error": result.error_message or "download_failed",
                    }
                    self._save_state(state, state_path)
                    continue

                audio_id = result.audio_id
                state.status.setdefault(video.id, {})
                state.status[video.id].update({
                    "downloaded": True,
                    "audio_id": audio_id,
                    "error": None,
                })
                self._save_state(state, state_path)

            # Transcribe if not already transcribed
            transcript_path = None
            if not status.get("transcribed"):
                try:
                    trans_result = transcription_service.transcribe_audio(audio_id)
                    if trans_result.success:
                        # Save transcript into channel folder
                        channel_dir = self._channel_dir_for(channel_key)
                        transcript_path = channel_dir / f"{audio_id}_transcript.txt"

                        # Get metadata for rich header
                        metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
                        video_metadata = metadata_manager.get_metadata(audio_id)

                        # Calculate statistics
                        word_count = len(trans_result.full_transcript.split())
                        char_count = len(trans_result.full_transcript)
                        char_count_no_spaces = len(trans_result.full_transcript.replace(' ', ''))

                        with open(transcript_path, 'w', encoding='utf-8') as f:
                            f.write("="*80 + "\n")
                            f.write("🎥 YOUTUBE VIDEO TRANSCRIPTION\n")
                            f.write("="*80 + "\n\n")

                            if video_metadata:
                                f.write("📺 VIDEO INFORMATION:\n")
                                f.write("-" * 40 + "\n")
                                f.write(f"Title: {video_metadata.title}\n")
                                f.write(f"URL: {video_metadata.original_url}\n")
                                f.write(f"Uploader: {video_metadata.uploader}\n")
                                f.write(f"Duration: {video_metadata.duration}\n")
                                if video_metadata.upload_date:
                                    try:
                                        upload_date = datetime.strptime(video_metadata.upload_date, '%Y%m%d').strftime('%B %d, %Y')
                                        f.write(f"Upload Date: {upload_date}\n")
                                    except:
                                        f.write(f"Upload Date: {video_metadata.upload_date}\n")
                                if video_metadata.view_count:
                                    f.write(f"Views: {video_metadata.view_count:,}\n")
                                f.write(f"Audio Format: {video_metadata.audio_format.upper()}\n")
                                f.write(f"Audio Quality: {video_metadata.audio_quality.title()}\n")
                                f.write(f"Downloaded: {video_metadata.download_date}\n")
                                f.write("\n")

                            f.write("🤖 TRANSCRIPTION INFORMATION:\n")
                            f.write("-" * 40 + "\n")
                            f.write(f"Audio ID: {trans_result.audio_id}\n")
                            f.write(f"Model: {trans_result.model_used}\n")
                            f.write(f"Processing Time: {trans_result.processing_time:.2f} seconds\n")
                            f.write(f"File Size: {trans_result.file_size_mb:.2f} MB\n")
                            if trans_result.optimization_applied:
                                f.write(f"Optimization: {trans_result.optimization_applied.replace('_', ' ').title()}\n")
                            if trans_result.total_chunks > 1:
                                f.write(f"Chunks Processed: {trans_result.total_chunks}\n")
                                if trans_result.failed_chunks > 0:
                                    f.write(f"Failed Chunks: {trans_result.failed_chunks}\n")
                            if trans_result.language:
                                f.write(f"Detected Language: {trans_result.language}\n")
                            f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                            f.write("\n")

                            f.write("📊 TRANSCRIPT STATISTICS:\n")
                            f.write("-" * 40 + "\n")
                            f.write(f"Total Words: {word_count:,}\n")
                            f.write(f"Total Characters: {char_count:,}\n")
                            f.write(f"Characters (no spaces): {char_count_no_spaces:,}\n")
                            if video_metadata and video_metadata.duration:
                                try:
                                    duration_parts = video_metadata.duration.split(':')
                                    if len(duration_parts) == 2:
                                        total_minutes = int(duration_parts[0]) + int(duration_parts[1]) / 60
                                    elif len(duration_parts) == 3:
                                        total_minutes = int(duration_parts[0]) * 60 + int(duration_parts[1]) + int(duration_parts[2]) / 60
                                    else:
                                        total_minutes = 0
                                    if total_minutes > 0:
                                        words_per_minute = word_count / total_minutes
                                        f.write(f"Words per Minute: {words_per_minute:.1f}\n")
                                except:
                                    pass
                            f.write("\n")

                            f.write("="*80 + "\n")
                            f.write("📝 TRANSCRIPT CONTENT:\n")
                            f.write("="*80 + "\n\n")
                            f.write(trans_result.full_transcript)
                            f.write("\n\n")
                            f.write("="*80 + "\n")
                            f.write("End of Transcript\n")
                            f.write("="*80 + "\n")

                        # Update state
                        state.status[video.id].update({
                            "transcribed": True,
                            "transcript_chars": len(trans_result.full_transcript or ""),
                            "transcript_file": str(transcript_path),
                        })
                        self._save_state(state, state_path)
                    else:
                        state.status[video.id].update({
                            "transcribed": False,
                            "error": trans_result.error_message or "transcription_failed",
                        })
                        self._save_state(state, state_path)
                        continue
                except TranscriptionError as e:
                    state.status[video.id].update({
                        "transcribed": False,
                        "error": str(e),
                    })
                    self._save_state(state, state_path)
                    continue
            else:
                # Already transcribed, load the path
                transcript_path = Path(status.get("transcript_file", ""))
                if not transcript_path.exists():
                    # Try to reconstruct the path
                    channel_dir = self._channel_dir_for(channel_key)
                    transcript_path = channel_dir / f"{audio_id}_transcript.txt"

            # Translation step (if requested)
            if translate_languages and transcript_path and transcript_path.exists():
                # Ensure translations dictionary exists
                if "translations" not in state.status[video.id]:
                    state.status[video.id]["translations"] = {}
                
                for language in translate_languages:
                    # Check if this language is already translated
                    lang_status = state.status[video.id]["translations"].get(language, {})
                    if lang_status.get("completed"):
                        print(f"    ✅ Already translated to {language}")
                        continue
                    
                    print(f"\n    🌍 Translating to {language}...")
                    try:
                        # Create a mock object with the language pre-selected
                        class MockTranslator:
                            def __init__(self, translator, target_lang):
                                self.translator = translator
                                self.target_lang = target_lang
                            
                            def translate_transcript(self, transcript_file, skip_translation=False):
                                # Temporarily override language selection
                                original_select = self.translator._select_target_language
                                self.translator._select_target_language = lambda: self.target_lang
                                try:
                                    result = self.translator.translate_transcript(transcript_file, skip_translation)
                                    return result
                                finally:
                                    self.translator._select_target_language = original_select
                        
                        mock_translator = MockTranslator(translator, language)
                        translation_result = mock_translator.translate_transcript(transcript_path, skip_translation=False)
                        
                        if translation_result.success:
                            # Save translation to channel folder
                            channel_dir = self._channel_dir_for(channel_key)
                            translated_filename = f"{audio_id}_translated_{language}.txt"
                            translated_path = channel_dir / translated_filename
                            
                            # Save the translation (handles both initial and reprocessed)
                            success, reprocessed_path = translator.save_translated_transcript(
                                translation_result, 
                                translated_path, 
                                transcript_path
                            )
                            
                            if success:
                                print(f"        ✅ Translation to {language} completed")
                                print(f"        📄 Saved to: {translated_path.name}")
                                if reprocessed_path:
                                    print(f"        📄 Reprocessed: {reprocessed_path.name}")
                                
                                # Update state
                                state.status[video.id]["translations"][language] = {
                                    "completed": True,
                                    "file": str(translated_path),
                                    "reprocessed_file": str(reprocessed_path) if reprocessed_path else None,
                                    "word_count_original": translation_result.word_count_original,
                                    "word_count_translated": translation_result.word_count_translated,
                                    "processing_time": translation_result.processing_time,
                                }
                            else:
                                print(f"        ❌ Failed to save translation for {language}")
                                state.status[video.id]["translations"][language] = {
                                    "completed": False,
                                    "error": "Failed to save translation"
                                }
                        else:
                            print(f"        ❌ Translation to {language} failed: {translation_result.error_message}")
                            state.status[video.id]["translations"][language] = {
                                "completed": False,
                                "error": translation_result.error_message
                            }
                    except Exception as e:
                        print(f"        ❌ Translation error for {language}: {str(e)}")
                        state.status[video.id]["translations"][language] = {
                            "completed": False,
                            "error": str(e)
                        }
                    
                    # Save state after each translation
                    self._save_state(state, state_path)
            
            processed_count += 1
            state.last_index = idx
            self._save_state(state, state_path)

        # Cleanup transcription service temp
        try:
            transcription_service.cleanup_temp_dir()
        except Exception:
            pass

        if verbose:
            print(f"Channel '{state.channel_title}' processed. Videos completed in this run: {processed_count}")

