from time import sleep

from app.research_jobs import ResearchJobs


def test_research_job_runs_in_background_and_returns_result():
    jobs = ResearchJobs()
    started = jobs.submit("test", lambda: {"isolated": True})
    assert started["status"] in {"running", "completed"}
    for _ in range(20):
        result = jobs.get(started["id"])
        if result and result["status"] == "completed":
            break
        sleep(.01)
    assert result["status"] == "completed"
    assert result["result"] == {"isolated": True}


def test_research_job_reuses_completed_result_for_the_same_cache_key():
    jobs = ResearchJobs()
    calls = 0

    def work():
        nonlocal calls
        calls += 1
        return {"run": calls}

    first = jobs.submit("test", work, cache_key="same-parameters")
    for _ in range(20):
        completed = jobs.get(first["id"])
        if completed and completed["status"] == "completed":
            break
        sleep(.01)

    reused = jobs.submit("test", work, cache_key="same-parameters")

    assert completed["status"] == "completed"
    assert reused["id"] == first["id"]
    assert reused["result"] == {"run": 1}
    assert calls == 1
