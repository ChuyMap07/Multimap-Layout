def classFactory(iface):
    from .multimap_plugin import MultiMapPlugin
    return MultiMapPlugin(iface)
