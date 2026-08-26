from osintbox.catalog import ToolSpec
from osintbox.queue import Job, run_queue
from osintbox.runner import RunResult

SPEC_A = ToolSpec(id="a", category="c", desc="d", command=["a", "{target}"], target_type="username", min_delay_s=5.0)
SPEC_B = ToolSpec(id="b", category="c", desc="d", command=["b", "{target}"], target_type="username", min_delay_s=0.0)
CATALOG = {"a": SPEC_A, "b": SPEC_B}


def _ok(tool_id: str, target: str) -> RunResult:
    return RunResult(tool_id=tool_id, target=target, status="ok", exit_code=0, stdout="", stderr="", findings=[])


def _rate_limited(tool_id: str, target: str) -> RunResult:
    return RunResult(tool_id=tool_id, target=target, status="rate_limited", exit_code=0, stdout="", stderr="", findings=[])


class _FakeClock:
    """now_fn/sleep_fn factices : sleep_fn avance l'horloge au lieu d'attendre reellement."""

    def __init__(self):
        self.t = 0.0
        self.slept: list[float] = []

    def now(self) -> float:
        return self.t

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.t += seconds


def test_single_job_ok():
    jobs_run = run_queue(CATALOG, [("a", "alice")], run_fn=_ok, sleep_fn=lambda s: None)
    assert len(jobs_run) == 1
    assert jobs_run[0].status == "done"
    assert jobs_run[0].attempts == 1


def test_status_transitions_emitted_in_order():
    seen = []
    run_queue(CATALOG, [("a", "alice")], run_fn=_ok, sleep_fn=lambda s: None, on_status_change=lambda j: seen.append(j.status))
    assert seen == ["queued", "running", "done"]


def test_maps_run_status_to_job_status():
    def _error(tool_id, target):
        return RunResult(tool_id=tool_id, target=target, status="error", exit_code=1, stdout="", stderr="", findings=[])

    jobs_run = run_queue(CATALOG, [("a", "alice")], run_fn=_error, sleep_fn=lambda s: None)
    assert jobs_run[0].status == "failed"


def test_enforces_min_delay_between_consecutive_same_tool_runs():
    clock = _FakeClock()
    run_queue(
        CATALOG,
        [("a", "alice"), ("a", "bob")],
        run_fn=_ok,
        sleep_fn=clock.sleep,
        now_fn=clock.now,
    )
    # SPEC_A.min_delay_s = 5.0 ; le 2e run de "a" doit avoir attendu ~5s (l'horloge factice
    # avance de la duree du sleep, donc le delai ecoule au moment du 2e run doit etre >= 5).
    assert 5.0 in clock.slept


def test_no_delay_between_different_tools():
    clock = _FakeClock()
    run_queue(
        CATALOG,
        [("a", "alice"), ("b", "alice")],
        run_fn=_ok,
        sleep_fn=clock.sleep,
        now_fn=clock.now,
    )
    # "b" a min_delay_s=0 et n'a jamais tourne avant -- aucune attente ne doit lui etre imputee.
    assert clock.slept == []


def test_retries_once_on_rate_limit_then_succeeds():
    calls = {"n": 0}

    def _flaky(tool_id, target):
        calls["n"] += 1
        if calls["n"] == 1:
            return _rate_limited(tool_id, target)
        return _ok(tool_id, target)

    jobs_run = run_queue(CATALOG, [("b", "alice")], run_fn=_flaky, sleep_fn=lambda s: None, max_retries_on_rate_limit=1)
    assert jobs_run[0].status == "done"
    assert jobs_run[0].attempts == 2


def test_intermediate_retry_status_is_distinct_from_final_rate_limited():
    # Regression : avant ce correctif, une tentative en cours de nouvelle tentative et un
    # abandon final utilisaient le meme statut "rate_limited", impossible a distinguer pour un
    # appelant qui voulait extraire les findings/compter un job une seule fois de facon fiable
    # (bug reel trouve en testant la GUI : des findings partiels reels etaient perdus, et un
    # "[ERREUR] ... rate_limited" apparaissait a tort pour une simple tentative en cours).
    calls = {"n": 0}

    def _flaky(tool_id, target):
        calls["n"] += 1
        if calls["n"] == 1:
            return _rate_limited(tool_id, target)
        return _ok(tool_id, target)

    seen = []
    run_queue(
        CATALOG, [("b", "alice")], run_fn=_flaky, sleep_fn=lambda s: None,
        max_retries_on_rate_limit=1, on_status_change=lambda j: seen.append(j.status),
    )
    assert seen == ["queued", "running", "retrying", "running", "done"]


