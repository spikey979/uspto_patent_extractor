#!/usr/bin/env python3
import os
import re
import sys
import time
import psycopg2
import psycopg2.extras

DB = dict(host="localhost", port=5432, dbname="companies_db", user="postgres", password="qwklmn711")

# Override port for remote runs via SSH tunnel (5555 on server)
try:
    if os.environ.get("DB_PORT"):
        DB["port"] = int(os.environ["DB_PORT"])  # type: ignore
except Exception:
    pass

BATCH = int(os.environ.get("BATCH", "3000"))

RE_CLAIM = re.compile(r"(?is)<claim\b[^>]*>(.*?)</claim>")
RE_TAG = re.compile(r"<[^>]+>")
RE_WS = re.compile(r"\s+")


def extract_claims_from_xml(path: str) -> str:
    try:
        with open(path, "rb") as f:
            data = f.read()
    except Exception:
        return ""
    try:
        s = data.decode("utf-8", errors="ignore")
    except Exception:
        try:
            s = data.decode("latin-1", errors="ignore")
        except Exception:
            return ""
    blocks = RE_CLAIM.findall(s)
    if not blocks:
        return ""
    out = []
    for b in blocks:
        t = RE_TAG.sub(" ", b)
        t = RE_WS.sub(" ", t).strip()
        if t:
            out.append(t)
    return "\n".join(out)


def main() -> None:
    conn = psycopg2.connect(**DB)
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    total_updated = 0
    start = time.time()
    while True:
        cur.execute(
            """
            SELECT pub_number, raw_xml_path
            FROM patent_data_unified
            WHERE claims_text IS NULL
              AND raw_xml_path IS NOT NULL
              AND char_length(raw_xml_path) > 0
            ORDER BY pub_date NULLS LAST
            LIMIT %s
            """,
            (BATCH,),
        )
        rows = cur.fetchall()
        if not rows:
            break

        upd = 0
        for r in rows:
            pub = r["pub_number"]
            path = r["raw_xml_path"]
            if not path or not os.path.isfile(path):
                continue
            claims = extract_claims_from_xml(path)
            if not claims:
                continue
            try:
                cur.execute(
                    "UPDATE patent_data_unified SET claims_text=%s WHERE pub_number=%s AND claims_text IS NULL",
                    (claims, pub),
                )
                upd += 1
                total_updated += 1
            except Exception:
                conn.rollback()
                cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
                continue
            if upd % 500 == 0:
                conn.commit()
                print(f"commit: {upd} updated (total {total_updated})", flush=True)

        conn.commit()
        print(f"batch done: {upd} updated (total {total_updated})", flush=True)
        if upd == 0:
            break

    dur = time.time() - start
    print(f"done: total updated {total_updated} in {dur/60:.1f} min", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        sys.exit(130)

