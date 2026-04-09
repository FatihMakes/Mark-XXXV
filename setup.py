import sys

from core.bootstrap_check import format_report, run_checks


def main() -> int:
    print("Running MARK-XXXV bootstrap validation...")
    report = run_checks()
    print(format_report(report))
    if not report["ok"]:
        print("\nInstall dependencies with 'pip install -r requirements.txt' and run 'playwright install'.")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
