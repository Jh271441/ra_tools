"""Activate already verified evaluation contexts; no acquisition or simulation."""
import argparse
import json
from pathlib import Path
from app.database import SessionLocal
from app.services.metric_profiles import activate


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('profile')
    parser.add_argument('--contexts',type=Path,required=True,help='JSON array of ready release/date contexts')
    parser.add_argument('--expected-active',required=True)
    args=parser.parse_args()
    with SessionLocal() as db:
        result=activate(db,args.profile,json.loads(args.contexts.read_text()),args.expected_active)
    print(json.dumps(result,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
