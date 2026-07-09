#!/usr/bin/env python3
import asyncio
import sys
import os

# Ensure the script can run standalone by adding project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from context_engine.library_index import ContextLibrary
from pipeline.summarize.guide import build_guide_context

def main():
    print("🧠 Analyzing recent history and standing state to build guide context...")
    try:
        lib = ContextLibrary()
        path = asyncio.run(build_guide_context(lib))
        print(f"✅ Guide context generated and cached at `{path}`.")
    except Exception as e:
        print(f"❌ Error generating guide: {e}")

if __name__ == "__main__":
    main()