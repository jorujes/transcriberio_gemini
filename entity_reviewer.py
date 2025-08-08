"""
Entity Review Module

This module provides an interactive CLI interface for reviewing and editing 
detected entities with find/replace functionality in transcript files.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

try:
    import inquirer
    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False


@dataclass
class EntityReview:
    """Data class for entity review results."""
    original: str
    replacement: str
    entity_type: str
    reviewed: bool = False


@dataclass 
class ReviewResult:
    """Data class for complete review session results."""
    success: bool
    reviews: List[EntityReview]
    replacements_made: int
    transcript_updated: bool
    error_message: Optional[str] = None


class EntityReviewer:
    """
    Interactive entity reviewer with CLI navigation.
    
    Provides a user-friendly interface to review detected entities and 
    make find/replace substitutions in transcript files.
    """
    
    def __init__(self, verbose: bool = False):
        """
        Initialize the entity reviewer.
        
        Args:
            verbose: Enable detailed logging
        """
        if not INQUIRER_AVAILABLE:
            raise ImportError(
                "inquirer library not available. Install with: pip install inquirer>=3.1.0"
            )
        
        self.verbose = verbose
    
    def review_entities(
        self, 
        entities_file: Path, 
        transcript_file: Path,
        skip_review: bool = False
    ) -> ReviewResult:
        """
        Start interactive entity review session.
        
        Args:
            entities_file: Path to entities JSON file
            transcript_file: Path to transcript file to modify
            skip_review: If True, skip interactive review
            
        Returns:
            ReviewResult with session details
        """
        try:
            # Load entities
            entities_data = self._load_entities(entities_file)
            if not entities_data:
                return ReviewResult(
                    success=False,
                    reviews=[],
                    replacements_made=0,
                    transcript_updated=False,
                    error_message="No entities found or invalid entities file"
                )
            
            # Load transcript
            transcript_content = self._load_transcript(transcript_file)
            if not transcript_content:
                return ReviewResult(
                    success=False,
                    reviews=[],
                    replacements_made=0,
                    transcript_updated=False,
                    error_message="Could not load transcript file"
                )
            
            print(f"\n🎯 Entity Review Session")
            print(f"📄 Transcript: {transcript_file.name}")
            print(f"🔍 Entities found: {sum(len(entities) for entities in entities_data.values())}")
            
            if skip_review:
                print("⏭️  Skipping review - using original entities")
                return ReviewResult(
                    success=True,
                    reviews=[],
                    replacements_made=0,
                    transcript_updated=False
                )
            
            # Interactive review
            reviews = self._interactive_review_session(entities_data)
            
            # Apply replacements
            updated_content, replacements_made = self._apply_replacements(
                transcript_content, reviews
            )
            
            # Save updated transcript if changes were made
            transcript_updated = False
            if replacements_made > 0:
                self._save_transcript(transcript_file, updated_content)
                transcript_updated = True
                print(f"\n✅ Transcript updated with {replacements_made} replacements")
            else:
                print(f"\n📝 No changes made to transcript")
            
            return ReviewResult(
                success=True,
                reviews=reviews,
                replacements_made=replacements_made,
                transcript_updated=transcript_updated
            )
            
        except Exception as e:
            return ReviewResult(
                success=False,
                reviews=[],
                replacements_made=0,
                transcript_updated=False,
                error_message=f"Review session failed: {str(e)}"
            )
    
    def _load_entities(self, entities_file: Path) -> Dict[str, List[Dict]]:
        """Load entities from JSON file."""
        try:
            with open(entities_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            return data.get('entities_by_type', {})
        except Exception as e:
            if self.verbose:
                print(f"Error loading entities: {e}")
            return {}
    
    def _load_transcript(self, transcript_file: Path) -> str:
        """Load transcript content from file."""
        try:
            with open(transcript_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract just the transcript content (after TRANSCRIPT CONTENT marker)
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
            
            # Fallback: return entire content if markers not found
            return content
            
        except Exception as e:
            if self.verbose:
                print(f"Error loading transcript: {e}")
            return ""
    
    def _interactive_review_session(self, entities_data: Dict[str, List[Dict]]) -> List[EntityReview]:
        """Run interactive review session with navigation."""
        reviews = []
        
        # Flatten entities for easy navigation
        all_entities = []
        for entity_type, entities in entities_data.items():
            for entity in entities:
                all_entities.append((entity_type, entity['text']))
        
        if not all_entities:
            print("📝 No entities to review")
            return reviews
        
        print(f"\n📋 Review Instructions:")
        print(f"• Use ↑/↓ arrows to navigate between entities")
        print(f"• Press Enter to keep original name")
        print(f"• Type replacement and press Enter to substitute")
        print(f"• Type 'skip' to skip remaining entities")
        print(f"• Type 'quit' to exit without saving")
        
        # Ask if user wants to proceed or skip all
        questions = [
            inquirer.List(
                'action',
                message="Choose action",
                choices=[
                    ('📝 Review entities one by one', 'review'),
                    ('⏭️  Skip review (keep all original)', 'skip'),
                    ('❌ Cancel', 'cancel')
                ]
            )
        ]
        
        answers = inquirer.prompt(questions)
        if not answers or answers['action'] != 'review':
            if answers and answers['action'] == 'cancel':
                print("❌ Review cancelled")
            return reviews
        
        print(f"\n🔍 Starting entity review...\n")
        
        # Review each entity
        for i, (entity_type, entity_text) in enumerate(all_entities):
            print(f"\n📍 Entity {i+1}/{len(all_entities)}")
            print(f"🏷️  Type: {entity_type}")
            print(f"📝 Current: '{entity_text}'")
            
            # Interactive input with custom message
            questions = [
                inquirer.Text(
                    'replacement',
                    message=f"Replace '{entity_text}' with",
                    default=""
                )
            ]
            
            try:
                answers = inquirer.prompt(questions)
                if not answers:  # User pressed Ctrl+C
                    print("\n⏹️  Review cancelled by user")
                    break
                
                replacement = answers['replacement'].strip()
                
                # Handle special commands
                if replacement.lower() == 'skip':
                    print("⏭️  Skipping remaining entities")
                    break
                elif replacement.lower() == 'quit':
                    print("❌ Quitting without saving")
                    return []
                elif replacement == '':
                    print(f"✅ Keeping original: '{entity_text}'")
                    reviews.append(EntityReview(
                        original=entity_text,
                        replacement=entity_text,
                        entity_type=entity_type,
                        reviewed=True
                    ))
                else:
                    print(f"🔄 Will replace '{entity_text}' → '{replacement}'")
                    reviews.append(EntityReview(
                        original=entity_text,
                        replacement=replacement,
                        entity_type=entity_type,
                        reviewed=True
                    ))
                    
            except KeyboardInterrupt:
                print("\n⏹️  Review cancelled by user")
                break
            except Exception as e:
                print(f"⚠️  Error during input: {e}")
                continue
        
        return reviews
    
    def _apply_replacements(
        self, 
        transcript_content: str, 
        reviews: List[EntityReview]
    ) -> Tuple[str, int]:
        """Apply entity replacements to transcript content."""
        updated_content = transcript_content
        replacements_made = 0
        
        for review in reviews:
            if review.replacement != review.original:
                # Use word boundary replacement to avoid partial matches
                pattern = r'\b' + re.escape(review.original) + r'\b'
                
                # Count how many replacements will be made
                matches = len(re.findall(pattern, updated_content, re.IGNORECASE))
                
                if matches > 0:
                    # Case-preserving replacement
                    updated_content = re.sub(
                        pattern, 
                        review.replacement, 
                        updated_content, 
                        flags=re.IGNORECASE
                    )
                    replacements_made += matches
                    
                    if self.verbose:
                        print(f"Replaced '{review.original}' → '{review.replacement}' ({matches} times)")
        
        return updated_content, replacements_made
    
    def _save_transcript(self, transcript_file: Path, updated_content: str):
        """Save updated transcript back to file."""
        try:
            # Read original file to preserve structure
            with open(transcript_file, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            # Replace only the transcript content section
            lines = original_content.split('\n')
            transcript_start = -1
            transcript_end = -1
            
            for i, line in enumerate(lines):
                if '📝 TRANSCRIPT CONTENT:' in line:
                    transcript_start = i + 2
                elif transcript_start > 0 and 'End of Transcript' in line:
                    transcript_end = i
                    break
            
            if transcript_start > 0:
                # Rebuild file with updated content
                new_lines = (
                    lines[:transcript_start] + 
                    updated_content.split('\n') +
                    ([''] if transcript_end > 0 else []) +
                    (lines[transcript_end:] if transcript_end > 0 else ['', '='*80, 'End of Transcript', '='*80])
                )
                
                with open(transcript_file, 'w', encoding='utf-8') as f:
                    f.write('\n'.join(new_lines))
            else:
                # Fallback: replace entire file content
                with open(transcript_file, 'w', encoding='utf-8') as f:
                    f.write(updated_content)
                    
        except Exception as e:
            if self.verbose:
                print(f"Error saving transcript: {e}")
            raise


def create_entity_reviewer(verbose: bool = False) -> EntityReviewer:
    """
    Factory function to create an EntityReviewer instance.
    
    Args:
        verbose: Enable verbose logging
        
    Returns:
        Configured EntityReviewer instance
    """
    return EntityReviewer(verbose=verbose) 