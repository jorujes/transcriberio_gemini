#!/usr/bin/env python3
"""
Centralized API Client for OpenAI and OpenRouter
Provides a unified interface to switch between providers easily
"""

import os
import json
from typing import Optional, Dict, Any, List
from openai import OpenAI


class APIConfig:
    """Configuration for API providers"""
    
    # Default configuration - easily changeable
    DEFAULT_PROVIDER = "gemini"  # "openai", "openrouter", or "gemini"
    
    # Centralized model configuration - CHANGE MODELS HERE ONLY!
    DEFAULT_TRANSCRIPTION_MODEL = "gemini-2.5-flash"  # For audio-to-text transcription
    DEFAULT_TEXT_MODEL = "gemini-2.5-pro"  # For text processing (translation, entity detection, etc.)
    
    # Valid transcription models
    VALID_TRANSCRIPTION_MODELS = ["gemini-2.5-flash", "gpt-4o-transcribe", "gpt-4o-mini-transcribe"]
    
    # Provider configurations
    PROVIDERS = {
        "openai": {
            "base_url": None,  # Uses default OpenAI URL
            "models": {
                "gpt-4.1": "gpt-4.1",
                "gpt-4o": "gpt-4o", 
                "gpt-4o-mini": "gpt-4o-mini",
                "gpt-4o-transcribe": "gpt-4o-transcribe",
                "gpt-4o-mini-transcribe": "gpt-4o-mini-transcribe"
            }
        },
        "gemini": {
            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
            "models": {
                "gemini-2.5-flash": "gemini-2.5-flash",
                "gemini-2.5-pro": "gemini-2.5-pro",
                "gemini-2.0-flash": "gemini-2.0-flash",
                "gemini-1.5-flash": "gemini-1.5-flash",
                "gemini-1.5-pro": "gemini-1.5-pro"
            }
        },
        "openrouter": {
            "base_url": "https://openrouter.ai/api/v1",
            "models": {
                "gpt-4.1": "openai/gpt-4.1",
                "gpt-4o": "openai/gpt-4o",
                "gpt-4o-mini": "openai/gpt-4o-mini",
                "claude-3.5-sonnet": "anthropic/claude-3.5-sonnet",
                "claude-3-haiku": "anthropic/claude-3-haiku",
                "claude-opus-4": "anthropic/claude-3.5-opus",
                "claude-sonnet-4": "anthropic/claude-3.5-sonnet",
                "claude-sonnet-3.7": "anthropic/claude-3.5-sonnet",
                "claude-haiku-3.5": "anthropic/claude-3.5-haiku"
            },
            "extra_headers": {
                "HTTP-Referer": "https://github.com/jorujes/transcriberio",
                "X-Title": "TranscriberIO"
            }
        }
    }


