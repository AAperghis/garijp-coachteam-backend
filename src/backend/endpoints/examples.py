import mimetypes
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

router = APIRouter(prefix="/examples", tags=["examples"])

# All example files live under this directory.
# Add new subfolders (e.g. examples/banaan/, examples/roster/) at any time
# without touching the endpoint code.
EXAMPLES_DIR = Path(__file__).parent.parent / "examples"


class ExampleFile(BaseModel):
    module: str
    name: str
    filename: str


@router.get("", response_model=list[ExampleFile])
def list_examples() -> list[ExampleFile]:
    """Return all available example files, grouped by module (subfolder name)."""
    if not EXAMPLES_DIR.is_dir():
        return []

    results: list[ExampleFile] = []
    for module_dir in sorted(EXAMPLES_DIR.iterdir()):
        if not module_dir.is_dir():
            continue
        for file in sorted(module_dir.iterdir()):
            if file.is_file() and not file.name.startswith("."):
                results.append(ExampleFile(
                    module=module_dir.name,
                    name=file.stem,
                    filename=file.name,
                ))
    return results


@router.get("/{module}/{filename}")
def download_example(module: str, filename: str) -> FileResponse:
    """Download a specific example file.

    - **module**: subfolder name (e.g. `banaan`, `roster`)
    - **filename**: exact filename including extension (e.g. `example_students.csv`)
    """
    # Prevent directory traversal
    if "/" in module or "\\" in module or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid path component")

    file_path = (EXAMPLES_DIR / module / filename).resolve()

    # Ensure the resolved path stays within EXAMPLES_DIR
    try:
        file_path.relative_to(EXAMPLES_DIR.resolve())
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail=f"Example '{module}/{filename}' not found")

    media_type, _ = mimetypes.guess_type(filename)
    return FileResponse(
        path=file_path,
        filename=filename,
        media_type=media_type or "application/octet-stream",
    )
