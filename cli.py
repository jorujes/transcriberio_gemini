#!/usr/bin/env python3
"""
YouTube Audio Transcriber CLI

A command-line interface for downloading and transcribing YouTube videos.
This module implements the main CLI using Click framework.
"""

import os
import sys
import time
import json
from datetime import datetime
from pathlib import Path
from typing import Optional

import click
from dotenv import load_dotenv

from downloader import YouTubeDownloader, DownloadResult, DownloadError
from audio_metadata import create_metadata_manager
from transcriber import create_transcription_service, TranscriptionError
from entity_detector import create_entity_detector, EntityDetectionError
from entity_reviewer import create_entity_reviewer
from translator_normalizer import create_translator_normalizer
from api_client import DEFAULT_TRANSCRIPTION_MODEL, DEFAULT_TEXT_MODEL, VALID_TRANSCRIPTION_MODELS

# Load environment variables from .env.local automatically
load_dotenv('.env.local')


def ensure_output_directory() -> Path:
    """
    Ensure the output directory exists and return its path.
    
    Returns:
        Path object for the output directory
    """
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)
    return output_dir


def get_output_path(filename: str) -> Path:
    """
    Get the full output path for a given filename in the output directory.
    
    Args:
        filename: Name of the file
        
    Returns:
        Full path in the output directory
    """
    output_dir = ensure_output_directory()
    return output_dir / filename


def validate_output_directory(ctx, param, value: Optional[str]) -> Path:
    """
    Validate and create output directory if it doesn't exist.
    
    Args:
        ctx: Click context
        param: Click parameter 
        value: Directory path string
        
    Returns:
        Path object for the output directory
        
    Raises:
        click.BadParameter: If directory cannot be created or accessed
    """
    if value is None:
        value = "./downloads"
    
    output_path = Path(value).resolve()
    
    try:
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Test write permissions
        test_file = output_path / ".write_test"
        test_file.touch()
        test_file.unlink()
        
        return output_path
    except (OSError, PermissionError) as e:
        raise click.BadParameter(
            f"Cannot create or access directory '{output_path}': {e}"
        )


@click.group(invoke_without_command=True)
@click.option(
    "--version", 
    is_flag=True,
    help="Show version information and exit."
)
@click.pass_context
def main(ctx: click.Context, version: bool) -> None:
    """
    YouTube Audio Transcriber - Download and transcribe YouTube videos.
    
    This tool allows you to download audio from YouTube videos in MP3 format
    and transcribe them using advanced speech recognition techniques.
    """
    if version:
        click.echo("YouTube Audio Transcriber v1.0.0")
        click.echo("Built with Click and yt-dlp")
        ctx.exit()
    
    if ctx.invoked_subcommand is None:
        click.echo(ctx.get_help())


@main.command()
@click.argument("url", required=True)
@click.option(
    "--output-dir", "-o",
    callback=validate_output_directory,
    help="Output directory for downloaded files (default: ./downloads)"
)
@click.option(
    "--quality", "-q",
    type=click.Choice(["best", "worst", "medium"], case_sensitive=False),
    default="best",
    help="Audio quality preference (default: best)"
)
@click.option(
    "--format", "-f",
    type=click.Choice(["mp3", "wav", "m4a"], case_sensitive=False),
    default="mp3",
    help="Output audio format (default: mp3)"
)
def download(
    url: str, 
    output_dir: Path, 
    quality: str, 
    format: str
) -> None:
    """
    Download audio from a YouTube video.
    
    URL should be a valid YouTube video URL.
    
    Examples:
        transcriber download "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        transcriber download -o ./my_audio -q medium "https://youtu.be/dQw4w9WgXcQ"
    """
    # Always show URL validation (not just in verbose)
    click.echo(f"🔍 Validating URL: {url}")
    
    # Initialize downloader
    downloader = YouTubeDownloader(
        output_directory=output_dir,
        audio_format=format,
        audio_quality=quality,
        verbose=False  # Remove verbose option - always show essential info only
    )
    
    try:
        # Validate URL first
        if not downloader.validate_url(url):
            click.echo(
                click.style("❌ Error: Invalid YouTube URL", fg="red"), 
                err=True
            )
            click.echo(
                "Please provide a valid YouTube video URL.", 
                err=True
            )
            sys.exit(1)
        
        # Always show comprehensive video information (like validate command)
        video_info = downloader.get_video_info(url)
        if video_info:
            click.echo(f"📺 Title: {video_info.title}")
            click.echo(f"⏱️  Duration: {video_info.duration}")
            click.echo(f"👤 Uploader: {video_info.uploader}")
            
            # Always show comprehensive details
            if video_info.view_count:
                click.echo(f"👁️  Views: {video_info.view_count:,}")
            if video_info.upload_date:
                click.echo(f"📅 Uploaded: {video_info.upload_date}")
        
        # Download audio
        click.echo("⬇️  Starting download...")
        click.echo("📊 Progress will be shown by yt-dlp below:")
        click.echo()
        
        result = downloader.download_audio(url)
        
        if result.success:
            click.echo(
                click.style("✅ Download completed successfully!", fg="green")
            )
            click.echo(f"🆔 Audio ID: {click.style(result.audio_id, fg='cyan', bold=True)}")
            click.echo(f"📁 File saved to: {result.output_path}")
            
            if result.file_size:
                size_mb = result.file_size / (1024 * 1024)
                click.echo(f"📊 File size: {size_mb:.2f} MB")
            
            if result.duration:
                click.echo(f"⏱️  Duration: {result.duration}")
                
            click.echo(f"\n💡 Use this ID for future operations:")
            click.echo(f"   transcriber transcribe {result.audio_id}")
            click.echo(f"   transcriber info {result.audio_id}")
                
        else:
            click.echo(
                click.style("❌ Download failed", fg="red"), 
                err=True
            )
            if result.error_message:
                click.echo(f"Error details: {result.error_message}", err=True)
            sys.exit(1)
            
    except DownloadError as e:
        click.echo(
            click.style(f"❌ Download Error: {e}", fg="red"), 
            err=True
        )
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo(
            click.style("\n🛑 Download cancelled by user", fg="yellow"), 
            err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(
            click.style(f"❌ Unexpected error: {e}", fg="red"), 
            err=True
        )
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)




