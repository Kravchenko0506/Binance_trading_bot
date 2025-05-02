import logging
import pytest
from unittest.mock import patch
from services.order_execution import place_order

@pytest.fixture
def mock_lot_size():
    return (0.1, 1)  # step_size, min_qty

@patch("services.order_execution.client.order_market_buy")
@patch("services.order_execution.get_lot_size")
@patch("services.order_execution.get_balance")
def test_place_order_buy_logs_correctly(mock_balance, mock_lot, mock_order, caplog, mock_lot_size):
    caplog.set_level(logging.INFO)
    mock_balance.return_value = 10.0
    mock_lot.return_value = mock_lot_size

    mock_order.return_value = {
        "fills": [
            {"price": "2.00", "qty": "1.0", "commission": "0.001", "commissionAsset": "XRP"},
            {"price": "2.10", "qty": "2.0", "commission": "0.002", "commissionAsset": "XRP"},
        ]
    }

    place_order("buy", "XRPUSDT", 0.001)

    log = caplog.text
    assert "Покупка: 3.000000 XRP" in log
    assert "по средней цене 2.066667 USDT" in log
    assert "Комиссия: 0.003000 XRP" in log

@patch("services.order_execution.client.order_market_sell")
@patch("services.order_execution.get_lot_size")
@patch("services.order_execution.get_balance")
def test_place_order_sell_logs_correctly(mock_balance, mock_lot, mock_order, caplog,):
    caplog.set_level(logging.INFO)
    mock_balance.return_value = 10.0
    mock_lot.return_value = (0.1, 1)

    mock_order.return_value = {
    "fills": [
        {"price": "2.50", "qty": "1.5", "commission": "0.001", "commissionAsset": "XRP"},
        {"price": "2.40", "qty": "1.5", "commission": "0.001", "commissionAsset": "XRP"},
    ]
}


    place_order("sell", "XRPUSDT", 0.001)

    log = caplog.text
    assert "Продажа: 3.000000 XRP" in log
    assert "по средней цене 2.450000 USDT" in log
    assert "Комиссия: 0.002000 XRP" in log
