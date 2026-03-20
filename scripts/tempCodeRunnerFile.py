"""
Pipeline automation: generate instances -> git push -> trigger workflow -> wait -> move data -> download summary.

Requirements:
  - gh CLI (https://cli.github.com/) installed and authenticated (gh auth login)
  - git configured with push access
  - Python 3.8+

Examples:
  python scripts/pipeline.py --name Lan5 --workflow run
  python scripts/pipeline.py --name Lan6 --workflow run-batch --batches 1 2 3
  python scripts/pipeline.py --name Lan7 --only-generate
  python scripts/pipeline.py --name Lan7 --only-download --run-id 12345678
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parent.parent
TRAIN_DATA_ROOT = Path(r"E:\TTTH\train_data")
BASELINE_ROOT = TRAIN_DATA_ROOT / "Baseline"

logger = logging.getLogger("pipeline")


class Namespace(argparse.Namespace):
    if TYPE_CHECKING:
        name: str
        workflow: str
        batches: list[int]
        files_per_batch: int
        only_generate: bool
        only_download: bool
        run_id: list[int] | None
        timeout: int
        skip_generate: bool
        skip_push: bool
        yes: bool


def setup_logging(name: str) -> Path:
    log_dir = ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_file = log_dir / f"pipeline_{name}_{timestamp}.log"

    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    logger.setLevel(logging.DEBUG)
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    return log_file


def run_cmd(
    args: list[str],
    check: bool = True,
    capture: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    cmd_str = " ".join(args)
    logger.debug(f"$ {cmd_str}")

    result = subprocess.run(
        args,
        capture_output=capture,
        text=True,
        cwd=cwd or ROOT,
    )

    if result.stdout:
        logger.debug(result.stdout.rstrip())
    if result.stderr:
        logger.debug(f"STDERR: {result.stderr.rstrip()}")

    if check and result.returncode != 0:
        msg = f"Command failed (exit {result.returncode}): {cmd_str}"
        if result.stderr:
            msg += f"\n{result.stderr.rstrip()}"
        raise RuntimeError(msg)

    return result


# ---------------------------------------------------------------------------
# Prerequisites
# ---------------------------------------------------------------------------

def _refresh_windows_path_env():
    if os.name != "nt":
        return
    try:
        machine = os.environ.get("Path", "")
        # Prefer registry-backed values (new terminals may not pick them up yet)
        import winreg  # type: ignore

        def read_reg_path(root, subkey, value):
            try:
                with winreg.OpenKey(root, subkey) as k:
                    v, _ = winreg.QueryValueEx(k, value)
                    return str(v)
            except OSError:
                return ""

        machine_path = read_reg_path(
            winreg.HKEY_LOCAL_MACHINE,
            r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment",
            "Path",
        )
        user_path = read_reg_path(winreg.HKEY_CURRENT_USER, r"Environment", "Path")
        combined = ";".join(p for p in [machine_path, user_path, machine] if p)
        os.environ["PATH"] = combined
    except Exception:
        # Best-effort only; don't fail pipeline because of PATH refresh
        return


def _ensure_gh_on_path() -> bool:
    _refresh_windows_path_env()
    if shutil.which("gh"):
        return True

    # Common installation locations for GitHub CLI on Windows
    candidates = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "GitHub CLI" / "gh.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "GitHub CLI" / "gh.exe",
        Path(os.environ.get("LocalAppData", "")) / "GitHub CLI" / "gh.exe",
    ]
    for p in candidates:
        if p.is_file():
            os.environ["PATH"] = str(p.parent) + ";" + os.environ.get("PATH", "")
            return True

    return False


def check_prerequisites():
    logger.info("Kiem tra prerequisites...")

    try:
        run_cmd(["git", "--version"])
    except (FileNotFoundError, RuntimeError):
        logger.error("git chua duoc cai dat!")
        sys.exit(1)

    if not _ensure_gh_on_path():
        logger.error(
            "gh CLI chua duoc cai dat!\n"
            "  Windows : winget install --id GitHub.cli\n"
            "  Hoac tai: https://cli.github.com/"
        )
        sys.exit(1)

    try:
        run_cmd(["gh", "--version"])
    except (FileNotFoundError, RuntimeError):
        logger.error(
            "Khong the chay 'gh' duoc (co the PATH chua cap nhat). Thu dong terminal moi hoac reboot.\n"
            "Neu van loi, chay: where gh"
        )
        sys.exit(1)

    result = run_cmd(["gh", "auth", "status"], check=False)
    if result.returncode != 0:
        logger.error("gh chua dang nhap! Chay: gh auth login")
        sys.exit(1)

    logger.info("  -> git va gh da san sang\n")


# ---------------------------------------------------------------------------
# Step 1 – Generate instances
# ---------------------------------------------------------------------------

def step1_generate_instances():
    logger.info("=" * 60)
    logger.info("STEP 1: Sinh instance")
    logger.info("=" * 60)

    script = ROOT / "problems" / "generate_instance.py"
    run_cmd([sys.executable, str(script)], capture=False)

    data_dir = ROOT / "problems" / "data"
    count = len(list(data_dir.glob("*.txt")))
    logger.info(f"  -> Da sinh {count} file trong {data_dir}\n")


# ---------------------------------------------------------------------------
# Step 2 – Git push
# ---------------------------------------------------------------------------

def step2_git_push():
    logger.info("=" * 60)
    logger.info("STEP 2: Git push")
    logger.info("=" * 60)

    run_cmd(["git", "add", "problems/data/"])

    result = run_cmd(["git", "diff", "--cached", "--stat"], check=False)
    if not result.stdout.strip():
        logger.info("  Khong co thay doi de commit, bo qua.\n")
        return

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    run_cmd(["git", "commit", "-m", f"data: generate instances ({timestamp})"])
    run_cmd(["git", "push"])
    logger.info("  -> Push thanh cong!\n")


# ---------------------------------------------------------------------------
# Step 3 – Trigger workflow
# ---------------------------------------------------------------------------

def _get_latest_run_id(workflow_file: str) -> int | None:
    result = run_cmd([
        "gh", "run", "list",
        "--workflow", workflow_file,
        "--limit", "1",
        "--json", "databaseId",
    ])
    runs = json.loads(result.stdout)
    return runs[0]["databaseId"] if runs else None


def _wait_for_new_run(workflow_file: str, previous_id: int | None, max_wait: int = 60) -> int:
    """Poll until a new run appears that differs from previous_id."""
    deadline = time.time() + max_wait
    while time.time() < deadline:
        new_id = _get_latest_run_id(workflow_file)
        if new_id and new_id != previous_id:
            return new_id
        time.sleep(3)
    raise RuntimeError(
        f"Khong tim thay run moi cho {workflow_file} sau {max_wait}s. "
        "Kiem tra GitHub Actions."
    )


def step3_trigger_workflow(
    workflow: str,
    batches: list[int] | None = None,
    files_per_batch: int = 1000,
) -> list[int]:
    logger.info("=" * 60)
    logger.info(f"STEP 3: Trigger workflow '{workflow}'")
    logger.info("=" * 60)

    workflow_file = f"{workflow}.yml" if workflow == "run" else "run-batch.yml"
    run_ids: list[int] = []

    if workflow == "run":
        prev_id = _get_latest_run_id(workflow_file)
        run_cmd(["gh", "workflow", "run", workflow_file])
        logger.info("  Da trigger 'Run algorithm'")

        run_id = _wait_for_new_run(workflow_file, prev_id)
        run_ids.append(run_id)
        logger.info(f"  -> Run ID: {run_id}")

    elif workflow == "run-batch":
        if not batches:
            logger.error("Can chi dinh --batches cho workflow run-batch!")
            sys.exit(1)

        for batch_num in batches:
            prev_id = _get_latest_run_id(workflow_file)
            run_cmd([
                "gh", "workflow", "run", workflow_file,
                "-f", f"batch_number={batch_num}",
                "-f", f"files_per_batch={files_per_batch}",
            ])
            logger.info(f"  Da trigger batch {batch_num}")

            run_id = _wait_for_new_run(workflow_file, prev_id)
            run_ids.append(run_id)
            logger.info(f"  -> Batch {batch_num} => Run ID: {run_id}")

    logger.info(f"  Tong cong {len(run_ids)} run\n")
    return run_ids


# ---------------------------------------------------------------------------
# Step 4 – Wait for workflows
# ---------------------------------------------------------------------------

def step4_wait_for_workflows(run_ids: list[int], timeout: int = 7200):
    logger.info("=" * 60)
    logger.info(f"STEP 4: Cho {len(run_ids)} workflow hoan thanh (timeout {timeout}s)")
    logger.info("=" * 60)

    start = time.time()
    pending = set(run_ids)
    poll_interval = 30
    failed: list[int] = []

    while pending:
        elapsed = int(time.time() - start)
        if elapsed > timeout:
            logger.error(f"Timeout sau {timeout}s! Cac run chua xong: {pending}")
            sys.exit(1)

        for run_id in list(pending):
            result = run_cmd([
                "gh", "run", "view", str(run_id),
                "--json", "status,conclusion",
            ])
            data = json.loads(result.stdout)
            status = data.get("status", "unknown")
            conclusion = data.get("conclusion", "")

            logger.info(f"  [{elapsed:>5}s] Run {run_id}: {status}"
                        + (f" ({conclusion})" if conclusion else ""))

            if status == "completed":
                pending.discard(run_id)
                if conclusion != "success":
                    failed.append(run_id)
                    logger.warning(f"  Run {run_id} ket thuc voi: {conclusion}")

        if pending:
            logger.info(f"  Con {len(pending)} run dang chay, cho {poll_interval}s...\n")
            time.sleep(poll_interval)

    if failed:
        logger.warning(f"  Cac run that bai: {failed}")
        logger.warning("  Tiep tuc cac buoc tiep theo...\n")
    else:
        logger.info("  -> Tat ca workflow da hoan thanh!\n")


# ---------------------------------------------------------------------------
# Step 5 – Move data
# ---------------------------------------------------------------------------

def step5_move_data(name: str):
    logger.info("=" * 60)
    logger.info(f"STEP 5: Chuyen data sang train_data/{name}")
    logger.info("=" * 60)

    data_dir = ROOT / "problems" / "data"
    target_dir = TRAIN_DATA_ROOT / name
    target_dir.mkdir(parents=True, exist_ok=True)

    txt_files = list(data_dir.glob("*.txt"))
    if not txt_files:
        logger.warning("  Khong co file .txt nao de chuyen!\n")
        return

    logger.info(f"  {len(txt_files)} file: {data_dir} -> {target_dir}")

    moved = 0
    for f in txt_files:
        shutil.move(str(f), str(target_dir / f.name))
        moved += 1
        if moved % 500 == 0:
            logger.info(f"  ... {moved}/{len(txt_files)}")

    logger.info(f"  -> Da chuyen {moved} file\n")


# ---------------------------------------------------------------------------
# Step 6 – Download summary
# ---------------------------------------------------------------------------

def step6_download_summary(name: str, run_ids: list[int], workflow: str):
    logger.info("=" * 60)
    logger.info(f"STEP 6: Tai summary ve Baseline/{name}")
    logger.info("=" * 60)

    baseline_dir = BASELINE_ROOT / name
    baseline_dir.mkdir(parents=True, exist_ok=True)

    for run_id in run_ids:
        artifact_names = _list_artifacts(run_id)
        # Chi tai summary-csv (run.yml) hoac summary-batch-N (run-batch.yml)
        summary_arts = [
            a for a in artifact_names
            if a == "summary-csv"
            or (a.startswith("summary-batch-") and a[len("summary-batch-"):].isdigit())
        ]

        if not summary_arts:
            logger.warning(f"  Run {run_id}: khong tim thay artifact summary")
            logger.info(f"  Cac artifact co san: {artifact_names}")
            continue

        for art in summary_arts:
            logger.info(f"  Tai '{art}' tu run {run_id}...")
            result = run_cmd([
                "gh", "run", "download", str(run_id),
                "--name", art,
                "--dir", str(baseline_dir),
            ], check=False)
            if result.returncode == 0:
                logger.info(f"  -> OK: {art}")
            else:
                logger.warning(f"  Khong tai duoc '{art}': {result.stderr.rstrip()}")

    logger.info(f"  -> Summary da luu tai {baseline_dir}\n")


def _list_artifacts(run_id: int) -> list[str]:
    result = run_cmd([
        "gh", "api",
        f"repos/{{owner}}/{{repo}}/actions/runs/{run_id}/artifacts",
        "--jq", ".artifacts[].name",
    ], check=False)
    if result.returncode != 0 or not result.stdout.strip():
        return []
    return result.stdout.strip().splitlines()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def confirm(message: str) -> bool:
    try:
        answer = input(f"{message} (y/n): ").strip().lower()
        return answer in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline tu dong: sinh instance -> push -> workflow -> chuyen data -> tai summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--name", required=True, help="Ten folder (VD: Lan5)")
    parser.add_argument("--workflow", choices=["run", "run-batch"], default="run",
                        help="Workflow can trigger (default: run)")
    parser.add_argument("--batches", type=int, nargs="+",
                        help="Batch numbers cho run-batch (VD: 1 2 3)")
    parser.add_argument("--files-per-batch", type=int, default=1000,
                        help="So file moi batch (default: 1000)")
    parser.add_argument("--timeout", type=int, default=7200,
                        help="Timeout cho workflow (giay, default: 7200)")
    parser.add_argument("--only-generate", action="store_true",
                        help="Chi sinh instance + push, khong trigger workflow")
    parser.add_argument("--only-download", action="store_true",
                        help="Chi chuyen data + tai summary (can --run-id)")
    parser.add_argument("--run-id", type=int, nargs="+",
                        help="Run ID(s) cho --only-download")
    parser.add_argument("--skip-generate", action="store_true",
                        help="Bo qua buoc sinh instance")
    parser.add_argument("--skip-push", action="store_true",
                        help="Bo qua buoc git push")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Bo qua xac nhan")

    args = parser.parse_args(namespace=Namespace())

    log_file = setup_logging(args.name)
    logger.info(f"Log file: {log_file}\n")

    data_dir = TRAIN_DATA_ROOT / args.name
    baseline_dir = BASELINE_ROOT / args.name

    if args.only_download:
        if not args.run_id:
            logger.error("Can chi dinh --run-id khi dung --only-download!")
            sys.exit(1)

        logger.info(f"CHE DO: Chi tai summary")
        logger.info(f"  Data dir     : {data_dir}")
        logger.info(f"  Baseline dir : {baseline_dir}")
        logger.info(f"  Run IDs      : {args.run_id}\n")

        check_prerequisites()
        step5_move_data(args.name)
        step6_download_summary(args.name, args.run_id, args.workflow)

    elif args.only_generate:
        logger.info("CHE DO: Chi sinh instance + push\n")
        step1_generate_instances()
        step2_git_push()

    else:
        logger.info("CHE DO: Full pipeline")
        logger.info(f"  Workflow      : {args.workflow}")
        logger.info(f"  Data dir     : {data_dir}")
        logger.info(f"  Baseline dir : {baseline_dir}")
        if args.batches:
            logger.info(f"  Batches      : {args.batches}")
        logger.info("")

        if not args.yes:
            if not confirm("Bat dau pipeline?"):
                logger.info("Da huy.")
                sys.exit(0)
            print()

        check_prerequisites()

        if not args.skip_generate:
            step1_generate_instances()

        if not args.skip_push:
            step2_git_push()

        run_ids = step3_trigger_workflow(args.workflow, args.batches, args.files_per_batch)
        step4_wait_for_workflows(run_ids, args.timeout)
        step5_move_data(args.name)
        step6_download_summary(args.name, run_ids, args.workflow)

    logger.info("=" * 60)
    logger.info("PIPELINE HOAN TAT!")
    logger.info("=" * 60)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\nDa huy pipeline (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\nLoi: {e}", exc_info=True)
        sys.exit(1)