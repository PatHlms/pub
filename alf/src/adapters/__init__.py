from src.adapters.base import BaseAdapter
from src.adapters.rest import RestAdapter

# Registry: "adapter" value in sites.json -> class
# Add new adapter classes here and register them with their name.
ADAPTER_REGISTRY: dict[str, type[BaseAdapter]] = {
    RestAdapter.name: RestAdapter,
}

__all__ = ["BaseAdapter", "RestAdapter", "ADAPTER_REGISTRY"]
