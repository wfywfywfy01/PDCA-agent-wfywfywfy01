"""Preview/apply the confirmed department roster to existing cards; sends no messages."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlmodel import Session
from app.database import get_engine
from app.duzhan_admin.service import configure_departments


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="apply after validation; default is preview")
    args = parser.parse_args()
    with Session(get_engine()) as session:
        changes = configure_departments(session, apply=args.apply)
    print(json.dumps({"applied": args.apply, "changes": changes}, ensure_ascii=False, indent=2))
