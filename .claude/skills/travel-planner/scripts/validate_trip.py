#!/usr/bin/env python3
"""Validate without modifying any input. Errors exit 2; review findings exit 0."""
import argparse,json,sys
from trip_core import load_trip,validate_trip

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('input');p.add_argument('--baseline');p.add_argument('--allow-changes')
 a=p.parse_args()
 try:
  report=validate_trip(load_trip(a.input),load_trip(a.baseline) if a.baseline else None,load_trip(a.allow_changes) if a.allow_changes else None)
 except (ValueError,OSError,TypeError) as exc:
  print(json.dumps({'status':'invalid_input','error':str(exc)},ensure_ascii=False));return 2
 print(json.dumps(report,ensure_ascii=False,indent=2));return 2 if report['errors'] else 0
if __name__=='__main__': sys.exit(main())
