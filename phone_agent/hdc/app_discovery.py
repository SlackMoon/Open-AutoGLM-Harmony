"""Discover installed HarmonyOS bundles and their actual entry abilities."""
from dataclasses import dataclass
import json
import re
import subprocess


@dataclass(frozen=True)
class InstalledApp:
    bundle: str
    ability: str
    module: str = ''
    label: str = ''


def _output(prefix, command):
    result = subprocess.run(prefix + ['shell', command], capture_output=True, timeout=8)
    if result.returncode:
        return ''
    return (result.stdout + result.stderr).decode('utf-8', errors='replace')


def _bundles(output):
    return sorted(set(re.findall(r'(?m)^\s*([A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+)\s*$', output)))


def _entry(bundle, output):
    try:
        data = json.loads(output[output.index('{'):output.rindex('}')+1])
    except (ValueError, TypeError):
        return None
    entries = []
    def visit(node):
        if isinstance(node, dict):
            ability = node.get('mainElementName') or node.get('mainAbility')
            if isinstance(ability, str) and ability:
                module = node.get('moduleName') or node.get('name') or ''
                label = node.get('label', '')
                if not isinstance(label, str) or label.startswith('$'):
                    label = ''
                rank = 2 if node.get('isEntry') or node.get('type') == 'entry' or module == 'entry' else 1
                entries.append((rank, InstalledApp(bundle, ability, module, label)))
            for value in node.values():
                if isinstance(value, (dict, list)):
                    visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)
    visit(data)
    if not entries:
        return None
    best = max(rank for rank, app in entries)
    choices = {app for rank, app in entries if rank == best}
    return next(iter(choices)) if len(choices) == 1 else None


def discover_apps(prefix, name, bundle_hints=()):
    """Return candidates; callers must not auto-pick between ambiguous matches.

    Resource IDs such as $string:app_name are not readable app labels. Chinese
    names that cannot be resolved from metadata are left to launcher search.
    """
    try:
        installed = _bundles(_output(prefix, 'bm dump -a'))
        query = name.casefold().strip()
        if not query:
            return []
        exact = [bundle for bundle in installed if bundle.casefold() == query]
        hinted = [bundle for bundle in installed if bundle in bundle_hints]
        words = [word for word in re.split(r'[\W_]+', query) if len(word) >= 3]
        similar = [bundle for bundle in installed
                   if words and any(word in bundle.casefold().split('.') for word in words)]
        bundles = exact or hinted or similar
        # An unbounded scan of every bundle is slow and does not resolve labels.
        if len(bundles) > 8:
            return []
        matches = []
        for bundle in bundles:
            entry = _entry(bundle, _output(prefix, 'bm dump -n ' + bundle))
            if entry:
                matches.append(entry)
        return matches
    except (OSError, subprocess.SubprocessError):
        return []
