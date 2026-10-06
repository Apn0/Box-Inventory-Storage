1. **Fix Exception Leakage in `server.py`:**
   - In `_handle_quickadd()`, change `return self._json(500, {"error": str(exc)[:200]})` to a generic `return self._json(500, {"error": "internal error"})`, and add `print(f"  quickadd error: {exc}")` before the return statement.
   - In `_handle_confirm_dismiss()`, change `return self._json(500, {"error": str(exc)[:200]})` to a generic `return self._json(500, {"error": "internal error"})`, and add `print(f"  confirm error: {exc}")` before the return statement.
   - In `_handle_undo()`, change `return self._json(409, {"error": str(exc)[:200]})` to a generic `return self._json(409, {"error": "undo failed"})`, and add `print(f"  undo error: {exc}")` before the return statement.

2. **Add Tests:**
   - Append a new function `test_handler_exception_leakage` to `tests/test_server.py`. Mock `identify.commit` and `identify.undo_last` to raise generic Exceptions. Initialize a `Handler` object with simulated POST requests to `/quickadd`, `/confirm`, and `/undo`. Verify that `_json` is called with generic error strings and does not contain the original exception message.

3. **Verify Tests:**
   - Run the full test suite using `PYTHONPATH=. python -m pytest tests/` to confirm the fix works and no regressions were introduced.

4. Complete pre-commit steps to ensure proper testing, verification, review, and reflection are done.

5. **Submit PR:**
   - Submit the changes using the title `🔒 Exception Detail Leakage in API Responses` with `What`, `Risk`, and `Solution` descriptions.
