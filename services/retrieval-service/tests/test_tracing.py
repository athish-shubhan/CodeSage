import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracing import Trace  # noqa: E402


def test_step_records_stage_and_elapsed_time():
    trace = Trace()

    with trace.step("dense_search", {"top_k": 5}) as meta:
        time.sleep(0.01)
        meta["hits"] = 3

    spans = trace.as_dict()
    assert len(spans) == 1
    assert spans[0]["stage"] == "dense_search"
    assert spans[0]["ms"] >= 10
    assert spans[0]["meta"] == {"top_k": 5, "hits": 3}


def test_multiple_steps_recorded_in_order():
    trace = Trace()
    with trace.step("a"):
        pass
    with trace.step("b"):
        pass

    stages = [s["stage"] for s in trace.as_dict()]
    assert stages == ["a", "b"]
