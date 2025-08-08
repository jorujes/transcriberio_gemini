# 🎙️ TranscriberIO Gemini

> **Google Gemini-Powered YouTube Transcription, Translation & Entity Detection Pipeline**

A complete Python CLI tool that downloads YouTube videos, transcribes them using Google Gemini 2.5-Flash, detects and reviews entities, and produces high-quality translations with intelligent reprocessing for natural, idiomatic output. Now featuring native Google Gemini integration for superior performance and cost-effectiveness.

## 🚀 Why Gemini?

### **🎯 Superior Performance**
- **Native Multimodal**: Gemini 2.5-Flash processes audio directly without conversion overhead
- **Structured Output**: Built-in JSON schema support for precise entity extraction
- **Advanced Context**: Better understanding of nuanced speech patterns and accents

### **💰 Cost-Effective**
- **Competitive Pricing**: Gemini offers excellent value for multimodal processing
- **Efficient Processing**: Faster inference times mean lower costs per operation
- **Native Integration**: Direct API calls eliminate middleware overhead

### **🔧 Technical Advantages**
- **Temperature Range**: 0-2 scale provides finer creativity control for translations
- **Consistent Output**: Enhanced prompt following for more predictable results
- **Modern Architecture**: Latest Google AI technology with regular model updates

## ✨ Features

### 🎯 **Complete Pipeline**
- **YouTube Audio Download**: Extract audio from any YouTube video
- **Gemini Transcription**: Google Gemini 2.5-Flash for superior multimodal speech-to-text
- **Entity Detection**: Advanced NER using Gemini 2.5-Pro with structured JSON output
- **Interactive Review**: CLI-based entity review and correction workflow  
- **Smart Translation**: Gemini-powered translation + intelligent reprocessing for naturalness
- **Multi-language Support**: 13+ target languages with regional variants

### 🚀 **Advanced Features**
- **Native Gemini SDK**: Direct integration with Google Gemini API for optimal performance
- **Multimodal Audio Processing**: Leverages Gemini's native audio understanding capabilities
- **Structured Output**: JSON schema-based entity detection with precise formatting
- **Intelligent Chunking**: Maintains semantic context during processing
- **Dual Translation Output**: Initial literal + reprocessed idiomatic versions
- **Multi-Provider Support**: Unified API client supporting Gemini, OpenAI, and OpenRouter
- **Entity Review Workflow**: Interactive correction of detected entities
- **Production Ready**: Robust error handling and retry logic
- **File Management**: Automatic organization in `output/` directory

## 🛠️ Installation

### Prerequisites
- Python 3.8+
- Google Gemini API key (primary - for transcription and text processing)
- OpenAI API key (optional - for fallback scenarios)
- OpenRouter API key (optional - for alternative models)

### Setup
```bash
# Clone the repository
git clone https://github.com/jorujes/transcriberio_gemini.git
cd transcriberio_gemini

# Install dependencies
pip3 install -r requirements.txt

# Configure environment variables
cp .env.example .env.local
# Edit .env.local with your API keys
```

### Environment Configuration
Create `.env.local` with your API keys:
```bash
# Primary API key (required)
GEMINI_API_KEY=your_gemini_api_key_here

# Optional fallback keys
OPENAI_API_KEY=your_openai_api_key_here
OPENROUTER_API_KEY=your_openrouter_api_key_here
```

**Get your Gemini API key at:** https://ai.google.dev/

## 📋 Usage

### Quick Start - Complete Pipeline
```bash
# Process any YouTube video end-to-end
python3 transcriberio.py "https://www.youtube.com/watch?v=VIDEO_ID"
```

**This single command will:**
1. 📥 Download audio from YouTube
2. 🎯 Transcribe using Google Gemini 2.5-Flash multimodal processing
3. 🔍 Detect entities using Gemini 2.5-Pro with structured JSON schema
4. 📝 Interactive entity review and correction
5. 🌍 Translate using Gemini 2.5-Pro with region-specific prompts
6. 💡 Reprocess translation for natural, idiomatic output with enhanced creativity

### Individual Commands
```bash
# Download audio only
python3 transcriberio.py download "https://www.youtube.com/watch?v=VIDEO_ID"

# Transcribe existing audio file  
python3 transcriberio.py transcribe audio_12345678.mp3

# Detect and review entities in transcript
python3 transcriberio.py entities audio_12345678_transcript.txt

# Translate transcript
python3 transcriberio.py translate audio_12345678_transcript.txt

# Run full pipeline from existing audio
python3 transcriberio.py run_full_pipeline audio_12345678.mp3
```

