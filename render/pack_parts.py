#!/usr/bin/env python3
"""Packs big shard files (staged as release assets, too big to pass between jobs as artifacts) into map files
below the 2 GB release file limit: "<name>-part1of5.mbtiles" ... The app shows all parts of a map as one map.

usage: pack_parts.py <stage release tag> <shard count> <out dir> <tmp dir>
Needs gh (GH_TOKEN, GITHUB_REPOSITORY). Adjacent shards are merged greedily up to LIMIT bytes
(identical tiles inside one part are stored once, so a part is never larger than the sum of its shards).
"""
import json
import os
import re
import sqlite3
import subprocess
import sys

LIMIT = 1_900_000_000
tag, shards, out_dir, tmp = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4]
repo = os.environ["GITHUB_REPOSITORY"]
os.makedirs(out_dir, exist_ok=True)
os.makedirs(tmp, exist_ok=True)

assets = json.loads(subprocess.run(["gh", "release", "view", tag, "-R", repo, "--json", "assets"],
                                   check=True, capture_output=True, text=True).stdout)["assets"]
groups = {}
for a in assets:
    m = re.match(r"^(.*)\.part(\d+)\.mbtiles$", a["name"])
    if m:
        groups.setdefault(m.group(1), []).append((int(m.group(2)), a["name"], a["size"]))


def new_db(path, first_part):
    if os.path.exists(path):
        os.remove(path)
    db = sqlite3.connect(path)
    db.executescript("""
        PRAGMA journal_mode = OFF; PRAGMA synchronous = OFF;
        CREATE TABLE metadata (name TEXT, value TEXT);
        CREATE TABLE map (zoom_level INTEGER, tile_column INTEGER, tile_row INTEGER, tile_id TEXT);
        CREATE TABLE images (tile_id TEXT, tile_data BLOB);
        CREATE UNIQUE INDEX images_id ON images (tile_id);""")
    db.execute("ATTACH DATABASE ? AS part", (first_part,))
    db.execute("INSERT INTO metadata SELECT * FROM part.metadata")
    db.commit()
    db.execute("DETACH DATABASE part")
    return db


def close_db(db, path):
    db.executescript("""
        CREATE UNIQUE INDEX map_index ON map (zoom_level, tile_column, tile_row);
        CREATE VIEW tiles AS SELECT map.zoom_level AS zoom_level, map.tile_column AS tile_column,
            map.tile_row AS tile_row, images.tile_data AS tile_data FROM map JOIN images ON images.tile_id = map.tile_id;""")
    db.commit()
    db.close()
    print(f"  {os.path.basename(path)}: {os.path.getsize(path) / 1e9:.2f} GB", flush=True)


for base, parts in sorted(groups.items()):
    parts.sort()
    name = base if len(parts) == shards else base + "-INCOMPLETE"
    if len(parts) != shards:
        print(f"WARN: {base}: only {len(parts)} of {shards} shards", flush=True)
    # greedy grouping of adjacent shards
    packs, cur, size = [], [], 0
    for p in parts:
        if cur and size + p[2] > LIMIT:
            packs.append(cur)
            cur, size = [], 0
        cur.append(p)
        size += p[2]
    if cur:
        packs.append(cur)
    print(f"{base}: {len(parts)} shards, {sum(p[2] for p in parts) / 1e9:.2f} GB -> {len(packs)} files", flush=True)
    for k, pack in enumerate(packs, 1):
        path = os.path.join(out_dir, f"{name}-part{k}of{len(packs)}.mbtiles")
        db = None
        for _, asset, _ in pack:
            local = os.path.join(tmp, asset)
            subprocess.run(["gh", "release", "download", tag, "-R", repo, "-p", asset, "-D", tmp, "--clobber"], check=True)
            if db is None:
                db = new_db(path, local)
            db.execute("ATTACH DATABASE ? AS part", (local,))
            db.execute("INSERT INTO map SELECT * FROM part.map")
            db.execute("INSERT OR IGNORE INTO images SELECT * FROM part.images")
            db.commit()
            db.execute("DETACH DATABASE part")
            os.remove(local)
        close_db(db, path)
