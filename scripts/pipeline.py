"""
Pipeline automation: generate instances -> git push -> trigger workflow -> wait -> move data -> download summary.

Requirements:
  - gh CLI (https://cli.github.com/) installed and authenticated (gh auth login)
  - git configured with push access
  - Python 3.8+

Examples:
  python scripts/pipeline.py -y                         # run-batch: 10 jobs/instance (tu-increment)
  python scripts/pipeline.py --workflow run-batch-v2 -y  # run-batch-v2: 1 job/instance
  python scripts/pipeline.py --loop -y                  # Loop run-batch: 10 jobs/instance (chạy liên tục)
  python scripts/pipeline.py --loop --workflow run-batch-v2 -y  # Loop run-batch-v2: 1 job/instance (chạy liên tục)
  python scripts/pipeline.py --loop --loop-interval 3600 -y  # Loop với delay 1h giữa các gen
  python scripts/pipeline.py --status                   # Xem lich su generation
  python scripts/pipeline.py --reset                    # Reset generation state ve 0
  python scripts/pipeline.py --only-generate -y         # Chi sinh 4000 + push (khong workflow)
  python scripts/pipeline.py --only-download --run-id 12345678  # Chi tai summary
  python scripts/pipeline.py --workflow run -y          # Dung 'run' workflow (single run, khong batch)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parent.parent
TRAIN_DATA_ROOT = Path(r"E:\TTTH\train_data")
BASELINE_ROOT = TRAIN_DATA_ROOT / "Baseline"
GENERATION_STATE_FILE = ROOT / "GENERATION_STATE.json"

logger = logging.getLogger("pipeline")


class Namespace(argparse.Namespace):
    if TYPE_CHECKING:
        name: str | None
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
        status: bool
        reset: bool
        loop: bool
        loop_interval: int


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

    # Load current state
    state = load_generation_state()
    start_number = state["next_start_number"]
    generation_num = state["generation_count"] + 1
    
    logger.info(f"  Generation #{generation_num}")
    logger.info(f"  Start number: {start_number}")
    logger.info(f"  Total instances generated so far: {state['total_instances_generated']}\n")

    # Clear old data files before generating new ones
    data_dir = ROOT / "problems" / "data"
    if data_dir.exists():
        old_files = list(data_dir.glob("*.txt"))
        if old_files:
            logger.info(f"  Clearing {len(old_files)} old files from {data_dir}")
            for f in old_files:
                f.unlink()
            logger.info(f"  -> Cleared!\n")

    script = ROOT / "problems" / "generate_instance.py"
    run_cmd([
        sys.executable, str(script),
        "--start-number", str(start_number),
        "--batch-size", "4000"
    ], capture=False)

    count = len(list(data_dir.glob("*.txt")))
    logger.info(f"  -> Da sinh {count} file trong {data_dir}\n")
    
    # Update generation state
    update_generation_state(count, start_number)


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
# Helper – Calculate batch count
# ---------------------------------------------------------------------------

def calculate_batch_count(files_per_batch: int) -> int:
    """Tinh so batch can thiet dua tren so file trong problems/data"""
    data_dir = ROOT / "problems" / "data"
    total_files = len(list(data_dir.glob("*.txt")))
    if total_files == 0:
        logger.warning("  Khong co file .txt nao trong problems/data!")
        return 0
    batch_count = (total_files + files_per_batch - 1) // files_per_batch
    logger.info(f"  Tinh toan: {total_files} files / {files_per_batch} files-per-batch = {batch_count} batches\n")
    return batch_count


# ---------------------------------------------------------------------------
# Helper – Generation State Management
# ---------------------------------------------------------------------------

def load_generation_state() -> dict:
    """Load generation state from JSON file"""
    if GENERATION_STATE_FILE.exists():
        try:
            with open(GENERATION_STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Cannot load state file: {e}, using defaults")
    
    # Default state
    return {
        "generation_count": 0,
        "next_start_number": 0,
        "total_instances_generated": 0,
        "last_generation_date": None,
        "history": []
    }


def save_generation_state(state: dict):
    """Save generation state to JSON file"""
    try:
        with open(GENERATION_STATE_FILE, 'w') as f:
            json.dump(state, f, indent=2)
        logger.info(f"  -> Generation state saved to {GENERATION_STATE_FILE}")
    except Exception as e:
        logger.error(f"Cannot save state file: {e}")


def update_generation_state(num_instances: int, start_number: int):
    """Update generation state after successful generation"""
    state = load_generation_state()
    
    state["generation_count"] += 1
    state["total_instances_generated"] += num_instances
    state["next_start_number"] = start_number + num_instances
    state["last_generation_date"] = datetime.now().isoformat()
    
    # Add to history
    history_entry = {
        "generation_num": state["generation_count"],
        "start_number": start_number,
        "num_instances": num_instances,
        "date": state["last_generation_date"],
        "total_so_far": state["total_instances_generated"]
    }
    state["history"].append(history_entry)
    
    save_generation_state(state)
    
    # Log summary
    logger.info(f"  Generation #{state['generation_count']}: {num_instances} instances (start={start_number})")
    logger.info(f"  Total instances generated so far: {state['total_instances_generated']}")
    logger.info(f"  Next start number: {state['next_start_number']}\n")


def reset_generation_state():
    """Reset generation state to initial state"""
    default_state = {
        "generation_count": 0,
        "next_start_number": 0,
        "total_instances_generated": 0,
        "last_generation_date": None,
        "history": []
    }
    save_generation_state(default_state)
    print(f"\n[INFO] Generation state reset to initial state\n")


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

    workflow_file = f"{workflow}.yml" if workflow == "run" else f"{workflow}.yml"
    run_ids: list[int] = []

    if workflow == "run":
        prev_id = _get_latest_run_id(workflow_file)
        run_cmd(["gh", "workflow", "run", workflow_file])
        logger.info("  Da trigger 'Run algorithm'")

        run_id = _wait_for_new_run(workflow_file, prev_id)
        run_ids.append(run_id)
        logger.info(f"  -> Run ID: {run_id}")

    elif workflow in ["run-batch", "run-batch-v2"]:
        # Auto-calculate batches if not provided
        if not batches:
            batch_count = calculate_batch_count(files_per_batch)
            if batch_count == 0:
                logger.error("Khong the tinh batch count!")
                sys.exit(1)
            batches = list(range(1, batch_count + 1))
            logger.info(f"  Auto-generated batches: {batches}\n")

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
        # Chi tai summary-csv (run.yml) hoac summary-batch-N (run-batch.yml) hoac summary-batch-v2-N (run-batch-v2.yml)
        summary_arts = [
            a for a in artifact_names
            if a == "summary-csv"
            or (a.startswith("summary-batch-") and a[len("summary-batch-"):].isdigit())
            or (a.startswith("summary-batch-v2-") and a[len("summary-batch-v2-"):].isdigit())
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


def confirm_with_timeout(message: str, timeout_seconds: int = 120) -> bool:
    """
    Ask user for Y/N confirmation with timeout.
    If no response within timeout, auto-returns True (continue).
    
    Args:
        message: Prompt message
        timeout_seconds: Timeout in seconds (default 120 = 2 minutes)
    
    Returns:
        True if user says 'y' or timeout expires (auto-continue)
        False if user says 'n'
    """
    result: dict[str, str | None] = {"answer": None}
    
    def get_input():
        try:
            result["answer"] = input(f"{message} (y/n) [auto-continue in {timeout_seconds}s]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            result["answer"] = "n"
    
    # Run input in a thread so we can timeout
    input_thread = threading.Thread(target=get_input, daemon=True)
    input_thread.start()
    input_thread.join(timeout=timeout_seconds)
    
    # If thread still alive, timeout occurred
    if input_thread.is_alive():
        print(f"[INFO] Timeout: tự động chạy tiếp iteration tiếp theo\n")
        return True
    
    # Check user response
    if result["answer"] is None:
        return True
    elif result["answer"] in ("y", "yes"):
        return True
    else:
        return False


def show_generation_status():
    """Display current generation status"""
    state = load_generation_state()
    print("\n" + "=" * 60)
    print("GENERATION STATUS")
    print("=" * 60)
    print(f"Total generations: {state['generation_count']}")
    print(f"Total instances generated: {state['total_instances_generated']}")
    print(f"Next start number: {state['next_start_number']}")
    print(f"Last generation date: {state['last_generation_date']}")
    
    if state['history']:
        print("\nHistory:")
        for entry in state['history'][-5:]:  # Show last 5 entries
            print(f"  Gen #{entry['generation_num']}: {entry['num_instances']} instances "
                  f"(start={entry['start_number']}, total={entry['total_so_far']}) - {entry['date'][:10]}")
    print("=" * 60 + "\n")


def run_pipeline_once(args: Namespace) -> bool:
    """
    Run pipeline once for one generation.
    Returns True if successful, False if failed.
    """
    try:
        # For other modes without --name, auto-generate from generation count
        if not args.name:
            state = load_generation_state()
            gen_num = state["generation_count"] + 1
            args.name = f"Lan{gen_num}"
            print(f"[INFO] Auto-generated name: {args.name} (generation #{gen_num})\n")

        log_file = setup_logging(args.name)
        logger.info(f"Log file: {log_file}\n")

        data_dir = TRAIN_DATA_ROOT / args.name
        baseline_dir = BASELINE_ROOT / args.name

        if args.only_download:
            if not args.run_id:
                logger.error("Can chi dinh --run-id khi dung --only-download!")
                return False

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
            
            # Auto-calculate batches if run-batch and not provided
            if args.workflow == "run-batch" and not args.batches:
                batch_count = calculate_batch_count(args.files_per_batch)
                if batch_count > 0:
                    args.batches = list(range(1, batch_count + 1))
                    logger.info(f"  Batches      : {args.batches} (auto-calculated)")
            elif args.batches:
                logger.info(f"  Batches      : {args.batches}")
            
            logger.info(f"  Files/batch  : {args.files_per_batch}\n")

            if not args.yes:
                if not confirm("Bat dau pipeline?"):
                    logger.info("Da huy.")
                    return False
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
        
        return True

    except Exception as e:
        logger.error(f"\nLoi: {e}", exc_info=True)
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline tu dong: sinh instance -> push -> workflow -> chuyen data -> tai summary",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--name", required=False, help="Ten folder (VD: Lan5). Neu khong co, tu-sinh Lan[generation_num]")
    parser.add_argument("--workflow", choices=["run", "run-batch", "run-batch-v2"], default="run-batch",
                        help="Workflow can trigger (default: run-batch, use run-batch-v2 for 1 job/instance)")
    parser.add_argument("--batches", type=int, nargs="+",
                        help="Batch numbers cho run-batch (VD: 1 2 3). Neu khong co, se tu-tinh tu file count")
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
    parser.add_argument("--status", action="store_true",
                        help="Chi hien thi generation status")
    parser.add_argument("--reset", action="store_true",
                        help="Reset generation state ve initial (0 generation, 0 instances)")
    parser.add_argument("--loop", action="store_true",
                        help="Loop mode: run pipeline liên tục (Ctrl+C để stop)")
    parser.add_argument("--loop-interval", type=int, default=0,
                        help="Delay (giay) giữa các iteration (default: 0 = chạy ngay lập tức)")

    args = parser.parse_args(namespace=Namespace())

    # If --status, show status and exit (no logging setup needed)
    if args.status:
        show_generation_status()
        return
    
    # If --reset, reset state and exit (no logging setup needed)
    if args.reset:
        reset_generation_state()
        return
    
    # For --only-download, --name is required
    if args.only_download and not args.name:
        parser.error("--name is required when using --only-download")

    # Loop mode
    if args.loop:
        loop_count = 0
        print("\n" + "=" * 60)
        print("LOOP MODE - Chạy liên tục (Ctrl+C để stop)")
        print("=" * 60 + "\n")
        
        try:
            while True:
                loop_count += 1
                print(f"\n{'='*60}")
                print(f"LOOP ITERATION #{loop_count}")
                print(f"{'='*60}\n")
                
                # Reset name to auto-generate for each iteration
                args.name = None
                
                # Run one pipeline iteration
                success = run_pipeline_once(args)
                
                if success:
                    # Ask user to continue or not (with 2 minute timeout)
                    print(f"\n{'='*60}")
                    print(f"Iteration #{loop_count} hoàn thành!")
                    print(f"{'='*60}")
                    
                    should_continue = confirm_with_timeout("\nChạy iteration tiếp theo?", timeout_seconds=120)
                    
                    if not should_continue:
                        print(f"\n[INFO] Loop stopped sau {loop_count} iterations (user declined)")
                        return
                    
                    # Apply delay if specified
                    if args.loop_interval > 0:
                        print(f"\n[INFO] Chờ {args.loop_interval}s trước iteration tiếp theo...")
                        time.sleep(args.loop_interval)
                else:
                    print(f"\n[WARNING] Iteration #{loop_count} thất bại, tiếp tục loop...")
                    should_continue = confirm_with_timeout("\nChạy iteration tiếp theo?", timeout_seconds=120)
                    
                    if not should_continue:
                        print(f"\n[INFO] Loop stopped sau {loop_count} iterations (user declined after failure)")
                        return
                    
                    if args.loop_interval > 0:
                        print(f"\n[INFO] Chờ {args.loop_interval}s trước iteration tiếp theo...")
                        time.sleep(args.loop_interval)
        except KeyboardInterrupt:
            print(f"\n[INFO] Loop stopped sau {loop_count} iterations (Ctrl+C)")
            return
        except Exception as e:
            print(f"\n[ERROR] Loop error: {e}")
            return
    
    # Single run mode
    else:
        run_pipeline_once(args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("\nDa huy pipeline (Ctrl+C)")
        sys.exit(130)
    except Exception as e:
        logger.error(f"\nLoi: {e}", exc_info=True)
        sys.exit(1)