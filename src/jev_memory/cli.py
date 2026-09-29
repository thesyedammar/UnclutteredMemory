import argparse


def main() -> int:
    parser = argparse.ArgumentParser(prog="jev", description="jev-memory CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run", help="run the frozen eval")
    sub.add_parser("calibrate", help="tune thresholds on train split only")
    sub.add_parser("redteam", help="fire the poison gauntlet, print survival rate")
    sub.add_parser("gauntlet", help="record the gauntlet demo")
    args = parser.parse_args()
    print(f"jev {args.command}: phase 1 in progress")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())