import numpy as np
import pytest
from sklearn.cluster import DBSCAN
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.utils.estimator_checks import parametrize_with_checks

from sklego.meta import SubjectiveClassifier


@parametrize_with_checks(
    [
        SubjectiveClassifier(
            estimator=LogisticRegression(),
            prior={0: 0.1, 1: 0.1, 2: 0.1, 3: 0.1, "one": 0.1, "two": 0.1, "three": 0.1, -1: 0.3},
        )
    ]
)
def test_sklearn_compatible_estimator(estimator, check):
    if check.func.__name__ in {
        "check_classifiers_regression_target",  # Custom message from `if set(y) - set(self.prior.keys())`
        "check_fit2d_1feature",  # Custom message
    }:
        pytest.skip()

    check(estimator)


@pytest.mark.parametrize(
    "classes, prior, cfm, first_class_posterior",
    [
        ([0, 1], [0.8, 0.2], [[90, 10], [10, 90]], 0.973),  # numeric classes
        (["a", "b"], [0.8, 0.2], [[90, 10], [10, 90]], 0.973),  # char classes
        ([False, True], [0.8, 0.2], [[90, 10], [10, 90]], 0.973),  # bool classes
        (
            ["a", "b", "c"],
            [0.8, 0.1, 0.1],
            [[80, 10, 10], [10, 90, 0], [0, 0, 100]],
            0.985,
        ),  # n classes
        (
            [0, 1],
            [0.8, 0.2],
            [[100, 0], [0, 100]],
            1.0,
        ),  # "perfect" confusion matrix (no FP) -> prior is ignored
        (
            [0, 1],
            [0.2, 0.8],
            [[0, 100], [0, 100]],
            0.2,
        ),  # failure to predict class by inner estimator
        (
            [0, 1, 2],
            [0.1, 0.1, 0.8],
            [[0, 0, 100], [0, 0, 100], [0, 0, 100]],
            0.1,
        ),  # extremely biased, n classes
        (
            [0, 1, 2],
            [0.2, 0.1, 0.7],
            [[80, 0, 20], [0, 0, 100], [10, 0, 90]],
            0.696,
        ),  # biased, n classes
    ],
)
def test_posterior_computation(mocker, classes, prior, cfm, first_class_posterior):
    def mock_confusion_matrix(y, y_pred):
        return np.array(cfm)

    mocker.patch("sklego.meta.subjective_classifier.confusion_matrix", side_effect=mock_confusion_matrix)
    mocker.patch(
        "sklego.meta.subjective_classifier.SubjectiveClassifier.classes_",
        new_callable=mocker.PropertyMock,
        return_value=np.array(classes),
    )

    mock_estimator = mocker.MagicMock(RandomForestClassifier())

    subjective_model = SubjectiveClassifier(mock_estimator, dict(zip(classes, prior)))
    subjective_model.fit(np.zeros((10, 10)), np.array([classes[0]] * 10))

    assert pytest.approx(subjective_model.posterior_matrix_[0, 0], 0.001) == first_class_posterior
    assert np.isclose(subjective_model.posterior_matrix_.sum(axis=0), 1).all()


@pytest.mark.parametrize(
    "prior, y",
    [
        (
            {"a": 0.8, "b": 0.2},
            ["a", "c"],
        ),  # class from train data not defined in prior
        ({"a": 0.8, "b": 0.2}, [0, 1]),  # different data types
    ],
)
def test_fit_y_data_inconsistent_with_prior_failure_conditions(prior, y):
    with pytest.raises(ValueError) as exc:
        SubjectiveClassifier(RandomForestClassifier(), prior).fit(np.zeros((len(y), 2)), np.array(y))

    assert str(exc.value).startswith("Training data is inconsistent with prior")


def test_to_discrete():
    assert np.isclose(
        SubjectiveClassifier._to_discrete(np.array([[1, 0], [0.8, 0.2], [0.5, 0.5], [0.2, 0.8]])),
        np.array([[1, 0], [1, 0], [1, 0], [0, 1]]),
    ).all()


@pytest.mark.parametrize(
    "weights,y_hats,expected_probas",
    [
        (
            [0.8, 0.2],
            [[1, 0], [0.5, 0.5], [0.8, 0.2]],
            [[1, 0], [0.8, 0.2], [0.94, 0.06]],
        ),
        (
            [0.5, 0.5],
            [[1, 0], [0.5, 0.5], [0.8, 0.2]],
            [[1, 0], [0.5, 0.5], [0.8, 0.2]],
        ),
        ([[0.8, 0.2], [0.5, 0.5]], [[1, 0], [0.8, 0.2]], [[1, 0], [0.8, 0.2]]),
    ],
)
def test_weighted_proba(weights, y_hats, expected_probas):
    assert np.isclose(
        SubjectiveClassifier._weighted_proba(np.array(weights), np.array(y_hats)),
        np.array(expected_probas),
        atol=1e-02,
    ).all()


@pytest.mark.parametrize(
    "evidence_type,expected_probas",
    [
        ("predict_proba", [[0.94, 0.06], [1, 0], [0.8, 0.2], [0.5, 0.5]]),
        ("confusion_matrix", [[0.97, 0.03], [0.97, 0.03], [0.97, 0.03], [0.47, 0.53]]),
        ("both", [[0.99, 0.01], [1, 0], [0.97, 0.03], [0.18, 0.82]]),
    ],
)
def test_predict_proba(mocker, evidence_type, expected_probas):
    subjective_model = SubjectiveClassifier(
        estimator=RandomForestClassifier(), prior={0: 0.8, 1: 0.2}, evidence=evidence_type
    )

    def mock_confusion_matrix(y, y_pred):
        return np.array([[80, 20], [10, 90]])

    classes = [0, 1]
    mocker.patch("sklego.meta.subjective_classifier.confusion_matrix", side_effect=mock_confusion_matrix)
    mocker.patch(
        "sklego.meta.subjective_classifier.SubjectiveClassifier.classes_",
        new_callable=mocker.PropertyMock,
        return_value=np.array(classes),
    )
    subjective_model.fit(np.zeros((10, 2)), np.zeros(10))

    subjective_model.estimator_.predict_proba = lambda X: np.array([[0.8, 0.2], [1, 0], [0.5, 0.5], [0.2, 0.8]])
    posterior_probabilities = subjective_model.predict_proba(np.zeros((4, 2)))

    assert posterior_probabilities.shape == (4, 2)
    assert np.isclose(posterior_probabilities, np.array(expected_probas), atol=0.01).all()


@pytest.mark.parametrize(
    "inner_estimator, prior, evidence, expected_error_msg",
    [
        (DBSCAN(), {"a": 1}, "both", "Invalid inner estimator"),
        (Ridge(), {"a": 1}, "predict_proba", "Invalid inner estimator"),
        (
            RandomForestClassifier(),
            {"a": 0.8, "b": 0.1},
            "confusion_matrix",
            "Invalid prior",
        ),
        (
            RandomForestClassifier(),
            {"a": 0.8, "b": 0.2},
            "foo_evidence",
            "Invalid evidence",
        ),
    ],
)
def test_params_failure_conditions(inner_estimator, prior, evidence, expected_error_msg):
    with pytest.raises(ValueError) as exc:
        SubjectiveClassifier(inner_estimator, prior, evidence).fit(np.zeros((2, 2)), np.zeros(2))

    assert str(exc.value).startswith(expected_error_msg)
