"""
Translation and Idiomatic Normalization Module

This module provides functionality for translating and idiomatically normalizing 
transcripts using GPT-4.1 with intelligent chunking and regional language variants.
"""

import os
import time
import json
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

try:
    import inquirer
    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False

try:
    from api_client import create_api_client, DEFAULT_TEXT_MODEL
    API_CLIENT_AVAILABLE = True
except ImportError:
    API_CLIENT_AVAILABLE = False
    DEFAULT_TEXT_MODEL = "gemini-2.5-pro"  # Fallback


@dataclass
class LanguageOption:
    """Data class for language selection options."""
    code: str
    name: str
    region: str
    
    def display_name(self) -> str:
        return f"{self.name} ({self.region})"


@dataclass
class TranslationChunk:
    """Data class for text chunks to be translated."""
    index: int
    text: str
    char_start: int
    char_end: int
    estimated_tokens: int


@dataclass
class TranslationResult:
    """Data class for translation results."""
    success: bool
    target_language: str
    original_text: str
    translated_text: str
    chunks_processed: int
    total_chunks: int
    processing_time: float
    word_count_original: int
    word_count_translated: int
    model_used: str = DEFAULT_TEXT_MODEL
    error_message: Optional[str] = None
    initial_translation: Optional[str] = None  # Store initial translation before reprocessing
    reprocessed: bool = False  # Flag to indicate if text was reprocessed


