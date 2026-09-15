"""Safe synthetic planner evaluation CLI."""
import argparse
import json
from app.planning.evaluation import evaluate,load_cases

def main(argv=None,*,write=print):
    parser=argparse.ArgumentParser(description="Synthetic planning diagnostics; no execution")
    parser.add_argument("command",choices=["evaluate","validate-dataset"])
    args=parser.parse_args(argv)
    try:
        report=evaluate() if args.command=="evaluate" else {"label":"synthetic diagnostic dataset","rows":len(load_cases()),"execution_permitted":False}
        write(json.dumps(report,sort_keys=True));return 0
    except Exception:
        write('{"status":"invalid_dataset","execution_permitted":false}');return 2

if __name__=="__main__": raise SystemExit(main())
