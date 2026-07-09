#!/usr/bin/env python3
import asyncio
import sys
import os
import argparse

# Ensure the script can run standalone by adding project root to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from context_engine.library_index import ContextLibrary
from pipeline.summarize.monthly_digest import run_monthly_digest

def main():
    parser = argparse.ArgumentParser(description="Run the ONM Monthly Digest Pipeline")
    parser.add_argument("--source", type=str, default="ec_transcript",
                        help="Source key (e.g. ec_transcript, leadership)")
    parser.add_argument("--month", type=str, default="2026-06", help="Target month (YYYY-MM)")

    args = parser.parse_args()

    print("======================================================")
    print("           MONTHLY EVENT DIGEST PIPELINE              ")
    print("======================================================")
    try:
        lib = ContextLibrary()
        asyncio.run(run_monthly_digest(args.source, args.month, lib))
    except Exception as e:
        print(f"❌ Error generating digest: {e}")

if __name__ == "__main__":
    main()