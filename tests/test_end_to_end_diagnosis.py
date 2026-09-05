"""End-to-end guardrails for every supported anomaly class."""
from datetime import datetime, timezone
import random

import pytest

from evaluate_recon import evaluate_batch
from src.constants import InjectedCause
from src.generate.anomaly_injectors import INJECTORS
from src.generate.entity_factory import case_to_dict, generate_clean_case


@pytest.mark.parametrize("injected_cause", list(INJECTORS))
def test_each_injector_reaches_its_expected_root_cause(injected_cause):
    """A synthetic anomaly must survive ingest, match, and diagnosis intact."""
    seed = list(INJECTORS).index(injected_cause) + 101
    clean = case_to_dict(generate_clean_case(
        random.Random(seed),
        base_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
        case_index=seed,
    ))
    case, ground_truth = INJECTORS[injected_cause](clean)
    case["ground_truth"] = ground_truth

    result = evaluate_batch([case])
    diagnosis = result["case_results"][case["order_id"]]["diagnosis"]

    assert diagnosis["hypothesis"] == ground_truth["expected_ch"], (
        f"{injected_cause.value} was not diagnosed as "
        f"{ground_truth['expected_ch']}: {diagnosis}"
    )

