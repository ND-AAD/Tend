"""Run one scenario's operation in this process and stop the process (os._exit, as a kill does: no
cleanup, the connection is dropped, an open transaction is rolled back by the server) immediately
before its Nth SQL statement. N = 0 runs to the end and prints the statement count."""
import os
import sys

import psycopg

import scenarios
from tend.app import App

STATE = {"n": 0, "kill_at": 0, "armed": False, "trace": None}


class KillCursor(psycopg.Cursor):
    def _tick(self, query):
        if not STATE["armed"]:
            return
        STATE["n"] += 1
        if STATE["trace"] is not None:
            STATE["trace"].append(" ".join(str(query).split())[:110])
        if STATE["n"] == STATE["kill_at"]:
            sys.stdout.flush()
            os._exit(9)

    def execute(self, query, params=None, **kw):
        self._tick(query)
        return super().execute(query, params, **kw)

    def executemany(self, query, params_seq, **kw):
        self._tick(query)
        return super().executemany(query, params_seq, **kw)


def main():
    dsn, name, n = sys.argv[1], sys.argv[2], int(sys.argv[3])
    trace = len(sys.argv) > 4
    _, op, _ = scenarios.SCENARIOS[name]
    conn = psycopg.connect(dsn, autocommit=True, cursor_factory=KillCursor)
    app = App(scenarios.cfg(dsn), conn=conn)
    STATE.update(kill_at=n, armed=True, trace=[] if trace else None)
    op(app)
    STATE["armed"] = False
    print("TOTAL", STATE["n"])
    if trace:
        for i, q in enumerate(STATE["trace"], 1):
            print(i, q)
    app.close()


if __name__ == "__main__":
    main()
