"""Apply the eleven-m5 oMLX patches and merge the host-owned settings."""

import argparse
import json
from pathlib import Path
import os
import subprocess
import sys
import tempfile


def read_object(path, default=None):
    if not path.exists() and default is not None:
        return default
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise ValueError(f"cannot read {path}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def merge_owned(existing, desired):
    result = dict(existing)
    for key, value in desired.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_owned(result[key], value)
        else:
            result[key] = value
    return result


def desired_models(existing, desired):
    current = existing.get("models", {})
    if not isinstance(current, dict):
        raise ValueError("model_settings.json models must be an object")
    models = {
        name: ({**value, "is_default": False} if isinstance(value, dict) else value)
        for name, value in current.items()
    }
    for name, owned in desired.items():
        previous = models.get(name)
        models[name] = merge_owned(previous if isinstance(previous, dict) else {}, owned)
    return {**existing, "models": models}


def patch_command(binary, directory, patch, *, reverse=False, dry_run=True):
    # --force disables patch's auto-reversal heuristic: a reverse check must
    # never turn into a successful forward dry-run on pristine source.
    command = [str(binary), "--force", "--silent", "--fuzz=0", "-p1", "-d", str(directory)]
    if reverse:
        command.append("--reverse")
    else:
        command.append("--forward")
    if dry_run:
        command.append("--dry-run")
    return subprocess.run(command, input=patch.read_text(), text=True, capture_output=True)


def patch_plan(binary, directories, patches):
    pending = []
    for directory in directories:
        if not (directory / "omlx").is_dir():
            raise ValueError(f"oMLX package missing from {directory}")
        for patch in patches:
            reverse = patch_command(binary, directory, patch, reverse=True)
            if reverse.returncode == 0:
                continue
            forward = patch_command(binary, directory, patch)
            if forward.returncode != 0:
                raise RuntimeError(
                    f"required patch {patch.name} does not apply to {directory}; "
                    f"check upstream compatibility\n{forward.stdout}{forward.stderr}"
                )
            pending.append((directory, patch))
    return pending


def write_object(path, value):
    # Replacements share the destination filesystem and always retain private
    # permissions, including the server file that holds the API credentials.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            os.chmod(temporary, 0o600)
            json.dump(value, stream, indent=2, sort_keys=True)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def configure(args):
    model_file = args.state_dir / "model_settings.json"
    server_file = args.state_dir / "settings.json"
    models = read_object(model_file, {"version": 1, "models": {}})
    server = read_object(server_file, {})
    wanted_models = desired_models(models, read_object(args.model_settings))
    wanted_server = merge_owned(server, read_object(args.server_settings))
    # Check every patch and settings input before the first source mutation.
    pending = patch_plan(args.patch_bin, args.site_packages, args.patch)
    args.state_dir.mkdir(parents=True, exist_ok=True)
    args.state_dir.chmod(0o700)
    for name in ("logs", "models", "downloads"):
        (args.state_dir / name).mkdir(exist_ok=True)
    marker = args.state_dir / ".restart-needed"
    changed_files = []
    for directory, patch in pending:
        result = patch_command(args.patch_bin, directory, patch, dry_run=False)
        if result.returncode != 0:
            raise RuntimeError(f"failed applying {patch.name}: {result.stdout}{result.stderr}")
        marker.touch()
        verified = patch_command(args.patch_bin, directory, patch, reverse=True)
        if verified.returncode != 0:
            raise RuntimeError(f"cannot verify applied {patch.name}: {verified.stdout}{verified.stderr}")
    for path, before, after in ((model_file, models, wanted_models), (server_file, server, wanted_server)):
        if before != after or not path.exists():
            write_object(path, after)
            marker.touch()
            changed_files.append(path.name)
    return {
        "changed": bool(pending or changed_files),
        "applied_patches": [patch.name for _, patch in pending],
        "changed_settings": changed_files,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, nargs="+", required=True)
    parser.add_argument("--patch-bin", type=Path, required=True)
    parser.add_argument("--patch", type=Path, action="append", required=True)
    parser.add_argument("--model-settings", type=Path, required=True)
    parser.add_argument("--server-settings", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = configure(args)
    except (OSError, ValueError, RuntimeError) as error:
        print(f"omlx-configure: {type(error).__name__}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
