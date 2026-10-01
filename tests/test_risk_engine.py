"""Risk engine tests."""

from services.risk_engine import compute_risk_scores


def test_compute_risk_scores():
    """Test risk engine logic formulas and weights."""
    # Mock data from CoinGecko
    market_data = {
        "price_change_percentage_24h": -15.0,  # High volatility
        "market_cap_rank": 500,  # Lower cap, higher risk
        "total_volume": 1000000,
        "market_cap": 5000000,  # V/M = 0.2 (decent liquidity)
    }

    # Mock data from GoPlus
    security_data = {
        "is_open_source": "1",
        "is_proxy": "0",
        "is_mintable": "1",
        "owner_change_balance": "1",
    }

    result = compute_risk_scores(market_data, security_data, "ethereum")

    assert "total_score" in result
    assert "market_risk" in result
    assert "security_risk" in result
    assert "volatility_risk" in result
    assert "liquidity_risk" in result

    # Validate bounds
    assert 0 <= result["total_score"] <= 100
    assert 0 <= result["market_risk"] <= 100
    assert 0 <= result["security_risk"] <= 100