class UnifiedAPIClient:
    """
    Unified API client that can use either OpenAI or OpenRouter
    """
    
    def __init__(
        self,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        verbose: bool = False
    ):
        """
        Initialize the unified API client
        
        Args:
            provider: "openai" or "openrouter" (defaults to APIConfig.DEFAULT_PROVIDER)
            model: Model name (defaults to APIConfig.DEFAULT_TRANSCRIPTION_MODEL)
            api_key: API key for the provider
            verbose: Enable verbose logging
        """
        self.provider = provider or APIConfig.DEFAULT_PROVIDER
        self.model = model or APIConfig.DEFAULT_TRANSCRIPTION_MODEL
        self.verbose = verbose
        
        # Validate provider
        if self.provider not in APIConfig.PROVIDERS:
            raise ValueError(f"Unsupported provider: {self.provider}")
        
        # Get provider config
        self.provider_config = APIConfig.PROVIDERS[self.provider]
        
        # Determine API key
        if api_key:
            self.api_key = api_key
        elif self.provider == "openai":
            self.api_key = os.getenv("OPENAI_API_KEY")
        elif self.provider == "openrouter":
            self.api_key = os.getenv("OPENROUTER_API_KEY")
        elif self.provider == "gemini":
            self.api_key = os.getenv("GEMINI_API_KEY")
        else:
            self.api_key = None
            
        if not self.api_key:
            raise ValueError(f"API key required for {self.provider}. Set {self.provider.upper()}_API_KEY environment variable")
        
        # Initialize client based on provider
        if self.provider == "gemini":
            # For Gemini, we'll initialize the client when needed in the transcription method
            self.client = None
        else:
            # Initialize OpenAI client with provider-specific configuration for OpenAI/OpenRouter
            client_kwargs = {"api_key": self.api_key}
            
            if self.provider_config["base_url"]:
                client_kwargs["base_url"] = self.provider_config["base_url"]
                
            self.client = OpenAI(**client_kwargs)
        
        if self.verbose:
            print(f"🔑 Initialized {self.provider} API client")
            print(f"🤖 Using model: {self.model}")
    
    def _get_provider_model(self, model: Optional[str] = None) -> str:
        """
        Convert model name to provider-specific format
        """
        model_to_use = model or self.model
        
        # If model is already in provider format, use as-is
        if "/" in model_to_use and self.provider == "openrouter":
            return model_to_use
            
        # Convert from generic name to provider-specific
        provider_models = self.provider_config["models"]
        
        # Direct mapping
        if model_to_use in provider_models:
            return provider_models[model_to_use]
            
        # For transcription models, use OpenAI directly regardless of provider
        if "transcribe" in model_to_use:
            return model_to_use
            
        # Fallback to original model name
        return model_to_use
    
    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[Dict[str, str]] = None,
        response_mime_type: Optional[str] = None,
        response_schema: Optional[Dict[str, Any]] = None,
        timeout: Optional[int] = None,
        **kwargs
    ) -> Any:
        """
        Create a chat completion using the configured provider
        """
        model_to_use = self._get_provider_model(model)
        
        # Prepare request parameters
        params = {
            "model": model_to_use,
            "messages": messages,
            "temperature": temperature,
            **kwargs
        }
        
        if max_tokens is not None:
            params["max_tokens"] = max_tokens
            
        if response_format is not None:
            params["response_format"] = response_format
            
        if timeout is not None:
            params["timeout"] = timeout
        
        # Add provider-specific headers for OpenRouter
        extra_params = {}
        if self.provider == "openrouter":
            extra_headers = self.provider_config.get("extra_headers", {})
            if extra_headers:
                extra_params["extra_headers"] = extra_headers
                extra_params["extra_body"] = {}
        
        if self.verbose:
            print(f"📞 Making API call to {self.provider} with model {model_to_use}")
        
        # For Gemini provider, handle differently
        if self.provider == "gemini":
            try:
                from google import genai
                from google.genai import types
            except ImportError:
                raise ValueError("google-genai package required for Gemini. Install with: pip install google-genai")
            
            gemini_client = genai.Client(api_key=self.api_key)
            
            # Convert messages to Gemini format
            contents = []
            for message in messages:
                if message["role"] == "system":
                    contents.append(f"System: {message['content']}")
                elif message["role"] == "user":
                    contents.append(message["content"])
                elif message["role"] == "assistant":
                    contents.append(f"Assistant: {message['content']}")
            
            # Prepare Gemini config
            config_kwargs = {
                "temperature": temperature
            }
            
            if max_tokens:
                config_kwargs["max_output_tokens"] = max_tokens
                
            # Handle structured output for Gemini
            if response_mime_type and response_schema:
                config_kwargs["response_mime_type"] = response_mime_type
                config_kwargs["response_schema"] = response_schema
            
            # Make request to Gemini
            response = gemini_client.models.generate_content(
                model=model_to_use,
                contents=contents,
                config=types.GenerateContentConfig(**config_kwargs)
            )
            
            # Create response object that mimics OpenAI format
            class GeminiChatResponse:
                def __init__(self, text_content):
                    self.choices = [
                        type('Choice', (), {
                            'message': type('Message', (), {
                                'content': text_content
                            })()
                        })()
                    ]
            
            return GeminiChatResponse(response.text)
        
        # Make the API call for OpenAI/OpenRouter
        return self.client.chat.completions.create(**params, **extra_params)
    
    def audio_transcription(
        self,
        file_path: str,
        model: Optional[str] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        response_format: str = "json",
        temperature: float = 0.0
    ) -> Any:
        """
        Create audio transcription - supports OpenAI and Gemini
        """
        # For Gemini, use chat completions instead of audio transcriptions
        if self.provider == "gemini":
            return self._gemini_audio_transcription(
                file_path, model, language, prompt, response_format, temperature
            )
        
        # For non-OpenAI providers, fall back to OpenAI for transcription
        if self.provider != "openai":
            # Create temporary OpenAI client for transcription
            openai_key = os.getenv("OPENAI_API_KEY")
            if not openai_key:
                raise ValueError("OpenAI API key required for transcription. Set OPENAI_API_KEY environment variable")
            
            temp_client = OpenAI(api_key=openai_key)
            client_to_use = temp_client
            # Use OpenAI model for transcription when falling back
            model_to_use = model or "gpt-4o-transcribe"
        else:
            client_to_use = self.client
            model_to_use = model or APIConfig.DEFAULT_TRANSCRIPTION_MODEL
        
        # Prepare parameters
        params = {
            "model": model_to_use,
            "file": open(file_path, "rb"),
            "response_format": response_format,
            "temperature": temperature,
        }
        
        if language:
            params["language"] = language
            
        if prompt:
            params["prompt"] = prompt
        
        if self.verbose:
            print(f"📞 Making transcription API call with model {model_to_use}")
        
        try:
            return client_to_use.audio.transcriptions.create(**params)
        finally:
            # Ensure file is closed
            if 'file' in params:
                try:
                    params['file'].close()
                except:
                    pass
    
    def _gemini_audio_transcription(
        self,
        file_path: str,
        model: Optional[str] = None,
        language: Optional[str] = None,
        prompt: Optional[str] = None,
        response_format: str = "json",
        temperature: float = 0.0
    ) -> Any:
        """
        Handle audio transcription using Gemini's native SDK approach
        """
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            raise ValueError("google-genai package required for Gemini. Install with: pip install google-genai")
        
        model_to_use = model or APIConfig.DEFAULT_TRANSCRIPTION_MODEL
        
        if self.verbose:
            print(f"📞 Making Gemini audio transcription with model {model_to_use}")
        
        # Initialize Gemini client using API key
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable required")
        
        try:
            gemini_client = genai.Client(api_key=api_key)
            
            # Upload the audio file to Gemini
            uploaded_file = gemini_client.files.upload(file=file_path)
            
            # Create detailed transcription prompt for consistency
            base_prompt = """Generate an accurate, word-for-word transcript of the speech. Follow these strict formatting rules:
- Include ALL spoken words exactly as heard
- Write text as CONTINUOUS paragraphs without line breaks
- Use proper punctuation and capitalization
- Put all dialogue and quoted speech in quotation marks
- Do NOT add extra commentary, descriptions, or stage directions
- Keep consistent formatting throughout all chunks
- Preserve natural speech patterns and flow
- Use periods, commas, and other punctuation naturally within continuous text"""
            
            if prompt:
                transcription_prompt = f"{prompt}\n\n{base_prompt}"
            else:
                transcription_prompt = base_prompt
            
            if language:
                transcription_prompt += f"\n\nThe audio language is {language}."
            
            # Make transcription request using Gemini's approach
            response = gemini_client.models.generate_content(
                model=model_to_use,
                contents=[transcription_prompt, uploaded_file],
                config=types.GenerateContentConfig(
                    temperature=min(temperature, 0.3)  # Force low temperature for consistency
                )
            )
            
            # Extract transcription text
            transcription_text = response.text
            
            # Create a response object that mimics OpenAI's transcription response
            class GeminiTranscriptionResponse:
                def __init__(self, text_content):
                    self.text = text_content
                    
            return GeminiTranscriptionResponse(transcription_text)
            
        except Exception as e:
            if self.verbose:
                print(f"❌ Gemini transcription failed: {e}")
            raise ValueError(f"Gemini audio transcription failed: {e}")


