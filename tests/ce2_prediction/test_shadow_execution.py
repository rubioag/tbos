import uuid

from sqlalchemy.orm import Session

from tbos.ce2_prediction.ensemble import combine_models
from tbos.ce2_prediction.serve_model import ServeModel
from tbos.ce2_prediction.shadow_execution import run_and_store_shadow, run_shadow, store_shadow_output
from tbos.inf1_config.taxonomy import ExecutionMode

from tests.ce2_prediction.factories import make_bundle


def test_run_shadow_tags_output_as_shadow_not_live() -> None:
    output = run_shadow(ServeModel(), make_bundle())
    assert output.execution_mode == ExecutionMode.SHADOW


def test_shadow_output_still_carries_correct_model_identity() -> None:
    output = run_shadow(ServeModel(), make_bundle())
    assert output.model_id == "serve_model"
    assert output.domain == "serve"


def test_shadow_output_never_participates_in_live_ensemble() -> None:
    """The structural enforcement point (CE.2.8): a SHADOW-tagged output
    injected into combine_models must be rejected, not silently combined.
    """
    shadow_output = run_shadow(ServeModel(), make_bundle())
    result = combine_models("match_1", [shadow_output])
    assert result.fully_abstained is True
    assert "execution_mode=SHADOW" in result.abstained[0].reason


def test_shadow_output_mixed_with_live_outputs_is_excluded_but_live_still_combines() -> None:
    shadow_output = run_shadow(ServeModel(), make_bundle())
    live_output = ServeModel().estimate(make_bundle())  # real live output, not run through shadow layer

    result = combine_models("match_1", [shadow_output, live_output])
    assert result.fully_abstained is False
    assert len(result.participating) == 1
    assert len(result.abstained) == 1


def test_store_shadow_output_persists_row(session: Session) -> None:
    output = run_shadow(ServeModel(), make_bundle())
    run_id = uuid.uuid4()
    row = store_shadow_output(session, run_id=run_id, match_id="match_1", output=output)
    session.commit()

    assert row.execution_mode == "SHADOW"
    assert row.model_id == "serve_model"
    assert row.output["execution_mode"] == "SHADOW"


def test_run_and_store_shadow_end_to_end(session: Session) -> None:
    run_id = uuid.uuid4()
    row = run_and_store_shadow(session, ServeModel(), make_bundle(), run_id=run_id)
    session.commit()
    assert row.run_id == run_id
    assert row.match_id == "match_1"
