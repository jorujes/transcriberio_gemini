"""
Audio Metadata Management System

This module manages audio file metadata using unique IDs instead of original filenames.
Provides mapping between alphanumeric IDs and original video information.
"""

import json
import uuid
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union
import re


@dataclass
class AudioMetadata:
    """
    Metadata for an audio file with unique ID.
    """
    audio_id: str
    title: str
    original_url: str
    uploader: str
    duration: str
    upload_date: Optional[str]
    view_count: Optional[int]
    file_path: str
    file_size: int
    download_date: str
    audio_format: str
    audio_quality: str
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> 'AudioMetadata':
        """Create from dictionary (JSON deserialization)."""
        return cls(**data)


class AudioMetadataManager:
    """
    Manages audio metadata using unique IDs.
    
    Features:
    - Generates unique alphanumeric IDs
    - Maps IDs to original video information
    - Persistent storage in JSON format
    - Search and lookup capabilities
    """
    
    def __init__(self, metadata_file: Union[str, Path] = "audio_metadata.json"):
        """
        Initialize metadata manager.
        
        Args:
            metadata_file: Path to JSON file storing metadata
        """
        self.metadata_file = Path(metadata_file)
        self.metadata: Dict[str, AudioMetadata] = {}
        self.load_metadata()
    
    def generate_audio_id(self, prefix: str = "audio") -> str:
        """
        Generate unique alphanumeric ID for audio file.
        
        Args:
            prefix: Prefix for the ID
            
        Returns:
            Unique alphanumeric ID (e.g., "audio_abc123def")
        """
        # Generate short UUID (8 characters)
        short_uuid = str(uuid.uuid4()).replace('-', '')[:8]
        return f"{prefix}_{short_uuid}"
    
    def create_safe_filename(self, audio_id: str, extension: str = "mp3") -> str:
        """
        Create safe filename from audio ID.
        
        Args:
            audio_id: Audio ID
            extension: File extension
            
        Returns:
            Safe filename
        """
        return f"{audio_id}.{extension}"
    
    def add_metadata(
        self, 
        title: str,
        original_url: str,
        uploader: str,
        duration: str,
        file_path: str,
        file_size: int,
        audio_format: str = "mp3",
        audio_quality: str = "best",
        upload_date: Optional[str] = None,
        view_count: Optional[int] = None,
        audio_id: Optional[str] = None
    ) -> str:
        """
        Add metadata for new audio file.
        
        Args:
            title: Original video title
            original_url: YouTube URL
            uploader: Video uploader
            duration: Audio duration
            file_path: Path to audio file
            file_size: File size in bytes
            audio_format: Audio format
            audio_quality: Audio quality
            upload_date: Video upload date
            view_count: Video view count
            audio_id: Optional custom ID (generates if None)
            
        Returns:
            Generated or provided audio ID
        """
        if audio_id is None:
            audio_id = self.generate_audio_id()
        
        metadata = AudioMetadata(
            audio_id=audio_id,
            title=title,
            original_url=original_url,
            uploader=uploader,
            duration=duration,
            upload_date=upload_date,
            view_count=view_count,
            file_path=file_path,
            file_size=file_size,
            download_date=datetime.now().isoformat(),
            audio_format=audio_format,
            audio_quality=audio_quality
        )
        
        self.metadata[audio_id] = metadata
        self.save_metadata()
        
        return audio_id
    
    def get_metadata(self, audio_id: str) -> Optional[AudioMetadata]:
        """
        Get metadata by audio ID.
        
        Args:
            audio_id: Audio ID
            
        Returns:
            AudioMetadata if found, None otherwise
        """
        return self.metadata.get(audio_id)
    
    def list_all(self) -> List[AudioMetadata]:
        """
        List all audio metadata.
        
        Returns:
            List of all AudioMetadata objects
        """
        return list(self.metadata.values())
    
    def search_by_title(self, query: str) -> List[AudioMetadata]:
        """
        Search audio by title.
        
        Args:
            query: Search query
            
        Returns:
            List of matching AudioMetadata objects
        """
        query_lower = query.lower()
        results = []
        
        for metadata in self.metadata.values():
            if query_lower in metadata.title.lower():
                results.append(metadata)
        
        return results
    
    def search_by_uploader(self, uploader: str) -> List[AudioMetadata]:
        """
        Search audio by uploader.
        
        Args:
            uploader: Uploader name
            
        Returns:
            List of matching AudioMetadata objects
        """
        uploader_lower = uploader.lower()
        results = []
        
        for metadata in self.metadata.values():
            if uploader_lower in metadata.uploader.lower():
                results.append(metadata)
        
        return results
    
    def remove_metadata(self, audio_id: str) -> bool:
        """
        Remove metadata by audio ID.
        
        Args:
            audio_id: Audio ID to remove
            
        Returns:
            True if removed, False if not found
        """
        if audio_id in self.metadata:
            del self.metadata[audio_id]
            self.save_metadata()
            return True
        return False

    def cleanup_orphaned_metadata(self) -> int:
        """
        Public method to manually clean up orphaned metadata entries.
        
        Returns:
            Number of orphaned entries removed
        """
        initial_count = len(self.metadata)
        self._cleanup_orphaned_metadata()
        return initial_count - len(self.metadata)
    
    def load_metadata(self) -> None:
        """Load metadata from JSON file and clean up orphaned entries."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                # Convert dict data back to AudioMetadata objects
                self.metadata = {
                    audio_id: AudioMetadata.from_dict(metadata_dict)
                    for audio_id, metadata_dict in data.items()
                }
                
                # Automatically clean up orphaned metadata entries
                self._cleanup_orphaned_metadata()
                
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                print(f"Warning: Failed to load metadata from {self.metadata_file}: {e}")
                self.metadata = {}
        else:
            self.metadata = {}

    def _cleanup_orphaned_metadata(self) -> None:
        """
        Clean up metadata entries for files that no longer exist.
        This method is called automatically when loading metadata.
        """
        if not self.metadata:
            return
        
        orphaned_entries = []
        
        for audio_id, metadata in self.metadata.items():
            file_path = Path(metadata.file_path)
            
            # Check if the file actually exists
            if not file_path.exists():
                orphaned_entries.append(audio_id)
        
        # Remove orphaned entries
        if orphaned_entries:
            for audio_id in orphaned_entries:
                del self.metadata[audio_id]
            
            # Save the cleaned metadata
            self.save_metadata()
            
            print(f"🧹 Cleaned up {len(orphaned_entries)} orphaned metadata entries")
            for audio_id in orphaned_entries[:3]:  # Show first 3 for reference
                print(f"   - Removed: {audio_id}")
            if len(orphaned_entries) > 3:
                print(f"   - ... and {len(orphaned_entries) - 3} more")
    
    def save_metadata(self) -> None:
        """Save metadata to JSON file."""
        try:
            # Convert AudioMetadata objects to dicts for JSON serialization
            data = {
                audio_id: metadata.to_dict()
                for audio_id, metadata in self.metadata.items()
            }
            
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"Warning: Failed to save metadata to {self.metadata_file}: {e}")
    
    def get_summary_table(self) -> str:
        """
        Generate summary table of all audio files.
        
        Returns:
            Formatted table string
        """
        if not self.metadata:
            return "📁 No audio files found."
        
        lines = [
            "📊 Audio Library Summary",
            "=" * 50,
            f"{'ID':<12} {'Title':<30} {'Duration':<10} {'Uploader':<15}",
            "-" * 50
        ]
        
        for metadata in sorted(self.metadata.values(), key=lambda x: x.download_date, reverse=True):
            title = metadata.title[:27] + "..." if len(metadata.title) > 30 else metadata.title
            uploader = metadata.uploader[:12] + "..." if len(metadata.uploader) > 15 else metadata.uploader
            
            lines.append(f"{metadata.audio_id:<12} {title:<30} {metadata.duration:<10} {uploader:<15}")
        
        lines.append("-" * 50)
        lines.append(f"Total: {len(self.metadata)} audio files")
        
        return "\n".join(lines)
    
    def get_detailed_info(self, audio_id: str) -> str:
        """
        Get detailed information about an audio file.
        
        Args:
            audio_id: Audio ID
            
        Returns:
            Formatted detailed information
        """
        metadata = self.get_metadata(audio_id)
        if not metadata:
            return f"❌ Audio ID '{audio_id}' not found."
        
        info = [
            f"🎵 Audio Details: {metadata.audio_id}",
            "=" * 40,
            f"📺 Title: {metadata.title}",
            f"👤 Uploader: {metadata.uploader}",
            f"⏱️  Duration: {metadata.duration}",
            f"🔗 URL: {metadata.original_url}",
            f"📁 File: {metadata.file_path}",
            f"📊 Size: {metadata.file_size / (1024*1024):.2f} MB",
            f"🎵 Format: {metadata.audio_format}",
            f"⚡ Quality: {metadata.audio_quality}",
            f"📅 Downloaded: {metadata.download_date[:10]}",
        ]
        
        if metadata.upload_date:
            info.append(f"📤 Uploaded: {metadata.upload_date}")
        
        if metadata.view_count:
            info.append(f"👁️  Views: {metadata.view_count:,}")
        
        return "\n".join(info)


def create_metadata_manager(metadata_file: str = "audio_metadata.json") -> AudioMetadataManager:
    """
    Factory function to create AudioMetadataManager.
    
    Args:
        metadata_file: Path to metadata JSON file
        
    Returns:
        AudioMetadataManager instance
    """
    return AudioMetadataManager(metadata_file) 