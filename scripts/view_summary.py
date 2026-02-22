import argparse
import json
from typing import Any, Dict, List


def load_summary(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise RuntimeError("Summary file must contain a JSON object")
    return data


def print_chunk(index: int, chunk: Dict[str, Any]) -> None:
    print(f"\n[{index}] {chunk.get('id', '')}")
    print(f"summary: {chunk.get('summary', '')}")
    facts = chunk.get("facts", [])
    decisions = chunk.get("decisions", [])
    open_items = chunk.get("open_items", [])
    source_ids = chunk.get("source_message_ids", [])
    print(f"facts({len(facts)}): {facts}")
    print(f"decisions({len(decisions)}): {decisions}")
    print(f"open_items({len(open_items)}): {open_items}")
    if source_ids:
        print(f"source_message_ids: {source_ids[0]} .. {source_ids[-1]} ({len(source_ids)})")


def main() -> None:
    parser = argparse.ArgumentParser(description="View backfilled summary JSON.")
    parser.add_argument("path", help="Path to *.summary.json file")
    parser.add_argument("--head", type=int, default=0, help="Show first N chunks")
    parser.add_argument("--tail", type=int, default=0, help="Show last N chunks")
    parser.add_argument("--index", type=int, help="Show a specific chunk index")
    parser.add_argument("--grep", default="", help="Filter chunks by text in summary/facts/decisions/open_items")
    args = parser.parse_args()

    state = load_summary(args.path)
    chunks = state.get("chunks", [])
    if not isinstance(chunks, list):
        raise RuntimeError("'chunks' must be a list")

    print("Summary file:")
    print(f"- path: {args.path}")
    print(f"- version: {state.get('version')}")
    print(f"- last_message_count: {state.get('last_message_count')}")
    print(f"- chunks: {len(chunks)}")

    if args.index is not None:
        if args.index < 0 or args.index >= len(chunks):
            raise RuntimeError(f"index out of range: {args.index}")
        print_chunk(args.index, chunks[args.index])
        return

    selected: List[tuple[int, Dict[str, Any]]] = list(enumerate(chunks))
    if args.grep:
        needle = args.grep.lower()
        filtered: List[tuple[int, Dict[str, Any]]] = []
        for idx, chunk in selected:
            payload = " ".join(
                [
                    str(chunk.get("summary", "")),
                    " ".join(chunk.get("facts", []) if isinstance(chunk.get("facts", []), list) else []),
                    " ".join(chunk.get("decisions", []) if isinstance(chunk.get("decisions", []), list) else []),
                    " ".join(chunk.get("open_items", []) if isinstance(chunk.get("open_items", []), list) else []),
                ]
            ).lower()
            if needle in payload:
                filtered.append((idx, chunk))
        selected = filtered
        print(f"- grep_matches: {len(selected)}")

    to_show: List[tuple[int, Dict[str, Any]]] = []
    if args.head > 0:
        to_show.extend(selected[: args.head])
    if args.tail > 0:
        tail_items = selected[-args.tail:]
        existing = {idx for idx, _ in to_show}
        to_show.extend([(idx, chunk) for idx, chunk in tail_items if idx not in existing])

    if not to_show:
        print("No chunks selected. Use --head/--tail/--index and optional --grep.")
        return

    for idx, chunk in to_show:
        print_chunk(idx, chunk)


if __name__ == "__main__":
    main()
