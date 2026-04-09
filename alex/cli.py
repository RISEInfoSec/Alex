from __future__ import annotations
import argparse
from alex.pipelines import discovery, citation_chain, quality_gate, harvest, classify, publish

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=["discover", "chain", "score", "harvest", "classify", "publish"])
    args = ap.parse_args()
    {
        "discover": discovery.run,
        "chain": citation_chain.run,
        "score": quality_gate.run,
        "harvest": harvest.run,
        "classify": classify.run,
        "publish": publish.run,
    }[args.command]()

if __name__ == "__main__":
    main()
