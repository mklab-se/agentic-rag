import argparse
from pathlib import Path

from voltrieve_data.generate import generate_all


def main() -> None:
    parser = argparse.ArgumentParser(prog="voltrieve-data")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate the Voltrieve document corpus")
    gen.add_argument("--catalog", type=Path, default=Path("data/voltrieve.yaml"))
    gen.add_argument("--out", type=Path, default=Path("data/generated"))
    args = parser.parse_args()

    if args.command == "generate":
        docs = generate_all(args.catalog, args.out)
        print(f"Generated {len(docs)} documents in {args.out}")


if __name__ == "__main__":
    main()
