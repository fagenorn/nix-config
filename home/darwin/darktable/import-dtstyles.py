#!/usr/bin/env python3
"""Minimal headless equivalent of darktable's .dtstyle import dialog."""

from __future__ import annotations

import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def text(node: ET.Element, key: str) -> str:
    value = node.findtext(key)
    if value is None:
        raise ValueError(f"missing <{key}>")
    return value


def import_style(db: sqlite3.Connection, path: Path) -> tuple[str, int]:
    root = ET.parse(path).getroot()
    if root.tag != "darktable_style" or root.attrib.get("version") != "1.0":
        raise ValueError(f"unsupported style format: {path}")
    info = root.find("info")
    style = root.find("style")
    if info is None or style is None:
        raise ValueError(f"incomplete style: {path}")
    name = text(info, "name")
    description = info.findtext("description", default="")
    prior = db.execute("SELECT id FROM styles WHERE name=?", (name,)).fetchone()
    if prior:
        db.execute("DELETE FROM style_items WHERE styleid=?", (prior[0],))
        db.execute("DELETE FROM styles WHERE id=?", (prior[0],))
    db.execute("INSERT INTO styles(name,description,iop_list) VALUES(?,?,NULL)",
               (name, description))
    style_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
    count = 0
    for plugin in style.findall("plugin"):
        op_params = bytes.fromhex(text(plugin, "op_params"))
        blend_params = bytes.fromhex(text(plugin, "blendop_params"))
        db.execute(
            "INSERT INTO style_items(styleid,num,module,operation,op_params,enabled,"
            "blendop_params,blendop_version,multi_priority,multi_name,"
            "multi_name_hand_edited) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (style_id, int(text(plugin, "num")), int(text(plugin, "module")),
             text(plugin, "operation"), op_params, int(text(plugin, "enabled")),
             blend_params, int(text(plugin, "blendop_version")),
             int(text(plugin, "multi_priority")), plugin.findtext("multi_name", default=""),
             int(plugin.findtext("multi_name_hand_edited", default="0"))),
        )
        count += 1
    return name, count


def main() -> None:
    db = sqlite3.connect(sys.argv[1])
    for filename in sys.argv[2:]:
        name, count = import_style(db, Path(filename))
        print(f"imported {name}: {count} items")
    db.commit()


if __name__ == "__main__":
    main()
