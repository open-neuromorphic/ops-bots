from jinja2 import Environment, FileSystemLoader
from pathlib import Path
import config

template_dir = Path(__file__).parent.parent / "templates"
env = Environment(loader=FileSystemLoader(template_dir))

def render_template(template_path: str, **kwargs) -> str:
    """Renders a Jinja2 template with the given kwargs."""
    template = env.get_template(template_path)
    return template.render(**kwargs)