class TranslatorNormalizer:
    """
    Translation and idiomatic normalization service using GPT-4.1.
    
    Provides intelligent chunking, regional language selection, and 
    idiomatic translation with natural fluency optimization.
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_TEXT_MODEL,
        max_retries: int = 3,
        verbose: bool = False,
        provider: Optional[str] = None
    ):
        """
        Initialize the translator.
        
        Args:
            api_key: OpenAI API key (if None, uses OPENAI_API_KEY env var)
            model: Model to use (gpt-4.1 recommended for context size)
            max_retries: Maximum number of retry attempts
            verbose: Enable detailed logging
        """
        if not API_CLIENT_AVAILABLE:
            raise ImportError(
                "API client not available. Check api_client.py module."
            )
        
        if not INQUIRER_AVAILABLE:
            raise ImportError(
                "inquirer library not available. Install with: pip install inquirer>=3.1.0"
            )
        
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.provider = provider
        
        # GPT-4.1 context limits
        self.max_input_tokens = 1000000  # 1M tokens context window
        self.max_output_tokens = 32768   # 32K max output
        self.safety_margin = 0.8         # Use 80% of context for safety
        
        # Initialize unified API client
        self.client = create_api_client(
            provider=provider,
            model=model,
            api_key=api_key,
            verbose=verbose
        )
        
        # Define supported languages with regional variants
        self.languages = [
            LanguageOption("pt-BR", "Português", "Brasil"),
            LanguageOption("pt-PT", "Português", "Portugal"),
            LanguageOption("es-ES", "Español", "España"),
            LanguageOption("es-MX", "Español", "México"),
            LanguageOption("es-AR", "Español", "Argentina"),
            LanguageOption("es-CO", "Español", "Colombia"),
            LanguageOption("fr-FR", "Français", "France"),
            LanguageOption("fr-CA", "Français", "Canada"),
            LanguageOption("de-DE", "Deutsch", "Deutschland"),
            LanguageOption("de-AT", "Deutsch", "Österreich"),
            LanguageOption("ja-JP", "日本語", "Japan"),
            LanguageOption("ru-RU", "Русский", "Russia"),
            LanguageOption("ar-SA", "العربية", "Saudi Arabia"),
            LanguageOption("ar-EG", "العربية", "Egypt"),
            LanguageOption("ar-MA", "العربية", "Morocco"),
            LanguageOption("ko-KR", "한국어", "Korea"),
            LanguageOption("en-US", "English", "United States"),
            LanguageOption("en-GB", "English", "United Kingdom"),
            LanguageOption("en-CA", "English", "Canada"),
            LanguageOption("en-AU", "English", "Australia"),
        ]
    
    def translate_transcript(
        self, 
        transcript_file: Path,
        skip_translation: bool = False
    ) -> TranslationResult:
        """
        Translate and normalize a transcript file.
        
        Args:
            transcript_file: Path to transcript file
            skip_translation: If True, skip translation and use original
            
        Returns:
            TranslationResult with translation details
        """
        start_time = time.time()
        
        try:
            # Load transcript content
            original_text = self._load_transcript_content(transcript_file)
            if not original_text:
                return TranslationResult(
                    success=False,
                    target_language="",
                    original_text="",
                    translated_text="",
                    chunks_processed=0,
                    total_chunks=0,
                    processing_time=0,
                    word_count_original=0,
                    word_count_translated=0,
                    error_message="Could not load transcript content"
                )
            
            print(f"\n🌍 Translation and Normalization")
            print(f"📄 Source: {transcript_file.name}")
            print(f"📊 Text length: {len(original_text)} characters")
            print(f"📝 Word count: {len(original_text.split())} words")
            
            if skip_translation:
                print("⏭️  Skipping translation - using original text")
                return TranslationResult(
                    success=True,
                    target_language="original",
                    original_text=original_text,
                    translated_text=original_text,
                    chunks_processed=0,
                    total_chunks=0,
                    processing_time=time.time() - start_time,
                    word_count_original=len(original_text.split()),
                    word_count_translated=len(original_text.split())
                )
            
            # Language selection
            target_language = self._select_target_language()
            if not target_language:
                print("❌ Translation cancelled")
                return TranslationResult(
                    success=False,
                    target_language="",
                    original_text=original_text,
                    translated_text="",
                    chunks_processed=0,
                    total_chunks=0,
                    processing_time=time.time() - start_time,
                    word_count_original=len(original_text.split()),
                    word_count_translated=0,
                    error_message="Translation cancelled by user"
                )
            
            # Test API connectivity with gpt-4.1
            if self.verbose:
                print(f"🔍 Testing API connectivity with gpt-4.1...")
            try:
                test_response = self.client.chat_completion(
                    messages=[{"role": "user", "content": "Hello"}],
                    model=self.model,
                    max_tokens=10,
                    timeout=30
                )
                if self.verbose:
                    print(f"✅ API connectivity test successful")
                    print(f"✅ gpt-4.1 is accessible")
            except Exception as e:
                print(f"❌ API connectivity test failed with gpt-4.1: {e}")
                return TranslationResult(
                    success=False,
                    target_language=target_language,
                    original_text=original_text,
                    translated_text="",
                    chunks_processed=0,
                    total_chunks=0,
                    processing_time=time.time() - start_time,
                    word_count_original=len(original_text.split()),
                    word_count_translated=0,
                    error_message=f"gpt-4.1 connectivity failed: {e}"
                )
            
            # Create intelligent chunks
            chunks = self._create_intelligent_chunks(original_text)
            print(f"🧩 Created {len(chunks)} chunks for processing")
            
            # Translate chunks
            translated_chunks = []
            for i, chunk in enumerate(chunks):
                print(f"🔄 Translating chunk {i+1}/{len(chunks)}...")
                
                if self.verbose:
                    print(f"   📝 Chunk text preview: {chunk.text[:100]}...")
                
                translated_text = self._translate_chunk(chunk.text, target_language)
                
                if self.verbose:
                    print(f"   🔙 Returned from _translate_chunk")
                
                if translated_text:
                    translated_chunks.append(translated_text)
                    if self.verbose:
                        print(f"   ✅ Chunk {i+1} completed ({len(translated_text)} chars)")
                else:
                    print(f"   ⚠️  Chunk {i+1} failed, using original")
                    translated_chunks.append(chunk.text)
            
            # Reconstruct final text
            final_translated_text = self._reconstruct_text(translated_chunks)
            
            # Create initial translation result
            initial_translation_result = TranslationResult(
                success=True,
                target_language=target_language,
                original_text=original_text,
                translated_text=final_translated_text,
                chunks_processed=len(translated_chunks),
                total_chunks=len(chunks),
                processing_time=time.time() - start_time,
                word_count_original=len(original_text.split()),
                word_count_translated=len(final_translated_text.split()),
                model_used=self.model
            )
            
            # Now automatically reprocess the translation for better quality
            if self.verbose:
                print(f"\n🔄 Starting automatic reprocessing for better quality...")
            
            reprocessing_result = self.reprocess_translation(final_translated_text, target_language)
            
            # Combine processing times
            total_processing_time = initial_translation_result.processing_time + reprocessing_result.processing_time
            
            # Return the reprocessed result with combined metadata
            return TranslationResult(
                success=True,
                target_language=target_language,
                original_text=original_text,
                translated_text=reprocessing_result.translated_text,
                chunks_processed=len(translated_chunks),
                total_chunks=len(chunks),
                processing_time=total_processing_time,
                word_count_original=len(original_text.split()),
                word_count_translated=len(reprocessing_result.translated_text.split()),
                model_used=self.model,
                initial_translation=final_translated_text,  # Store the initial translation
                reprocessed=True
            )
            
        except Exception as e:
            return TranslationResult(
                success=False,
                target_language="",
                original_text="",
                translated_text="",
                chunks_processed=0,
                total_chunks=0,
                processing_time=time.time() - start_time,
                word_count_original=0,
                word_count_translated=0,
                error_message=f"Translation failed: {str(e)}"
            )
    
    def _load_transcript_content(self, transcript_file: Path) -> str:
        """Load and extract transcript content from file."""
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract transcript content section
            lines = content.split('\n')
            transcript_start = -1
            
            for i, line in enumerate(lines):
                if '📝 TRANSCRIPT CONTENT:' in line:
                    transcript_start = i + 2  # Skip the === line
                    break
            
            if transcript_start > 0:
                transcript_content = '\n'.join(lines[transcript_start:])
                # Remove ending markers
                if 'End of Transcript' in transcript_content:
                    transcript_content = transcript_content.split('End of Transcript')[0]
                return transcript_content.strip()
            
            # Fallback: use entire content
            return content.strip()
            
        except Exception as e:
            if self.verbose:
                print(f"Error loading transcript: {e}")
            return ""
    
    def _extract_youtube_metadata(self, transcript_file: Path) -> str:
        """Extract YouTube metadata from transcript file."""
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract everything before the transcript content
            if '📝 TRANSCRIPT CONTENT:' in content:
                metadata_section = content.split('📝 TRANSCRIPT CONTENT:')[0]
                return metadata_section.strip()
            
            return ""
        except Exception as e:
            if self.verbose:
                print(f"Warning: Could not extract metadata: {e}")
            return ""
    
    def _select_target_language(self) -> str:
        """Interactive language selection with navigation."""
        print(f"\n🌍 Language Selection")
        print(f"Choose target language for translation and normalization:")
        
        # Create choices for inquirer
        choices = []
        for lang in self.languages:
            choices.append((f"{lang.code} - {lang.display_name()}", lang.code))
        
        # Add option to skip translation
        choices.append(("⏭️  Skip translation (keep original)", "skip"))
        choices.append(("❌ Cancel", "cancel"))
        
        questions = [
            inquirer.List(
                'language',
                message="Select target language",
                choices=choices,
                carousel=True  # Enable circular navigation
            )
        ]
        
        try:
            answers = inquirer.prompt(questions)
            if not answers:
                return ""
            
            selected = answers['language']
            
            if selected == 'skip':
                return "original"
            elif selected == 'cancel':
                return ""
            else:
                # Find the selected language details
                lang_info = next((l for l in self.languages if l.code == selected), None)
                if lang_info:
                    print(f"✅ Selected: {lang_info.display_name()} ({lang_info.code})")
                return selected
                
        except KeyboardInterrupt:
            print("\n⏹️  Language selection cancelled")
            return ""
        except Exception as e:
            if self.verbose:
                print(f"Error in language selection: {e}")
            return ""
    
    def _create_intelligent_chunks(self, text: str) -> List[TranslationChunk]:
        """
        Splits a long text into smaller, intelligent chunks for translation.
        This method tries to preserve sentence boundaries to provide better context.
        """
        # GPT-4.1 has a large context window, but smaller chunks can be faster
        # and more reliable for very long texts. Let's aim for ~3-4 chunks for a 30-min video transcript.
        # ~45k chars / 3 chunks = ~15k chars/chunk
        max_chars_per_chunk = 7000  # Aiming for smaller chunks for more detailed processing
        if self.verbose:
            print(f"Max chars per chunk: {max_chars_per_chunk}")

        sentences = self._split_into_sentences(text)
        if not sentences:
            return []

        chunks = []
        current_chunk = ""
        current_start = 0

        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > max_chars_per_chunk:
                if current_chunk:
                    chunk_end = current_start + len(current_chunk) - 1
                    chunks.append(TranslationChunk(
                        index=len(chunks) + 1,
                        text=current_chunk.strip(),
                        char_start=current_start,
                        char_end=chunk_end,
                        estimated_tokens=len(current_chunk) // 4 # Conservative estimate
                    ))
                    current_start = chunk_end + 1
                current_chunk = sentence
            else:
                current_chunk += (" " + sentence) if current_chunk else sentence

        if current_chunk:
            chunk_end = current_start + len(current_chunk) - 1
            chunks.append(TranslationChunk(
                index=len(chunks) + 1,
                text=current_chunk.strip(),
                char_start=current_start,
                char_end=chunk_end,
                estimated_tokens=len(current_chunk) // 4 # Conservative estimate
            ))
        
        if self.verbose:
            print(f"Created {len(chunks)} chunks, total chars: {sum(len(c.text) for c in chunks):,}")

        return chunks

    def _split_into_sentences(self, text: str) -> List[str]:
        """Splits text into sentences using regex."""
        # This regex handles various sentence endings and abbreviations
        # It's not perfect but works reasonably well for this use case
        return re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s', text)

    def _translate_chunk(self, chunk_text: str, target_language: str) -> str:
        """Translates a single chunk of text using the specified language."""
        
        lang_info = next((l for l in self.languages if l.code == target_language), None)
        if not lang_info:
            if self.verbose:
                print(f"   ⚠️ Unknown language '{target_language}', using original text.")
            return chunk_text
        
        if self.verbose:
            print(f"   🌍 Target: {lang_info.display_name()}")
        
        # Create specialized prompt for idiomatic translation (concise system, detailed user)
        system_prompt = f"""You are an expert translator specializing in {lang_info.display_name()}. Return only the translated text, maintaining original structure."""

        user_prompt = f"""Please translate and idiomatically normalize this text to {lang_info.display_name()} ({lang_info.region}).

