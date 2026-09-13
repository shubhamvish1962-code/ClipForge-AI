"""
ClipForge AI — Backend API & Pipeline Integration Tests.
"""

import pytest
import shortuuid
from httpx import AsyncClient, ASGITransport
from apps.api.main import app

@pytest.mark.asyncio
async def test_health_check():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/health")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] in ["ok", "healthy"]
        assert data["app"] == "ClipForge AI"

@pytest.mark.asyncio
async def test_user_registration_and_login():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        uid = shortuuid.uuid()
        email = f"test_{uid}@example.com"
        reg_res = await ac.post("/api/auth/register", json={
            "email": email,
            "username": f"usr_{uid[:8]}",
            "password": "Password123!",
            "full_name": "Test User"
        })
        assert reg_res.status_code == 201
        tokens = reg_res.json()
        assert "access_token" in tokens

        # Login
        login_res = await ac.post("/api/auth/login", json={
            "email": email,
            "password": "Password123!"
        })
        assert login_res.status_code == 200
        assert "access_token" in login_res.json()

        # Me
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        me_res = await ac.get("/api/auth/me", headers=headers)
        assert me_res.status_code == 200
        assert me_res.json()["email"] == email

@pytest.mark.asyncio
async def test_youtube_url_source_pipeline():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        uid = shortuuid.uuid()
        email = f"test_url_{uid}@example.com"
        reg_res = await ac.post("/api/auth/register", json={
            "email": email,
            "username": f"uurl_{uid[:8]}",
            "password": "Password123!",
            "full_name": "URL Tester"
        })
        assert reg_res.status_code == 201
        token = reg_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # 1. Create project
        p_res = await ac.post("/api/projects", json={"name": "YouTube Test Project"}, headers=headers)
        assert p_res.status_code == 201
        project_id = p_res.json()["id"]

        # 2. Add URL source
        s_res = await ac.post(f"/api/projects/{project_id}/sources", json={
            "source_type": "url",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        }, headers=headers)
        assert s_res.status_code == 201
        assert s_res.json()["status"] == "accepted"

        # 3. Confirm rights
        r_res = await ac.post(f"/api/projects/{project_id}/rights", json={
            "content_type": "user_uploaded",
            "confirmation_text": "I confirm rights",
            "confirmed": True
        }, headers=headers)
        assert r_res.status_code == 201

        # 4. Trigger processing
        proc_res = await ac.post(f"/api/projects/{project_id}/process", json={}, headers=headers)
        assert proc_res.status_code == 200
        assert "job_id" in proc_res.json()

@pytest.mark.asyncio
async def test_virality_checker_ensemble():
    from apps.api.agents.virality_checker_agent import ViralityCheckerAgent
    agent = ViralityCheckerAgent()
    res = await agent.run({
        "transcript_text": "You know what's interesting about building AI products? 95% accuracy means nothing if nobody uses it. We got rejected by 47 investors before someone said yes.",
        "start_time": 0.0,
        "end_time": 45.0,
        "hook_time": 0.0,
        "duration": 45.0,
        "topic": "AI Startups & UX",
    })
    assert res.status == "success"
    assert "total_score" in res.output
    assert res.output["total_score"] > 0

@pytest.mark.asyncio
async def test_quality_control_agent():
    from apps.api.agents.quality_control_agent import QualityControlAgent
    agent = QualityControlAgent()
    res = await agent.run({
        "transcript_text": "Sample transcript for QA testing",
        "duration": 45.0,
        "width": 1080,
        "height": 1920,
    })
    assert res.status == "success"
    assert "overall_passed" in res.output
