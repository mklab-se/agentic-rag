import argparse
from pathlib import Path

from voltrieve_data.car_images import contact_sheet, generate_images, load_identities
from voltrieve_data.generate import generate_all


def main() -> None:
    parser = argparse.ArgumentParser(prog="voltrieve-data")
    sub = parser.add_subparsers(dest="command", required=True)
    gen = sub.add_parser("generate", help="Generate the Voltrieve document corpus")
    gen.add_argument("--catalog", type=Path, default=Path("data/voltrieve.yaml"))
    gen.add_argument("--out", type=Path, default=Path("data/generated"))
    img = sub.add_parser("images", help="Generate missing car images with ailloy (existing files are kept)")
    img.add_argument("--shots", default="master_front,master_rear")
    img.add_argument("--only", default="", help="comma-separated car slugs")
    img.add_argument("--out", type=Path, default=Path("data/design/images"))
    args = parser.parse_args()

    if args.command == "generate":
        docs = generate_all(args.catalog, args.out)
        print(f"Generated {len(docs)} documents in {args.out}")
    elif args.command == "images":
        cars = load_identities()
        if args.only:
            cars = {slug: cars[slug] for slug in args.only.split(",")}
        created = generate_images(cars, args.shots.split(","), args.out)
        sheets = [contact_sheet(slug, args.out) for slug in cars]
        print(f"Generated {len(created)} images; contact sheets: {', '.join(map(str, sheets))}")


if __name__ == "__main__":
    main()
