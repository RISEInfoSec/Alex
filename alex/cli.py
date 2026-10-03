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
    ap.add_argument("--record-collection", action="store_true", help="Record a completed collection's date and newly published count (publish only)")
    args = ap.parse_args()
    if args.record_collection and args.command != "publish":
        ap.error("--record-collection is only valid with publish")
    if args.command == "publish":
        publish.run(record_collection=args.record_collection)
        return
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