## 📁 Output Files

After processing, you'll get these files in the `output/` directory:

```
output/
├── audio_12345678_transcript.txt                    # Original transcription
├── audio_12345678_entities.json                     # Detected entities  
├── audio_12345678_transcript_entities.json          # Transcript with corrected entities
├── audio_12345678_translated_pt-BR.txt              # Initial translation
└── audio_12345678_translated_pt-BR_reprocessed.txt  # Enhanced natural translation
```

## 🌍 Supported Languages

- **Portuguese**: pt-BR (Brasil), pt-PT (Portugal)
- **Spanish**: es-ES (España), es-MX (México), es-AR (Argentina), es-CO (Colombia)
- **French**: fr-FR (France), fr-CA (Canada)
- **German**: de-DE (Deutschland), de-AT (Österreich)
- **Japanese**: ja-JP (Japan)
- **Russian**: ru-RU (Russia)
- **Arabic**: ar-SA (Saudi Arabia)

## ⚙️ Configuration

### API Provider Selection
The system uses **Google Gemini by default** for superior performance and cost-effectiveness across all operations.

To change the default provider, edit `api_client.py`:
```python
class APIConfig:
    DEFAULT_PROVIDER = "gemini"  # "gemini", "openai", or "openrouter" 
    DEFAULT_TRANSCRIPTION_MODEL = "gemini-2.5-flash"  # Audio transcription
    DEFAULT_TEXT_MODEL = "gemini-2.5-pro"             # Text processing
```

### Model Configuration
- **Transcription**: Google Gemini 2.5-Flash (multimodal audio processing)
- **Entity Detection**: Google Gemini 2.5-Pro with structured JSON output
- **Translation**: Google Gemini 2.5-Pro with temperature-optimized creativity
- **Fallback**: OpenAI and OpenRouter support available for hybrid workflows

## 🎯 Advanced Usage

### Entity Detection & Review
The interactive entity review allows you to:
- ✅ Keep original entity names
- ✏️ Replace with corrected versions  
- ⏭️ Skip remaining entities
- ❌ Cancel without saving

### Translation Reprocessing
The system performs **dual-stage translation**:
1. **Initial Translation**: Direct, literal translation
2. **Reprocessing**: Uses "scolding prompt" to create natural, idiomatic translation

Both versions are saved for comparison and quality control.

## 🔧 Development

### Project Structure
```
transcriberio/
├── transcriberio.py           # Main CLI application
├── api_client.py             # Centralized API management
├── downloader.py             # YouTube audio download
├── transcriber.py            # Audio transcription
├── entity_detector.py        # Entity detection & review
├── translator_normalizer.py  # Translation & reprocessing
├── audio_metadata.py         # Audio file metadata
└── cli.py                   # CLI command definitions
```

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## 📊 Performance

**Typical Processing Times** (approximate):
- **Download**: ~1-5 seconds per minute of video
- **Gemini Transcription**: ~2-4 seconds per minute of audio (improved with native multimodal)
- **Gemini Entity Detection**: ~1-3 seconds per transcript (optimized structured output)
- **Gemini Translation**: ~3-8 seconds per 1000 words (enhanced efficiency)
- **Gemini Reprocessing**: ~3-8 seconds per 1000 words (faster creative processing)

## 🔒 Privacy & Security

- ✅ Audio files are processed locally
- ✅ Only text content is sent to AI APIs
- ✅ No data stored by third-party services
- ✅ Temporary files automatically cleaned up
- ✅ API keys stored in local environment files

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Support

For issues, feature requests, or questions:
- 📂 Open an issue on GitHub
- 💬 Check existing issues for solutions
- 📧 Contact the development team

## 🙏 Acknowledgments

- **Google** for Gemini 2.5-Flash and 2.5-Pro multimodal AI capabilities
- **OpenAI** for GPT models and fallback support
- **OpenRouter** for additional model access and cost optimization
- **yt-dlp** for YouTube download capabilities
- **Click** for CLI framework
- **Inquirer** for interactive prompts
- **google-genai** for native Gemini SDK integration

---

**Made with ❤️ for the AI transcription community** 