IMPORTANT GUIDELINES:
- Correct any grammatical or punctuation errors found in the original source text.
- Censor and replace any swear words or sexually explicit language with politically correct and appropriate alternatives.
- Adapt all elements for a natural, local feel: idioms, cultural references, transition phrases, interjections, modifiers, and colloquialisms.
- Translate meaning, not just words.
- Maintain the original tone and narrative style (e.g., serious, humorous).
- Ensure the final translated text has perfect grammar and a natural rhythm for {lang_info.region}.
- CRITICAL: Enclose all dialogues and spoken lines in double quotation marks (" ").
- Preserve paragraph breaks and formatting.
- REMEMBER: All character speech must be inside quotation marks.
- Ensure no sentences are lost or truncated from the original.
- Answer with a continual paragraph, not a list of sentences, and do not use markdown formatting.
- Do not put line breaks in your answer.

TEXT TO TRANSLATE:
{chunk_text}

TRANSLATED TEXT:"""
        
        if self.verbose:
            print(f"   📝 System prompt length: {len(system_prompt)} chars")
            print(f"   📝 User prompt length: {len(user_prompt)} chars")
            print(f"   📝 System: {system_prompt[:100]}...")
            print(f"   📝 User preview: {user_prompt[:200]}...")

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    print(f"   🔄 Retry attempt {attempt + 1}/{self.max_retries}")
                
                if self.verbose:
                    estimated_tokens = min(len(chunk_text) * 2, self.max_output_tokens)
                    print(f"   📞 Calling OpenAI API (max_tokens: {estimated_tokens})")
                    print(f"   🤖 Model: {self.model}")
                    print(f"   ⏱️  Starting API call at {time.strftime('%H:%M:%S')}")
                
                start_api_time = time.time()
                
                try:
                    print(f"   🔄 Making API request...")
                    response = self.client.chat_completion(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        model=self.model,
                        temperature=0.8,  # Adjusted for Gemini range (0-2), equivalent to 0.4 in GPT
                        max_tokens=min(len(chunk_text) * 2, self.max_output_tokens),  # Estimate output length
                        timeout=120  # 2 minute timeout to prevent hanging
                    )
                    
                    api_duration = time.time() - start_api_time
                    print(f"   ✅ API response received in {api_duration:.2f}s")
                    
                except Exception as api_error:
                    api_duration = time.time() - start_api_time
                    print(f"   ❌ API call failed after {api_duration:.2f}s: {api_error}")
                    raise api_error
                
                if self.verbose:
                    print(f"   🔍 Processing API response...")
                    print(f"   📊 Response choices: {len(response.choices)}")
                
                translated_text = response.choices[0].message.content
                
                if self.verbose:
                    if translated_text:
                        print(f"   📝 Response length: {len(translated_text)} chars")
                        print(f"   📝 Response preview: {translated_text[:100]}...")
                    else:
                        print(f"   ⚠️  Empty response content")
                
                if translated_text:
                    if self.verbose:
                        print(f"   ✅ Translation successful, returning result")
                    return translated_text.strip()
                else:
                    if self.verbose:
                        print(f"   ⚠️  No content in response, will retry")
                
            except Exception as e:
                if self.verbose:
                    print(f"   ⚠️  Translation attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    return chunk_text  # Return original on final failure
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return chunk_text
    
    def _reconstruct_text(self, translated_chunks: List[str]) -> str:
        """Reconstruct final text from translated chunks."""
        # Join chunks with single space instead of line breaks for continuous text
        return " ".join(chunk.strip() for chunk in translated_chunks if chunk.strip())

    def _reprocess_chunk(self, chunk_text: str, target_language: str) -> str:
        """Reprocesses a translated chunk to make it more natural and less literal."""
        
        lang_info = next((l for l in self.languages if l.code == target_language), None)
        if not lang_info:
            if self.verbose:
                print(f"   ⚠️ Unknown language '{target_language}', using original text.")
            return chunk_text
        
        if self.verbose:
            print(f"   🔄 Reprocessing for: {lang_info.display_name()}")
        
        # Create the "scolding" prompt to improve translation quality
        system_prompt = f"""You are an expert translator and language editor specializing in {lang_info.display_name()}. Your task is to improve translations that are too literal."""

        user_prompt = f"""The translation you did earlier was too literal. I need you to pay attention to the characteristics of the target language ({lang_info.display_name()}), which you didn't do! Please rewrite these sentences, keep the quotation marks for dialogues, use better punctuation if you can, but get rid of the 'translator's English' feel and adapt them to decent {lang_info.display_name()}. Again, avoid line breaks and dashes, but make sure the text feels natural and well-translated, not artificial as it is now.

