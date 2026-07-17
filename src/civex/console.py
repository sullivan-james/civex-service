from rich.console import Console
from rich.theme import Theme

console = Console(
    theme=Theme(
        {
            "info": "cyan",
            "success": "green",
            "warning": "yellow",
            "error": "bold red",
        }
    )
)
