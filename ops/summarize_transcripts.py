#!/usr/bin/env python3
import asyncio
import sys
import os
import argparse

# Ensure the script can run standalone by adding project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from context_engine.library_index import ContextLibrary
from pipeline.summarize.transcript import summarize_stale_transcripts

def main():
    parser = argparse.ArgumentParser(description="Summarize stale or new transcripts using AI.")
    parser.add_argument("--force", action="store_true", help="Force summarization of all transcripts, ignoring cache.")
    args = parser.parse_args()

    print(f"🤖 Starting transcript summarization pipeline (Force mode: {args.force})...")
    try:
        lib = ContextLibrary()
        count = asyncio.run(summarize_stale_transcripts(lib, force=args.force))
        print(f"✅ Summarization complete. Generated new summaries for {count} transcripts.")
    except Exception as e:
        print(f"❌ Error during summarization: {e}")

if __name__ == "__main__":
    main()