CRITICAL REQUIREMENTS:
- Make it sound natural in {lang_info.display_name()}, not like a machine translation
- Eliminate awkward literal translations and English sentence structures
- Use idiomatic expressions native to {lang_info.region}
- Maintain all quotation marks for dialogues
- Improve punctuation and flow
- Keep the same meaning but make it sound like it was originally written in {lang_info.display_name()}
- Answer with a continual paragraph, not a list of sentences
- Do not use markdown formatting or line breaks



TEXT TO REPROCESS:
{chunk_text}

IMPROVED TEXT:"""
        
        if self.verbose:
            print(f"   📝 Reprocessing system prompt length: {len(system_prompt)} chars")
            print(f"   📝 Reprocessing user prompt length: {len(user_prompt)} chars")

        for attempt in range(self.max_retries):
            try:
                if attempt > 0:
                    print(f"   🔄 Reprocessing retry attempt {attempt + 1}/{self.max_retries}")
                
                if self.verbose:
                    estimated_tokens = min(len(chunk_text) * 2, self.max_output_tokens)
                    print(f"   📞 Calling API for reprocessing (max_tokens: {estimated_tokens})")
                    print(f"   🤖 Model: {self.model}")
                    print(f"   ⏱️  Starting reprocessing API call at {time.strftime('%H:%M:%S')}")
                
                start_api_time = time.time()
                
                try:
                    print(f"   🔄 Making reprocessing API request...")
                    response = self.client.chat_completion(
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt}
                        ],
                        model=self.model,
                        temperature=1.6,  # Higher creativity for reprocessing (equivalent to 0.8 in GPT)
                        max_tokens=min(len(chunk_text) * 2, self.max_output_tokens),
                        timeout=120
                    )
                    
                    api_duration = time.time() - start_api_time
                    print(f"   ✅ Reprocessing API response received in {api_duration:.2f}s")
                    
                except Exception as api_error:
                    api_duration = time.time() - start_api_time
                    print(f"   ❌ Reprocessing API call failed after {api_duration:.2f}s: {api_error}")
                    raise api_error
                
                if self.verbose:
                    print(f"   🔍 Processing reprocessing API response...")
                    print(f"   📊 Response choices: {len(response.choices)}")
                
                reprocessed_text = response.choices[0].message.content
                
                if self.verbose:
                    if reprocessed_text:
                        print(f"   📝 Reprocessed length: {len(reprocessed_text)} chars")
                        print(f"   📝 Reprocessed preview: {reprocessed_text[:100]}...")
                    else:
                        print(f"   ⚠️  Empty reprocessing response content")
                
                if reprocessed_text:
                    if self.verbose:
                        print(f"   ✅ Reprocessing successful, returning result")
                    return reprocessed_text.strip()
                else:
                    if self.verbose:
                        print(f"   ⚠️  No content in reprocessing response, will retry")
                
            except Exception as e:
                if self.verbose:
                    print(f"   ⚠️  Reprocessing attempt {attempt + 1} failed: {e}")
                if attempt == self.max_retries - 1:
                    return chunk_text  # Return original on final failure
                time.sleep(2 ** attempt)  # Exponential backoff
        
        return chunk_text

    def reprocess_translation(self, translated_text: str, target_language: str) -> TranslationResult:
        """
        Reprocesses an already translated text to make it more natural and less literal.
        
        Args:
            translated_text: The translated text to reprocess
            target_language: Target language code (e.g., 'pt-PT', 'pt-BR')
            
        Returns:
            TranslationResult with reprocessed text
        """
        if self.verbose:
            print(f"\n🔄 Starting translation reprocessing...")
            print(f"📝 Text length: {len(translated_text):,} characters")
            print(f"📝 Estimated words: {len(translated_text.split()):,}")
            print(f"🌍 Target language: {target_language}")
            print(f"🤖 Model: {self.model}")
        
        start_time = time.time()
        
        # Create chunks using the same method as translation
        chunks = self._create_intelligent_chunks(translated_text)
        
        if self.verbose:
            print(f"🧩 Created {len(chunks)} chunks for reprocessing")
        
        reprocessed_chunks = []
        
        for i, chunk in enumerate(chunks, 1):
            if self.verbose:
                print(f"🔄 Reprocessing chunk {i}/{len(chunks)}...")
                print(f"   📝 Chunk text preview: {chunk.text[:100]}...")
            
            chunk_start_time = time.time()
            reprocessed_chunk = self._reprocess_chunk(chunk.text, target_language)
            chunk_duration = time.time() - chunk_start_time
            
            if self.verbose:
                print(f"   🔙 Returned from _reprocess_chunk")
                print(f"   ✅ Chunk {i} completed ({len(reprocessed_chunk)} chars)")
            
            reprocessed_chunks.append(reprocessed_chunk)
        
        # Reconstruct final text
        final_text = self._reconstruct_text(reprocessed_chunks)
        
        # Calculate metrics
        processing_time = time.time() - start_time
        word_count_original = len(translated_text.split())
        word_count_reprocessed = len(final_text.split())
        
        result = TranslationResult(
            success=True,
            translated_text=final_text,
            target_language=target_language,
            model_used=self.model,
            processing_time=processing_time,
            word_count_original=word_count_original,
            word_count_translated=word_count_reprocessed,
            chunks_processed=len(reprocessed_chunks),
            total_chunks=len(chunks),
            original_text=translated_text  # Store the original translated text
        )
        
        if self.verbose:
            print(f"\n✅ Reprocessing completed successfully!")
            print(f"🌍 Target language: {target_language}")
            print(f"📊 Original words: {word_count_original:,}")
            print(f"📊 Reprocessed words: {word_count_reprocessed:,}")
            print(f"🧩 Chunks processed: {len(reprocessed_chunks)}/{len(chunks)}")
            print(f"⏱️  Total time: {processing_time:.2f} seconds")
            print(f"🤖 Model used: {self.model}")
            print(f"🔄 Average time per chunk: {processing_time/len(chunks):.2f}s")
        
        return result
    
    def save_translated_transcript(
        self, 
        result: TranslationResult, 
        output_file: Path,
        original_transcript_file: Optional[Path] = None
    ) -> Tuple[bool, Optional[Path]]:
        """Save translated transcript to file with metadata. If reprocessed, also saves the initial translation."""
        try:
            reprocessed_file = None
            
            # If this is a reprocessed result, save the initial translation first
            if result.reprocessed and result.initial_translation:
                # Save initial translation
                with open(output_file, 'w', encoding='utf-8') as f:
                    self._write_translation_file(f, result, result.initial_translation, original_transcript_file, is_initial=True)
                
                # Create reprocessed filename
                file_stem = output_file.stem
                file_suffix = output_file.suffix
                reprocessed_file = output_file.parent / f"{file_stem}_reprocessed{file_suffix}"
                
                # Save reprocessed translation
                with open(reprocessed_file, 'w', encoding='utf-8') as f:
                    self._write_translation_file(f, result, result.translated_text, original_transcript_file, is_initial=False)
                
                if self.verbose:
                    print(f"📄 Initial translation saved: {output_file}")
                    print(f"📄 Reprocessed translation saved: {reprocessed_file}")
                
            else:
                # Save regular translation
                with open(output_file, 'w', encoding='utf-8') as f:
                    self._write_translation_file(f, result, result.translated_text, original_transcript_file, is_initial=False)
                
                if self.verbose:
                    print(f"📄 Translation saved: {output_file}")
            
            return True, reprocessed_file
            
        except Exception as e:
            if self.verbose:
                print(f"Error saving translated transcript: {e}")
            return False, None

    def _write_translation_file(
        self, 
        file_handle, 
        result: TranslationResult, 
        content: str, 
        original_transcript_file: Optional[Path], 
        is_initial: bool
    ):
        """Helper method to write translation file content."""
        # Include YouTube metadata if available
        if original_transcript_file:
            youtube_metadata = self._extract_youtube_metadata(original_transcript_file)
            if youtube_metadata:
                file_handle.write(youtube_metadata + "\n\n")
        
        file_handle.write("="*80 + "\n")
        if is_initial:
            file_handle.write("🌍 TRANSLATED TRANSCRIPT (INITIAL)\n")
        elif result.reprocessed:
            file_handle.write("🌍 TRANSLATED TRANSCRIPT (REPROCESSED)\n")
        else:
            file_handle.write("🌍 TRANSLATED AND NORMALIZED TRANSCRIPT\n")
        file_handle.write("="*80 + "\n\n")
        
        # Translation Information
        file_handle.write("🔄 TRANSLATION INFORMATION:\n")
        file_handle.write("-" * 40 + "\n")
        file_handle.write(f"Target Language: {result.target_language}\n")
        file_handle.write(f"Model Used: {result.model_used}\n")
        file_handle.write(f"Processing Time: {result.processing_time:.2f} seconds\n")
        file_handle.write(f"Chunks Processed: {result.chunks_processed}/{result.total_chunks}\n")
        if result.reprocessed:
            file_handle.write(f"Reprocessed: {'Yes' if not is_initial else 'No'}\n")
        file_handle.write(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        file_handle.write("\n")
        
        # Statistics
        file_handle.write("📊 TRANSLATION STATISTICS:\n")
        file_handle.write("-" * 40 + "\n")
        file_handle.write(f"Original Words: {result.word_count_original:,}\n")
        
        if is_initial and result.initial_translation:
            word_count = len(result.initial_translation.split())
            file_handle.write(f"Translated Words: {word_count:,}\n")
            file_handle.write(f"Word Ratio: {word_count/result.word_count_original:.2f}x\n")
            file_handle.write(f"Original Characters: {len(result.original_text):,}\n")
            file_handle.write(f"Translated Characters: {len(result.initial_translation):,}\n")
        else:
            file_handle.write(f"Translated Words: {result.word_count_translated:,}\n")
            file_handle.write(f"Word Ratio: {result.word_count_translated/result.word_count_original:.2f}x\n")
            file_handle.write(f"Original Characters: {len(result.original_text):,}\n")
            file_handle.write(f"Translated Characters: {len(content):,}\n")
        
        file_handle.write("\n")
        
        # Translated Content
        file_handle.write("="*80 + "\n")
        if is_initial:
            file_handle.write("📝 INITIAL TRANSLATED CONTENT:\n")
        else:
            file_handle.write("📝 TRANSLATED CONTENT:\n")
        file_handle.write("="*80 + "\n\n")
        file_handle.write(content)
        file_handle.write("\n\n")
        file_handle.write("="*80 + "\n")
        file_handle.write("End of Translated Transcript\n")
        file_handle.write("="*80 + "\n")


def create_translator_normalizer(
    api_key: Optional[str] = None,
    model: str = DEFAULT_TEXT_MODEL,
    verbose: bool = False,
    provider: Optional[str] = None
) -> TranslatorNormalizer:
    """
    Factory function to create a TranslatorNormalizer instance.
    
    Args:
        api_key: API key (optional)
        model: Model to use for translation
        verbose: Enable verbose logging
        provider: API provider (automatically detected from model if not specified)
        
    Returns:
        Configured TranslatorNormalizer instance
    """
    return TranslatorNormalizer(
        api_key=api_key,
        model=model,
        verbose=verbose,
        provider=provider
    ) 