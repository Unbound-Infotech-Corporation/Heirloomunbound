"""Stream generators must not rebind a name they close over. That raises UnboundLocalError."""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _names_bound(fn: ast.AST) -> set[str]:
    found: set[str] = set()

    def walk(node: ast.AST, top: bool = False) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not top:
            return
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
            found.add(node.target.id)
        for child in ast.iter_child_nodes(node):
            walk(child, False)

    walk(fn, True)
    return found


def test_streamed_generators_do_not_rebind_closed_over_names():
    tree = ast.parse((ROOT / "routers" / "twin.py").read_text(encoding="utf-8"))
    offenders: list[str] = []
    for outer in ast.walk(tree):
        if not isinstance(outer, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        outer_bound = _names_bound(outer)
        for child in ast.walk(outer):
            if child is outer or not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if child.name not in {"gen_local", "gen", "music_stream", "skill_stream", "crisis_stream"}:
                continue
            rebound = _names_bound(child) & outer_bound
            rebound.discard("result")
            if rebound:
                offenders.append(f"{outer.name}/{child.name}:{sorted(rebound)}")
    assert offenders == []
