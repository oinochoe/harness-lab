#!/usr/bin/env python3
"""Report capabilities for selected formats only. Never install anything."""
import argparse,importlib.util,json,sys
from pathlib import Path

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--formats',nargs='+',choices=('html','pdf'),required=True);p.add_argument('--photos',action='store_true');a=p.parse_args()
 root=Path(__file__).resolve().parents[1];issues=[]
 if sys.version_info<(3,10): issues.append('Python 3.10+ is required')
 files=['scripts/trip_core.py']
 if 'html' in a.formats: files+=['assets/dashboard.html','assets/vendor/chart.js','assets/vendor/leaflet.js','assets/vendor/leaflet.css']
 if 'pdf' in a.formats:
  files+=['assets/fonts/Pretendard-Regular.ttf','assets/fonts/Pretendard-Medium.ttf','assets/fonts/NotoSerifKR-Regular.ttf','assets/fonts/NotoSansJP-Regular.ttf']
  for module in ('reportlab','PIL'):
   if importlib.util.find_spec(module) is None: issues.append('PDF dependency unavailable: '+module)
 if a.photos:
  files+=['scripts/media_pipeline.py']
  if importlib.util.find_spec('PIL') is None: issues.append('Photo preparation dependency unavailable: Pillow (PIL)')
 for f in files:
  if not (root/f).is_file():issues.append('Package asset missing: '+f)
 print(json.dumps({'ok':not issues,'formats':a.formats,'python':sys.version.split()[0],'issues':issues},ensure_ascii=False,indent=2))
 return 1 if issues else 0
if __name__=='__main__':sys.exit(main())
