#!/usr/bin/env python3
"""Fail closed before publishing a relevance queue with private columns."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from alex.source_relevance_fields import validate_queue

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: validate_source_relevance_queue.py <csv>')
    validate_queue(sys.argv[1])
