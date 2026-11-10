import argparse
from pathlib import Path

from voltrieve_data.car_images import contact_sheet, generate_images, load_identities
from voltrieve_data.generate import generate_all
from voltrieve_data.load import load_catalog


def main() -> None:
    parser = argparse.ArgumentParser(prog="voltrieve-data")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate the Voltrieve document corpus")
    gen.add_argument("--catalog", type=Path, default=Path("data/voltrieve.yaml"))
    gen.add_argument("--out", type=Path, default=Path("data/generated"))
    img = sub.add_parser("images", help="Generate missing car images with ailloy (existing files are kept)")
    img.add_argument("--shots", default="master_front,master_rear",
                     help='comma-separated shots, or "all" for every shot including color and wheel variants')
    img.add_argument("--catalog", type=Path, default=Path("data/voltrieve.yaml"))
    img.add_argument("--only", default="", help="comma-separated car slugs")
    img.add_argument("--out", type=Path, default=Path("data/design/images"))
    args = parser.parse_args()

    if args.command == "generate":
        docs = generate_all(args.catalog, args.out)
        print(f"Generated {len(docs)} documents in {args.out}")
    elif args.command == "images":
        cars = load_identities(catalog=load_catalog(args.catalog))
        if args.only:
            cars = {slug: cars[slug] for slug in args.only.split(",")}
        shots = None if args.shots == "all" else args.shots.split(",")
        created = generate_images(cars, shots, args.out)
        sheets = [contact_sheet(slug, args.out) for slug in cars]
        print(f"Generated {len(created)} images; contact sheets: {', '.join(map(str, sheets))}")


if __name__ == "__main__":
    main()