@main.command()
@click.argument("url", required=True)
def validate(url: str) -> None:
    """
    Validate a YouTube URL without downloading.
    
    This command checks if the provided URL is a valid YouTube video URL
    and displays basic information about the video.
    """
    downloader = YouTubeDownloader()
    
    click.echo(f"🔍 Validating URL: {url}")
    
    try:
        if downloader.validate_url(url):
            click.echo(click.style("✅ Valid YouTube URL", fg="green"))
            
            # Get and display video information
            video_info = downloader.get_video_info(url)
            if video_info:
                click.echo(f"📺 Title: {video_info.title}")
                click.echo(f"⏱️  Duration: {video_info.duration}")
                click.echo(f"👤 Uploader: {video_info.uploader}")
                click.echo(f"📅 Upload Date: {video_info.upload_date}")
                if video_info.view_count:
                    click.echo(f"👁️  Views: {video_info.view_count:,}")
        else:
            click.echo(click.style("❌ Invalid YouTube URL", fg="red"))
            sys.exit(1)
            
    except DownloadError as e:
        click.echo(click.style(f"❌ Error: {e}", fg="red"), err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(click.style(f"❌ Unexpected error: {e}", fg="red"), err=True)
        sys.exit(1)


@main.command()
def list() -> None:
    """
    List all downloaded audio files with their IDs.
    
    Shows a summary table of all audio files in the library
    with IDs, titles, duration, and uploader information.
    """
    try:
        # Load metadata from default location
        metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
        
        summary = metadata_manager.get_summary_table()
        click.echo(summary)
        
        if metadata_manager.metadata:
            click.echo(f"\n💡 Use 'transcriber info <AUDIO_ID>' for detailed information")
            click.echo(f"💡 Use 'transcriber transcribe <AUDIO_ID>' to transcribe audio")
            
    except Exception as e:
        click.echo(
            click.style(f"❌ Error listing audio files: {e}", fg="red"),
            err=True
        )
        sys.exit(1)


@main.command()
@click.argument("audio_id", required=True)
def info(audio_id: str) -> None:
    """
    Show detailed information about an audio file.
    
    AUDIO_ID should be the unique ID assigned when the file was downloaded.
    
    Examples:
        transcriber info audio_abc12345
        transcriber info audio_xyz98765
    """
    try:
        # Load metadata from default location
        metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
        
        detailed_info = metadata_manager.get_detailed_info(audio_id)
        click.echo(detailed_info)
        
        # Check if file still exists
        metadata = metadata_manager.get_metadata(audio_id)
        if metadata:
            file_path = Path(metadata.file_path)
            if not file_path.exists():
                click.echo(
                    click.style(f"\n⚠️  Warning: Audio file not found at {file_path}", fg="yellow")
                )
            else:
                click.echo(f"\n💡 Available operations:")
                click.echo(f"   transcriber transcribe {audio_id}")
                if file_path.suffix == '.mp3':
                    click.echo(f"   transcriber transcribe \"{file_path}\"")
                    
    except Exception as e:
        click.echo(
            click.style(f"❌ Error getting audio info: {e}", fg="red"),
            err=True
        )
        sys.exit(1)


@main.command()
@click.argument("audio_input", required=True)
@click.option(
    "--model", "-m",
    type=click.Choice(VALID_TRANSCRIPTION_MODELS, case_sensitive=False),
    default=DEFAULT_TRANSCRIPTION_MODEL,
    help=f"Transcription model to use (default: {DEFAULT_TRANSCRIPTION_MODEL})"
)
@click.option(
    "--language", "-l",
    type=str,
    help="Language code for transcription (e.g., 'en', 'pt', 'es')"
)
@click.option(
    "--prompt", "-p",
    type=str,
    help="Optional prompt to guide transcription"
)
@click.option(
    "--output", "-o",
    type=str,
    help="Output file path for transcript (default: audio_id_transcript.txt)"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable detailed logging and progress information"
)
@click.option(
    "--api-key",
    type=str,
    help="OpenAI API key (if not set in OPENAI_API_KEY environment variable)"
)
@click.option(
    "--detect-entities",
    is_flag=True,
    help="Automatically detect entities after transcription"
)
@click.option(
    "--review-entities",
    is_flag=True,
    help="Automatically detect AND review entities after transcription (interactive)"
)
@click.option(
    "--translate",
    is_flag=True,
    help="Automatically translate and normalize the transcript after processing"
)
@click.option(
    "--skip-translation",
    is_flag=True,
    help="Skip translation step (used with --translate to use original text)"
)
def transcribe(
    audio_input: str,
    model: str,
    language: Optional[str],
    prompt: Optional[str],
    output: Optional[str],
    verbose: bool,
    api_key: Optional[str],
    detect_entities: bool,
    review_entities: bool,
    translate: bool,
    skip_translation: bool
) -> None:
    """
    Transcribe audio using OpenAI's gpt-4o-transcribe models.
    
    AUDIO_INPUT can be either:
    - An audio ID (e.g., audio_454dc0f4)
    - A file path (e.g., audio.mp3)
    
    The system automatically optimizes file size and chunking strategy:
    1. Videos >12 minutes: Auto-download in medium quality 
    2. Files ≤25MB AND ≤12 minutes: Direct transcription (fastest)
    3. Files >25MB: Audio compression 
    4. Still >25MB OR >12 minutes: Intelligent chunking with minimal overlap
    
    Optional processing pipeline:
    - --detect-entities: Detect named entities (people, places, etc.)
    - --review-entities: Interactive entity review and replacement
    - --translate: Idiomatic translation to selected language
    
    Examples:
        transcriber transcribe audio_454dc0f4
        transcriber transcribe audio.mp3 --model gpt-4o-mini-transcribe
        transcriber transcribe audio_xyz123 --detect-entities --review-entities
        transcriber transcribe large_audio.mp3 --translate
        transcriber transcribe audio.mp3 --review-entities --translate
    """
    # Validate API key
    api_key_to_use = api_key or os.getenv("OPENAI_API_KEY")
    if not api_key_to_use:
        click.echo(
            click.style("❌ Error: OpenAI API key required", fg="red"),
            err=True
        )
        click.echo(
            "Please add OPENAI_API_KEY to .env.local file or use --api-key option",
            err=True
        )
        sys.exit(1)
    
    try:
        click.echo(f"🎯 Starting transcription with {model}")
        if verbose:
            click.echo(f"📝 Input: {audio_input}")
            if language:
                click.echo(f"🌐 Language: {language}")
            if prompt:
                click.echo(f"💭 Prompt: {prompt}")
        
        # Create transcription service
        transcription_service = create_transcription_service(
            api_key=api_key_to_use,
            model=model,
            verbose=verbose
        )
        
        # Perform transcription
        if verbose:
            click.echo("🔄 Processing audio file...")
        
        result = transcription_service.transcribe_audio(
            audio_input=audio_input,
            language=language,
            prompt=prompt
        )
        
        if result.success:
            # Display success information
            click.echo(click.style("✅ Transcription completed successfully!", fg="green"))
            click.echo(f"🆔 Audio ID: {result.audio_id}")
            click.echo(f"🤖 Model: {result.model_used}")
            click.echo(f"⏱️  Processing time: {result.processing_time:.2f} seconds")
            click.echo(f"📊 File size: {result.file_size_mb:.2f} MB")
            
            if result.optimization_applied:
                click.echo(f"⚡ Optimization: {result.optimization_applied}")
            
            if result.total_chunks > 1:
                click.echo(f"🧩 Chunks processed: {result.total_chunks}")
                if result.failed_chunks > 0:
                    click.echo(
                        click.style(f"⚠️  Failed chunks: {result.failed_chunks}", fg="yellow")
                    )
            
            if result.language:
                click.echo(f"🌐 Detected language: {result.language}")
            
            # Display transcript
            click.echo("\n" + "="*50)
            click.echo("📝 TRANSCRIPT:")
            click.echo("="*50)
            click.echo(result.full_transcript)
            click.echo("="*50)
            
            # Save to file in output directory
            if output:
                output_path = get_output_path(Path(output).name)
            else:
                output_path = get_output_path(f"{result.audio_id}_transcript.txt")
            
            try:
                # Get video metadata for rich header information
                metadata_manager = create_metadata_manager("downloads/audio_metadata.json")
                video_metadata = metadata_manager.get_metadata(result.audio_id)
                
                # Calculate word and character statistics
                word_count = len(result.full_transcript.split())
                char_count = len(result.full_transcript)
                char_count_no_spaces = len(result.full_transcript.replace(' ', ''))
                
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write("="*80 + "\n")
                    f.write("🎥 YOUTUBE VIDEO TRANSCRIPTION\n")
                    f.write("="*80 + "\n\n")
                    
                    # Video Information Section
                    if video_metadata:
                        f.write("📺 VIDEO INFORMATION:\n")
                        f.write("-" * 40 + "\n")
                        f.write(f"Title: {video_metadata.title}\n")
                        f.write(f"URL: {video_metadata.original_url}\n")
                        f.write(f"Uploader: {video_metadata.uploader}\n")
                        f.write(f"Duration: {video_metadata.duration}\n")
                        if video_metadata.upload_date:
                            # Format upload date nicely
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
                    
                    # Transcription Information Section
                    f.write("🤖 TRANSCRIPTION INFORMATION:\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"Audio ID: {result.audio_id}\n")
                    f.write(f"Model: {result.model_used}\n")
                    f.write(f"Processing Time: {result.processing_time:.2f} seconds\n")
                    f.write(f"File Size: {result.file_size_mb:.2f} MB\n")
                    if result.optimization_applied:
                        f.write(f"Optimization: {result.optimization_applied.replace('_', ' ').title()}\n")
                    if result.total_chunks > 1:
                        f.write(f"Chunks Processed: {result.total_chunks}\n")
                        if result.failed_chunks > 0:
                            f.write(f"Failed Chunks: {result.failed_chunks}\n")
                    if result.language:
                        f.write(f"Detected Language: {result.language}\n")
                    f.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("\n")
                    
                    # Statistics Section
                    f.write("📊 TRANSCRIPT STATISTICS:\n")
                    f.write("-" * 40 + "\n")
                    f.write(f"Total Words: {word_count:,}\n")
                    f.write(f"Total Characters: {char_count:,}\n")
                    f.write(f"Characters (no spaces): {char_count_no_spaces:,}\n")
                    if video_metadata and video_metadata.duration:
                        # Calculate words per minute if duration is available
                        try:
                            # Parse duration string (e.g., "33:29" or "1:23:45")
                            duration_parts = video_metadata.duration.split(':')
                            if len(duration_parts) == 2:  # MM:SS
                                total_minutes = int(duration_parts[0]) + int(duration_parts[1]) / 60
                            elif len(duration_parts) == 3:  # HH:MM:SS
                                total_minutes = int(duration_parts[0]) * 60 + int(duration_parts[1]) + int(duration_parts[2]) / 60
                            else:
                                total_minutes = 0
                            
                            if total_minutes > 0:
                                words_per_minute = word_count / total_minutes
                                f.write(f"Words per Minute: {words_per_minute:.1f}\n")
                        except:
                            pass
                    f.write("\n")
                    
                    # Transcript Content
                    f.write("="*80 + "\n")
                    f.write("📝 TRANSCRIPT CONTENT:\n")
                    f.write("="*80 + "\n\n")
                    f.write(result.full_transcript)
                    f.write("\n\n")
                    f.write("="*80 + "\n")
                    f.write("End of Transcript\n")
                    f.write("="*80 + "\n")
                
                click.echo(f"\n💾 Transcript saved to: {output_path}")
                
                # Show segment information if verbose and multiple segments
                if verbose and len(result.segments) > 1:
                    click.echo(f"\n🧩 Segment details:")
                    for i, segment in enumerate(result.segments):
                        click.echo(f"  {i+1}. {segment.start_time:.1f}s-{segment.end_time:.1f}s: {segment.text[:50]}...")
                
                # Entity detection if requested (either explicit or via review)
                if detect_entities or review_entities:
                    click.echo("\n🔍 Detecting entities...")
                    try:
                        entity_detector = create_entity_detector(
                            api_key=api_key,
                            verbose=verbose
                        )
                        
                        entity_result = entity_detector.detect_entities(result.full_transcript)
                        
                        if entity_result.success:
                            click.echo("\n" + entity_detector.format_entities_summary(entity_result))
                            
                            # Save entities to JSON file
                            entities_filename = output_path.stem + '_entities.json'
                            entities_path = get_output_path(entities_filename)
                            entities_data = {
                                "audio_id": result.audio_id,
                                "total_entities": entity_result.total_entities,
                                "unique_entities": entity_result.unique_entities,
                                "processing_time": entity_result.processing_time,
                                "model_used": entity_result.model_used,
                                "entities_by_type": {
                                    entity_type: [
                                        {
                                            "text": entity.text,
                                            "start": entity.start,
                                            "end": entity.end,
                                            "confidence": entity.confidence
                                        }
                                        for entity in entities
                                    ]
                                    for entity_type, entities in entity_result.grouped_entities.items()
                                }
                            }
                            
                            with open(entities_path, 'w', encoding='utf-8') as f:
                                json.dump(entities_data, f, indent=2, ensure_ascii=False)
                            
                            click.echo(f"💾 Entities saved to: {entities_path}")
                            
                            # Interactive entity review if requested
                            if review_entities:
                                click.echo("\n📝 Starting interactive entity review...")
                                try:
                                    entity_reviewer = create_entity_reviewer(verbose=verbose)
                                    review_result = entity_reviewer.review_entities(
                                        entities_file=entities_path,
                                        transcript_file=output_path,
                                        skip_review=False
                                    )
                                    
                                    if review_result.success:
                                        if review_result.transcript_updated:
                                            click.echo(f"🔄 Transcript updated with {review_result.replacements_made} entity replacements")
                                        else:
                                            click.echo("📝 Entity review completed, no changes made")
                                    else:
                                        click.echo(
                                            click.style(f"⚠️  Entity review failed: {review_result.error_message}", fg="yellow")
                                        )
                                        
                                except ImportError:
                                    click.echo(
                                        click.style("⚠️  Interactive review requires 'inquirer' library. Install with: pip install inquirer>=3.1.0", fg="yellow")
                                    )
                                except Exception as e:
                                    click.echo(
                                        click.style(f"⚠️  Entity review error: {e}", fg="yellow")
                                    )
                        else:
                            click.echo(
                                click.style(f"⚠️  Entity detection failed: {entity_result.error_message}", fg="yellow")
                            )
                            
                    except EntityDetectionError as e:
                        click.echo(
                            click.style(f"⚠️  Entity detection error: {e}", fg="yellow")
                        )
                    except Exception as e:
                        click.echo(
                            click.style(f"⚠️  Unexpected entity detection error: {e}", fg="yellow")
                        )
                
            except Exception as e:
                click.echo(
                    click.style(f"⚠️  Warning: Could not save transcript to file: {e}", fg="yellow")
                )
                
            # Step 4: Translation and Normalization
            if translate:
                try:
                    click.echo(click.style("\n🌍 Step 4: Translation and Normalization", fg="cyan"))
                    
                    # Initialize translator
                    translator = create_translator_normalizer(
                        api_key=api_key,
                        model=DEFAULT_TEXT_MODEL,
                        verbose=verbose
                    )
                    
                    # Perform translation
                    translation_result = translator.translate_transcript(
                        transcript_file=output_path,
                        skip_translation=skip_translation
                    )
                    
                    if translation_result.success:
                        # Generate translated filename
                        if translation_result.target_language == "original":
                            suffix = "original"
                        else:
                            suffix = f"translated_{translation_result.target_language}"
                        
                        base_name = output_path.stem.replace("_transcript", "")
                        translated_filename = f"{base_name}_{suffix}.txt"
                        translated_file = get_output_path(translated_filename)
                        
                        # Save translated transcript
                        if translator.save_translated_transcript(translation_result, translated_file, output_path):
                            click.echo(f"✅ Translation completed: {translated_file}")
                            click.echo(f"🌍 Target language: {translation_result.target_language}")
                            click.echo(f"📊 Words: {translation_result.word_count_original:,} → {translation_result.word_count_translated:,}")
                            
                            if translation_result.chunks_processed > 0:
                                click.echo(f"🧩 Chunks processed: {translation_result.chunks_processed}/{translation_result.total_chunks}")
                        else:
                            click.echo(
                                click.style("⚠️  Failed to save translated transcript", fg="yellow")
                            )
                    else:
                        click.echo(
                            click.style(f"⚠️  Translation failed: {translation_result.error_message}", fg="yellow")
                        )
                        
                except ImportError:
                    click.echo(
                        click.style("⚠️  Translation requires OpenAI and inquirer libraries", fg="yellow")
                    )
                except Exception as e:
                    click.echo(
                        click.style(f"⚠️  Translation error: {e}", fg="yellow")
                    )
        else:
            # Display error information
            click.echo(click.style("❌ Transcription failed", fg="red"), err=True)
            if result.error_message:
                click.echo(f"Error details: {result.error_message}", err=True)
            
            if result.total_chunks > 0:
                click.echo(f"Chunks attempted: {result.total_chunks}", err=True)
                click.echo(f"Chunks failed: {result.failed_chunks}", err=True)
            
            sys.exit(1)
    
    except TranscriptionError as e:
        click.echo(
            click.style(f"❌ Transcription Error: {e}", fg="red"),
            err=True
        )
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo(
            click.style("\n🛑 Transcription cancelled by user", fg="yellow"),
            err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(
            click.style(f"❌ Unexpected error: {e}", fg="red"),
            err=True
        )
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)
    finally:
        # Cleanup
        try:
            if 'transcription_service' in locals():
                transcription_service.cleanup_temp_dir()
        except:
            pass


@main.command()
@click.argument("input_file", required=True)
@click.option(
    "--output", "-o",
    type=str,
    help="Output file path for entities JSON (default: input_file.entities.json)"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable detailed logging and progress information"
)
@click.option(
    "--api-key",
    type=str,
    help="OpenAI API key (if not set in OPENAI_API_KEY environment variable)"
)
def entities(
    input_file: str,
    output: Optional[str],
    verbose: bool,
    api_key: Optional[str]
) -> None:
    """
    Detect entities in a transcript file or from an audio ID.
    
    INPUT_FILE can be either:
    - An audio ID (e.g., audio_454dc0f4) - will look for existing transcript
    - A transcript file path (e.g., transcript.txt)
    
    Examples:
        transcriber entities audio_454dc0f4
        transcriber entities transcript.txt --output entities.json
    """
    click.echo("🔍 Starting entity detection...")
    
    try:
        # Determine input type and get transcript content
        transcript_content = ""
        audio_id = ""
        
        input_path = Path(input_file)
        
        if input_path.exists() and input_path.is_file():
            # Input is a file path
            click.echo(f"📄 Reading transcript from: {input_path}")
            with open(input_path, 'r', encoding='utf-8') as f:
                transcript_content = f.read()
            audio_id = input_path.stem
        else:
            # Assume it's an audio ID, look for existing transcript
            possible_transcript = Path(f"{input_file}_transcript.txt")
            if possible_transcript.exists():
                click.echo(f"📄 Found transcript file: {possible_transcript}")
                with open(possible_transcript, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # Extract just the transcript content (after the last === line)
                    lines = content.split('\n')
                    transcript_start = -1
                    for i, line in enumerate(lines):
                        if '📝 TRANSCRIPT CONTENT:' in line:
                            transcript_start = i + 2  # Skip the === line after
                            break
                    
                    if transcript_start > 0:
                        transcript_content = '\n'.join(lines[transcript_start:])
                        # Remove ending markers
                        if 'End of Transcript' in transcript_content:
                            transcript_content = transcript_content.split('End of Transcript')[0]
                        transcript_content = transcript_content.strip()
                    else:
                        transcript_content = content
                audio_id = input_file
            else:
                click.echo(
                    click.style(f"❌ No transcript found for audio ID: {input_file}", fg="red"),
                    err=True
                )
                click.echo(f"Expected file: {possible_transcript}", err=True)
                sys.exit(1)
        
        if not transcript_content.strip():
            click.echo(
                click.style("❌ Transcript content is empty", fg="red"),
                err=True
            )
            sys.exit(1)
        
        click.echo(f"📊 Analyzing {len(transcript_content)} characters...")
        
        # Initialize entity detector
        entity_detector = create_entity_detector(
            api_key=api_key,
            verbose=verbose
        )
        
        # Detect entities
        entity_result = entity_detector.detect_entities(transcript_content)
        
        if entity_result.success:
            # Display results
            click.echo("\n" + entity_detector.format_entities_summary(entity_result))
            
            # Save entities to JSON file in output directory
            if output:
                output_path = get_output_path(Path(output).name)
            else:
                if input_path.exists():
                    entities_filename = input_path.stem + '_entities.json'
                    output_path = get_output_path(entities_filename)
                else:
                    output_path = get_output_path(f"{input_file}_entities.json")
            
            entities_data = {
                "source_file": str(input_file),
                "audio_id": audio_id,
                "total_entities": entity_result.total_entities,
                "unique_entities": entity_result.unique_entities,
                "processing_time": entity_result.processing_time,
                "model_used": entity_result.model_used,
                "generated": time.strftime('%Y-%m-%d %H:%M:%S'),
                "entities_by_type": {
                    entity_type: [
                        {
                            "text": entity.text,
                            "start": entity.start,
                            "end": entity.end,
                            "confidence": entity.confidence
                        }
                        for entity in entities
                    ]
                    for entity_type, entities in entity_result.grouped_entities.items()
                }
            }
            
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(entities_data, f, indent=2, ensure_ascii=False)
            
            click.echo(f"\n💾 Entities saved to: {output_path}")
            
        else:
            click.echo(
                click.style(f"❌ Entity detection failed: {entity_result.error_message}", fg="red"),
                err=True
            )
            sys.exit(1)
    
    except EntityDetectionError as e:
        click.echo(
            click.style(f"❌ Entity Detection Error: {e}", fg="red"),
            err=True
        )
        sys.exit(1)
    except KeyboardInterrupt:
        click.echo(
            click.style("\n🛑 Entity detection cancelled by user", fg="yellow"),
            err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(
            click.style(f"❌ Unexpected error: {e}", fg="red"),
            err=True
        )
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@main.command()
@click.argument("entities_file", required=True)
@click.argument("transcript_file", required=True)
@click.option(
    "--skip-review",
    is_flag=True,
    help="Skip interactive review and use entities as-is"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable detailed logging and progress information"
)
def review(
    entities_file: str,
    transcript_file: str,
    skip_review: bool,
    verbose: bool
) -> None:
    """
    Review and edit detected entities with interactive CLI.
    
    ENTITIES_FILE: Path to entities JSON file (e.g., audio_123_entities.json)
    TRANSCRIPT_FILE: Path to transcript file to modify (e.g., audio_123_transcript.txt)
    
    Provides an interactive interface to review detected entities and make
    find/replace substitutions in the transcript file.
    
    Examples:
        transcriber review audio_123_entities.json audio_123_transcript.txt
        transcriber review entities.json transcript.txt --skip-review
    """
    click.echo("📝 Starting entity review session...")
    
    try:
        entities_path = Path(entities_file)
        transcript_path = Path(transcript_file)
        
        # Validate file existence
        if not entities_path.exists():
            click.echo(
                click.style(f"❌ Entities file not found: {entities_path}", fg="red"),
                err=True
            )
            sys.exit(1)
            
        if not transcript_path.exists():
            click.echo(
                click.style(f"❌ Transcript file not found: {transcript_path}", fg="red"),
                err=True
            )
            sys.exit(1)
        
        # Initialize entity reviewer
        try:
            entity_reviewer = create_entity_reviewer(verbose=verbose)
        except ImportError:
            click.echo(
                click.style("❌ Interactive review requires 'inquirer' library. Install with: pip install inquirer>=3.1.0", fg="red"),
                err=True
            )
            sys.exit(1)
        
        # Start review session
        review_result = entity_reviewer.review_entities(
            entities_file=entities_path,
            transcript_file=transcript_path,
            skip_review=skip_review
        )
        
        if review_result.success:
            if review_result.transcript_updated:
                click.echo(f"\n✅ Review completed successfully!")
                click.echo(f"🔄 Made {review_result.replacements_made} entity replacements")
                click.echo(f"📄 Updated transcript: {transcript_path}")
            else:
                click.echo(f"\n✅ Review completed successfully!")
                click.echo("📝 No changes made to transcript")
        else:
            click.echo(
                click.style(f"❌ Review failed: {review_result.error_message}", fg="red"),
                err=True
            )
            sys.exit(1)
    
    except KeyboardInterrupt:
        click.echo(
            click.style("\n🛑 Review cancelled by user", fg="yellow"),
            err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(
            click.style(f"❌ Unexpected error: {e}", fg="red"),
            err=True
        )
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


@main.command()
@click.argument("transcript_file", type=click.Path(path_type=Path))
@click.option(
    "--output-file", "-o",
    type=click.Path(path_type=Path),
    help="Output file for translated transcript (default: auto-generated)"
)
@click.option(
    "--skip-translation", "-s",
    is_flag=True,
    help="Skip translation and use original text"
)
@click.option(
    "--model",
    default=DEFAULT_TEXT_MODEL,
    help=f"Model to use for translation (default: {DEFAULT_TEXT_MODEL})"
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    help="Enable verbose output with detailed processing information"
)
def translate(
    transcript_file: Path,
    output_file: Optional[Path],
    skip_translation: bool,
    model: str,
    verbose: bool
) -> None:
    """
    Translate and normalize a transcript idiomatically.
    
    TRANSCRIPT_FILE should be the path to an existing transcript file.
    
    The tool will:
    1. Present a navigable language selection interface
    2. Intelligently chunk the transcript for GPT-4.1 processing
    3. Translate and normalize each chunk idiomatically
    4. Reconstruct and save the final translated transcript
    
    Examples:
        transcriber translate audio_123_transcript.txt
        transcriber translate audio_123_transcript.txt -o translated_pt-BR.txt
        transcriber translate audio_123_transcript.txt --skip-translation
    """
    try:
        start_time = time.time()
        
        # Try to find the transcript file (first in output directory if just filename)
        if not transcript_file.exists():
            if transcript_file.is_absolute() or "/" in str(transcript_file):
                # Absolute path or path with directories - file not found
                click.echo(
                    click.style(f"❌ Transcript file not found: {transcript_file}", fg="red"),
                    err=True
                )
                sys.exit(1)
            else:
                # Just a filename - try to find in output directory
                output_file_path = get_output_path(transcript_file.name)
                if output_file_path.exists():
                    transcript_file = output_file_path
                else:
                    click.echo(
                        click.style(f"❌ Transcript file not found: {transcript_file}", fg="red"),
                        err=True
                    )
                    click.echo(f"Also tried: {output_file_path}", err=True)
                    sys.exit(1)
        
        click.echo(
            click.style(f"🌍 Starting translation for: {transcript_file.name}", fg="blue")
        )
        
        # Initialize translator
        try:
            translator = create_translator_normalizer(
                model=model,
                verbose=verbose
            )
        except Exception as e:
            click.echo(
                click.style(f"❌ Failed to initialize translator: {e}", fg="red"),
                err=True
            )
            sys.exit(1)
        
        # Perform translation
        result = translator.translate_transcript(
            transcript_file=transcript_file,
            skip_translation=skip_translation
        )
        
        if not result.success:
            click.echo(
                click.style(f"❌ Translation failed: {result.error_message}", fg="red"),
                err=True
            )
            sys.exit(1)
        
        # Generate output filename if not provided
        if output_file is None:
            if result.target_language == "original":
                suffix = "original"
            else:
                suffix = f"translated_{result.target_language}"
            
            base_name = transcript_file.stem.replace("_transcript", "")
            output_filename = f"{base_name}_{suffix}.txt"
            output_file = get_output_path(output_filename)
        
        # Save translated transcript
        success = translator.save_translated_transcript(result, output_file, transcript_file)
        
        if success:
            # Show completion summary
            processing_time = time.time() - start_time
            
            click.echo()
            click.echo(click.style("✅ Translation completed successfully!", fg="green"))
            click.echo(f"📄 Output file: {output_file}")
            click.echo(f"🌍 Target language: {result.target_language}")
            click.echo(f"📊 Original words: {result.word_count_original:,}")
            click.echo(f"📊 Translated words: {result.word_count_translated:,}")
            
            if result.chunks_processed > 0:
                click.echo(f"🧩 Chunks processed: {result.chunks_processed}/{result.total_chunks}")
            
            click.echo(f"⏱️  Total time: {processing_time:.2f} seconds")
            
            if verbose:
                click.echo(f"🤖 Model used: {result.model_used}")
                if result.total_chunks > 1:
                    click.echo(f"🔄 Average time per chunk: {result.processing_time/result.total_chunks:.2f}s")
        else:
            click.echo(
                click.style(f"❌ Failed to save translated transcript to {output_file}", fg="red"),
                err=True
            )
            sys.exit(1)
    
    except KeyboardInterrupt:
        click.echo(
            click.style("\n🛑 Translation cancelled by user", fg="yellow"),
            err=True
        )
        sys.exit(1)
    except Exception as e:
        click.echo(
            click.style(f"❌ Unexpected error: {e}", fg="red"),
            err=True
        )
        if verbose:
            import traceback
            click.echo(traceback.format_exc(), err=True)
        sys.exit(1)


if __name__ == "__main__":
    main() 