"""Kill sweep (adopted from the sixth review's probes). For every statement of a scenario's operation: copy the prepared database, run the
operation in a child process that is stopped before that statement, then read the list from a fresh
process state (a new App, as the next command would), and again after the same operation is retried."""
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg

import scenarios
from tend.app import App

ADMIN = os.environ.get("TEND_TEST_DSN", "postgresql://tend:tend@localhost/tend_dev")
HERE = os.path.dirname(os.path.abspath(__file__))


def dsn(name):
    return ADMIN.rsplit("/", 1)[0] + "/" + name


def admin(sql):
    with psycopg.connect(ADMIN, autocommit=True) as a:
        a.execute(sql)


def child(db, name, n, trace=False):
    args = [sys.executable, os.path.join(HERE, "crash_runner.py"), dsn(db), name, str(n)] + (["trace"] if trace else [])
    return subprocess.run(args, capture_output=True, text=True)


def read(db):
    app = App(scenarios.cfg(dsn(db)))
    try:
        text = app.brief("now").render()
        return app, "\n".join(text.split("\n")[1:])       # without the "as of" line
    except Exception:
        app.close()
        raise


def one(tmpl, name, n):
    _, op, ok = scenarios.SCENARIOS[name]
    db = "tend_k_" + uuid.uuid4().hex[:10]
    admin(f'CREATE DATABASE "{db}" TEMPLATE "{tmpl}"')
    out = {"n": n}
    try:
        r = child(db, name, n)
        out["exit"] = r.returncode
        if r.returncode not in (0, 9):
            out["child_error"] = r.stderr.strip().splitlines()[-1][:200] if r.stderr.strip() else "?"
        # the next command: a fresh App reads the list
        try:
            app, text = read(db)
            good, note = ok(app, text)
            out["after_kill"] = good
            out["note"] = note
            out["state"] = (app.ledger.meta("stale"), len(app.ledger.unprojected()))
            if not good:
                out["list"] = text.replace("\n", " / ")[:400]
            app.close()
        except Exception as e:
            out["after_kill"] = False
            out["list"] = f"{type(e).__name__}: {e}"[:300]
        # the same operation retried, then the list again
        try:
            app = App(scenarios.cfg(dsn(db)))
            try:
                op(app)
            finally:
                app.close()
            app, text = read(db)
            good, note = ok(app, text)
            out["after_retry"] = good
            if not good:
                out["retry_list"] = text.replace("\n", " / ")[:400]
            out["retry_text"] = text
            app.close()
        except Exception as e:
            out["after_retry"] = False
            out["retry_list"] = f"{type(e).__name__}: {e}"[:300]
    finally:
        try:
            admin(f'DROP DATABASE "{db}" WITH (FORCE)')
        except Exception:
            pass
    return out


def sweep(name, points="all", workers=3):
    """Run the scenario uninterrupted, then killed before each chosen statement. Returns the counts
    and the failing points."""
    setup, op, ok = scenarios.SCENARIOS[name]
    tmpl = "tend_tmpl_" + uuid.uuid4().hex[:8]
    admin(f'CREATE DATABASE "{tmpl}"')
    try:
        app = App(scenarios.cfg(dsn(tmpl)))
        setup(app)
        app.close()
        base = "tend_k_" + uuid.uuid4().hex[:10]
        admin(f'CREATE DATABASE "{base}" TEMPLATE "{tmpl}"')
        r = child(base, name, 0)
        if r.returncode != 0:
            raise RuntimeError("uninterrupted run failed: " + r.stderr[-2000:])
        total = int(r.stdout.split("TOTAL", 1)[1].split()[0])
        app, baseline = read(base)
        good, _ = ok(app, baseline)
        app.close()
        admin(f'DROP DATABASE "{base}" WITH (FORCE)')
        if points == "all":
            ns = list(range(1, total + 1))
        elif points.startswith("stride"):
            k = int(points.split("=")[1])
            ns = sorted(set(range(1, total + 1, k)) | set(range(max(1, total - 15), total + 1)))
        else:
            ns = [int(x) for x in points.split(",")]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(lambda n: one(tmpl, name, n), ns))
    finally:
        admin(f'DROP DATABASE "{tmpl}" WITH (FORCE)')
    return {
        "total": total, "baseline_ok": good, "tried": len(ns),
        "wrong_after_kill": [r["n"] for r in results if not r.get("after_kill")],
        "wrong_after_retry": [r["n"] for r in results if not r.get("after_retry")],
        "retry_differs": [r["n"] for r in results if r.get("after_retry") and r.get("retry_text") != baseline],
        "child_errors": [(r["n"], r["child_error"]) for r in results if "child_error" in r],
        "examples": [(r["n"], r.get("list") or r.get("retry_list")) for r in results
                     if not (r.get("after_kill") and r.get("after_retry"))][:3],
    }


if __name__ == "__main__":
    import json
    print(json.dumps(sweep(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "all"), indent=1))
