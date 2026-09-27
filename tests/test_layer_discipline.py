"""Enforces the import rules from PRD §3.1. These are the boundaries that keep
each layer independently testable; a violation is a design regression."""
import ast
import builtins
import re
from pathlib import Path

ROOT = Path(__file__).parent.parent


def imports_module(source: str, module: str) -> bool:
    """Whether `source` imports `module` in any form.

    Catches all three shapes a real violation takes:
        import storage
        from storage import memory
        from storage.memory import owner_hints     <- submodule; the easy one to miss

    A plain substring test misses the `from` forms entirely, and a naive
    `from\\s+MODULE[\\s.]+import` misses the submodule form, because the dotted
    tail sits between the module name and the `import` keyword. Anchored at a
    line start so a mention inside a comment or docstring does not count.
    """
    pattern = (rf"^\s*(?:import\s+{re.escape(module)}\b"
               rf"|from\s+{re.escape(module)}(?:\.[\w.]+)?\s+import\b)")
    return re.search(pattern, source, re.MULTILINE) is not None


def _sources(package: str) -> list[tuple[str, str]]:
    return [(p.name, p.read_text()) for p in (ROOT / package).glob("*.py")]


def test_ui_does_not_import_openai_or_sqlite():
    for name, source in _sources("ui"):
        assert not imports_module(source, "openai"), f"ui/{name} imports openai"
        assert not imports_module(source, "sqlite3"), f"ui/{name} imports sqlite3"
        assert "conn.execute(" not in source, (
            f"ui/{name} calls conn.execute() directly — the UI must not write SQL; "
            f"go through storage/db.py")


def test_agent_does_not_import_storage_or_streamlit():
    for name, source in _sources("agent"):
        assert not imports_module(source, "storage"), f"agent/{name} imports storage"
        assert not imports_module(source, "streamlit"), f"agent/{name} imports streamlit"


def test_storage_does_not_import_openai_or_streamlit():
    for name, source in _sources("storage"):
        assert not imports_module(source, "openai"), f"storage/{name} imports openai"
        assert not imports_module(source, "streamlit"), f"storage/{name} imports streamlit"


def test_only_llm_client_imports_openai():
    importers = [name for name, source in _sources("agent") if imports_module(source, "openai")]
    assert importers == ["llm_client.py"]


def test_ui_helper_modules_are_streamlit_free():
    """state.py, gap_display.py, markdown_export.py and technical_display.py
    must stay unit-testable."""
    for module in ("state.py", "gap_display.py", "markdown_export.py",
                   "technical_display.py", "upload_helpers.py"):
        source = (ROOT / "ui" / module).read_text()
        assert not imports_module(source, "streamlit"), f"ui/{module} imports streamlit"


CONVERGED_FILES = ["agent/gaps.py", "agent/pipeline.py", "ui/gap_display.py",
                   "ui/review_view.py"]

# A re-implemented "is this blank?" check, written the obvious way. Each pattern
# is deliberately anchored on the owner/deadline names so that a call already
# routed through the predicate — `normalize_optional_text(owner) is None`,
# `normalize_optional_text(item["owner"]) or ""` — does not match: in those the
# field name is followed by `)`, never by the operator.
BARE_BLANK_CHECKS = (
    r"\bnot\s+(?:owner|deadline)\b",                       # if not owner / not owner.strip()
    r"\b(?:owner|deadline)\.strip\(\)",                      # owner.strip() as a blank test
    r"\b(?:owner|deadline)\s*(?:==|!=)\s*(?:None|[\"']{2})",  # owner == "" / owner is compared
    r"\b(?:owner|deadline)\s+is\s+(?:not\s+)?None\b",       # owner is None
    r"\[[\"'](?:owner|deadline)[\"']\]\s*(?:or|and|if)\b",    # item["owner"] or ""
    r"\bif\s+\w+\[[\"'](?:owner|deadline)[\"']\]",          # ... if i["owner"]
    r"\bif\s+\w+\.(?:owner|deadline)\b",                   # if item.owner:
    r"\.(?:owner|deadline)\s+(?:or|and)\b",                 # item.owner or ""
)


def test_blank_checks_all_use_the_shared_predicate():
    """Four places once re-implemented this and a literal "null" from the model
    defeated all of them. They must not drift apart again."""
    for path in CONVERGED_FILES:
        source = (ROOT / path).read_text()
        assert "normalize_optional_text" in source, f"{path} lost the shared predicate"


