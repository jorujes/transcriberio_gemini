"""
Transcription Module

This module provides functionality for transcribing audio files using OpenAI's
gpt-4o-transcribe models. Implements smart file size optimization, retry logic,
and intelligent handling of both single files and chunked processing.
"""

import os
import time
import base64
import tempfile
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Dict, Any, Union, Tuple
import json
import logging
import math

try:
    import openai
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from pydub import AudioSegment
    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from audio_metadata import AudioMetadataManager, create_metadata_manager
from downloader import YouTubeDownloader

try:
    from api_client import create_api_client, DEFAULT_TRANSCRIPTION_MODEL, VALID_TRANSCRIPTION_MODELS
    API_CLIENT_AVAILABLE = True
except ImportError:
    API_CLIENT_AVAILABLE = False
    DEFAULT_TRANSCRIPTION_MODEL = "gemini-2.5-flash"  # Fallback
    VALID_TRANSCRIPTION_MODELS = ["gemini-2.5-flash", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"]


class TranscriptionError(Exception):
    """Custom exception for transcription-related errors."""
    pass


@dataclass
class TranscriptionSegment:
    """
    Data class representing a transcribed segment with timing information.
    """
    start_time: float
    end_time: float
    text: str
    confidence: Optional[float] = None
    tokens: Optional[List[Dict]] = None


@dataclass 
class TranscriptionResult:
    """
    Data class containing the complete transcription results.
    """
    success: bool
    audio_id: str
    full_transcript: str
    segments: List[TranscriptionSegment]
    language: Optional[str] = None
    model_used: str = DEFAULT_TRANSCRIPTION_MODEL
    processing_time: float = 0.0
    total_chunks: int = 1
    failed_chunks: int = 0
    file_size_mb: float = 0.0
    optimization_applied: Optional[str] = None
    error_message: Optional[str] = None


class TranscriptionService:
    """
    Service for transcribing audio files using OpenAI's gpt-4o-transcribe models.
    
    Implements intelligent file size optimization, retry logic, and handles both
    direct transcription and chunked processing for large files.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_TRANSCRIPTION_MODEL,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_file_size_mb: float = 25.0,
        chunk_duration: float = 30.0,
        chunk_overlap: float = 0.5,
        temp_dir: Optional[Path] = None,
        verbose: bool = False
    ):
        """
        Initialize the transcription service.
        
        Args:
            api_key: OpenAI API key (if None, uses OPENAI_API_KEY env var)
            model: Model to use ("gemini-2.5-flash", "gpt-4o-transcribe" or "gpt-4o-mini-transcribe")
            max_retries: Maximum number of retry attempts for failed API calls
            base_delay: Base delay for exponential backoff (seconds)
            max_file_size_mb: Maximum file size for direct processing (MB)
            chunk_duration: Duration for audio chunks when needed (seconds)
            chunk_overlap: Overlap between chunks when needed (seconds)
            temp_dir: Directory for temporary files
            verbose: Enable detailed logging
        """
        if not OPENAI_AVAILABLE:
            raise TranscriptionError(
                "OpenAI library not available. Install with: pip install openai>=1.54.0"
            )
        
        if not PYDUB_AVAILABLE:
            raise TranscriptionError(
                "Pydub library not available. Install with: pip install pydub>=0.25.0"
            )
            
        # Validate model choice
        if model not in VALID_TRANSCRIPTION_MODELS:
            raise TranscriptionError(f"Invalid model: {model}")
        
        self.model = model
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_file_size_mb = max_file_size_mb
        self.chunk_duration = chunk_duration
        self.chunk_overlap = chunk_overlap
        self.verbose = verbose
        
        # Set up temporary directory
        self.temp_dir = Path(temp_dir) if temp_dir else Path(tempfile.mkdtemp())
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize API client using UnifiedAPIClient
        # Import here to avoid circular imports
        from api_client import create_api_client
        
        self.client = create_api_client(model=model, verbose=verbose)
        
        # Set up logging
        self.logger = logging.getLogger(__name__)
        if verbose:
            self.logger.setLevel(logging.DEBUG)
        
    def transcribe_audio(
        self,
        audio_input: Union[str, Path],
        language: Optional[str] = None,
        prompt: Optional[str] = None
    ) -> TranscriptionResult:
        """
        Transcribe an audio file using the optimal strategy.
        
        Args:
            audio_input: Audio ID, file path, or Path object
            language: Language code (e.g., 'en', 'pt', 'es')
            prompt: Optional prompt to guide transcription
            
        Returns:
            TranscriptionResult with complete transcription data
        """
        start_time = time.time()
        
        try:
            # Resolve audio file path
            audio_path, audio_id = self._resolve_audio_input(audio_input)
            
            if not audio_path.exists():
                return TranscriptionResult(
                    success=False,
                    audio_id=audio_id,
                    full_transcript="",
                    segments=[],
                    error_message=f"Audio file not found: {audio_path}"
                )
            
            # Check file size and apply optimization strategy
            file_size_mb = audio_path.stat().st_size / (1024 * 1024)
            
            if self.verbose:
                self.logger.info(f"Processing audio file: {audio_path}")
                self.logger.info(f"File size: {file_size_mb:.2f} MB")
                
            # Apply optimization strategy based on file size
            optimized_path, optimization = self._optimize_audio_file(
                audio_path, audio_id, file_size_mb
            )
            
            final_file_size_mb = optimized_path.stat().st_size / (1024 * 1024)
            
            # Check audio duration (API limit: 1400 seconds = ~23 minutes)
            # But we must chunk earlier due to token output limits
            try:
                duration_seconds = self._get_audio_duration_efficient(optimized_path)
                max_duration_seconds = 1400  # API limit
                # CRITICAL: For safety, force chunking for videos >12 minutes (720 seconds)
                # This prevents exceeding gpt-4o-transcribe max_tokens even for shorter videos
                safe_duration_limit = 720  # 12 minutes - much more conservative
                
                if self.verbose:
                    self.logger.info(f"Audio duration: {duration_seconds:.1f} seconds ({duration_seconds/60:.1f} minutes)")
                    
            except Exception as e:
                if self.verbose:
                    self.logger.warning(f"Could not check duration: {e}")
                duration_seconds = 0
                max_duration_seconds = 1400
                safe_duration_limit = 720
            
            # Choose transcription strategy (check both size AND conservative duration)
            # ALWAYS chunk if video is >12 minutes, regardless of file size
            if (final_file_size_mb <= self.max_file_size_mb and 
                duration_seconds <= safe_duration_limit):
                # Direct transcription (optimal path - only for short videos ≤12 min)
                if self.verbose:
                    self.logger.info(f"Using direct transcription: {duration_seconds/60:.1f} min ≤ {safe_duration_limit/60:.1f} min safe limit")
                result = self._transcribe_direct(
                    optimized_path, audio_id, language, prompt
                )
            else:
                # Chunked transcription (fallback for size OR duration)
                import math
                
                # Calculate chunks needed and explain to user why chunking is required
                chunks_needed = math.ceil(duration_seconds / safe_duration_limit) if duration_seconds > safe_duration_limit else 1
                
                reasons = []
                if final_file_size_mb > self.max_file_size_mb:
                    reasons.append(f"file size {final_file_size_mb:.1f}MB exceeds API limit ({self.max_file_size_mb}MB)")
                if duration_seconds > safe_duration_limit:
                    reasons.append(f"duration {duration_seconds/60:.1f} minutes exceeds safe limit ({safe_duration_limit/60:.1f} minutes)")
                if duration_seconds > max_duration_seconds:
                    reasons.append(f"duration {duration_seconds/60:.1f} minutes exceeds absolute API limit ({max_duration_seconds/60:.1f} minutes)")
                
                reason_text = " and ".join(reasons)
                print(f"📋 Using chunking strategy: {reason_text}")
                # Note: Actual chunk count will be determined by ultra-conservative chunking strategy
                
                if self.verbose:
                    if final_file_size_mb > self.max_file_size_mb:
                        self.logger.info(f"Using chunking: file size {final_file_size_mb:.1f}MB > {self.max_file_size_mb}MB")
                    if duration_seconds > safe_duration_limit:
                        self.logger.info(f"Using chunking: duration {duration_seconds:.1f}s > {safe_duration_limit}s (safe limit)")
                    if duration_seconds > max_duration_seconds:
                        self.logger.info(f"Using chunking: duration {duration_seconds:.1f}s > {max_duration_seconds}s (absolute limit)")
                
                result = self._transcribe_chunked(
                    optimized_path, audio_id, language, prompt
                )
            
            # Add processing metadata
            result.processing_time = time.time() - start_time
            result.file_size_mb = final_file_size_mb
            result.optimization_applied = optimization
            
            # Cleanup temporary files if different from original
            if optimized_path != audio_path:
                self._cleanup_temp_file(optimized_path)
                
            return result
            
        except Exception as e:
            return TranscriptionResult(
                success=False,
                audio_id=audio_id if 'audio_id' in locals() else "unknown",
                full_transcript="",
                segments=[],
                processing_time=time.time() - start_time,
                error_message=f"Transcription failed: {str(e)}"
            )
    
    def _resolve_audio_input(self, audio_input: Union[str, Path]) -> Tuple[Path, str]:
        """
        Resolve audio input to file path and audio ID.
        For video files, extracts audio first to ensure efficient processing.
        
        Returns:
            Tuple of (audio_path, audio_id)
        """
        if isinstance(audio_input, Path):
            input_path = audio_input
            audio_id = audio_input.stem
        else:
            audio_input_str = str(audio_input)
            
            # Try to resolve as audio ID
            try:
                metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
                metadata = metadata_manager.get_metadata(audio_input_str)
                
                if metadata:
                    return Path(metadata.file_path), audio_input_str
            except:
                pass
            
            # Treat as file path
            input_path = Path(audio_input_str)
            audio_id = input_path.stem
        
        # Check if this is a video file that needs audio extraction
        video_extensions = {'.mov', '.mp4', '.avi', '.mkv', '.webm', '.m4v', '.flv', '.wmv'}
        if input_path.suffix.lower() in video_extensions:
            print(f"🎬 Detected video file: {input_path.name}")
            print(f"📂 Original size: {input_path.stat().st_size / (1024 * 1024):.1f}MB")
            
            # Extract audio to temporary location
            extracted_audio_path = self._extract_audio_from_video(input_path, audio_id)
            if extracted_audio_path:
                extracted_size_mb = extracted_audio_path.stat().st_size / (1024 * 1024)
                print(f"🎵 Extracted audio: {extracted_size_mb:.1f}MB")
                print(f"📉 Size reduction: {100 * (1 - extracted_size_mb / (input_path.stat().st_size / (1024 * 1024))):.1f}%")
                return extracted_audio_path, audio_id
            else:
                print("⚠️  Audio extraction failed, processing original file")
                return input_path, audio_id
        
        # Return as-is for audio files
        return input_path, audio_id
    
    def _extract_audio_from_video(self, video_path: Path, audio_id: str) -> Optional[Path]:
        """
        Extract audio from video file using FFmpeg.
        Similar to yt-dlp's audio extraction but for local files.
        
        Returns:
            Path to extracted audio file or None if extraction fails
        """
        import subprocess
        import shutil
        
        try:
            # Check if FFmpeg is available
            if not shutil.which("ffmpeg"):
                if self.verbose:
                    self.logger.warning("FFmpeg not found, cannot extract audio from video")
                return None
            
            print("🎵 Extracting audio from video file...")
            
            # Create output path in temp directory
            extracted_audio_path = self.temp_dir / f"{audio_id}_extracted.mp3"
            
            # FFmpeg command for audio extraction
            # -i: input video file
            # -vn: no video (audio only)
            # -acodec mp3: use MP3 codec
            # -ab 320k: high quality audio bitrate
            # -ar 44100: standard sample rate
            # -y: overwrite output
            cmd = [
                "ffmpeg",
                "-i", str(video_path),
                "-vn",                # No video
                "-acodec", "mp3",     # MP3 codec
                "-ab", "320k",        # High quality bitrate
                "-ar", "44100",       # Standard sample rate
                "-y",                 # Overwrite
                str(extracted_audio_path)
            ]
            
            if self.verbose:
                self.logger.info(f"Extracting audio: {' '.join(cmd)}")
            
            # Run FFmpeg with progress feedback
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Simple progress indicator for extraction
            print("🔄 Extracting audio (this is much faster than compression)...")
            
            # Wait for process to complete
            stdout, stderr = process.communicate()
            
            # Check if extraction was successful
            if process.returncode != 0:
                if self.verbose:
                    self.logger.warning(f"FFmpeg extraction failed: {stderr}")
                print(f"❌ Audio extraction failed (return code {process.returncode})")
                return None
                
            if not extracted_audio_path.exists():
                if self.verbose:
                    self.logger.warning("FFmpeg completed but extracted audio file not found")
                print("❌ Audio extraction completed but file not found")
                return None
            
            print("✅ Audio extraction completed successfully")
            return extracted_audio_path
            
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Audio extraction failed: {e}")
            print(f"❌ Audio extraction error: {e}")
            return None
    
    def _optimize_audio_file(
        self, 
        audio_path: Path, 
        audio_id: str, 
        file_size_mb: float
    ) -> Tuple[Path, Optional[str]]:
        """
        Apply size optimization strategy to audio file.
        
        Returns:
            Tuple of (optimized_path, optimization_description)
        """
        if file_size_mb <= self.max_file_size_mb:
            return audio_path, None
            
        # Show clear user feedback about optimization process
        print(f"📊 File size {file_size_mb:.1f}MB exceeds limit ({self.max_file_size_mb}MB)")
        print("🔄 Applying optimization strategy...")
        
        if self.verbose:
            self.logger.info(f"File size {file_size_mb:.2f}MB exceeds limit. Applying optimization...")
        
        # Strategy 1: Check if chunking will solve the size problem without compression
        try:
            duration_seconds = self._get_audio_duration_efficient(audio_path)
            safe_duration_limit = 720  # 12 minutes
            
            if duration_seconds > safe_duration_limit:
                # We'll need chunking anyway, so calculate if chunks will be small enough
                import math
                chunks_needed = math.ceil(duration_seconds / safe_duration_limit)
                estimated_chunk_size_mb = file_size_mb / chunks_needed
                
                if estimated_chunk_size_mb <= self.max_file_size_mb:
                    print(f"🎯 Smart optimization: Skipping compression - chunking strategy will handle file size")
                    if self.verbose:
                        self.logger.info(f"Skipping compression - chunking will create manageable chunk sizes (~{estimated_chunk_size_mb:.1f}MB each)")
                    return audio_path, "chunking_optimized"
                else:
                    print(f"🎯 Strategy 1: Even with chunking ({chunks_needed} chunks), estimated chunk size {estimated_chunk_size_mb:.1f}MB > {self.max_file_size_mb}MB")
                    print("🗜️  Strategy 2: Compression needed before chunking")
            else:
                print("🗜️  Strategy 1: File needs compression for direct transcription")
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Duration check failed, proceeding with compression: {e}")
            print("🗜️  Strategy 1: Compressing audio for API upload")
        
        # Strategy 2: Try compression
        compressed_path = self._try_compression(audio_path)
        if compressed_path:
            compressed_size_mb = compressed_path.stat().st_size / (1024 * 1024)
            if compressed_size_mb <= self.max_file_size_mb:
                print(f"✅ Compression successful! New size: {compressed_size_mb:.1f}MB")
                if self.verbose:
                    self.logger.info(f"Compression successful: {compressed_size_mb:.2f}MB")
                return compressed_path, "compression"
            else:
                print(f"⚠️  Compressed file still too large: {compressed_size_mb:.1f}MB")
        else:
            print("⚠️  Compression failed")
        
        # Strategy 3: Will need chunking (return original or compressed)
        print("🧩 Final strategy: Using chunking for multiple API calls")
        if self.verbose:
            self.logger.info("Optimization failed, will use chunking strategy")
        return audio_path, "chunking_required"
    
    def _try_redownload_medium_quality(
        self, 
        audio_id: str, 
        original_path: Path
    ) -> Optional[Path]:
        """
        Try to re-download audio in medium quality if it's from YouTube.
        """
        try:
            # Check if this is a YouTube-downloaded file with metadata
            metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
            metadata = metadata_manager.get_metadata(audio_id)
            
            if not metadata or not hasattr(metadata, 'original_url'):
                return None
                
            if self.verbose:
                self.logger.info("Attempting re-download in medium quality...")
            
            # Set up downloader for medium quality
            downloader = YouTubeDownloader(
                output_directory=original_path.parent,
                audio_format="mp3",
                audio_quality="medium",
                metadata_file=str(metadata_manager.metadata_file)
            )
            
            # Download in medium quality
            result = downloader.download_audio(metadata.original_url)
            
            if result.success and result.output_path:
                # Rename the new file to maintain the original audio_id
                new_file_path = Path(result.output_path)
                
                # Remove original file
                if original_path.exists():
                    original_path.unlink()
                
                # Rename new file to original name (maintain audio_id)
                final_path = original_path  # Keep original path/name
                new_file_path.rename(final_path)
                
                # Update the ORIGINAL metadata with new quality info
                metadata.audio_quality = "medium"
                metadata.file_size = final_path.stat().st_size
                
                # Remove the NEW metadata entry (we don't want duplicate)
                if result.audio_id != audio_id:
                    metadata_manager.metadata.pop(result.audio_id, None)
                
                # Save updated metadata
                metadata_manager.save_metadata()
                
                if self.verbose:
                    self.logger.info(f"Re-download completed and renamed to: {final_path}")
                    
                return final_path  # Return original path with optimized content
            
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Re-download failed: {e}")
        
        return None
    
    def _try_compression(self, audio_path: Path) -> Optional[Path]:
        """
        Try to compress audio file using FFmpeg directly (efficient, low memory).
        Applies: mono, reduced sample rate, low bitrate.
        """
        import subprocess
        import shutil
        import time
        import threading
        
        try:
            # Show initial compression info
            original_size_mb = audio_path.stat().st_size / (1024 * 1024)
            print(f"🗜️  Starting audio compression: {original_size_mb:.1f}MB → target ~64kbps")
            print(f"⚙️  Compression settings: mono, 22kHz, 64kbps bitrate")
            
            if self.verbose:
                self.logger.info("Attempting audio compression using FFmpeg...")
            
            # Check if FFmpeg is available
            if not shutil.which("ffmpeg"):
                if self.verbose:
                    self.logger.warning("FFmpeg not found, falling back to PyDub compression")
                print("⚠️  FFmpeg not found - using PyDub fallback (slower)")
                return self._try_compression_pydub_fallback(audio_path)
                
            # Create temp compressed file
            temp_compressed_path = self.temp_dir / f"compressed_{audio_path.name}"
            
            # FFmpeg command for efficient compression
            # -i: input file
            # -ac 1: mono (1 channel)
            # -ar 22050: sample rate 22kHz
            # -ab 64k: bitrate 64kbps  
            # -y: overwrite output
            # -progress pipe:1: show progress information
            cmd = [
                "ffmpeg",
                "-i", str(audio_path),
                "-ac", "1",           # Mono
                "-ar", "22050",       # 22kHz sample rate
                "-ab", "64k",         # 64kbps bitrate
                "-progress", "pipe:1", # Progress output
                "-v", "warning",      # Only warnings and errors
                "-y",                 # Overwrite
                str(temp_compressed_path)
            ]
            
            # Get audio duration for progress calculation
            print("🔄 Compressing audio file...")
            start_time = time.time()
            
            # Get total duration first
            try:
                duration_seconds = self._get_audio_duration_efficient(audio_path)
                if duration_seconds <= 0:
                    duration_seconds = None
            except:
                duration_seconds = None
            
            # Start compression process
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            # Monitor FFmpeg progress in real-time
            def monitor_ffmpeg_progress():
                current_time = 0
                last_update = time.time()
                
                for line in iter(process.stdout.readline, ''):
                    if not line:
                        break
                    
                    line = line.strip()
                    
                    # Parse out_time_us (microseconds) for current position
                    if line.startswith('out_time_us='):
                        try:
                            microseconds = int(line.split('=')[1])
                            current_time = microseconds / 1_000_000  # Convert to seconds
                            
                            # Update progress every 2 seconds to avoid spam
                            now = time.time()
                            if now - last_update >= 2.0:
                                if duration_seconds and duration_seconds > 0:
                                    progress_percent = min(100, (current_time / duration_seconds) * 100)
                                    elapsed = now - start_time
                                    
                                    # Estimate remaining time
                                    if progress_percent > 5:  # Avoid division by very small numbers
                                        eta_seconds = (elapsed / (progress_percent / 100)) - elapsed
                                        eta_str = f" (ETA: {eta_seconds:.0f}s)" if eta_seconds > 0 else ""
                                    else:
                                        eta_str = ""
                                    
                                    print(f"\r🗜️  Compressing: {progress_percent:.1f}% ({current_time:.0f}s/{duration_seconds:.0f}s){eta_str}", end="", flush=True)
                                else:
                                    # No duration info, just show time processed
                                    print(f"\r🗜️  Compressing: {current_time:.0f}s processed", end="", flush=True)
                                
                                last_update = now
                        except (ValueError, IndexError):
                            pass
            
            # Start progress monitoring in separate thread
            progress_thread = threading.Thread(target=monitor_ffmpeg_progress)
            progress_thread.daemon = True
            progress_thread.start()
            
            # Wait for process to complete
            stderr_output = []
            for line in iter(process.stderr.readline, ''):
                if line.strip():
                    stderr_output.append(line.strip())
            
            process.wait()  # Wait for process to finish
            progress_thread.join(timeout=1)  # Wait for progress thread to finish
            
            print("\r" + " " * 80 + "\r", end="")  # Clear progress line
            
            elapsed_time = time.time() - start_time
            
            # Check if compression was successful
            if process.returncode != 0:
                print(f"❌ FFmpeg compression failed (return code {process.returncode})")
                if stderr_output and self.verbose:
                    self.logger.warning(f"FFmpeg error: {' '.join(stderr_output)}")
                return None
                
            if not temp_compressed_path.exists():
                print("❌ Compression completed but output file not found")
                if self.verbose:
                    self.logger.warning("FFmpeg completed but output file not found")
                return None
            
            # Show compression results
            compressed_size_mb = temp_compressed_path.stat().st_size / (1024 * 1024)
            compression_ratio = (1 - compressed_size_mb / original_size_mb) * 100
            
            print(f"✅ Compression completed in {elapsed_time:.1f}s")
            print(f"📊 Size reduction: {original_size_mb:.1f}MB → {compressed_size_mb:.1f}MB ({compression_ratio:.1f}% smaller)")
            
            if self.verbose:
                self.logger.info(
                    f"FFmpeg compression: {original_size_mb:.2f}MB → {compressed_size_mb:.2f}MB "
                    f"({compression_ratio:.1f}% reduction) in {elapsed_time:.1f}s"
                )
            
            # Replace original file with compressed version (maintain same path/name)
            audio_path.unlink()  # Remove original
            temp_compressed_path.rename(audio_path)  # Rename compressed to original name
            
            return audio_path  # Return original path with compressed content
            
        except Exception as e:
            print(f"❌ FFmpeg compression error: {e}")
            if self.verbose:
                self.logger.warning(f"FFmpeg compression failed: {e}")
            print("🔄 Trying PyDub fallback compression...")
            # Try PyDub fallback
            return self._try_compression_pydub_fallback(audio_path)
        
    def _try_compression_pydub_fallback(self, audio_path: Path) -> Optional[Path]:
        """
        Fallback compression using PyDub (higher memory usage).
        Only used when FFmpeg is not available.
        """
        import time
        
        try:
            # Show initial compression info
            original_size_mb = audio_path.stat().st_size / (1024 * 1024)
            print(f"🗜️  PyDub compression fallback: {original_size_mb:.1f}MB (higher memory usage)")
            print(f"⚙️  Settings: mono, 22kHz, 64kbps - loading file into memory...")
            
            if self.verbose:
                self.logger.info("Using PyDub fallback compression (higher memory usage)...")
            
            start_time = time.time()
            
            # Load audio (this loads entire file into memory)
            print("📂 Loading audio file into memory...")
            audio = AudioSegment.from_file(audio_path)
            
            # Apply compression: mono, reduced bitrate
            print("🔄 Applying compression (mono, 22kHz)...")
            compressed_audio = audio.set_channels(1).set_frame_rate(22050)
            
            # Save compressed version to temp location first
            print("💾 Exporting compressed audio...")
            temp_compressed_path = self.temp_dir / f"compressed_{audio_path.name}"
            compressed_audio.export(
                temp_compressed_path,
                format="mp3",
                bitrate="64k"
            )
            
            elapsed_time = time.time() - start_time
            
            # Show compression results
            compressed_size_mb = temp_compressed_path.stat().st_size / (1024 * 1024)
            compression_ratio = (1 - compressed_size_mb / original_size_mb) * 100
            
            print(f"✅ PyDub compression completed in {elapsed_time:.1f}s")
            print(f"📊 Size reduction: {original_size_mb:.1f}MB → {compressed_size_mb:.1f}MB ({compression_ratio:.1f}% smaller)")
            
            if self.verbose:
                self.logger.info(
                    f"PyDub compression: {original_size_mb:.2f}MB → {compressed_size_mb:.2f}MB "
                    f"({compression_ratio:.1f}% reduction) in {elapsed_time:.1f}s"
                )
            
            # Replace original file with compressed version (maintain same path/name)
            audio_path.unlink()  # Remove original
            temp_compressed_path.rename(audio_path)  # Rename compressed to original name
            
            return audio_path  # Return original path with compressed content
            
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"PyDub compression failed: {e}")
        
        return None
    
    def _get_audio_duration_efficient(self, audio_path: Path) -> float:
        """
        Get audio duration using FFprobe (no memory loading).
        Much more efficient than loading entire file with PyDub.
        """
        import subprocess
        import shutil
        
        try:
            # Check if FFprobe is available (comes with FFmpeg)
            if not shutil.which("ffprobe"):
                if self.verbose:
                    self.logger.warning("FFprobe not found, falling back to PyDub")
                # Fallback to PyDub (will load into memory)
                audio = AudioSegment.from_file(audio_path)
                return len(audio) / 1000.0
                
            # Use FFprobe to get duration efficiently
            cmd = [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(audio_path)
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=10  # Timeout to prevent hanging
            )
            
            if result.returncode == 0 and result.stdout.strip():
                duration = float(result.stdout.strip())
                return duration
            else:
                if self.verbose:
                    self.logger.warning(f"FFprobe failed, falling back to PyDub")
                # Fallback to PyDub
                audio = AudioSegment.from_file(audio_path)
                return len(audio) / 1000.0
                
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Duration check failed: {e}, falling back to PyDub")
            # Fallback to PyDub
            audio = AudioSegment.from_file(audio_path)
            return len(audio) / 1000.0
    
    def _create_intelligent_chunks_ffmpeg(self, audio_path: Path, total_duration: float, effective_duration_limit: float) -> List[Tuple[Any, float, float]]:
        """
        Create audio chunks using FFmpeg directly (streaming, no memory loading).
        Uses MINIMAL chunking strategy - only creates as many chunks as necessary.
        """
        import subprocess
        import shutil
        import math
        
        chunks = []
        
        # Calculate MINIMUM chunks needed based on API limits
        max_duration_per_chunk = effective_duration_limit  # Use the effective limit
        chunks_needed = math.ceil(total_duration / max_duration_per_chunk)
        
        # Calculate optimal chunk duration (divide total time evenly)
        optimal_chunk_duration = total_duration / chunks_needed
        
        # Use minimal overlap only if chunks are very close to limit
        chunk_overlap = 0.5 if optimal_chunk_duration > 1350 else 0.0
        
        if self.verbose:
            self.logger.info(f"Optimized chunking: {chunks_needed} chunks of ~{optimal_chunk_duration/60:.1f} minutes each")
        print(f"🎯 Strategy: {chunks_needed} chunks of ~{optimal_chunk_duration/60:.1f} minutes each")
        
        chunk_duration = optimal_chunk_duration
        
        # Calculate chunk positions
        current_pos = 0.0
        chunk_index = 0
        
        while current_pos < total_duration:
            start_time = current_pos
            end_time = min(current_pos + chunk_duration, total_duration)
            actual_duration = end_time - start_time
            
            # Skip very short chunks at the end
            if actual_duration < 1.0:
                break
                
            # Create chunk using FFmpeg (efficient streaming)
            chunk_path = self.temp_dir / f"chunk_{chunk_index:03d}.mp3"
            
            try:
                if shutil.which("ffmpeg"):
                    # Use FFmpeg for efficient chunk extraction
                    cmd = [
                        "ffmpeg",
                        "-i", str(audio_path),
                        "-ss", str(start_time),          # Start time
                        "-t", str(actual_duration),      # Duration
                        "-ac", "1",                      # Mono
                        "-ar", "22050",                  # 22kHz
                        "-ab", "128k",                   # 128kbps
                        "-avoid_negative_ts", "make_zero",  # Reset timestamps
                        "-reset_timestamps", "1",        # Reset timestamps to start from 0
                        "-y",                            # Overwrite
                        str(chunk_path)
                    ]
                    
                    result = subprocess.run(
                        cmd,
                        text=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL
                    )
                    
                    if result.returncode == 0 and chunk_path.exists():
                        # Create a fake AudioSegment-like object for compatibility
                        class FFmpegChunk:
                            def __init__(self, path):
                                self.path = path
                            def export(self, path, **kwargs):
                                # Files are already in the right format
                                if path != self.path:
                                    shutil.copy2(self.path, path)
                        
                        chunk_audio = FFmpegChunk(chunk_path)
                        chunks.append((chunk_audio, start_time, end_time))
                        
                        if self.verbose:
                            self.logger.info(f"Created chunk {chunk_index}: {start_time:.1f}s-{end_time:.1f}s ({actual_duration:.1f}s)")
                    else:
                        if self.verbose:
                            self.logger.warning(f"FFmpeg chunk creation failed for chunk {chunk_index}")
                        break
                else:
                    # Fallback to PyDub (will use more memory)
                    if self.verbose:
                        self.logger.warning("FFmpeg not available, using PyDub fallback")
                    return self._create_intelligent_chunks_pydub_fallback(audio_path, total_duration)
                    
            except Exception as e:
                if self.verbose:
                    self.logger.error(f"Error creating chunk {chunk_index}: {e}")
                break
            
            # Move to next chunk position - FIXED: ensure we don't skip audio at the end
            chunk_index += 1
            if chunk_index >= chunks_needed:
                # We've created all the chunks we calculated we need
                break
            
            # For intermediate chunks, advance by full duration minus overlap
            # For the last chunk, we'll process all remaining audio
            if chunk_index < chunks_needed - 1:
                current_pos += chunk_duration - chunk_overlap
            else:
                # Last chunk: start from where previous ended and go to the end
                current_pos = start_time + chunk_duration - chunk_overlap
        
        return chunks
    
    def _create_intelligent_chunks_pydub_fallback(self, audio_path: Path, total_duration: float) -> List[Tuple[Any, float, float]]:
        """
        Fallback chunking using PyDub (higher memory usage).
        Only used when FFmpeg is not available.
        """
        if self.verbose:
            self.logger.warning("Using PyDub fallback for chunking (high memory usage)")
            
        # Load entire file into memory (high memory usage)
        audio = AudioSegment.from_file(audio_path)
        
        chunks = []
        chunk_duration_ms = int(self.chunk_duration * 1000)
        overlap_ms = int(self.chunk_overlap * 1000)
        current_pos_ms = 0
        
        while current_pos_ms < len(audio):
            end_pos_ms = min(current_pos_ms + chunk_duration_ms, len(audio))
            
            # Extract chunk
            chunk_audio = audio[current_pos_ms:end_pos_ms]
            start_time = current_pos_ms / 1000.0
            end_time = end_pos_ms / 1000.0
            
            chunks.append((chunk_audio, start_time, end_time))
            
            # Move to next position
            current_pos_ms += chunk_duration_ms - overlap_ms
        
        return chunks
    
    def _transcribe_direct(
        self,
        audio_path: Path,
        audio_id: str,
        language: Optional[str],
        prompt: Optional[str],
        show_progress: bool = True
    ) -> TranscriptionResult:
        """
        Direct transcription for files <= 25MB (optimal path).
        """
        start_time = time.time()  # Track processing time
        
        if self.verbose:
            self.logger.info("Using direct transcription strategy")
        
        try:
            # Show user that we're sending to API (only if show_progress is True)
            if show_progress:
                file_size_mb = audio_path.stat().st_size / (1024 * 1024)
                print(f"📤 Sending {file_size_mb:.1f}MB file to transcription API...")
            
            # Make API call with retry logic
            response = self._make_api_call_with_retry(audio_path, language, prompt)
            
            # Parse response
            if response:
                transcript = response.text or ""
                detected_language = getattr(response, 'language', language)
                
                if transcript:
                    # Create segment from this chunk
                    segment = TranscriptionSegment(
                        text=transcript,
                        start_time=0.0,
                        end_time=0.0  # Will be set later if needed
                    )
                    
                    return TranscriptionResult(
                        success=True,
                        audio_id=audio_id,
                        full_transcript=transcript,
                        segments=[segment],
                        language=detected_language,
                        model_used=self.model,
                        processing_time=time.time() - start_time,
                        total_chunks=1,
                        failed_chunks=0,
                        file_size_mb=audio_path.stat().st_size / (1024 * 1024)
                    )
            else:
                return TranscriptionResult(
                    success=False,
                    audio_id=audio_id,
                    full_transcript="",
                    segments=[],
                    error_message="No response from API"
                )
                
        except Exception as e:
            return TranscriptionResult(
                success=False,
                audio_id=audio_id,
                full_transcript="",
                segments=[],
                error_message=f"Direct transcription failed: {str(e)}"
            )
    
    def _transcribe_chunked(
        self,
        audio_path: Path,
        audio_id: str,
        language: Optional[str],
        prompt: Optional[str]
    ) -> TranscriptionResult:
        """
        Chunked transcription for files > 25MB (fallback strategy).
        """
        if self.verbose:
            self.logger.info("Using chunked transcription strategy")
        
        try:
            # Get audio duration efficiently without loading entire file
            total_duration = self._get_audio_duration_efficient(audio_path)
            
            # Calculate optimal chunking strategy
            # CRITICAL: gpt-4o-transcribe has a 2048 token OUTPUT limit
            # Each token ≈ 0.75 words, so max ~1536 words per chunk
            # Audio ratio: ~2-3 words per second, so max ~8-10 minutes per chunk
            max_output_tokens = 2048
            words_per_token = 0.75
            words_per_second = 3.0  # More conservative estimate (was 2.5)
            max_words_per_chunk = max_output_tokens * words_per_token  # ~1536 words
            max_duration_per_chunk_tokens = max_words_per_chunk / words_per_second  # ~512 seconds ≈ 8.5 minutes
            
            # Be even MORE conservative - use only 60% of the calculated limit
            conservative_limit = max_duration_per_chunk_tokens * 0.60  # ~5.1 minutes per chunk
            
            # Use the more restrictive limit between API file size (25MB) and token output (5.1 min)
            api_duration_limit = 1400  # 23.3 minutes (25MB limit)
            effective_duration_limit = min(api_duration_limit, conservative_limit)
            
            print(f"🎯 Ultra-conservative chunking: max {effective_duration_limit/60:.1f} minutes per chunk")
            
            chunks_needed = math.ceil(total_duration / effective_duration_limit)
            
            # Create chunks using FFmpeg directly (no memory loading)
            chunks = self._create_intelligent_chunks_ffmpeg(audio_path, total_duration, effective_duration_limit)
            
            # Clear user feedback about chunking process
            print(f"🧩 Creating {chunks_needed} chunks for processing")
            print(f"⏱️  Total duration: {total_duration/60:.1f} minutes")
            optimal_chunk_duration = total_duration / chunks_needed
            
            if self.verbose:
                self.logger.info(f"Created {len(chunks)} chunks for processing")
            
            segments = []
            failed_chunks = 0
            
            # Process each chunk
            for i, (chunk_audio, start_time, end_time) in enumerate(chunks):
                # Show progress to user
                print(f"🔄 Processing chunk {i+1}/{len(chunks)} ({start_time/60:.1f}m-{end_time/60:.1f}m)...")
                try:
                    # Handle different chunk types
                    if hasattr(chunk_audio, 'path'):
                        # FFmpeg chunk - file already exists
                        chunk_path = Path(chunk_audio.path)
                    else:
                        # PyDub chunk - need to export
                        chunk_path = self.temp_dir / f"chunk_{i:03d}.mp3"
                        chunk_audio.export(chunk_path, format="mp3", bitrate="128k")
                    
                    # Transcribe this chunk
                    chunk_result = self._transcribe_direct(chunk_path, None, language, prompt)
                    chunk_path.unlink(missing_ok=True)
                    
                    if chunk_result.success and chunk_result.segments:
                        # Adjust timing for chunk position
                        segment = chunk_result.segments[0]
                        segment.start_time = start_time
                        segment.end_time = end_time
                        segments.append(segment)
                        print(f"   ✅ Transcribed {len(segment.text)} characters")
                        
                        if self.verbose:
                            chunk_text_preview = segment.text[:100] + "..." if len(segment.text) > 100 else segment.text
                            self.logger.info(f"Chunk {i} transcribed: {len(segment.text)} chars - '{chunk_text_preview}'")
                    else:
                        failed_chunks += 1
                        print(f"   ❌ Failed: {chunk_result.error_message}")
                        if self.verbose:
                            self.logger.warning(f"Chunk {i} failed: {chunk_result.error_message}")
                    
                    # Cleanup chunk file (but keep debug copy)
                    chunk_path.unlink(missing_ok=True)
                    
                except Exception as e:
                    failed_chunks += 1
                    print("❌")  # Failure feedback for this chunk
                    if self.verbose:
                        self.logger.error(f"Chunk {i} processing error: {e}")
                    else:
                        print(f"   ❌ Error: {e}")
            
            # Show final chunking summary
            print(f"\n📋 Chunking summary: {len(segments)} successful chunks out of {len(chunks)} total")
            if failed_chunks > 0:
                print(f"⚠️  {failed_chunks} chunks failed")
            
            # DEBUG: Show segments info before assembly
            if self.verbose:
                for i, seg in enumerate(segments):
                    preview = seg.text[:50] + "..." if len(seg.text) > 50 else seg.text
                    self.logger.info(f"Segment {i}: {seg.start_time:.1f}s-{seg.end_time:.1f}s, {len(seg.text)} chars: '{preview}'")
            
            # Assemble final transcript
            full_transcript = self._assemble_transcript_from_segments(segments)
            
            return TranscriptionResult(
                success=len(segments) > 0,
                audio_id=audio_id,
                full_transcript=full_transcript,
                segments=segments,
                language=language,
                model_used=self.model,
                total_chunks=len(chunks),
                failed_chunks=failed_chunks
            )
            
        except Exception as e:
            return TranscriptionResult(
                success=False,
                audio_id=audio_id,
                full_transcript="",
                segments=[],
                error_message=f"Chunked transcription failed: {str(e)}"
            )
    

    
    def _assemble_transcript_from_segments(self, segments: List[TranscriptionSegment]) -> str:
        """
        Assemble final transcript from segments, handling overlaps intelligently.
        """
        if not segments:
            print("⚠️  No segments to assemble!")
            return ""
        
        print(f"🔧 Assembling transcript from {len(segments)} segments:")
        
        # Sort segments by start time
        sorted_segments = sorted(segments, key=lambda s: s.start_time)
        
        # Debug: show each segment info
        for i, segment in enumerate(sorted_segments):
            preview = segment.text[:100] + "..." if len(segment.text) > 100 else segment.text
            print(f"   Segment {i+1}: {segment.start_time:.1f}s-{segment.end_time:.1f}s, {len(segment.text)} chars")
            print(f"      Preview: '{preview}'")
        
        # Simple concatenation for now - could be enhanced with overlap detection
        transcript_parts = [segment.text.strip() for segment in sorted_segments if segment.text.strip()]
        
        print(f"📝 Final transcript parts: {len(transcript_parts)} non-empty segments")
        
        full_text = " ".join(transcript_parts)
        print(f"📊 Final transcript length: {len(full_text)} characters")
        
        return full_text
    
    def _make_api_call_with_retry(
        self, 
        audio_file_path: Path, 
        language: Optional[str],
        prompt: Optional[str]
    ) -> Optional[Any]:
        """
        Make API call with exponential backoff retry logic.
        """
        for attempt in range(self.max_retries + 1):
            try:
                if self.verbose and attempt > 0:
                    self.logger.info(f"Retry attempt {attempt}")
                
                # Make API call using UnifiedAPIClient
                response = self.client.audio_transcription(
                    file_path=str(audio_file_path),
                    model=self.model,
                    language=language,
                    prompt=prompt,
                    response_format="json",
                    temperature=0.0
                )
                return response
                
            except Exception as e:
                error_msg = str(e).lower()
                
                # Check if this is a retryable error
                is_retryable = any(keyword in error_msg for keyword in [
                    'timeout', 'rate limit', '5', 'server error', 'connection'
                ])
                
                if attempt < self.max_retries and is_retryable:
                    delay = self.base_delay * (2 ** attempt)  # Exponential backoff
                    if self.verbose:
                        self.logger.warning(f"API call failed (attempt {attempt + 1}): {e}")
                        self.logger.info(f"Retrying in {delay} seconds...")
                    time.sleep(delay)
                else:
                    if self.verbose:
                        self.logger.error(f"API call failed after {attempt + 1} attempts: {e}")
                    raise TranscriptionError(f"API call failed: {e}")
            finally:
                # File handling is managed by UnifiedAPIClient
                pass
        
        return None
    
    def _cleanup_temp_file(self, file_path: Path):
        """Clean up temporary file."""
        try:
            if file_path.exists():
                file_path.unlink()
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Failed to cleanup temp file {file_path}: {e}")
    
    def cleanup_temp_dir(self):
        """Clean up temporary directory and all contents."""
        try:
            import shutil
            if self.temp_dir.exists():
                shutil.rmtree(self.temp_dir)
        except Exception as e:
            if self.verbose:
                self.logger.warning(f"Failed to cleanup temp directory: {e}")


def create_transcription_service(
    api_key: Optional[str] = None,
    model: str = DEFAULT_TRANSCRIPTION_MODEL,
    verbose: bool = False,
    **kwargs
) -> TranscriptionService:
    """
    Factory function to create a TranscriptionService instance.
    
    Args:
        api_key: API key (automatically determines provider based on model)
        model: Model to use for transcription
        verbose: Enable verbose logging
        **kwargs: Additional parameters for TranscriptionService
        
    Returns:
        Configured TranscriptionService instance
    """
    return TranscriptionService(
        api_key=api_key,
        model=model,
        verbose=verbose,
        **kwargs
    ) 