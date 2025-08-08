"""
YouTube Audio Downloader Module

This module provides functionality for downloading audio from YouTube videos
using yt-dlp library. It handles URL validation, video information extraction,
and audio downloading with proper error handling.
"""

import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Union
from urllib.parse import urlparse, parse_qs

import yt_dlp
from yt_dlp.utils import DownloadError as YtDlpDownloadError
from audio_metadata import AudioMetadataManager, create_metadata_manager


class DownloadError(Exception):
    """Custom exception for download-related errors."""
    pass


@dataclass
class VideoInfo:
    """
    Data class containing basic information about a YouTube video.
    """
    title: str
    duration: str
    uploader: str
    upload_date: Optional[str] = None
    view_count: Optional[int] = None
    description: Optional[str] = None
    video_id: str = ""


@dataclass
class DownloadResult:
    """
    Data class containing results of a download operation.
    """
    success: bool
    audio_id: Optional[str] = None
    output_path: Optional[Path] = None
    file_size: Optional[int] = None
    duration: Optional[str] = None
    error_message: Optional[str] = None
    video_info: Optional[VideoInfo] = None


class YouTubeDownloader:
    """
    A robust YouTube audio downloader using yt-dlp.
    
    This class handles downloading audio from YouTube videos with various
    configuration options and comprehensive error handling.
    """
    
    # YouTube URL patterns for validation
    YOUTUBE_REGEX_PATTERNS = [
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/v/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?youtu\.be/([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/watch\?.*v=([a-zA-Z0-9_-]{11})',
        r'(?:https?://)?(?:www\.)?youtube\.com/shorts/([a-zA-Z0-9_-]{11})',
    ]
    
    def __init__(
        self,
        output_directory: Optional[Union[str, Path]] = None,
        audio_format: str = "mp3",
        audio_quality: str = "best",
        verbose: bool = False,
        metadata_file: Optional[str] = None
    ):
        """
        Initialize the YouTube downloader.
        
        Args:
            output_directory: Directory to save downloaded files
            audio_format: Audio format (mp3, wav, m4a)
            audio_quality: Audio quality preference (best, worst, medium)
            verbose: Enable verbose logging
            metadata_file: Path to metadata file (default: audio_metadata.json)
        """
        self.output_directory = Path(output_directory or "./downloads")
        self.audio_format = audio_format.lower()
        self.audio_quality = audio_quality.lower()
        self.verbose = verbose
        
        # Ensure output directory exists
        self.output_directory.mkdir(parents=True, exist_ok=True)
        
        # Initialize metadata manager
        if metadata_file:
            self.metadata_manager = create_metadata_manager(metadata_file)
        else:
            metadata_path = self.output_directory / "audio_metadata.json"
            self.metadata_manager = create_metadata_manager(str(metadata_path))
        
        # Initialize default options (will be configured per download)
        pass
    
    def _configure_ytdlp_options(self, audio_id: Optional[str] = None) -> Dict[str, Any]:
        """Configure yt-dlp options based on initialization parameters."""
        if audio_id:
            # Use safe filename with audio ID
            filename_template = f"{audio_id}.%(ext)s"
        else:
            # Fallback to original title (should not be used)
            filename_template = '%(title)s.%(ext)s'
            
        ytdlp_opts = {
            'format': 'bestaudio/best',
            'outtmpl': str(self.output_directory / filename_template),
            'extractaudio': True,
            'audioformat': self.audio_format,
            'audioquality': self._map_quality_to_ytdlp(),
            'noplaylist': True,
            'ignoreerrors': False,
            'no_warnings': not self.verbose,
            'quiet': not self.verbose,
            'writeinfojson': False,
            'writesubtitles': False,
            'writeautomaticsub': False,
        }
        
        # Add post-processor for audio conversion
        ytdlp_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': self.audio_format,
            'preferredquality': self._map_quality_to_bitrate(),
        }]
        
        return ytdlp_opts
    
    def _map_quality_to_ytdlp(self) -> str:
        """Map quality preference to yt-dlp format."""
        quality_map = {
            'best': '0',
            'medium': '5',
            'worst': '9'
        }
        return quality_map.get(self.audio_quality, '0')
    
    def _map_quality_to_bitrate(self) -> str:
        """Map quality preference to audio bitrate."""
        bitrate_map = {
            'best': '320',
            'medium': '192',
            'worst': '128'
        }
        return bitrate_map.get(self.audio_quality, '320')
    
    def validate_url(self, url: str) -> bool:
        """
        Validate if the provided URL is a valid YouTube video URL.
        
        Args:
            url: URL string to validate
            
        Returns:
            True if URL is valid YouTube video URL, False otherwise
        """
        if not url or not isinstance(url, str):
            return False
        
        # Check against all YouTube URL patterns
        for pattern in self.YOUTUBE_REGEX_PATTERNS:
            if re.match(pattern, url.strip()):
                return True
        
        return False
    
    def extract_video_id(self, url: str) -> Optional[str]:
        """
        Extract video ID from YouTube URL.
        
        Args:
            url: YouTube URL
            
        Returns:
            Video ID string or None if not found
        """
        for pattern in self.YOUTUBE_REGEX_PATTERNS:
            match = re.match(pattern, url.strip())
            if match:
                return match.group(1)
        return None
    
    def get_video_info(self, url: str) -> Optional[VideoInfo]:
        """
        Extract basic information about a YouTube video without downloading.
        
        Args:
            url: YouTube video URL
            
        Returns:
            VideoInfo object with video metadata or None if extraction fails
            
        Raises:
            DownloadError: If video information cannot be extracted
        """
        if not self.validate_url(url):
            raise DownloadError("Invalid YouTube URL provided")
        
        try:
            # Configure yt-dlp for info extraction only
            opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': False,
                'skip_download': True,
            }
            
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=False)
                
                if not info:
                    return None
                
                # Format duration
                duration = self._format_duration(info.get('duration', 0))
                
                return VideoInfo(
                    title=info.get('title', 'Unknown Title'),
                    duration=duration,
                    uploader=info.get('uploader', 'Unknown'),
                    upload_date=info.get('upload_date'),
                    view_count=info.get('view_count'),
                    description=info.get('description', ''),
                    video_id=info.get('id', '')
                )
                
        except YtDlpDownloadError as e:
            raise DownloadError(f"Failed to extract video information: {str(e)}")
        except Exception as e:
            raise DownloadError(f"Unexpected error extracting video info: {str(e)}")
    
    def download_audio(
        self, 
        url: str
    ) -> DownloadResult:
        """
        Download audio from a YouTube video.
        
        Args:
            url: YouTube video URL
            
        Returns:
            DownloadResult object containing download results
            
        Raises:
            DownloadError: If download fails
        """
        if not self.validate_url(url):
            return DownloadResult(
                success=False,
                error_message="Invalid YouTube URL provided"
            )
        
        try:
            # Get video info first
            video_info = self.get_video_info(url)
            
            # Generate unique audio ID
            audio_id = self.metadata_manager.generate_audio_id()
            
            # Configure yt-dlp with unique filename
            opts = self._configure_ytdlp_options(audio_id)
            # Enable yt-dlp's own progress display (remove quiet mode for downloads)
            opts['quiet'] = False
            opts['no_warnings'] = False
            
            # Perform download
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
            
            # Find the downloaded file using audio ID
            output_file = self._find_downloaded_file_by_id(audio_id)
            
            if output_file and output_file.exists():
                file_size = output_file.stat().st_size
                
                # Add metadata to manager
                self.metadata_manager.add_metadata(
                    audio_id=audio_id,
                    title=video_info.title if video_info else "Unknown Title",
                    original_url=url,
                    uploader=video_info.uploader if video_info else "Unknown",
                    duration=video_info.duration if video_info else "Unknown",
                    upload_date=video_info.upload_date if video_info else None,
                    view_count=video_info.view_count if video_info else None,
                    file_path=str(output_file),
                    file_size=file_size,
                    audio_format=self.audio_format,
                    audio_quality=self.audio_quality
                )
                
                return DownloadResult(
                    success=True,
                    audio_id=audio_id,
                    output_path=output_file,
                    file_size=file_size,
                    duration=video_info.duration if video_info else None,
                    video_info=video_info
                )
            else:
                return DownloadResult(
                    success=False,
                    error_message="Download completed but output file not found"
                )
                
        except YtDlpDownloadError as e:
            error_msg = str(e)
            
            # Provide more user-friendly error messages
            if "Video unavailable" in error_msg:
                error_msg = "Video is unavailable (may be private, deleted, or region-restricted)"
            elif "Sign in to confirm your age" in error_msg:
                error_msg = "Video is age-restricted and requires authentication"
            elif "Private video" in error_msg:
                error_msg = "Video is private and cannot be accessed"
            elif "This live event will begin in" in error_msg:
                error_msg = "This is a scheduled live stream that hasn't started yet"
            
            return DownloadResult(
                success=False,
                error_message=error_msg,
                video_info=video_info
            )
            
        except Exception as e:
            return DownloadResult(
                success=False,
                error_message=f"Unexpected error during download: {str(e)}",
                video_info=video_info
            )
    
    def _find_downloaded_file_by_id(self, audio_id: str) -> Optional[Path]:
        """
        Find the downloaded file by audio ID.
        
        Args:
            audio_id: Audio ID to search for
            
        Returns:
            Path to the downloaded file or None if not found
        """
        try:
            # Look for file with audio ID
            expected_file = self.output_directory / f"{audio_id}.{self.audio_format}"
            
            if expected_file.exists():
                return expected_file
            
            # Fallback: search for files starting with audio_id
            pattern = f"{audio_id}.*"
            files = list(self.output_directory.glob(pattern))
            
            if files:
                return files[0]  # Return first match
            
            return None
            
        except Exception:
            return None

    def _find_downloaded_file(self, title: str) -> Optional[Path]:
        """
        Legacy method: Find the downloaded file in the output directory.
        
        Args:
            title: Video title to help locate the file
            
        Returns:
            Path to the downloaded file or None if not found
        """
        try:
            # Look for files with the expected extension
            pattern = f"*.{self.audio_format}"
            files = list(self.output_directory.glob(pattern))
            
            if not files:
                return None
            
            # If we have a title, try to find the best match
            if title:
                # Sanitize title for comparison
                clean_title = re.sub(r'[^\w\s-]', '', title.lower())
                
                for file_path in files:
                    clean_filename = re.sub(r'[^\w\s-]', '', file_path.stem.lower())
                    if clean_title in clean_filename or clean_filename in clean_title:
                        return file_path
            
            # Return the most recently created file
            return max(files, key=lambda f: f.stat().st_ctime)
            
        except Exception:
            return None
    
    def _format_duration(self, seconds: Union[int, float]) -> str:
        """
        Format duration from seconds to human-readable string.
        
        Args:
            seconds: Duration in seconds
            
        Returns:
            Formatted duration string (e.g., "3:45", "1:23:45")
        """
        if not seconds or seconds <= 0:
            return "Unknown"
        
        try:
            seconds = int(seconds)
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            seconds = seconds % 60
            
            if hours > 0:
                return f"{hours}:{minutes:02d}:{seconds:02d}"
            else:
                return f"{minutes}:{seconds:02d}"
        except (ValueError, TypeError):
            return "Unknown"
    
    def cleanup_temp_files(self) -> None:
        """Clean up any temporary files created during download."""
        try:
            # Clean up any .part files (incomplete downloads)
            for part_file in self.output_directory.glob("*.part"):
                try:
                    part_file.unlink()
                except OSError:
                    pass
            
            # Clean up any .tmp files
            for tmp_file in self.output_directory.glob("*.tmp"):
                try:
                    tmp_file.unlink()
                except OSError:
                    pass
                    
        except Exception:
            # Silently ignore cleanup errors
            pass 