def test_no_converged_file_re_implements_a_blank_check():
    """The presence half above is satisfied by one correct call anywhere in the
    file, so a new bare `if not owner:` alongside it passes unnoticed. This is
    the absence half: it fails on a hand-rolled blankness test even when the
    shared predicate is still imported and used elsewhere in the same file.

    There are no whitelisted exceptions. `ui/review_view.py`'s two widget
    defaults (`item["owner"] or ""`) and its owner-set comprehension were the
    only ones, and they were routed through the predicate rather than exempted —
    a row holding "TBD" must show as blank, because blank is what every gate
    check already believes it to be.
    """
    for path in CONVERGED_FILES:
        source = (ROOT / path).read_text()
        for pattern in BARE_BLANK_CHECKS:
            match = re.search(pattern, source)
            assert match is None, (
                f"{path} re-implements a blank check: {match.group(0)!r} "
                f"(matched {pattern!r}). Call normalize_optional_text() instead.")


# --- AST undefined-name check -------------------------------------------------
#
# No test in this suite imports ui/review_view.py, ui/export_view.py or
# ui/input_view.py — test_gap_display.py and the checks above only read them
# as text. Even a plain `import ui.review_view` would not have caught the
# `needs_manual_resolution` regression: it was a *global lookup that fails
# inside a function body* at call time, not an import-time error. This test
# statically finds that whole class of bug without ever importing streamlit
# UI modules or running a script.

_BUILTIN_NAMES: frozenset[str] = frozenset(dir(builtins)) | {
    "__builtins__", "__name__", "__file__", "__doc__",
    "__package__", "__spec__", "__loader__", "__debug__", "__builtin__",
}


def _bound_names(tree: ast.AST) -> set[str]:
    """Every name bound anywhere in the module, ignoring scope boundaries.

    Real scoping is fussy to get exactly right (a name bound in one function
    is not visible in another). Collecting the union across the whole module
    instead is a deliberate under-approximation: it can miss a genuinely
    undefined name that happens to match a binding in a sibling scope, but it
    can never flag a name that really is bound somewhere. No false positives
    is the property that matters for a test that must stay green — a test
    that cries wolf gets silenced, which defeats the point.
    """
    bound = set(_BUILTIN_NAMES)

    def _collect_params(args: ast.arguments) -> None:
        for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs):
            bound.add(arg.arg)
        if args.vararg:
            bound.add(args.vararg.arg)
        if args.kwarg:
            bound.add(args.kwarg.arg)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)  # the def itself binds a name in its own scope
            _collect_params(node.args)
            for tp in getattr(node, "type_params", None) or ():
                name = getattr(tp, "name", None)
                if name:
                    bound.add(name)
        elif isinstance(node, ast.Lambda):
            _collect_params(node.args)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
            for tp in getattr(node, "type_params", None) or ():
                name = getattr(tp, "name", None)
                if name:
                    bound.add(name)
        elif isinstance(node, ast.ExceptHandler):
            if node.name:
                bound.add(node.name)  # `except E as name:`
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            # Covers plain assignment, tuple/list/starred unpacking, augmented
            # and annotated assignment, `for`/`async for` targets, comprehension
            # targets, `with ... as` targets (single or tupled), and walrus
            # (`:=`) targets — every one of those binds via a Name node in
            # Store context somewhere in this subtree, which ast.walk reaches
            # regardless of nesting depth.
            bound.add(node.id)
        elif isinstance(node, getattr(ast, "MatchAs", ())) and node.name:
            bound.add(node.name)
        elif isinstance(node, getattr(ast, "MatchStar", ())) and node.name:
            bound.add(node.name)
        elif isinstance(node, getattr(ast, "MatchMapping", ())) and node.rest:
            bound.add(node.rest)

    return bound


def test_no_undefined_names_in_ui_or_agent():
    """Falsifiable regression guard for the `needs_manual_resolution` NameError:
    every `ui/review_view.py` Save on a gapped item raised at runtime while all
    159 existing tests stayed green, because none of them imported the module.

    Verified by deliberately removing `needs_manual_resolution` from the
    `ui.gap_display` import list in ui/review_view.py and re-running this test:
    it failed with `ui/review_view.py:213: undefined name
    'needs_manual_resolution'` before the import was restored.
    """
    problems = []
    for package in ("ui", "agent"):
        for path in sorted((ROOT / package).glob("*.py")):
            source = path.read_text()
            tree = ast.parse(source, filename=str(path))
            bound = _bound_names(tree)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    if node.id not in bound:
                        problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: "
                                        f"undefined name {node.id!r}")
    assert not problems, "undefined name(s) found:\n" + "\n".join(problems)


