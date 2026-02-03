#!/usr/bin/env python3
"""
verify_deploy.py - Pre-flight checks before production deployment

Runs all verification checks required before deploying to production:
1. Git working tree is clean (no uncommitted changes)
2. Git branch is synced with origin
3. php_deploy/ is in sync with src/
4. MySQL export is valid and current
5. SSH connectivity to production server

Usage:
    python3 scripts/verify_deploy.py

Exit codes:
    0 - All checks passed, ready to deploy
    1 - One or more checks failed
"""

import subprocess
import sys
from pathlib import Path

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent

# Production server config
PROD_HOST = 'oldbooks.humspace.ucla.edu'
PROD_USER = 'oldbooks'

# Check symbols
CHECK = '[✓]'
CROSS = '[✗]'


def run_command(cmd: list, capture: bool = True) -> tuple:
    """Run a command and return (success, output)."""
    try:
        result = subprocess.run(
            cmd,
            capture_output=capture,
            text=True,
            cwd=PROJECT_ROOT,
            timeout=30
        )
        return result.returncode == 0, result.stdout.strip() if capture else ''
    except subprocess.TimeoutExpired:
        return False, 'Command timed out'
    except Exception as e:
        return False, str(e)


def check_git_clean() -> tuple:
    """Check if git working tree is clean. Returns (passed, message)."""
    success, output = run_command(['git', 'status', '--porcelain'])
    if not success:
        return False, 'Failed to check git status'

    if output:
        # Count changes
        lines = [l for l in output.split('\n') if l.strip()]
        return False, f'{len(lines)} uncommitted changes. Commit or stash before deploying.'

    return True, 'Git working tree clean'


def check_git_synced() -> tuple:
    """Check if git branch is synced with origin. Returns (passed, message)."""
    # Fetch latest from origin
    success, _ = run_command(['git', 'fetch', 'origin'])
    if not success:
        return False, 'Failed to fetch from origin'

    # Get current branch
    success, branch = run_command(['git', 'rev-parse', '--abbrev-ref', 'HEAD'])
    if not success:
        return False, 'Failed to get current branch'

    # Check if remote tracking branch exists
    success, remote = run_command(['git', 'rev-parse', '--abbrev-ref', f'{branch}@{{upstream}}'])
    if not success:
        return False, f'No upstream tracking branch for {branch}'

    # Count commits ahead/behind
    success, ahead = run_command(['git', 'rev-list', '--count', f'{remote}..HEAD'])
    success2, behind = run_command(['git', 'rev-list', '--count', f'HEAD..{remote}'])

    if not success or not success2:
        return False, 'Failed to compare with remote'

    ahead = int(ahead) if ahead else 0
    behind = int(behind) if behind else 0

    if ahead > 0 and behind > 0:
        return False, f'Branch diverged: {ahead} ahead, {behind} behind. Pull and merge.'
    elif ahead > 0:
        return False, f'{ahead} commits ahead of origin. Run: git push'
    elif behind > 0:
        return False, f'{behind} commits behind origin. Run: git pull'

    return True, f'Git synced with origin ({branch})'


def check_php_deploy() -> tuple:
    """Check if php_deploy/ is in sync with src/. Returns (passed, message)."""
    result = subprocess.run(
        [sys.executable, 'scripts/build_php.py', '--check'],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT
    )

    if result.returncode == 0:
        return True, 'php_deploy/ in sync with src/'
    else:
        return False, 'php_deploy/ out of sync. Run: python3 scripts/build_php.py'


def check_mysql_export() -> tuple:
    """Check if MySQL export is valid and current. Returns (passed, message)."""
    result = subprocess.run(
        [sys.executable, 'scripts/export_mysql.py', '--check'],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT
    )

    if result.returncode == 0:
        # Extract counts from output
        output = result.stdout.strip()
        # Output format: "[✓] MySQL export is valid (14 repos, 4728 manuscripts)"
        return True, output.replace('[✓] ', '')
    else:
        return False, 'MySQL export stale or invalid. Run: python3 scripts/export_mysql.py'


def check_ssh_connection() -> tuple:
    """Check SSH connectivity to production server. Returns (passed, message)."""
    success, output = run_command([
        'ssh',
        '-o', 'ConnectTimeout=10',
        '-o', 'BatchMode=yes',
        f'{PROD_USER}@{PROD_HOST}',
        'echo ok'
    ])

    if success and 'ok' in output:
        return True, f'SSH connection to {PROD_HOST} OK'
    else:
        return False, f'Cannot connect to {PROD_HOST}. Check SSH keys and network.'


def main():
    print('=== Compilatio Deploy Verification ===\n')

    all_passed = True
    checks = [
        ('Git clean', check_git_clean),
        ('Git synced', check_git_synced),
        ('PHP build', check_php_deploy),
        ('MySQL export', check_mysql_export),
        ('SSH connection', check_ssh_connection),
    ]

    for name, check_func in checks:
        passed, message = check_func()
        symbol = CHECK if passed else CROSS
        print(f'{symbol} {message}')

        if not passed:
            all_passed = False

    print()
    if all_passed:
        print('All checks passed. Ready to deploy.')
        sys.exit(0)
    else:
        print('Deployment blocked. Fix issues above.')
        sys.exit(1)


if __name__ == '__main__':
    main()
