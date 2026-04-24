from __future__ import annotations
import argparse
import logging
from alex.pipelines import discovery, citation_chain, quality_gate, harvest, rescore, classify, publish


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    ap = argparse.ArgumentParser(prog="alex", description="OSINT research corpus pipeline")
    ap.add_argument("command", choices=["discover", "chain", "score", "harvest", "rescore", "classify", "publish"])
    args = ap.parse_args()
    {
        "discover": discovery.run,
        "chain": citation_chain.run,
        "score": quality_gate.run,
        "harvest": harvest.run,
        "rescore": rescore.run,
        "classify": classify.run,
        "publish": publish.run,
    }[args.command]()


if __name__ == "__main__":
    main()
