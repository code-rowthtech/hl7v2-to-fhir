import argparse, json, sys
from pathlib import Path
from .convert import convert

def main():
    parser = argparse.ArgumentParser(description="Convert the documented HL7 subset to FHIR R4")
    parser.add_argument("input", nargs="?", default="sample-data/result.hl7")
    args = parser.parse_args()
    try: print(json.dumps(convert(Path(args.input).read_text()), indent=2))
    except (ValueError, OSError) as error:
        print(str(error), file=sys.stderr); return 1
    return 0
if __name__ == "__main__": sys.exit(main())
