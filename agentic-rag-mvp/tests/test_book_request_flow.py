import importlib.util
import os
import sys
import types


def load_gradio_copy_module():
    # Load the module by file path (filename contains a space so importlib by name won't work)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    mod_path = os.path.join(root, "app", "gradio_main copy.py")
    # Ensure a minimal dummy 'gradio' module exists so the copy file can import
    # without requiring the real Gradio package during unit tests.
    if "gradio" not in sys.modules:
        gr_mod = types.ModuleType("gradio")

        class _DummyCtx:
            def __init__(self, *a, **k):
                pass
            def __enter__(self):
                return self
            def __exit__(self, exc_type, exc, tb):
                return False

        def _component(*a, **k):
            return _DummyCtx()

        # Assign common names used in the module to the dummy module
        for name in ["Blocks", "Accordion", "Tabs", "Tab", "Row"]:
            setattr(gr_mod, name, lambda *a, **k: _DummyCtx())
        for name in ["Slider", "Dataframe", "Markdown", "Dropdown", "Textbox", "Button", "CheckboxGroup", "Files", "Code", "Plot", "Radio", "Checkbox"]:
            setattr(gr_mod, name, lambda *a, **k: _DummyCtx())

        sys.modules["gradio"] = gr_mod
    spec = importlib.util.spec_from_file_location("gradio_copy", mod_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_submit_and_approve_flow():
    mod = load_gradio_copy_module()

    # reset stores
    mod.BOOK_REQUESTS = {}
    mod.LIBRARIAN_QUEUES = {"requests": [], "returns": []}

    user = "alice"
    book_label = mod._book_label("book1")

    msg, rows, approved_choices = mod.submit_book_request(user, book_label, "2025-10-01", "Need for class")
    assert "Request submitted" in msg
    assert user in mod.BOOK_REQUESTS
    assert any(r.get("book_id") == "book1" for r in mod.BOOK_REQUESTS[user])

    pending = mod.librarian_list_pending()
    assert pending and len(pending) >= 1
    selected = pending[0]

    msg2, pending_after, student_rows = mod.librarian_approve(selected, "2025-10-02", "On shelf")
    assert "Approved" in msg2

    # refresh_my_requests should show the approved status
    refreshed_rows, approved_choices = mod.refresh_my_requests(user)
    assert any((r[1].lower() == "approved") for r in refreshed_rows)


def test_reject_flow():
    mod = load_gradio_copy_module()

    # reset stores
    mod.BOOK_REQUESTS = {}
    mod.LIBRARIAN_QUEUES = {"requests": [], "returns": []}

    user = "bob"
    book_label = mod._book_label("book2")

    mod.submit_book_request(user, book_label, "", "")
    pending = mod.librarian_list_pending()
    assert pending
    selected = pending[0]

    msg, pending_after, student_rows = mod.librarian_reject(selected, "Not available")
    assert "Rejected" in msg

    refreshed_rows, approved_choices = mod.refresh_my_requests(user)
    assert any((r[1].lower() == "rejected") for r in refreshed_rows)
