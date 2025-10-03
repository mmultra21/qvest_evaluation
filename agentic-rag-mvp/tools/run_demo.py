#!/usr/bin/env python3
"""Run a quick local demo: init/seed DB and launch Admin + Student UIs.

Usage examples:
  python agentic-rag-mvp/tools/run_demo.py --init-db --seed --plan --launch-admin 7861 --launch-student --wait
  python agentic-rag-mvp/tools/run_demo.py --all --wait

The script uses the repo's Python executable (sys.executable) to launch UI subprocesses
so activate your venv first if you want the same environment (recommended).
"""

import argparse
import os
import subprocess
import sys
import time


ROOT = os.path.dirname(os.path.dirname(__file__))
ADMIN_SCRIPT = os.path.join(ROOT, 'tools', 'admin_ui.py')


def init_and_seed():
    """Import tools.agent_job and initialize + seed + plan actions."""
    try:
        from tools import agent_job
    except Exception:
        # try import by path
        import importlib.util
        spec = importlib.util.spec_from_file_location('agent_job', os.path.join(ROOT, 'tools', 'agent_job.py'))
        agent_job = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(agent_job)

    con = agent_job.init_db()
    print('DB initialized at', agent_job.DB_PATH)
    try:
        agent_job.seed_students(con)
        print('Seeded students')
    except Exception as e:
        print('seed_students failed:', e)
    try:
        actions = agent_job.plan_actions(con)
        if actions:
            ids = agent_job.persist_actions(con, actions)
            print(f'Persisted {len(ids)} audit rows (pending_approval)')
        else:
            print('No actions planned')
    except Exception as e:
        print('plan/persist failed:', e)
    con.close()


def launch_admin(port: int | None = None, logpath: str | None = '/tmp/admin_ui.log'):
    chosen = str(port) if port else '7861'
    cmd = [sys.executable, ADMIN_SCRIPT, chosen]
    print('Launching Admin UI:', ' '.join(cmd))
    f = open(logpath, 'ab')
    proc = subprocess.Popen(cmd, cwd=ROOT, stdout=f, stderr=subprocess.STDOUT)
    print('Admin PID', proc.pid, 'log->', logpath)
    return proc


def launch_student(port: int | None = None, logpath: str | None = '/tmp/student_ui.log'):
    # student UI runs as module app.gradio_main
    cmd = [sys.executable, '-m', 'app.gradio_main']
    if port:
        # set PORT env for gradio if the module reads it
        env = os.environ.copy()
        env['PORT'] = str(port)
    else:
        env = None
    print('Launching Student UI:', ' '.join(cmd))
    f = open(logpath, 'ab')
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env, stdout=f, stderr=subprocess.STDOUT)
    print('Student PID', proc.pid, 'log->', logpath)
    return proc


def main(argv: list[str] | None = None):
    p = argparse.ArgumentParser()
    p.add_argument('--init-db', action='store_true')
    p.add_argument('--seed', action='store_true', help='Seed students table from POC catalog')
    p.add_argument('--plan', action='store_true', help='Run planner and persist audit rows (pending_approval)')
    p.add_argument('--launch-admin', nargs='?', const=7861, type=int, help='Launch admin UI on given port (default 7861)')
    p.add_argument('--launch-student', nargs='?', const=7864, type=int, help='Launch student UI on given port (default 7864)')
    p.add_argument('--all', action='store_true', help='Do init-db, seed, plan, and launch both UIs')
    p.add_argument('--wait', action='store_true', help='Block until launched processes exit')

    args = p.parse_args(argv)

    procs = []

    if args.all:
        print('Running full demo sequence: init, seed, plan, launch admin & student')
        init_and_seed()
        procs.append(launch_admin(args.launch_admin or 7861))
        procs.append(launch_student(args.launch_student or 7864))
    else:
        if args.init_db or args.seed or args.plan:
            # run the Python init+seed+plan path for fine-grained control
            init_and_seed()
        if args.launch_admin is not None:
            procs.append(launch_admin(args.launch_admin))
        if args.launch_student is not None:
            procs.append(launch_student(args.launch_student))

    if procs:
        print('Launched processes:', [p.pid for p in procs])
        if args.wait:
            try:
                for pr in procs:
                    pr.wait()
            except KeyboardInterrupt:
                print('Interrupted — terminating children')
                for pr in procs:
                    try:
                        pr.terminate()
                    except Exception:
                        pass


if __name__ == '__main__':
    main()
