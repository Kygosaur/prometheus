from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from .data import load_workbook
from .llm import answer_workspace_question, explain_schedule, understand_request
from .local_llm import LocalLLM
from .models import PlanningRequest
from .psplib import parse_sm, serial_schedule
from .rag import WorkspaceIndex
from .scheduler import create_schedule


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Private local industrial planning agent")
    parser.add_argument("--llm-url", default=os.getenv("LOCAL_LLM_BASE_URL", "http://127.0.0.1:11434/v1"))
    parser.add_argument("--model", default=os.getenv("LOCAL_LLM_MODEL", "kimi"))
    subparsers = parser.add_subparsers(dest="command", required=True)

    schedule_parser = subparsers.add_parser("schedule", help="Schedule Excel planning data")
    schedule_parser.add_argument("--workbook", required=True)
    schedule_parser.add_argument("--request", default="Create a feasible schedule")
    schedule_parser.add_argument("--workspace", default="documents")
    schedule_parser.add_argument("--blocked-machine", action="append", default=[])
    schedule_parser.add_argument("--blocked-worker", action="append", default=[])
    schedule_parser.add_argument("--blocked-vehicle", action="append", default=[])
    schedule_parser.add_argument("--no-llm", action="store_true")
    schedule_parser.add_argument("--output", default="outputs/schedule.json")

    chat_parser = subparsers.add_parser("chat", help="Ask a local model about read-only workspace files")
    chat_parser.add_argument("--workspace", required=True)
    chat_parser.add_argument("--question")
    chat_parser.add_argument("--top-k", type=int, default=5)

    psplib_parser = subparsers.add_parser("psplib", help="Schedule a PSPLIB single-mode instance")
    psplib_parser.add_argument("--instance", required=True)
    args = parser.parse_args()
    if args.command == "psplib":
        instance = parse_sm(args.instance)
        schedule = serial_schedule(instance)
        print(json.dumps({"schedule": schedule, "makespan": max(end for _, end in schedule.values())}, indent=2))
    elif args.command == "chat":
        _run_chat(args)
    else:
        _run_schedule(args)


def _local_client(args: argparse.Namespace) -> LocalLLM:
    return LocalLLM(base_url=args.llm_url, model=args.model)


def _run_schedule(args: argparse.Namespace) -> None:
    workers, tasks, machines, vehicles = load_workbook(args.workbook)
    explicit = PlanningRequest(tuple(args.blocked_machine), tuple(args.blocked_worker), tuple(args.blocked_vehicle))
    client: LocalLLM | None = None
    request = explicit
    if not args.no_llm:
        client = _local_client(args)
        parsed = understand_request(client, args.request)
        request = PlanningRequest(
            tuple(dict.fromkeys((*parsed.blocked_machines, *explicit.blocked_machines))),
            tuple(dict.fromkeys((*parsed.blocked_workers, *explicit.blocked_workers))),
            tuple(dict.fromkeys((*parsed.blocked_vehicles, *explicit.blocked_vehicles))),
            parsed.safety_question,
        )
    result = create_schedule(workers, tasks, machines, vehicles, request)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    print(json.dumps(result.to_dict(), indent=2))
    if client:
        passages = []
        workspace = Path(args.workspace)
        if request.safety_question and workspace.is_dir():
            index = WorkspaceIndex(workspace)
            index.build()
            passages = index.search(request.safety_question)
        print("\nLocal model explanation:\n")
        print(explain_schedule(client, args.request, result, passages))
    print(f"\nSaved structured result to {output.resolve()}")


def _run_chat(args: argparse.Namespace) -> None:
    client = _local_client(args)
    index = WorkspaceIndex(args.workspace)
    count = index.build()
    print(f"Indexed {count} local excerpts from {index.root}")
    if index.skipped:
        print(f"Skipped {len(index.skipped)} unreadable or oversized files")
    history: list[dict[str, str]] = []
    if args.question:
        print(_answer(client, index, args.question, args.top_k, history))
        return
    print("Private read-only chat. Type 'exit' to stop.")
    while True:
        try:
            question = input("\nYou: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.casefold() in {"exit", "quit"}:
            break
        if not question:
            continue
        answer = _answer(client, index, question, args.top_k, history)
        print(f"\nKimi: {answer}")
        history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])


def _answer(client: LocalLLM, index: WorkspaceIndex, question: str, top_k: int, history: list[dict[str, str]]) -> str:
    passages = index.search(question, top_k=max(1, min(top_k, 10)))
    return answer_workspace_question(client, question, passages, history)


if __name__ == "__main__":
    main()

