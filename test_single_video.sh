#!/bin/bash

# Test with a small channel (only 1 video for quick test)
echo "Testing channel translation with 1 video limit..."
echo ""

# Using a channel with few videos for testing
python3 transcriberio.py -transcribe -translate pt-BR "https://www.youtube.com/@mkbhd" &

# Wait a bit for it to start
sleep 5

# Find the python process and monitor
PID=$(ps aux | grep "python3 transcriberio.py" | grep -v grep | awk '{print $2}')

if [ ! -z "$PID" ]; then
    echo "Process started with PID: $PID"
    echo "Monitoring output folder..."
    echo ""
    
    # Wait for first video to complete (checking for transcript file)
    while true; do
        TRANSCRIPT_COUNT=$(find output/channels -name "*_transcript.txt" 2>/dev/null | wc -l)
        TRANSLATION_COUNT=$(find output/channels -name "*_translated_*.txt" 2>/dev/null | wc -l)
        
        echo -ne "\rTranscripts: $TRANSCRIPT_COUNT | Translations: $TRANSLATION_COUNT"
        
        # If we have at least one translation, kill the process
        if [ $TRANSLATION_COUNT -gt 0 ]; then
            echo ""
            echo "First video completed! Stopping process..."
            kill $PID
            break
        fi
        
        sleep 2
    done
    
    echo ""
    echo "Test completed!"
    echo ""
    echo "Files created:"
    find output/channels -type f -name "*.txt" -o -name "*.json" | sort
else
    echo "Failed to start process"
fi
