from app.models.model_score import ModelScore
from app.services.recommendations import select_model_score_by_fallback


def _score(trim, year):
    return ModelScore(
        make="toyota",
        model="camry",
        trim=trim,
        year=year,
        design=7,
        performance=7,
        technology=7,
        practicality=7,
        future_value=7,
    )


def test_select_model_score_prefers_exact_trim_and_year():
    exact = _score("xse", 2024)
    fallback_trim = _score("xse", None)
    fallback_year = _score(None, 2024)
    generic = _score(None, None)

    selected = select_model_score_by_fallback(
        [generic, fallback_year, fallback_trim, exact],
        year=2024,
        trim="XSE",
    )

    assert selected is exact


def test_select_model_score_fallback_order():
    fallback_trim = _score("xse", None)
    fallback_year = _score(None, 2024)
    generic = _score(None, None)

    selected = select_model_score_by_fallback(
        [generic, fallback_year, fallback_trim],
        year=2024,
        trim="XSE",
    )
    assert selected is fallback_trim

    selected = select_model_score_by_fallback(
        [generic, fallback_year],
        year=2024,
        trim="XSE",
    )
    assert selected is fallback_year

    selected = select_model_score_by_fallback(
        [generic],
        year=2024,
        trim="XSE",
    )
    assert selected is generic
