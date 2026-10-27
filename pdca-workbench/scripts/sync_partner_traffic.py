"""Fetch route-5 traffic; ZIP credentials stay in memory and never enter output."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.growth import ga4, partner_traffic


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--credentials-zip", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--days", type=int, default=28)
    parser.add_argument("--end-date", help="Last completed GA4 property date, YYYY-MM-DD")
    args = parser.parse_args()
    if args.credentials_zip:
        with ZipFile(args.credentials_zip) as archive:
            names = ("ga4-config.json", "ga4-service-account.json")
            if any(archive.getinfo(name).file_size > 64000 for name in names):
                raise ga4.Ga4Error("凭据文件大小异常")
            config, account = (json.loads(archive.read(name)) for name in names)
        if (config.get("scope") != ga4.SCOPE or account.get("type") != "service_account"
                or account.get("token_uri") != "https://oauth2.googleapis.com/token"
                or account.get("client_email") != config.get("service_account_email")):
            raise ga4.Ga4Error("凭据配置与服务账号不一致")
        os.environ["PDCA_GROWTH_GA4_PROPERTY_ID"] = str(config["property_id"])
        os.environ["PDCA_GROWTH_GA4_SA_JSON"] = json.dumps(account)
    data = partner_traffic.collect(args.days, end_date=args.end_date)
    partner_traffic.write_snapshot(args.output, data)
    print(json.dumps({"output": str(args.output), "period": data["period"], "quality": data["quality"],
                      "scopes": {key: {"summary": value["summary"], "seo": value["seo"], "ai": value["ai"],
                                       "pages": len(value["pages"])} for key, value in data["scopes"].items()}}))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        # Unexpected errors may contain credential values; only known safe errors are printed.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__,
                          "detail": str(exc) if isinstance(exc, ga4.Ga4Error) else "读取失败，请检查文件或配置"}), file=sys.stderr)
        sys.exit(1)
