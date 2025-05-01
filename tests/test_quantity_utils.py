import pytest
from utils.quantity_utils import round_step_size

@pytest.mark.parametrize("value,step,expected", [
    (1.2345, 0.1, 1.2),
    (1.239, 0.01, 1.23),
    (1.239, 0.001, 1.239),
    (0.0009, 0.0005, 0.0005),
])
def test_round_step_size(value, step, expected):
    assert round_step_size(value, step) == expected