def test_findings_from_earlier_rate_limited_attempt_survive_a_worse_retry():
    # Regression (bug reel trouve en testant Maigret contre "jean_dovy", 2026-08-26) : le 1er
    # essai trouve des comptes reels avant d'etre rate-limite, le retry repart d'un scan complet
    # et est bloque plus tot (0 resultat) -- le job final ne doit pas perdre les comptes reels
    # du 1er essai juste parce que le dernier essai n'en a trouve aucun.
    from osintbox.normalizers import Finding

    found = Finding(source="maigret", category="username", type="social_profile", value="https://x/alice")

    def _rate_limited_with_finding(tool_id, target):
        return RunResult(
            tool_id=tool_id, target=target, status="rate_limited", exit_code=0,
            stdout="", stderr="", findings=[found],
        )

    def _rate_limited_without_finding(tool_id, target):
        return RunResult(
            tool_id=tool_id, target=target, status="rate_limited", exit_code=0,
            stdout="", stderr="", findings=[],
        )

    calls = {"n": 0}

    def _flaky(tool_id, target):
        calls["n"] += 1
        return _rate_limited_with_finding(tool_id, target) if calls["n"] == 1 else _rate_limited_without_finding(tool_id, target)

    jobs_run = run_queue(CATALOG, [("b", "alice")], run_fn=_flaky, sleep_fn=lambda s: None, max_retries_on_rate_limit=1)
    assert jobs_run[0].status == "rate_limited"
    assert jobs_run[0].result.findings == [found]


def test_findings_deduplicated_across_retries():
    from osintbox.normalizers import Finding

    found = Finding(source="maigret", category="username", type="social_profile", value="https://x/alice")

    def _same_finding_each_time(tool_id, target):
        return RunResult(
            tool_id=tool_id, target=target, status="rate_limited", exit_code=0,
            stdout="", stderr="", findings=[found],
        )

    jobs_run = run_queue(CATALOG, [("b", "alice")], run_fn=_same_finding_each_time, sleep_fn=lambda s: None, max_retries_on_rate_limit=1)
    assert jobs_run[0].result.findings == [found]  # pas duplique malgre 2 tentatives


def test_gives_up_as_rate_limited_after_max_retries():
    jobs_run = run_queue(CATALOG, [("b", "alice")], run_fn=_rate_limited, sleep_fn=lambda s: None, max_retries_on_rate_limit=1)
    assert jobs_run[0].status == "rate_limited"
    assert jobs_run[0].attempts == 2


def test_backoff_increases_between_retries():
    sleeps = []
    run_queue(
        CATALOG, [("b", "alice")], run_fn=_rate_limited, sleep_fn=lambda s: sleeps.append(s),
        max_retries_on_rate_limit=2, backoff_base_s=10.0,
    )
    # 1er retry : backoff_base_s * 1, 2e retry : backoff_base_s * 2.
    assert sleeps == [10.0, 20.0]


def test_multiple_jobs_return_one_result_each_in_order():
    jobs_run = run_queue(CATALOG, [("a", "alice"), ("b", "bob"), ("a", "carol")], run_fn=_ok, sleep_fn=lambda s: None)
    assert [(j.tool_id, j.target) for j in jobs_run] == [("a", "alice"), ("b", "bob"), ("a", "carol")]


def test_should_cancel_stops_before_next_job_not_mid_job():
    # Le premier job doit quand meme tourner jusqu'au bout -- la verification se fait
    # UNIQUEMENT entre deux jobs, pas a mi-course d'un sous-processus deja lance.
    jobs_run = run_queue(
        CATALOG, [("a", "alice"), ("b", "bob")], run_fn=_ok, sleep_fn=lambda s: None,
        should_cancel=lambda: True,
    )
    assert jobs_run == []


def test_should_cancel_checked_after_first_job_stops_the_rest():
    calls = {"n": 0}

    def _cancel_after_first_job():
        return calls["n"] >= 1

    def _counting_ok(tool_id, target):
        calls["n"] += 1
        return _ok(tool_id, target)

    jobs_run = run_queue(
        CATALOG, [("a", "alice"), ("b", "bob"), ("a", "carol")],
        run_fn=_counting_ok, sleep_fn=lambda s: None, should_cancel=_cancel_after_first_job,
    )
    assert [j.tool_id for j in jobs_run] == ["a"]


def test_should_cancel_none_runs_normally():
    jobs_run = run_queue(CATALOG, [("a", "alice")], run_fn=_ok, sleep_fn=lambda s: None, should_cancel=None)
    assert len(jobs_run) == 1
