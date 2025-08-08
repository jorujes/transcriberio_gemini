"""
Entity Detection Module

This module provides functionality for detecting entities in transcriptions using 
OpenAI's GPT-4.1 with Structured Outputs to ensure reliable JSON parsing.
"""

import json
import re
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from tenacity import retry, stop_after_attempt, wait_random_exponential
from api_client import create_api_client, DEFAULT_TEXT_MODEL


class EntityDetectionError(Exception):
    """Exception raised for errors in entity detection process."""
    pass


# Data classes (no change)
@dataclass
class Entity:
    """Data class for a single detected entity."""
    name: str
    type: str

@dataclass
class EntityDetectionResult:
    """Data class for the result of entity detection."""
    entities: List[Entity] = field(default_factory=list)
    unique_entity_count: int = 0
    processing_time: float = 0.0
    model_used: str = DEFAULT_TEXT_MODEL
    error_message: Optional[str] = None

class EntityDetector:
    """Detects entities in text using chunking for better performance."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = DEFAULT_TEXT_MODEL,
        max_retries: int = 3,
        verbose: bool = False,
        provider: Optional[str] = None
    ):
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self.verbose = verbose
        self.provider = provider
        
        # Create unified API client
        self.client = create_api_client(
            provider=provider,
            model=model,
            api_key=api_key,
            verbose=verbose
        )

    def detect_entities(self, transcript: str) -> EntityDetectionResult:
        """Orchestrates the entity detection process with chunking."""
        start_time = time.time()
        
        if self.verbose:
            print(f"📊 Transcript length: {len(transcript)} characters")

        if not transcript.strip():
            return EntityDetectionResult(
                entities=[],
                processing_time=time.time() - start_time,
                error_message="Transcript is empty."
            )

        try:
            chunks = self._create_text_chunks(transcript)
            if self.verbose:
                print(f"🧩 Divided transcript into {len(chunks)} chunks for entity detection.")

            all_entities_from_chunks = []
            for i, chunk in enumerate(chunks):
                if self.verbose:
                    print(f"🔄 Processing chunk {i+1}/{len(chunks)} ({len(chunk)} chars)...")
                
                chunk_entities = self._extract_entities_from_chunk(chunk)
                all_entities_from_chunks.extend(chunk_entities)

            unique_entities = self._merge_and_deduplicate_entities(all_entities_from_chunks)

            return EntityDetectionResult(
                entities=unique_entities,
                unique_entity_count=len(unique_entities),
                processing_time=time.time() - start_time
            )
        except Exception as e:
            if self.verbose:
                print(f"❌ An unexpected error occurred during entity detection: {e}")
            return EntityDetectionResult(
                entities=[],
                processing_time=time.time() - start_time,
                error_message=str(e)
            )

    def _create_text_chunks(self, text: str, max_chars: int = 8000) -> List[str]:
        """Splits text into chunks, respecting sentence boundaries."""
        sentences = re.split(r'(?<!\w\.\w.)(?<![A-Z][a-z]\.)(?<=\.|\?|\!)\s', text)
        chunks = []
        current_chunk = ""
        
        for sentence in sentences:
            if len(current_chunk) + len(sentence) + 1 > max_chars:
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = sentence
            else:
                current_chunk += (" " + sentence) if current_chunk else sentence
        
        if current_chunk:
            chunks.append(current_chunk)
            
        return chunks

    def _merge_and_deduplicate_entities(self, all_entities: List[Entity]) -> List[Entity]:
        """Merges entities from all chunks and removes duplicates."""
        unique_entities_map: Dict[tuple[str, str], Entity] = {}
        for entity in all_entities:
            key = (entity.name.strip().lower(), entity.type)
            if key not in unique_entities_map:
                unique_entities_map[key] = entity
        
        if self.verbose:
            print(f"🤝 Merged {len(all_entities)} total entities into {len(unique_entities_map)} unique ones.")
            
        return sorted(list(unique_entities_map.values()), key=lambda e: e.name)

    @retry(wait=wait_random_exponential(min=1, max=60), stop=stop_after_attempt(3))
    def _extract_entities_from_chunk(self, chunk_text: str) -> List[Entity]:
        """Extracts entities from a single text chunk, requesting a simple JSON list."""
        if self.verbose:
            print(f"   🎯 Analyzing chunk for entities...")

        system_prompt = "You are an expert entity extractor. Your task is to find all proper names of people and places in a given text and return them in a structured JSON format."
        user_prompt = f"""From the transcript chunk below, extract ALL proper names of people and places.

Follow these rules:
- Entity Types: Only 'PERSON' and 'LOCATION'.
- Extraction: Be comprehensive. Extract every proper name, even if mentioned only once.
- Output: Return a JSON object with two keys: "PERSON" (array of person names) and "LOCATION" (array of place names).

Example: {{"PERSON": ["John Doe", "Sarah Johnson"], "LOCATION": ["New York", "Harvard University"]}}

TRANSCRIPT CHUNK:
---
{chunk_text}
---
"""
        
        try:
            start_api_time = time.time()
            response = self.client.chat_completion(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                model=self.model,
                response_mime_type="application/json",
                response_schema={
                    "type": "object",
                    "properties": {
                        "PERSON": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Array of person names found in the text"
                        },
                        "LOCATION": {
                            "type": "array", 
                            "items": {"type": "string"},
                            "description": "Array of location names found in the text"
                        }
                    },
                    "required": ["PERSON", "LOCATION"]
                },
                temperature=0.0,
                timeout=180, # 3 minute timeout per chunk
            )
            api_duration = time.time() - start_api_time
            if self.verbose:
                print(f"   ✅ API response for chunk received in {api_duration:.2f}s")

            response_data = json.loads(response.choices[0].message.content)
            
            # Convert the optimized format to our Entity objects
            entities = []
            
            # Process PERSON entities
            persons = response_data.get("PERSON", [])
            for person_name in persons:
                if person_name and person_name.strip():
                    entities.append(Entity(name=person_name.strip(), type="PERSON"))
            
            # Process LOCATION entities
            locations = response_data.get("LOCATION", [])
            for location_name in locations:
                if location_name and location_name.strip():
                    entities.append(Entity(name=location_name.strip(), type="LOCATION"))
            
            return entities
        except Exception as e:
            if self.verbose:
                print(f"   ❌ API call or parsing failed for chunk: {e}")
            # Re-raise the exception to be handled by the tenacity @retry decorator
            raise e

def create_entity_detector(
    api_key: Optional[str] = None,
    model: str = DEFAULT_TEXT_MODEL,
    max_retries: int = 3,
    verbose: bool = False,
    provider: Optional[str] = None
) -> EntityDetector:
    """Factory function to create an EntityDetector instance."""
    return EntityDetector(
        api_key=api_key, 
        model=model, 
        max_retries=max_retries, 
        verbose=verbose,
        provider=provider
    ) 