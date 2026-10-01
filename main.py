#!/usr/bin/env python3
"""Launch a standalone sandbox or a temporary IBus input method."""
import argparse
import logging
import sys
from backend import download, server
from core import Corrector


def main():
    parser = argparse.ArgumentParser(description="Gemma-4-E2B local proofreading after an 800 ms pause")
    parser.add_argument("mode", choices=["demo", "ibus", "download", "check"], nargs="?", default="demo")
    parser.add_argument("--model", help="Use an existing GGUF instead of the pinned default")
    parser.add_argument("--llama-server", default="llama-server", help="Override server binary")
    parser.add_argument("--verbose", action="store_true", help="Log debounce and input decisions, without typed text")
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    model = args.model or download()
    if args.mode == "download":
        print(model)
        return
    logging.getLogger("proofread").info("Loading Gemma locally; mode=%s", args.mode)
    with server(model, args.llama_server) as (url, key):
        correct = Corrector(url, key)
        if args.mode == "check":
            print(correct(sys.stdin.read()))
        elif args.mode == "ibus":
            from engine import run_engine
            run_engine(correct)
        else:
            from demo import run_demo
            run_demo(correct)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        print(f"ibus-proofread: {exc}", file=sys.stderr)
        sys.exit(1)