def create_api_client(
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    verbose: bool = False
) -> UnifiedAPIClient:
    """
    Factory function to create a unified API client
    """
    return UnifiedAPIClient(
        provider=provider,
        model=model,
        api_key=api_key,
        verbose=verbose
    )


# Convenience functions for backward compatibility
def create_openai_client(api_key: Optional[str] = None, verbose: bool = False) -> UnifiedAPIClient:
    """Create an OpenAI client"""
    return create_api_client(provider="openai", api_key=api_key, verbose=verbose)


def create_openrouter_client(api_key: Optional[str] = None, verbose: bool = False) -> UnifiedAPIClient:
    """Create an OpenRouter client"""
    return create_api_client(provider="openrouter", api_key=api_key, verbose=verbose)


def create_gemini_client(api_key: Optional[str] = None, verbose: bool = False) -> UnifiedAPIClient:
    """Create a Gemini client"""
    return create_api_client(provider="gemini", api_key=api_key, verbose=verbose)


# Export centralized model configurations for easy import
DEFAULT_TRANSCRIPTION_MODEL = APIConfig.DEFAULT_TRANSCRIPTION_MODEL
DEFAULT_TEXT_MODEL = APIConfig.DEFAULT_TEXT_MODEL
VALID_TRANSCRIPTION_MODELS = APIConfig.VALID_TRANSCRIPTION_MODELS 