import os
import sys

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient

from app.main import app

def test_flow():
    with TestClient(app) as client:
        print("Testing Root Endpoint...")
        response = client.get("/")
        assert response.status_code == 200
        assert response.json()["status"] == "online"
        print("OK")

        print("Testing Motor Catalog...")
        response = client.get("/api/v1/motor/")
        assert response.status_code == 200
        data = response.json()
        assert len(data) > 0
        assert any(x["model_name"] == "Honda CB100" for x in data)
        print("OK")

        print("Testing Register...")
        email = "test@pocketmechanic.com"
        password = "password123"
        response = client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": password,
                "full_name": "Test Montir",
            },
        )
        if response.status_code == 201:
            print("Register Success (New User)")
        else:
            assert response.status_code == 400
            print("Register response (User already exists, status 400 - Expected)")

        print("Testing Login...")
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200
        token_data = response.json()
        assert "access_token" in token_data
        token = token_data["access_token"]
        print("OK - Token received")

        print("Testing Auth Me...")
        headers = {"Authorization": f"Bearer {token}"}
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200
        assert response.json()["email"] == email
        print("OK")

        print("Testing Chat Send (RAG)...")
        response = client.post(
            "/api/v1/chat/send",
            data={
                "message": "Kenapa seher GL Max sering macet?",
                "motor_model": "Honda GL Max",
            },
            headers=headers,
        )
        assert response.status_code == 200
        chat_resp = response.json()
        assert "ai_response" in chat_resp
        print("OK - Chat Response:", chat_resp["ai_response"][:100], "...")

        print("Testing Chat History...")
        response = client.get("/api/v1/chat/history", headers=headers)
        assert response.status_code == 200
        history = response.json()
        assert len(history) > 0
        print("OK - History has", len(history), "messages")

        print("\n--- ALL ENDPOINT TESTS PASSED SUCCESSFULLY! ---")


if __name__ == "__main__":
    test_flow()
