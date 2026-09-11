"""cnode_platform — Plugin-Framework der cNode-Plattform (erweiterbare Bibliothek)."""
from .contracts import (
    AgentPlugin,
    Connector,
    FormatHandler,
    Plugin,
    PluginKind,
    PluginManifest,
    SystemConnector,
)
from .registry import PluginRegistry, registry

__all__ = [
    "Plugin", "PluginManifest", "PluginKind",
    "Connector", "FormatHandler", "AgentPlugin", "SystemConnector",
    "PluginRegistry", "registry",
]
