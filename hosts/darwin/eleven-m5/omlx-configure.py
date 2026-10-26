"""Apply the eleven-m5 oMLX patches, merge the host-owned settings and sync steering presets."""

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


STEERING_MARKER = ".omlx-steering-preset"
DOWNLOAD_MARKER = ".omlx-download-complete"


def steering_plan(models_dir, presets):
    """Validate the declared presets and list stale preset directories to remove."""
    for name, preset in presets.items():
        if "/" in name or name.startswith(".") or "/" in preset.get("base", "/"):
            raise ValueError(f"invalid steering preset directory {name!r}")
        if not preset.get("neurons"):
            raise ValueError(f"steering preset {name} lists no neurons")
        existing = models_dir / name
        if existing.exists() and not (existing / STEERING_MARKER).exists():
            raise ValueError(f"{existing} exists and is not a steering preset directory")
    stale = []
    if models_dir.is_dir():
        for directory in sorted(models_dir.iterdir()):
            if (directory / STEERING_MARKER).exists() and directory.name not in presets:
                for entry in directory.iterdir():
                    if not (entry.is_symlink() or entry.name in (STEERING_MARKER, "steering.json")):
                        raise ValueError(f"stale steering preset {directory} holds {entry.name}")
                stale.append(directory)
    return stale


def sync_steering(models_dir, presets, stale):
    """Mirror each preset's downloaded base model as symlinks beside its steering.json.

    A preset whose base has not finished downloading is left for the next run
    (the downloader runs this command again once it has)."""
    changed, pending = [], []
    for directory in stale:
        for entry in directory.iterdir():
            entry.unlink()
        directory.rmdir()
        changed.append(directory.name)
    for name, preset in sorted(presets.items()):
        base = models_dir / preset["base"]
        if not (base / DOWNLOAD_MARKER).exists():
            pending.append(name)
            continue
        directory = models_dir / name
        dirty = not directory.exists()
        directory.mkdir(exist_ok=True)
        (directory / STEERING_MARKER).touch()
        wanted = {entry.name: entry for entry in base.iterdir() if not entry.name.startswith(".")}
        for entry in directory.iterdir():
            if entry.is_symlink() and wanted.get(entry.name) != Path(os.readlink(entry)):
                entry.unlink()
                dirty = True
        for link_name, target in wanted.items():
            link = directory / link_name
            if not link.is_symlink():
                link.symlink_to(target)
                dirty = True
        spec = json.dumps({"neurons": preset["neurons"]}, indent=2, sort_keys=True) + "\n"
        steering = directory / "steering.json"
        if not steering.exists() or steering.read_text() != spec:
            steering.write_text(spec)
            dirty = True
        if dirty:
            changed.append(name)
    return changed, pending


def configure(args):
    model_file = args.state_dir / "model_settings.json"
    server_file = args.state_dir / "settings.json"
    models = read_object(model_file, {"version": 1, "models": {}})
    server = read_object(server_file, {})
    wanted_models = desired_models(models, read_object(args.model_settings))
    wanted_server = merge_owned(server, read_object(args.server_settings))
    presets = read_object(args.steering) if args.steering else {}
    stale = steering_plan(args.state_dir / "models", presets)
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
    changed_presets, pending_presets = sync_steering(args.state_dir / "models", presets, stale)
    if changed_presets:
        marker.touch()
    return {
        "changed": bool(pending or changed_files or changed_presets),
        "applied_patches": [patch.name for _, patch in pending],
        "changed_settings": changed_files,
        "changed_steering": changed_presets,
        "pending_steering": pending_presets,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--site-packages", type=Path, nargs="+", required=True)
    parser.add_argument("--patch-bin", type=Path, required=True)
    parser.add_argument("--patch", type=Path, action="append", required=True)
    parser.add_argument("--model-settings", type=Path, required=True)
    parser.add_argument("--server-settings", type=Path, required=True)
    parser.add_argument("--steering", type=Path)
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
