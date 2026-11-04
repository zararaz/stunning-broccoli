"""Chat with the city guide in the terminal.

Usage:
    python src/chat_cli.py                         # interactive, no model needed
    python src/chat_cli.py --trace                 # also show each pipeline step
    python src/chat_cli.py --llm hf                # use a small Hugging Face model
    python src/chat_cli.py --llm claude            # use Claude (needs ANTHROPIC_API_KEY)
    python src/chat_cli.py -m "I'm visiting philly on Sunday, love art"
"""

import argparse
import json

from engine import Engine


def show(reply, trace, with_trace):
    print("\n" + reply.replace("**", "").replace("_", ""))
    if with_trace:
        print("\n--- trace ---")
        print(json.dumps(trace, indent=2, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", help="rules (default), hf or claude")
    ap.add_argument("--user", default="demo", help="user id, for weekly-pick history")
    ap.add_argument("--trace", action="store_true")
    ap.add_argument("-m", "--message", help="send one message and exit")
    args = ap.parse_args()

    engine = Engine(args.llm)
    print(f"City guide ({'rules, no model' if engine.llm is None else engine.llm.name}). Ctrl-C to quit.")
    if args.message:
        show(*engine.handle(args.message, args.user), args.trace)
        return
    while True:
        try:
            msg = input("\nyou> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if msg:
            show(*engine.handle(msg, args.user), args.trace)


if __name__ == "__main__":
    main()
