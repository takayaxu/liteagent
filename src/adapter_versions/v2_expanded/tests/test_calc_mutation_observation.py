from copy import deepcopy
from types import SimpleNamespace

from integrations.lite_agent.adapter_results import execution_context_summary, adapter_context_hint
from integrations.lite_agent.context_projection import compact_execution_summary_for_model


def test_prior_labels_identify_referenced_measure_and_overwritten_target():
    read = {"sheet": "Forecast", "range": "H4:J5", "workbook_url": "file:///synthetic.xlsx",
            "cell_addresses": [["H4", "I4", "J4"], ["H5", "I5", "J5"]],
            "display_text": [["Person", "Q3", "Q4"], ["Ada", "17", "29"]],
            "kinds": [["string"] * 3, ["string", "number", "number"]]}
    receipt = {"target_count": 1, "targets_omitted_count": 0, "targets": [{
        "cell": "J5", "before": {"kind": "number", "value": 29},
        "after": {"kind": "formula", "formula": "=(J5-I5)/I5", "display_text": "0.7"},
        "references": {"status": "observed", "cells": [{"sheet": "Forecast", "cell": "I5", "value": 17}]},
    }]}
    write = adapter_context_hint("libreoffice_calc", "cells.set_formulas", {"result": {
        "sheet": "Forecast", "workbook_url": read["workbook_url"], "cells": [],
        "mutation_observation": receipt,
    }})
    events = [SimpleNamespace(step=i, executed=True, error=None,
        proposed={"kind": "adapter", "action": action, "arguments": {}},
        result={"context_hint": hint}) for i, action, hint in [
            (1, "range.read", read), (2, "cells.set_formulas", write)]]
    original = deepcopy(receipt)
    projected = execution_context_summary(events, "libreoffice_calc", strict_generic=True)
    mutation = projected[-1]["result"]["context_hint"]["mutation_observation"]
    cell = mutation["targets"][0]
    assert cell["overwrote_nonblank"] is True
    assert cell["row_text_left"] == {"cell": "H5", "text": "Ada"}
    assert cell["column_text_above"] == {"cell": "J4", "text": "Q4"}
    assert cell["references"]["cells"][0]["column_text_above"]["text"] == "Q3"
    assert receipt == original
    retry = compact_execution_summary_for_model(projected, max_chars=2300)
    assert retry[-1]["result"]["context_hint"]["mutation_observation"]["targets"][0]["before"]["value"] == 29
    # A different workbook's labels must not be attached to this write.
    write["workbook_url"] = "file:///other.xlsx"
    changed = execution_context_summary(events, "libreoffice_calc", strict_generic=True)
    assert changed[-1]["result"]["context_hint"]["mutation_observation"]["targets"][0]["row_text_left"] is None