def test_context_builder_is_streamlit_free():
    """It is pure translation; keeping it testable keeps the seam honest."""
    source = (ROOT / "ui" / "context_builder.py").read_text()
    assert not imports_module(source, "streamlit")


def test_loop_does_not_import_storage_or_streamlit():
    source = (ROOT / "agent" / "loop.py").read_text()
    assert not imports_module(source, "storage")
    assert not imports_module(source, "streamlit")


def test_input_view_persists_the_loop_processing_pass():
    """F18 wiring: storage can accept processing provenance only if the UI passes
    the actual LoopOutcome value instead of omitting it or inventing a constant."""
    path = ROOT / "ui" / "input_view.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
        and node.func.attr == "save_extraction"
    ]
    assert len(calls) == 1
    keywords = {keyword.arg: keyword.value for keyword in calls[0].keywords}
    value = keywords.get("processing_pass")
    assert (
        isinstance(value, ast.Attribute)
        and isinstance(value.value, ast.Name)
        and value.value.id == "outcome"
        and value.attr == "passes"
    )


def test_input_view_rebuilds_the_index_only_after_extraction_is_saved():
    """A user meeting becomes searchable only after its analysis is durable."""
    path = ROOT / "ui" / "input_view.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "rebuild_meeting_index"
    ]
    assert len(calls) == 1
    call = calls[0]
    assert [argument.id for argument in call.args] == ["conn", "meeting_id"]

    analyze = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                   and node.name == "_analyze")
    statements = [node for node in ast.walk(analyze) if isinstance(node, ast.Call)]
    save_call = next(
        node for node in statements
        if isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "db"
        and node.func.attr == "save_extraction"
    )
    assert call.lineno > save_call.lineno


def test_owner_hints_are_never_read_by_the_agent_package():
    """Invariant 3, structurally.

    `MeetingContext.owner_hints` exists so the UI can suggest an owner to a
    human. If anything under agent/ ever READS it, a model is one f-string
    away from being told who "usually" owns the work — which is the
    fabrication this product exists to prevent.

    Uses `ast` rather than a substring scan on purpose: `agent/pipeline.py`'s
    docstring deliberately mentions the field to warn future readers not to
    use it, and that documentation should not have to be deleted to keep this
    test green. Attribute access is the thing that matters.
    """
    import ast

    for path in (ROOT / "agent").rglob("*.py"):
        if path.name == "schemas.py":
            continue                      # may define it; defining is not reading
        tree = ast.parse(path.read_text(), filename=str(path))
        reads = [node for node in ast.walk(tree)
                 if isinstance(node, ast.Attribute) and node.attr == "owner_hints"]
        assert not reads, (
            f"agent/{path.name}:{reads[0].lineno} reads .owner_hints — owner hints "
            f"must never reach a model")


def test_query_view_depends_on_the_query_service_not_storage_or_retrieval():
    """The Ask meetings view talks to QueryService only; retrieval, verification,
    vector internals, and storage stay behind that boundary."""
    source = (ROOT / "ui" / "query_view.py").read_text()
    for module in ("storage", "sqlite3", "query.retrieval", "query.verification",
                   "query.vector", "query.prompts"):
        assert not imports_module(source, module), f"ui/query_view.py imports {module}"
    assert imports_module(source, "query.service")


def test_an_indexing_failure_never_deletes_the_saved_analysis():
    """rebuild_meeting_index runs after the extraction is durable; it must sit
    outside the try whose handler deletes the meeting, or a search-index error
    throws away an analysis that was already saved and paid for."""
    path = ROOT / "ui" / "input_view.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        deletes = any(isinstance(n, ast.Attribute) and n.attr == "delete_meeting"
                      for handler in node.handlers for n in ast.walk(handler))
        if not deletes:
            continue
        guarded = [n for stmt in node.body for n in ast.walk(stmt)
                   if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                   and n.func.id == "rebuild_meeting_index"]
        assert guarded == [], "rebuild_meeting_index is inside the delete-on-failure try"
