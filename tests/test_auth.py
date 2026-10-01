"""Auth tests."""

import pytest
from services.auth_service import hash_password, verify_password

from app import create_app


@pytest.fixture
def app():
    app = create_app()
    app.config.update(
        {
            "TESTING": True,
            "SECRET_KEY": "test_secret",
            "JWT_SECRET_KEY": "test_jwt_secret",
        }
    )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


def test_password_hashing():
    """Test bcrypt hashing and verification."""
    password = "secure_password_123"
    hashed = hash_password(password)
    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False


def test_health_endpoint(client):
    """Test health endpoint."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.get_json()
    assert data["success"] is True
    assert data["status"] == "healthy"
