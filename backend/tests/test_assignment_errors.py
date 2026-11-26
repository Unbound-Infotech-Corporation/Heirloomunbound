"""The assignments router maps domain errors to 400s instead of crashing."""
import os

os.environ.setdefault("MONGO_URL", "mongodb://127.0.0.1:27017")
os.environ.setdefault("DB_NAME", "heirloom")

from assignments import ApprovalFinal, AssignmentError  # noqa: E402
from routers.assignments import _map_error  # noqa: E402


def test_a_closed_approval_is_a_400_not_a_name_error():
    mapped = _map_error(ApprovalFinal("Approval is approved and cannot be retried"))
    assert mapped.status_code == 400
    assert "cannot be retried" in mapped.detail


def test_other_errors_get_the_generic_message():
    assert _map_error(AssignmentError("bad")).detail == "bad"
    assert _map_error(RuntimeError("boom")).detail == "Could not update the assignment"
